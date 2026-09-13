import atexit
import base64
import os
import queue
import sys

import modal

from modal_ai.settings import NUM_SHARDS, QUEUE_VERSION, RESULT_QUEUE_LIMIT, VIEWER_CAMERA_IDS
from modal_ai.sharding import frame_queue_name, shard_id_for_camera
from modal_ai.time_utils import utc_iso
from modal_ai.viewer import CAMERA_VIEWER_HTML, VIEWER_HTML


APP_NAME = "hitek-frame-passthrough-ai-server"
RESULT_QUEUE_PREFIX = "hitek-passthrough-result-shard-queue-{}".format(QUEUE_VERSION)
STATE_DICT_NAME = "hitek-passthrough-state-{}".format(QUEUE_VERSION)


image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi[standard]")
    .env(
        {
            "MODAL_QUEUE_VERSION_FIXED": QUEUE_VERSION,
            "MODAL_VIEWER_CAMERA_IDS": ",".join(VIEWER_CAMERA_IDS),
        }
    )
    .add_local_python_source("modal_ai")
)

app = modal.App(APP_NAME)
result_queues = [
    modal.Queue.from_name(frame_queue_name(RESULT_QUEUE_PREFIX, shard_id), create_if_missing=True)
    for shard_id in range(NUM_SHARDS)
]
state_store = modal.Dict.from_name(STATE_DICT_NAME, create_if_missing=True)


def _is_local_modal_serve_process() -> bool:
    return os.getenv("MODAL_IS_REMOTE") != "1" and "serve" in sys.argv


def _delete_runtime_objects_sync(reason: str) -> None:
    queue_names = [
        frame_queue_name(RESULT_QUEUE_PREFIX, shard_id)
        for shard_id in range(NUM_SHARDS)
    ]
    for queue_name in queue_names:
        modal.Queue.objects.delete(queue_name, allow_missing=True)
    modal.Dict.objects.delete(STATE_DICT_NAME, allow_missing=True)
    print(
        "Passthrough runtime objects deleted version={} reason={} queues={} state={}".format(
            QUEUE_VERSION,
            reason,
            ",".join(queue_names),
            STATE_DICT_NAME,
        )
    )


def _clear_runtime_data_sync(reason: str) -> None:
    for result_queue in result_queues:
        result_queue.clear()
    state_store.clear()
    print("Passthrough runtime cleared version={} reason={}".format(QUEUE_VERSION, reason))


def _clear_runtime_data_on_local_exit() -> None:
    try:
        _delete_runtime_objects_sync("local_modal_serve_exit")
    except Exception as exc:
        print("Passthrough runtime delete failed version={} error={}".format(QUEUE_VERSION, exc))
        try:
            _clear_runtime_data_sync("local_modal_serve_exit_fallback_clear")
        except Exception as fallback_exc:
            print("Passthrough runtime fallback clear failed version={} error={}".format(QUEUE_VERSION, fallback_exc))


if _is_local_modal_serve_process():
    try:
        _delete_runtime_objects_sync("local_modal_serve_start")
    except Exception as exc:
        print("Passthrough runtime start delete skipped version={} error={}".format(QUEUE_VERSION, exc))
    atexit.register(_clear_runtime_data_on_local_exit)


def latest_results_snapshot():
    values = []
    for key, value in state_store.items():
        if str(key).startswith("latest:"):
            values.append(value)
    values.sort(key=lambda item: str(item.get("camera_id", "")))
    return values


def publish_result(result: dict, shard_id: int) -> None:
    camera_id = result["camera_id"]
    state_store["latest:{}".format(camera_id)] = result
    state_store["stats:{}".format(camera_id)] = {
        "camera_id": camera_id,
        "last_frame_id": result.get("frame_id"),
        "last_sequence_number": result.get("sequence_number"),
        "last_processed_at": result.get("modal_processed_at"),
        "last_detection_count": result.get("detection_count"),
    }

    result_queue = result_queues[shard_id]
    try:
        current_size = result_queue.len()
        drop_count = max(0, current_size - RESULT_QUEUE_LIMIT + 1)
        if drop_count:
            result_queue.get_many(drop_count, block=False)
        result_queue.put(result, block=False)
    except queue.Full:
        pass


async def publish_result_async(result: dict, shard_id: int) -> None:
    camera_id = result["camera_id"]
    await state_store.put.aio("latest:{}".format(camera_id), result)
    await state_store.put.aio(
        "stats:{}".format(camera_id),
        {
            "camera_id": camera_id,
            "last_frame_id": result.get("frame_id"),
            "last_sequence_number": result.get("sequence_number"),
            "last_processed_at": result.get("modal_processed_at"),
            "last_detection_count": result.get("detection_count"),
        },
    )

    result_queue = result_queues[shard_id]
    try:
        current_size = await result_queue.len.aio()
        drop_count = max(0, current_size - RESULT_QUEUE_LIMIT + 1)
        if drop_count:
            await result_queue.get_many.aio(drop_count, block=False)
        await result_queue.put.aio(result, block=False)
    except queue.Full:
        pass


def make_passthrough_result(payload: dict) -> dict:
    shard_id = int(payload["shard_id"])
    return {
        "tenant_id": payload.get("tenant_id"),
        "camera_id": payload.get("camera_id"),
        "location_id": payload.get("location_id"),
        "frame_id": payload.get("frame_id"),
        "sequence_number": payload.get("sequence_number"),
        "captured_at": payload.get("captured_at"),
        "edge_sent_at": payload.get("edge_sent_at"),
        "modal_received_at": payload.get("modal_received_at"),
        "modal_processed_at": utc_iso(),
        "model": "passthrough-no-yolo",
        "classes": [],
        "detections": [],
        "detection_count": 0,
        "inference_ms": 0.0,
        "image_b64": payload.get("image_b64"),
        "shard_id": shard_id,
        "worker_id": "passthrough-api-{}".format(shard_id),
    }


@app.function(image=image, timeout=3600)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def api():
    import asyncio

    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse

    web = FastAPI(title="Hitek Modal Frame Passthrough AI Server")

    def normalize_payload(payload: dict) -> dict:
        required = ["camera_id", "frame_id", "sequence_number", "image_b64"]
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError("Missing required fields: {}".format(", ".join(missing)))

        payload["modal_received_at"] = utc_iso()
        payload["sequence_number"] = int(payload["sequence_number"])
        payload["shard_id"] = shard_id_for_camera(str(payload["camera_id"]), NUM_SHARDS)
        return payload

    async def clear_runtime_data_async(reason: str) -> None:
        for result_queue in result_queues:
            await result_queue.clear.aio()
        await state_store.clear.aio()
        print("Passthrough runtime cleared version={} reason={}".format(QUEUE_VERSION, reason))

    def publish_payload(payload: dict) -> dict:
        result = make_passthrough_result(payload)
        publish_result(result, int(result["shard_id"]))
        print(
            "Passthrough published version={} camera={} shard={} seq={}".format(
                QUEUE_VERSION,
                result.get("camera_id"),
                result.get("shard_id"),
                result.get("sequence_number"),
            )
        )
        return result

    async def publish_payload_async(payload: dict) -> dict:
        result = make_passthrough_result(payload)
        await publish_result_async(result, int(result["shard_id"]))
        print(
            "Passthrough published version={} camera={} shard={} seq={}".format(
                QUEUE_VERSION,
                result.get("camera_id"),
                result.get("shard_id"),
                result.get("sequence_number"),
            )
        )
        return result

    @web.get("/health")
    def health():
        return {
            "status": "ok",
            "service": APP_NAME,
            "mode": "passthrough-no-yolo",
            "queue_backend": "modal_result_queues_only",
            "queue_version": QUEUE_VERSION,
            "num_shards": NUM_SHARDS,
            "result_queue_limit": RESULT_QUEUE_LIMIT,
            "result_queues": [frame_queue_name(RESULT_QUEUE_PREFIX, shard_id) for shard_id in range(NUM_SHARDS)],
            "state": STATE_DICT_NAME,
            "timestamp": utc_iso(),
        }

    @web.get("/queues")
    def queues():
        return {
            "backend": "modal_result_queues_only",
            "mode": "passthrough-no-yolo",
            "queue_version": QUEUE_VERSION,
            "num_shards": NUM_SHARDS,
            "result_queue_limit": RESULT_QUEUE_LIMIT,
            "result_queue_lengths": {
                str(shard_id): result_queues[shard_id].len() for shard_id in range(NUM_SHARDS)
            },
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
            result = publish_payload(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "status": "accepted",
            "mode": "passthrough-no-yolo",
            "camera_id": result["camera_id"],
            "frame_id": result["frame_id"],
            "sequence_number": result["sequence_number"],
            "shard_id": result["shard_id"],
            "modal_received_at": result["modal_received_at"],
        }

    @web.websocket("/ingest")
    @web.websocket("/ws/ingest")
    async def websocket_ingest(websocket: WebSocket):
        await websocket.accept()
        await clear_runtime_data_async("websocket_ingest_start")
        accepted = 0
        try:
            while True:
                payload = await websocket.receive_json()
                try:
                    payload = normalize_payload(payload)
                    result = await publish_payload_async(payload)
                except Exception as exc:
                    if isinstance(payload, dict) and payload.get("ack"):
                        await websocket.send_json({"type": "error", "detail": str(exc), "timestamp": utc_iso()})
                    continue

                accepted += 1
                if payload.get("ack"):
                    await websocket.send_json(
                        {
                            "type": "accepted",
                            "mode": "passthrough-no-yolo",
                            "camera_id": result["camera_id"],
                            "frame_id": result["frame_id"],
                            "sequence_number": result["sequence_number"],
                            "shard_id": result["shard_id"],
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
                    await asyncio.sleep(0.02)
                    continue

                if result is None:
                    await asyncio.sleep(0.02)
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
                    await asyncio.sleep(0.02)
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
def main(image_path: str = ""):
    if not image_path:
        print("Dev server: modal serve code/ai_service/modal_passthrough_service.py")
        print("Viewer:     https://<modal-app-url>/viewer")
        return

    with open(image_path, "rb") as image_file:
        image_b64 = base64.b64encode(image_file.read()).decode("ascii")

    payload = {
        "camera_id": "local-test-camera",
        "location_id": "local-test-location",
        "frame_id": "local-test-frame",
        "sequence_number": 1,
        "image_b64": image_b64,
        "captured_at": utc_iso(),
        "edge_sent_at": utc_iso(),
    }
    payload["shard_id"] = shard_id_for_camera(payload["camera_id"], NUM_SHARDS)
    print(make_passthrough_result(payload))
