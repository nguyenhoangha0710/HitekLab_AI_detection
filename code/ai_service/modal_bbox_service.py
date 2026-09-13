import base64
import time
from typing import Dict, List

import modal

from modal_ai.settings import COCO_CLASS_IDS, DEFAULT_CONFIDENCE, DEFAULT_IMAGE_SIZE
from modal_ai.time_utils import utc_iso


APP_NAME = "hitek-yolo11-bbox-ai-service"
DEFAULT_MODEL = "yolo11n.pt"


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("fastapi[standard]", "opencv-python-headless", "numpy", "ultralytics")
    .env({"YOLO_CONFIG_DIR": "/tmp/Ultralytics"})
    .add_local_python_source("modal_ai")
)

app = modal.App(APP_NAME)


def parse_class_ids(value) -> List[int]:
    if value is None:
        return [COCO_CLASS_IDS["person"], COCO_CLASS_IDS["car"]]

    raw_items = value.split(",") if isinstance(value, str) else value
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


@app.cls(image=image, gpu="L4", timeout=300)
class Yolo11BboxDetector:
    model_name: str = modal.parameter(default=DEFAULT_MODEL)

    @modal.enter()
    def load_model(self):
        from ultralytics import YOLO

        self.model = YOLO(self.model_name)

    @modal.method()
    def detect(self, payload: Dict) -> Dict:
        import cv2
        import numpy as np

        started_at = time.monotonic()
        image_bytes = base64.b64decode(payload["image_b64"])
        frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Cannot decode image_b64 as an image.")

        confidence = float(payload.get("confidence", DEFAULT_CONFIDENCE))
        image_size = int(payload.get("imgsz", DEFAULT_IMAGE_SIZE))
        class_ids = parse_class_ids(payload.get("classes", ["person", "car"]))

        results = self.model.predict(
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

        inference_ms = round((time.monotonic() - started_at) * 1000.0, 2)
        return {
            "tenant_id": payload.get("tenant_id"),
            "camera_id": payload.get("camera_id"),
            "location_id": payload.get("location_id"),
            "frame_id": payload.get("frame_id"),
            "sequence_number": int(payload.get("sequence_number", 0)),
            "frame_width": int(payload.get("frame_width", frame.shape[1])),
            "frame_height": int(payload.get("frame_height", frame.shape[0])),
            "captured_at": payload.get("captured_at"),
            "edge_sent_at": payload.get("edge_sent_at"),
            "modal_received_at": payload.get("modal_received_at") or utc_iso(),
            "modal_processed_at": utc_iso(),
            "model": self.model_name,
            "classes": class_ids,
            "detections": detections,
            "detection_count": len(detections),
            "inference_ms": inference_ms,
        }


detector = Yolo11BboxDetector(model_name=DEFAULT_MODEL)


@app.function(image=image, timeout=3600)
@modal.asgi_app()
def api():
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

    web = FastAPI(title="Hitek YOLOv11 BBox AI Service")

    def normalize_payload(payload: Dict) -> Dict:
        required = ["camera_id", "frame_id", "sequence_number", "image_b64"]
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError("Missing required fields: {}".format(", ".join(missing)))

        payload["modal_received_at"] = utc_iso()
        payload["sequence_number"] = int(payload["sequence_number"])
        payload.setdefault("classes", ["person", "car"])
        payload.setdefault("confidence", DEFAULT_CONFIDENCE)
        payload.setdefault("imgsz", DEFAULT_IMAGE_SIZE)
        return payload

    @web.get("/health")
    def health():
        return {
            "status": "ok",
            "service": APP_NAME,
            "mode": "bbox-only",
            "model": DEFAULT_MODEL,
            "classes": ["person", "car"],
            "timestamp": utc_iso(),
        }

    @web.post("/detect")
    def detect(payload: Dict):
        try:
            payload = normalize_payload(payload)
            return detector.detect.remote(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @web.websocket("/ws/detect")
    async def detect_websocket(websocket: WebSocket):
        await websocket.accept()
        accepted = 0
        try:
            while True:
                payload = await websocket.receive_json()
                try:
                    payload = normalize_payload(payload)
                    result = await detector.detect.remote.aio(payload)
                except Exception as exc:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "detail": str(exc),
                            "timestamp": utc_iso(),
                        }
                    )
                    continue

                accepted += 1
                await websocket.send_json(
                    {
                        "type": "result",
                        "accepted": accepted,
                        "result": result,
                        "timestamp": utc_iso(),
                    }
                )
        except WebSocketDisconnect:
            return

    return web


@app.local_entrypoint()
def main(image_path: str = ""):
    if not image_path:
        print("Serve:  modal serve code/ai_service/modal_bbox_service.py")
        print("Detect: POST https://<modal-url>/detect")
        print("WS:     wss://<modal-url>/ws/detect")
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
        "confidence": DEFAULT_CONFIDENCE,
    }
    print(detector.detect.remote(payload))
