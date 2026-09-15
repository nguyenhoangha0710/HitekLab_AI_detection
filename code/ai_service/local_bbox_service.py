import base64
import os
import threading
import time
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from local_ai.byte_tracker import MultiCameraByteTracker
from local_ai.detector import COCO_CLASS_IDS, parse_coco_class_filter
from modal_ai.time_utils import utc_iso


APP_NAME = "hitek-local-yolo11-bbox-ai-service"
DEFAULT_MODEL = os.getenv("LOCAL_YOLO_MODEL", "yolo11n.pt")
DEFAULT_CONFIDENCE = float(os.getenv("LOCAL_YOLO_CONFIDENCE", "0.35"))
DEFAULT_IMAGE_SIZE = int(os.getenv("LOCAL_YOLO_IMAGE_SIZE", "640"))
DEFAULT_CLASSES = os.getenv("LOCAL_YOLO_CLASSES", "person,car")
DEFAULT_DEVICE = os.getenv("LOCAL_YOLO_DEVICE") or None
DEFAULT_TRACK_IOU = float(os.getenv("LOCAL_TRACK_IOU", "0.3"))
DEFAULT_TRACK_BUFFER_FRAMES = int(os.getenv("LOCAL_TRACK_BUFFER_FRAMES", "45"))
DEFAULT_TRACK_HIGH_THRESH = float(os.getenv("LOCAL_TRACK_HIGH_THRESH", "0.5"))
DEFAULT_TRACK_LOW_THRESH = float(os.getenv("LOCAL_TRACK_LOW_THRESH", "0.1"))
DEFAULT_NEW_TRACK_THRESH = float(os.getenv("LOCAL_NEW_TRACK_THRESH", "0.5"))
DEFAULT_TRACK_MATCH_THRESH = float(os.getenv("LOCAL_TRACK_MATCH_THRESH", "0.8"))


class LocalYoloBboxDetector:
    """YOLOv11 bbox-only detector chay local, khong phu thuoc Modal."""

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        confidence_threshold: float = DEFAULT_CONFIDENCE,
        class_ids: Optional[List[int]] = None,
        device: Optional[str] = DEFAULT_DEVICE,
    ) -> None:
        from ultralytics import YOLO

        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.class_ids = class_ids or [COCO_CLASS_IDS["person"], COCO_CLASS_IDS["car"]]
        self.device = device
        self.model = YOLO(model_path)
        self.tracker = MultiCameraByteTracker(
            iou_threshold=DEFAULT_TRACK_IOU,
            max_missing_frames=DEFAULT_TRACK_BUFFER_FRAMES,
            track_high_thresh=DEFAULT_TRACK_HIGH_THRESH,
            track_low_thresh=DEFAULT_TRACK_LOW_THRESH,
            new_track_thresh=DEFAULT_NEW_TRACK_THRESH,
            match_thresh=DEFAULT_TRACK_MATCH_THRESH,
        )
        self._tracker_lock = threading.Lock()

    def detect(self, payload: Dict) -> Dict:
        import cv2
        import numpy as np

        started_at = time.monotonic()
        image_bytes = base64.b64decode(payload["image_b64"])
        frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Cannot decode image_b64 as an image.")

        confidence = float(payload.get("confidence", self.confidence_threshold))
        image_size = int(payload.get("imgsz", DEFAULT_IMAGE_SIZE))
        class_ids = _parse_class_ids(payload.get("classes", DEFAULT_CLASSES))

        kwargs = {
            "conf": confidence,
            "classes": class_ids,
            "imgsz": image_size,
            "verbose": False,
        }
        if self.device:
            kwargs["device"] = self.device

        results = self.model.predict(frame, **kwargs)
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

        camera_id = str(payload.get("camera_id"))
        sequence_number = int(payload.get("sequence_number", 0))
        # ByteTrack state phai tach theo camera_id. Moi detection sau YOLO se
        # duoc gan track_id de Rule Engine tinh thoi gian dung trong zone.
        with self._tracker_lock:
            detections = self.tracker.update(camera_id, detections, sequence_number)
            tracking_method = self.tracker.method_for_camera(camera_id)

        inference_ms = round((time.monotonic() - started_at) * 1000.0, 2)
        return {
            "tenant_id": payload.get("tenant_id"),
            "camera_id": camera_id,
            "location_id": payload.get("location_id"),
            "frame_id": payload.get("frame_id"),
            "sequence_number": sequence_number,
            "frame_width": int(payload.get("frame_width", frame.shape[1])),
            "frame_height": int(payload.get("frame_height", frame.shape[0])),
            "captured_at": payload.get("captured_at"),
            "edge_sent_at": payload.get("edge_sent_at"),
            "local_received_at": payload.get("local_received_at") or utc_iso(),
            "local_processed_at": utc_iso(),
            "modal_received_at": payload.get("local_received_at") or utc_iso(),
            "modal_processed_at": utc_iso(),
            "model": self.model_path,
            "classes": class_ids,
            "detections": detections,
            "detection_count": len(detections),
            "inference_ms": inference_ms,
            "tracking": {
                "enabled": True,
                "method": tracking_method,
                "iou_threshold": DEFAULT_TRACK_IOU,
                "max_missing_frames": DEFAULT_TRACK_BUFFER_FRAMES,
                "track_high_thresh": DEFAULT_TRACK_HIGH_THRESH,
                "track_low_thresh": DEFAULT_TRACK_LOW_THRESH,
                "new_track_thresh": DEFAULT_NEW_TRACK_THRESH,
                "match_thresh": DEFAULT_TRACK_MATCH_THRESH,
            },
        }


app = FastAPI(title="Hitek Local YOLOv11 BBox AI Service")
_detector: Optional[LocalYoloBboxDetector] = None
_detector_lock = threading.Lock()


def _parse_class_ids(value) -> List[int]:
    if value is None:
        return [COCO_CLASS_IDS["person"], COCO_CLASS_IDS["car"]]
    if isinstance(value, str):
        return parse_coco_class_filter(value)
    return parse_coco_class_filter(",".join(str(item) for item in value))


def _get_detector() -> LocalYoloBboxDetector:
    global _detector
    if _detector is not None:
        return _detector
    with _detector_lock:
        if _detector is None:
            _detector = LocalYoloBboxDetector(
                model_path=DEFAULT_MODEL,
                confidence_threshold=DEFAULT_CONFIDENCE,
                class_ids=_parse_class_ids(DEFAULT_CLASSES),
                device=DEFAULT_DEVICE,
            )
    return _detector


def normalize_payload(payload: Dict) -> Dict:
    required = ["camera_id", "frame_id", "sequence_number", "image_b64"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError("Missing required fields: {}".format(", ".join(missing)))

    payload["local_received_at"] = utc_iso()
    payload["sequence_number"] = int(payload["sequence_number"])
    payload.setdefault("classes", DEFAULT_CLASSES.split(","))
    payload.setdefault("confidence", DEFAULT_CONFIDENCE)
    payload.setdefault("imgsz", DEFAULT_IMAGE_SIZE)
    return payload


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": APP_NAME,
        "mode": "local-bbox-only",
        "model": DEFAULT_MODEL,
        "classes": DEFAULT_CLASSES.split(","),
        "device": DEFAULT_DEVICE or "auto",
        "tracking": {
            "enabled": True,
            "method": "ultralytics_bytetrack",
            "iou_threshold": DEFAULT_TRACK_IOU,
            "max_missing_frames": DEFAULT_TRACK_BUFFER_FRAMES,
            "track_high_thresh": DEFAULT_TRACK_HIGH_THRESH,
            "track_low_thresh": DEFAULT_TRACK_LOW_THRESH,
            "new_track_thresh": DEFAULT_NEW_TRACK_THRESH,
            "match_thresh": DEFAULT_TRACK_MATCH_THRESH,
        },
        "timestamp": utc_iso(),
    }


@app.post("/detect")
def detect(payload: Dict):
    try:
        payload = normalize_payload(payload)
        return _get_detector().detect(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.websocket("/ws/detect")
async def detect_websocket(websocket: WebSocket):
    await websocket.accept()
    accepted = 0
    try:
        while True:
            payload = await websocket.receive_json()
            try:
                payload = normalize_payload(payload)
                result = _get_detector().detect(payload)
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("local_bbox_service:app", host="0.0.0.0", port=8003, reload=False)
