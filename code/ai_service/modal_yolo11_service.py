import base64
import queue
import time
from datetime import datetime, timezone
from typing import Dict, List

import modal


APP_NAME = "hitek-yolo11-async-ai-server"
FRAME_QUEUE_NAME = "hitek-yolo11-ws-frame-queue-v2"
RESULT_QUEUE_NAME = "hitek-yolo11-ws-result-queue-v2"
STATE_DICT_NAME = "hitek-yolo11-ws-state-v2"
DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_CONFIDENCE = 0.35
DEFAULT_IMAGE_SIZE = 640
MAX_WORKER_DRAIN = 32
WORKER_SPAWN_EVERY_N_FRAMES = 4
API_WEBSOCKET_TIMEOUT_SECONDS = 3600
COCO_CLASS_IDS: Dict[str, int] = {
    "person": 0,
    "car": 2,
}


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("fastapi[standard]", "opencv-python-headless", "numpy", "ultralytics")
    .env({"YOLO_CONFIG_DIR": "/tmp/Ultralytics"})
)

app = modal.App(APP_NAME)
frame_queue = modal.Queue.from_name(FRAME_QUEUE_NAME, create_if_missing=True)
result_queue = modal.Queue.from_name(RESULT_QUEUE_NAME, create_if_missing=True)
state_store = modal.Dict.from_name(STATE_DICT_NAME, create_if_missing=True)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def latest_results_snapshot() -> List[dict]:
    values = []
    for key, value in state_store.items():
        if str(key).startswith("latest:"):
            values.append(value)
    values.sort(key=lambda item: str(item.get("camera_id", "")))
    return values


def parse_class_ids(value) -> List[int]:
    if value is None:
        return [COCO_CLASS_IDS["person"], COCO_CLASS_IDS["car"]]

    raw_items = value
    if isinstance(value, str):
        raw_items = value.split(",")

    class_ids: List[int] = []
    for raw_item in raw_items:
        item = str(raw_item).strip().lower()
        if not item:
            continue
        if item.isdigit():
            class_id = int(item)
        elif item in COCO_CLASS_IDS:
            class_id = COCO_CLASS_IDS[item]
        else:
            raise ValueError("Unsupported class '{}'. Use person, car, 0, or 2.".format(item))
        if class_id not in class_ids:
            class_ids.append(class_id)
    return class_ids or [COCO_CLASS_IDS["person"], COCO_CLASS_IDS["car"]]


def draw_and_detect(model, payload: dict) -> dict:
    import cv2
    import numpy as np

    modal_received_at = payload.get("modal_received_at") or utc_iso()
    started_at = time.monotonic()
    image_bytes = base64.b64decode(payload["image_b64"])
    np_buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Cannot decode image_b64 as an image.")

    confidence = float(payload.get("confidence", DEFAULT_CONFIDENCE))
    image_size = int(payload.get("imgsz", DEFAULT_IMAGE_SIZE))
    class_ids = parse_class_ids(payload.get("classes", ["person", "car"]))

    results = model.predict(
        frame,
        conf=confidence,
        classes=class_ids,
        imgsz=image_size,
        verbose=False,
    )

    detections = []
    result = results[0] if results else None
    names = result.names if result is not None else {}
    boxes = result.boxes if result is not None else None

    if boxes is not None:
        for box in boxes:
            class_id = int(box.cls[0].item())
            score = float(box.conf[0].item())
            x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
            detections.append(
                {
                    "class_id": class_id,
                    "class_name": str(names.get(class_id, class_id)),
                    "confidence": score,
                    "bbox_xyxy": [x1, y1, x2, y2],
                }
            )

            color = (32, 220, 80) if class_id == COCO_CLASS_IDS["person"] else (40, 170, 255)
            label = "{} {:.2f}".format(names.get(class_id, class_id), score)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    processed_at = utc_iso()
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    annotated_b64 = base64.b64encode(encoded.tobytes()).decode("ascii") if ok else None

    inference_ms = round((time.monotonic() - started_at) * 1000.0, 2)
    return {
        "tenant_id": payload.get("tenant_id"),
        "camera_id": payload.get("camera_id"),
        "location_id": payload.get("location_id"),
        "frame_id": payload.get("frame_id"),
        "sequence_number": payload.get("sequence_number"),
        "captured_at": payload.get("captured_at"),
        "edge_sent_at": payload.get("edge_sent_at"),
        "modal_received_at": modal_received_at,
        "modal_processed_at": processed_at,
        "model": payload.get("model", DEFAULT_MODEL),
        "classes": class_ids,
        "detections": detections,
        "detection_count": len(detections),
        "inference_ms": inference_ms,
        "image_b64": annotated_b64,
    }


@app.cls(image=image, gpu="T4", timeout=300, scaledown_window=300, max_containers=2)
class ModalYoloQueueWorker:
    model_name: str = modal.parameter(default=DEFAULT_MODEL)

    @modal.enter()
    def load_model(self):
        from ultralytics import YOLO

        self.model = YOLO(self.model_name)

    def _process_payload_internal(self, payload: dict) -> dict:
        result = draw_and_detect(self.model, payload)
        camera_id = result["camera_id"]
        if camera_id:
            state_store["latest:{}".format(camera_id)] = result
            state_store["stats:{}".format(camera_id)] = {
                "camera_id": camera_id,
                "last_frame_id": result.get("frame_id"),
                "last_sequence_number": result.get("sequence_number"),
                "last_processed_at": result.get("modal_processed_at"),
                "last_detection_count": result.get("detection_count"),
            }
        try:
            result_queue.put(result, block=False)
        except queue.Full:
            pass
        return result

    @modal.method()
    def process_payload(self, payload: dict) -> dict:
        return self._process_payload_internal(payload)

    @modal.method()
    def process_next(self, max_items: int = MAX_WORKER_DRAIN) -> dict:
        processed = 0
        skipped = 0
        last_result = None
        while processed < max(1, max_items):
            try:
                payload = frame_queue.get(block=False)
            except queue.Empty:
                break

            if payload is None:
                break
            if not isinstance(payload, dict):
                skipped += 1
                continue

            last_result = self._process_payload_internal(payload)
            processed += 1

        return {
            "status": "processed" if processed else "empty",
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
        return payload

    async def spawn_worker_async() -> None:
        try:
            await ModalYoloQueueWorker(model_name=DEFAULT_MODEL).process_next.spawn.aio(MAX_WORKER_DRAIN)
        except Exception:
            # Worker spawn loi khong duoc lam dut WebSocket ingest. Frame van da
            # nam trong Modal Queue, frame sau se tiep tuc kich hoat worker.
            pass

    async def enqueue_payload_async(payload: dict) -> bool:
        await frame_queue.put.aio(payload, block=False)
        sequence_number = int(payload["sequence_number"])
        worker_spawned = sequence_number <= 1 or sequence_number % WORKER_SPAWN_EVERY_N_FRAMES == 0
        if worker_spawned:
            # Khong await spawn trong receive loop, neu khong TCP/WebSocket bi
            # backpressure va Edge Gateway se gui frame cham hon target_fps.
            asyncio.create_task(spawn_worker_async())
        return worker_spawned

    def enqueue_payload(payload: dict) -> bool:
        frame_queue.put(payload, block=False)
        sequence_number = int(payload["sequence_number"])
        worker_spawned = sequence_number <= 1 or sequence_number % WORKER_SPAWN_EVERY_N_FRAMES == 0
        if worker_spawned:
            ModalYoloQueueWorker(model_name=DEFAULT_MODEL).process_next.spawn(MAX_WORKER_DRAIN)
        return worker_spawned

    @web.get("/health")
    def health():
        return {
            "status": "ok",
            "service": APP_NAME,
            "queue_backend": "modal_queue",
            "frame_queue": FRAME_QUEUE_NAME,
            "result_queue": RESULT_QUEUE_NAME,
            "state": STATE_DICT_NAME,
            "timestamp": utc_iso(),
        }

    @web.get("/queues")
    def queues():
        return {
            "backend": "modal_queue",
            "message": "Modal Queue does not expose per-camera queue statistics.",
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
        return HTMLResponse(
            """
            <!doctype html>
            <html>
              <head>
                <title>Modal YOLOv11 Result Viewer</title>
                <style>
                  body { margin: 0; font-family: Arial, sans-serif; background: #111; color: #eee; }
                  h1 { margin: 16px; font-size: 20px; }
                  main { padding: 16px; display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }
                  h2 { margin: 0 0 6px; font-size: 14px; }
                  p { margin: 0 0 8px; color: #bbb; font-size: 12px; }
                  img { width: 100%; aspect-ratio: 16 / 9; object-fit: contain; background: #000; border: 1px solid #333; }
                </style>
              </head>
              <body>
                <h1>Modal YOLOv11 Live Result Viewer</h1>
                <p id="status" style="margin: -8px 16px 0; color: #7dd3fc; font-size: 13px;">Connecting result WebSocket...</p>
                <main id="grid"></main>
                <script>
                  const grid = document.getElementById("grid");
                  const status = document.getElementById("status");
                  const sections = new Map();
                  function ensure(frame) {
                    let state = sections.get(frame.camera_id);
                    if (state) return state;
                    const section = document.createElement("section");
                    const title = document.createElement("h2");
                    const meta = document.createElement("p");
                    const img = document.createElement("img");
                    section.append(title, meta, img);
                    grid.append(section);
                    state = { title, meta, img };
                    sections.set(frame.camera_id, state);
                    return state;
                  }
                  function render(frame) {
                    const s = ensure(frame);
                    s.title.textContent = frame.camera_id;
                    s.meta.textContent = `seq ${frame.sequence_number} | detections ${frame.detection_count} | inference ${frame.inference_ms}ms | ${frame.modal_processed_at}`;
                    if (frame.image_b64) s.img.src = "data:image/jpeg;base64," + frame.image_b64;
                  }
                  function connectResults() {
                    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
                    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/results`);
                    socket.onopen = () => {
                      status.textContent = "Result WebSocket connected. Waiting for processed frames...";
                    };
                    socket.onmessage = (event) => {
                      const message = JSON.parse(event.data);
                      if (message.type === "frame") {
                        status.textContent = `Receiving live processed frames - ${message.timestamp}`;
                        render(message.frame);
                      }
                    };
                    socket.onclose = () => {
                      status.textContent = "Result WebSocket disconnected. Reconnecting...";
                      setTimeout(connectResults, 1000);
                    };
                    socket.onerror = () => {
                      status.textContent = "Result WebSocket error.";
                      socket.close();
                    };
                  }
                  connectResults();
                </script>
              </body>
            </html>
            """
        )

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
