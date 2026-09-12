import base64
import queue

import modal

from modal_ai.results import latest_results_snapshot, publish_result
from modal_ai.runtime import app, frame_queues, image, result_queue, state_store
from modal_ai.settings import (
    API_WEBSOCKET_TIMEOUT_SECONDS,
    APP_NAME,
    DEFAULT_CONFIDENCE,
    DEFAULT_IMAGE_SIZE,
    DEFAULT_MODEL,
    FRAME_QUEUE_PREFIX,
    MAX_WORKER_DRAIN,
    NUM_SHARDS,
    RESULT_QUEUE_NAME,
    STATE_DICT_NAME,
    WORKER_SPAWN_EVERY_N_FRAMES,
)
from modal_ai.sharding import frame_queue_name, shard_id_for_camera
from modal_ai.time_utils import utc_iso
from modal_ai.viewer import VIEWER_HTML
from modal_ai.yolo import draw_and_detect


@app.cls(image=image, gpu="T4", timeout=300, scaledown_window=300, max_containers=NUM_SHARDS)
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
        publish_result(result)
        print(
            "Modal worker processed camera={} shard={} seq={} published=True".format(
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
    def process_next(self, shard_id: int = 0, max_items: int = MAX_WORKER_DRAIN) -> dict:
        processed = 0
        skipped = 0
        last_result = None
        active_key = "worker_active:{}".format(shard_id)
        try:
            while processed < max(1, max_items):
                try:
                    payload = frame_queues[shard_id].get(block=False)
                except queue.Empty:
                    break

                if payload is None:
                    break
                if not isinstance(payload, dict):
                    skipped += 1
                    continue

                last_result = self._process_payload_internal(payload, shard_id)
                processed += 1
        finally:
            state_store[active_key] = False

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

    async def spawn_worker_async(shard_id: int) -> bool:
        active_key = worker_active_key(shard_id)
        if await state_store.get.aio(active_key):
            return False
        await state_store.put.aio(active_key, True)
        try:
            await ModalYoloQueueWorker(model_name=DEFAULT_MODEL).process_next.spawn.aio(shard_id, MAX_WORKER_DRAIN)
            return True
        except Exception:
            # Worker spawn loi khong duoc lam dut WebSocket ingest. Frame van da
            # nam trong shard queue, frame sau se tiep tuc kich hoat worker.
            await state_store.put.aio(active_key, False)
            return False

    async def enqueue_payload_async(payload: dict) -> bool:
        shard_id = int(payload["shard_id"])
        await frame_queues[shard_id].put.aio(payload, block=False)
        sequence_number = int(payload["sequence_number"])
        worker_spawned = sequence_number <= 1 or sequence_number % WORKER_SPAWN_EVERY_N_FRAMES == 0
        if worker_spawned:
            # Khong await spawn trong receive loop, neu khong TCP/WebSocket bi
            # backpressure va Edge Gateway se gui frame cham hon target_fps.
            asyncio.create_task(spawn_worker_async(shard_id))
        return worker_spawned

    def enqueue_payload(payload: dict) -> bool:
        shard_id = int(payload["shard_id"])
        frame_queues[shard_id].put(payload, block=False)
        sequence_number = int(payload["sequence_number"])
        worker_spawned = sequence_number <= 1 or sequence_number % WORKER_SPAWN_EVERY_N_FRAMES == 0
        if worker_spawned:
            active_key = worker_active_key(shard_id)
            if not state_store.get(active_key):
                state_store[active_key] = True
                try:
                    ModalYoloQueueWorker(model_name=DEFAULT_MODEL).process_next.spawn(shard_id, MAX_WORKER_DRAIN)
                except Exception:
                    state_store[active_key] = False
                    raise
            else:
                worker_spawned = False
        return worker_spawned

    @web.get("/health")
    def health():
        return {
            "status": "ok",
            "service": APP_NAME,
            "queue_backend": "modal_queue_shards",
            "num_shards": NUM_SHARDS,
            "frame_queues": [frame_queue_name(FRAME_QUEUE_PREFIX, shard_id) for shard_id in range(NUM_SHARDS)],
            "result_queue": RESULT_QUEUE_NAME,
            "state": STATE_DICT_NAME,
            "timestamp": utc_iso(),
        }

    @web.get("/queues")
    def queues():
        return {
            "backend": "modal_queue_shards",
            "num_shards": NUM_SHARDS,
            "frame_queues": [frame_queue_name(FRAME_QUEUE_PREFIX, shard_id) for shard_id in range(NUM_SHARDS)],
            "active_workers": {
                str(shard_id): bool(state_store.get(worker_active_key(shard_id))) for shard_id in range(NUM_SHARDS)
            },
            "message": "Modal Queue does not expose exact queue length statistics.",
            "timestamp": utc_iso(),
        }

    @web.post("/ingest", status_code=202)
    def ingest(payload: dict):
        try:
            payload = normalize_payload(payload)
            worker_spawned = enqueue_payload(payload)
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
            "worker_spawned": worker_spawned,
            "modal_received_at": payload["modal_received_at"],
        }

    @web.websocket("/ingest")
    @web.websocket("/ws/ingest")
    async def websocket_ingest(websocket: WebSocket):
        await websocket.accept()
        accepted = 0
        try:
            while True:
                payload = await websocket.receive_json()
                try:
                    payload = normalize_payload(payload)
                    worker_spawned = await enqueue_payload_async(payload)
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
                            "worker_spawned": worker_spawned,
                            "accepted": accepted,
                            "timestamp": utc_iso(),
                        }
                    )
        except WebSocketDisconnect:
            return

    @web.websocket("/ws/results")
    async def websocket_results(websocket: WebSocket):
        await websocket.accept()
        try:
            snapshot = await asyncio.to_thread(latest_results_snapshot)
            for result in snapshot:
                await websocket.send_json({"type": "frame", "frame": result, "snapshot": True, "timestamp": utc_iso()})

            while True:
                try:
                    result = await result_queue.get.aio(block=False)
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue

                if result is None:
                    await asyncio.sleep(0.05)
                    continue

                await websocket.send_json({"type": "frame", "frame": result, "timestamp": utc_iso()})
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
