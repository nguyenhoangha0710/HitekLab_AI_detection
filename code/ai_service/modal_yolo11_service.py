import base64
import atexit
import os
import queue
import sys
import time

import modal

from modal_ai.results import latest_results_snapshot, publish_result
from modal_ai.runtime import app, frame_queues, image, result_queues, state_store
from modal_ai.settings import (
    API_WEBSOCKET_TIMEOUT_SECONDS,
    APP_NAME,
    DEFAULT_CONFIDENCE,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_MODEL,
    FRAME_QUEUE_LIMIT,
    FRAME_QUEUE_PREFIX,
    NUM_SHARDS,
    QUEUE_VERSION,
    RESULT_QUEUE_LIMIT,
    RESULT_QUEUE_PREFIX,
    SHARD_WORKER_IDLE_TIMEOUT_SECONDS,
    SHARD_WORKER_POLL_TIMEOUT_SECONDS,
    STATE_DICT_NAME,
    VIEWER_CAMERA_IDS,
)
from modal_ai.sharding import frame_queue_name, shard_id_for_camera
from modal_ai.time_utils import utc_iso
from modal_ai.viewer import CAMERA_VIEWER_HTML, VIEWER_HTML
from modal_ai.yolo import draw_and_detect


def _is_local_modal_serve_process() -> bool:
    return os.getenv("MODAL_IS_REMOTE") != "1" and "serve" in sys.argv


def _clear_runtime_data_sync(reason: str) -> None:
    for frame_queue in frame_queues:
        frame_queue.clear()
    for result_queue in result_queues:
        result_queue.clear()
    state_store.clear()
    print("Modal runtime queues cleared version={} reason={}".format(QUEUE_VERSION, reason))


def _delete_runtime_objects_sync(reason: str) -> None:
    queue_names = [
        frame_queue_name(FRAME_QUEUE_PREFIX, shard_id)
        for shard_id in range(NUM_SHARDS)
    ] + [
        frame_queue_name(RESULT_QUEUE_PREFIX, shard_id)
        for shard_id in range(NUM_SHARDS)
    ]
    for queue_name in queue_names:
        modal.Queue.objects.delete(queue_name, allow_missing=True)
    modal.Dict.objects.delete(STATE_DICT_NAME, allow_missing=True)
    print(
        "Modal runtime queue objects deleted version={} reason={} queues={} state={}".format(
            QUEUE_VERSION,
            reason,
            ",".join(queue_names),
            STATE_DICT_NAME,
        )
    )


def _clear_runtime_data_on_local_exit() -> None:
    try:
        _delete_runtime_objects_sync("local_modal_serve_exit")
    except Exception as exc:
        print("Modal runtime queue delete failed version={} error={}".format(QUEUE_VERSION, exc))
        try:
            _clear_runtime_data_sync("local_modal_serve_exit_fallback_clear")
        except Exception as fallback_exc:
            print("Modal runtime queue fallback clear failed version={} error={}".format(QUEUE_VERSION, fallback_exc))


if _is_local_modal_serve_process():
    try:
        _delete_runtime_objects_sync("local_modal_serve_start")
    except Exception as exc:
        print("Modal runtime queue start delete skipped version={} error={}".format(QUEUE_VERSION, exc))
    atexit.register(_clear_runtime_data_on_local_exit)


@app.cls(image=image, gpu="L4", timeout=API_WEBSOCKET_TIMEOUT_SECONDS, scaledown_window=300, max_containers=NUM_SHARDS)
class ModalYoloQueueWorker:
    model_name: str = modal.parameter(default=DEFAULT_MODEL)

    @modal.enter()
    def load_model(self):
        from ultralytics import YOLO

        self.model = YOLO(self.model_name)

    def _process_payload_internal(self, payload: dict, shard_id: int) -> dict:
        result = draw_and_detect(self.model, payload)
        result["shard_id"] = shard_id
        result["worker_id"] = "ai-worker-{}".format(shard_id)
        publish_result(result, shard_id)
        print(
            "Modal worker processed version={} camera={} shard={} seq={} published=True".format(
                QUEUE_VERSION,
                result.get("camera_id"),
                shard_id,
                result.get("sequence_number"),
            )
        )
        return result

    @modal.method()
    def process_payload(self, payload: dict) -> dict:
        shard_id = int(payload.get("shard_id", shard_id_for_camera(str(payload.get("camera_id", "")), NUM_SHARDS)))
        return self._process_payload_internal(payload, shard_id)

    @modal.method()
    def run_shard_loop(self, shard_id: int = 0, idle_timeout_seconds: float = SHARD_WORKER_IDLE_TIMEOUT_SECONDS) -> dict:
        processed = 0
        skipped = 0
        last_result = None
        active_key = "worker_active:{}".format(shard_id)
        heartbeat_key = "worker_heartbeat:{}".format(shard_id)
        last_frame_at = time.monotonic()
        state_store[active_key] = True
        state_store[heartbeat_key] = utc_iso()
        print(
            "Modal shard worker started version={} shard={} worker=ai-worker-{}".format(
                QUEUE_VERSION,
                shard_id,
                shard_id,
            )
        )
        try:
            while True:
                try:
                    payload = frame_queues[shard_id].get(
                        block=True,
                        timeout=SHARD_WORKER_POLL_TIMEOUT_SECONDS,
                    )
                except queue.Empty:
                    payload = None

                if payload is None:
                    if time.monotonic() - last_frame_at >= idle_timeout_seconds:
                        break
                    state_store[heartbeat_key] = utc_iso()
                    continue
                if not isinstance(payload, dict):
                    skipped += 1
                    continue

                last_frame_at = time.monotonic()
                state_store[heartbeat_key] = utc_iso()
                print(
                    "Modal worker claimed version={} camera={} shard={} seq={} worker=ai-worker-{}".format(
                        QUEUE_VERSION,
                        payload.get("camera_id"),
                        shard_id,
                        payload.get("sequence_number"),
                        shard_id,
                    )
                )
                last_result = self._process_payload_internal(payload, shard_id)
                processed += 1
        finally:
            state_store[active_key] = False
            state_store[heartbeat_key] = utc_iso()
            print(
                "Modal shard worker stopped version={} shard={} processed={} skipped={}".format(
                    QUEUE_VERSION,
                    shard_id,
                    processed,
                    skipped,
                )
            )

        return {
            "status": "processed" if processed else "empty",
            "shard_id": shard_id,
            "processed": processed,
            "skipped": skipped,
            "last_result": last_result,
        }


@app.function(image=image, timeout=API_WEBSOCKET_TIMEOUT_SECONDS)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def api():
    import asyncio

    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse

    web = FastAPI(title="Hitek Modal YOLOv11 Async AI Server")

    def normalize_payload(payload: dict) -> dict:
        required = ["camera_id", "frame_id", "sequence_number", "image_b64"]
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError("Missing required fields: {}".format(", ".join(missing)))

        payload["modal_received_at"] = utc_iso()
        payload.setdefault("classes", ["person", "car"])
        payload.setdefault("confidence", DEFAULT_CONFIDENCE)
        payload.setdefault("imgsz", DEFAULT_IMAGE_SIZE)
        payload.setdefault("model", DEFAULT_MODEL)
        payload["sequence_number"] = int(payload["sequence_number"])
        payload["shard_id"] = shard_id_for_camera(str(payload["camera_id"]), NUM_SHARDS)
        return payload

    def worker_active_key(shard_id: int) -> str:
        return "worker_active:{}".format(shard_id)

    def frame_drop_key(shard_id: int) -> str:
        return "frame_dropped:{}".format(shard_id)

    async def clear_runtime_data_async(reason: str) -> None:
        for frame_queue in frame_queues:
            await frame_queue.clear.aio()
        for result_queue in result_queues:
            await result_queue.clear.aio()
        await state_store.clear.aio()
        print("Modal runtime queues cleared version={} reason={}".format(QUEUE_VERSION, reason))

    async def trim_frame_queue_for_put_async(shard_id: int) -> int:
        frame_queue = frame_queues[shard_id]
        current_size = await frame_queue.len.aio()
        drop_count = max(0, current_size - FRAME_QUEUE_LIMIT + 1)
        if not drop_count:
            return 0

        dropped = await frame_queue.get_many.aio(drop_count, block=False)
        dropped_count = len(dropped)
        if dropped_count:
            total_key = frame_drop_key(shard_id)
            total_dropped = int(await state_store.get.aio(total_key) or 0) + dropped_count
            await state_store.put.aio(total_key, total_dropped)
            oldest = dropped[0] if isinstance(dropped[0], dict) else {}
            newest = dropped[-1] if isinstance(dropped[-1], dict) else {}
            print(
                "MODAL_FRAME_QUEUE_DROP version={} shard={} dropped={} oldest_camera={} oldest_seq={} newest_camera={} newest_seq={} limit={} total_dropped={}".format(
                    QUEUE_VERSION,
                    shard_id,
                    dropped_count,
                    oldest.get("camera_id"),
                    oldest.get("sequence_number"),
                    newest.get("camera_id"),
                    newest.get("sequence_number"),
                    FRAME_QUEUE_LIMIT,
                    total_dropped,
                )
            )
        return dropped_count

    def trim_frame_queue_for_put(shard_id: int) -> int:
        frame_queue = frame_queues[shard_id]
        current_size = frame_queue.len()
        drop_count = max(0, current_size - FRAME_QUEUE_LIMIT + 1)
        if not drop_count:
            return 0

        dropped = frame_queue.get_many(drop_count, block=False)
        dropped_count = len(dropped)
        if dropped_count:
            total_key = frame_drop_key(shard_id)
            total_dropped = int(state_store.get(total_key) or 0) + dropped_count
            state_store[total_key] = total_dropped
            oldest = dropped[0] if isinstance(dropped[0], dict) else {}
            newest = dropped[-1] if isinstance(dropped[-1], dict) else {}
            print(
                "MODAL_FRAME_QUEUE_DROP version={} shard={} dropped={} oldest_camera={} oldest_seq={} newest_camera={} newest_seq={} limit={} total_dropped={}".format(
                    QUEUE_VERSION,
                    shard_id,
                    dropped_count,
                    oldest.get("camera_id"),
                    oldest.get("sequence_number"),
                    newest.get("camera_id"),
                    newest.get("sequence_number"),
                    FRAME_QUEUE_LIMIT,
                    total_dropped,
                )
            )
        return dropped_count

    async def ensure_shard_worker_async(shard_id: int) -> bool:
        active_key = worker_active_key(shard_id)
        if await state_store.get.aio(active_key):
            return False
        await state_store.put.aio(active_key, True)
        try:
            await ModalYoloQueueWorker(model_name=DEFAULT_MODEL).run_shard_loop.spawn.aio(
                shard_id,
                SHARD_WORKER_IDLE_TIMEOUT_SECONDS,
            )
            return True
        except Exception:
            await state_store.put.aio(active_key, False)
            return False

    async def ensure_all_shard_workers_async() -> None:
        for shard_id in range(NUM_SHARDS):
            await ensure_shard_worker_async(shard_id)

    async def enqueue_payload_async(payload: dict) -> bool:
        shard_id = int(payload["shard_id"])
        await trim_frame_queue_for_put_async(shard_id)
        await frame_queues[shard_id].put.aio(payload, block=False)
        return await ensure_shard_worker_async(shard_id)

    def ensure_shard_worker(shard_id: int) -> bool:
        active_key = worker_active_key(shard_id)
        if state_store.get(active_key):
            return False
        state_store[active_key] = True
        try:
            ModalYoloQueueWorker(model_name=DEFAULT_MODEL).run_shard_loop.spawn(
                shard_id,
                SHARD_WORKER_IDLE_TIMEOUT_SECONDS,
            )
            return True
        except Exception:
            state_store[active_key] = False
            raise

    def enqueue_payload(payload: dict) -> bool:
        shard_id = int(payload["shard_id"])
        trim_frame_queue_for_put(shard_id)
        frame_queues[shard_id].put(payload, block=False)
        return ensure_shard_worker(shard_id)

    @web.get("/health")
    def health():
        return {
            "status": "ok",
            "service": APP_NAME,
            "queue_backend": "modal_queue_shards",
            "queue_version": QUEUE_VERSION,
            "num_shards": NUM_SHARDS,
            "frame_queue_limit": FRAME_QUEUE_LIMIT,
            "result_queue_limit": RESULT_QUEUE_LIMIT,
            "frame_queues": [frame_queue_name(FRAME_QUEUE_PREFIX, shard_id) for shard_id in range(NUM_SHARDS)],
            "result_queues": [frame_queue_name(RESULT_QUEUE_PREFIX, shard_id) for shard_id in range(NUM_SHARDS)],
            "state": STATE_DICT_NAME,
            "timestamp": utc_iso(),
        }

    @web.get("/queues")
    def queues():
        return {
            "backend": "modal_queue_shards",
            "queue_version": QUEUE_VERSION,
            "num_shards": NUM_SHARDS,
            "frame_queue_limit": FRAME_QUEUE_LIMIT,
            "result_queue_limit": RESULT_QUEUE_LIMIT,
            "frame_queues": [frame_queue_name(FRAME_QUEUE_PREFIX, shard_id) for shard_id in range(NUM_SHARDS)],
            "result_queues": [frame_queue_name(RESULT_QUEUE_PREFIX, shard_id) for shard_id in range(NUM_SHARDS)],
            "frame_queue_lengths": {
                str(shard_id): frame_queues[shard_id].len() for shard_id in range(NUM_SHARDS)
            },
            "result_queue_lengths": {
                str(shard_id): result_queues[shard_id].len() for shard_id in range(NUM_SHARDS)
            },
            "frame_dropped": {
                str(shard_id): int(state_store.get(frame_drop_key(shard_id)) or 0) for shard_id in range(NUM_SHARDS)
            },
            "active_workers": {
                str(shard_id): bool(state_store.get(worker_active_key(shard_id))) for shard_id in range(NUM_SHARDS)
            },
            "worker_heartbeats": {
                str(shard_id): state_store.get("worker_heartbeat:{}".format(shard_id)) for shard_id in range(NUM_SHARDS)
            },
            "message": "Frame/result queues are FIFO-limited per shard for live demo latency control.",
            "timestamp": utc_iso(),
        }

    @web.post("/admin/clear-queues")
    async def clear_queues():
        await clear_runtime_data_async("manual_admin_clear")
        return {"status": "cleared", "queue_version": QUEUE_VERSION, "timestamp": utc_iso()}

    @web.post("/ingest", status_code=202)
    def ingest(payload: dict):
        try:
            payload = normalize_payload(payload)
            worker_started = enqueue_payload(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except queue.Full as exc:
            raise HTTPException(status_code=503, detail="Modal frame queue is full") from exc

        return {
            "status": "accepted",
            "camera_id": payload["camera_id"],
            "frame_id": payload["frame_id"],
            "sequence_number": payload["sequence_number"],
            "shard_id": payload["shard_id"],
            "worker_started": worker_started,
            "modal_received_at": payload["modal_received_at"],
        }

    @web.websocket("/ingest")
    @web.websocket("/ws/ingest")
    async def websocket_ingest(websocket: WebSocket):
        await websocket.accept()
        await clear_runtime_data_async("websocket_ingest_start")
        await ensure_all_shard_workers_async()
        accepted = 0
        try:
            while True:
                payload = await websocket.receive_json()
                try:
                    payload = normalize_payload(payload)
                    worker_started = await enqueue_payload_async(payload)
                except Exception as exc:
                    if isinstance(payload, dict) and payload.get("ack"):
                        await websocket.send_json({"type": "error", "detail": str(exc), "timestamp": utc_iso()})
                    continue

                accepted += 1
                if payload.get("ack"):
                    await websocket.send_json(
                        {
                            "type": "accepted",
                            "camera_id": payload["camera_id"],
                            "frame_id": payload["frame_id"],
                            "sequence_number": payload["sequence_number"],
                            "shard_id": payload["shard_id"],
                            "worker_started": worker_started,
                            "accepted": accepted,
                            "timestamp": utc_iso(),
                        }
                    )
        except WebSocketDisconnect:
            return

    def snapshot_for_shard(shard_id: int):
        return [result for result in latest_results_snapshot() if int(result.get("shard_id", -1)) == shard_id]

    @web.websocket("/ws/results/shards/{shard_id}")
    async def websocket_results_shard(websocket: WebSocket, shard_id: int):
        await websocket.accept()
        if shard_id < 0 or shard_id >= NUM_SHARDS:
            await websocket.send_json({"type": "error", "detail": "Invalid shard_id", "timestamp": utc_iso()})
            await websocket.close()
            return

        try:
            snapshot = await asyncio.to_thread(snapshot_for_shard, shard_id)
            for result in snapshot:
                await websocket.send_json({"type": "frame", "frame": result, "snapshot": True, "timestamp": utc_iso()})

            while True:
                try:
                    result = await result_queues[shard_id].get.aio(block=False)
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue

                if result is None:
                    await asyncio.sleep(0.05)
                    continue

                await websocket.send_json({"type": "frame", "frame": result, "timestamp": utc_iso()})
        except WebSocketDisconnect:
            return

    @web.websocket("/ws/results")
    async def websocket_results(websocket: WebSocket):
        await websocket.accept()
        try:
            snapshot = await asyncio.to_thread(latest_results_snapshot)
            for result in snapshot:
                await websocket.send_json({"type": "frame", "frame": result, "snapshot": True, "timestamp": utc_iso()})

            shard_cursor = 0
            while True:
                delivered = False
                for offset in range(NUM_SHARDS):
                    shard_id = (shard_cursor + offset) % NUM_SHARDS
                    try:
                        result = await result_queues[shard_id].get.aio(block=False)
                    except queue.Empty:
                        continue

                    if result is None:
                        continue

                    shard_cursor = (shard_id + 1) % NUM_SHARDS
                    delivered = True
                    await websocket.send_json({"type": "frame", "frame": result, "timestamp": utc_iso()})
                    break

                if not delivered:
                    await asyncio.sleep(0.05)
        except WebSocketDisconnect:
            return

    @web.get("/results")
    def results():
        values = latest_results_snapshot()
        return {"value": values, "count": len(values), "timestamp": utc_iso()}

    @web.get("/results/{camera_id}")
    def result_by_camera(camera_id: str):
        result = state_store.get("latest:{}".format(camera_id))
        if result is None:
            raise HTTPException(status_code=404, detail="No result for camera {}".format(camera_id))
        return result

    @web.get("/viewer")
    def viewer():
        return HTMLResponse(VIEWER_HTML)

    @web.get("/viewer/cameras")
    def viewer_cameras():
        cameras = [
            {
                "camera_id": camera_id,
                "shard_id": shard_id_for_camera(camera_id, NUM_SHARDS),
            }
            for camera_id in VIEWER_CAMERA_IDS
        ]
        return {"cameras": cameras, "count": len(cameras), "timestamp": utc_iso()}

    @web.get("/viewer/camera/{camera_id}")
    def viewer_camera(camera_id: str):
        return HTMLResponse(CAMERA_VIEWER_HTML)

    return web


@app.local_entrypoint()
def main(image_path: str = "", confidence: float = DEFAULT_CONFIDENCE):
    if not image_path:
        print("Dev server: modal serve code/ai_service/modal_yolo11_service.py")
        print("Deploy:     modal deploy code/ai_service/modal_yolo11_service.py")
        return

    with open(image_path, "rb") as image_file:
        image_b64 = base64.b64encode(image_file.read()).decode("ascii")

    payload = {
        "camera_id": "local-test-camera",
        "location_id": "local-test-location",
        "frame_id": "local-test-frame",
        "sequence_number": 1,
        "image_b64": image_b64,
        "classes": ["person", "car"],
        "confidence": confidence,
        "modal_received_at": utc_iso(),
    }
    result = ModalYoloQueueWorker(model_name=DEFAULT_MODEL).process_payload.remote(payload)
    print(result)
