import base64
import os
import socket
import threading
import time
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from common.time_utils import to_iso_utc, utc_now
from local_ai.byte_tracker import MultiCameraByteTracker
from local_ai.detector import COCO_CLASS_IDS, parse_coco_class_filter
from local_ai.motion import MotionEstimator, MotionSettings
from rule_engine import AiEventPublisher, RuleEngine, RuleEngineSettings, ZoneServiceConfigProvider


APP_NAME = "hitek-ai-service"
DEFAULT_MODEL = os.getenv("LOCAL_YOLO_MODEL", "yolo11n.pt")
DEFAULT_CONFIDENCE = float(os.getenv("LOCAL_YOLO_CONFIDENCE", "0.35"))
DEFAULT_IMAGE_SIZE = int(os.getenv("LOCAL_YOLO_IMAGE_SIZE", "640"))
DEFAULT_CLASSES = os.getenv("LOCAL_YOLO_CLASSES", "person,car,motorcycle")
DEFAULT_DEVICE = os.getenv("LOCAL_YOLO_DEVICE") or None
DEFAULT_TRACK_IOU = float(os.getenv("LOCAL_TRACK_IOU", "0.3"))
DEFAULT_TRACK_BUFFER_FRAMES = int(os.getenv("LOCAL_TRACK_BUFFER_FRAMES", "45"))
DEFAULT_TRACK_HIGH_THRESH = float(os.getenv("LOCAL_TRACK_HIGH_THRESH", "0.5"))
DEFAULT_TRACK_LOW_THRESH = float(os.getenv("LOCAL_TRACK_LOW_THRESH", "0.1"))
DEFAULT_NEW_TRACK_THRESH = float(os.getenv("LOCAL_NEW_TRACK_THRESH", "0.5"))
DEFAULT_TRACK_MATCH_THRESH = float(os.getenv("LOCAL_TRACK_MATCH_THRESH", "0.8"))

# Rule Engine: lay zone/rule tu Zone Service va gui AI Event nguoc lai Zone Service.
RULE_ENGINE_ENABLED = os.getenv("RULE_ENGINE_ENABLED", "true").lower() in {"1", "true", "yes"}
ZONE_SERVICE_URL = os.getenv("ZONE_SERVICE_URL", "http://localhost:8010").rstrip("/")
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY") or None
RULE_CONFIG_TTL_SECONDS = float(os.getenv("RULE_CONFIG_TTL_SECONDS", "10"))
RULE_EVENT_HEARTBEAT_SECONDS = float(os.getenv("RULE_EVENT_HEARTBEAT_SECONDS", "1"))
RULE_STATE_EXPIRE_SECONDS = float(os.getenv("RULE_STATE_EXPIRE_SECONDS", "5"))
RULE_TIMEZONE_OFFSET_HOURS = float(os.getenv("RULE_TIMEZONE_OFFSET_HOURS", "7"))

# Huong di chuyen: tinh tu lich su vi tri chan cua tung track trong MOTION_WINDOW_SECONDS.
MOTION_WINDOW_SECONDS = float(os.getenv("MOTION_WINDOW_SECONDS", "1.0"))
MOTION_STATIONARY_SPEED_RATIO = float(os.getenv("MOTION_STATIONARY_SPEED_RATIO", "0.02"))


# Nhan hien thi noi AI dang chay (vd "khoa-gpu", "laptop-ha"). Mac dinh = hostname.
AI_HOST_LABEL = os.getenv("AI_HOST_LABEL") or socket.gethostname()


def utc_iso() -> str:
    return to_iso_utc(utc_now())


def detect_runtime(device: Optional[str] = DEFAULT_DEVICE) -> Dict:
    """AI dang chay tren CPU hay GPU nao, o may nao. Gan vao /health va moi ket qua frame."""
    info = {"host": AI_HOST_LABEL, "device": "cpu", "device_name": "CPU", "accelerator": "cpu", "cuda_available": False}
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        wants_cpu = str(device or "").lower() == "cpu"
        if info["cuda_available"] and not wants_cpu:
            index = int(device) if str(device or "").isdigit() else 0
            if str(device or "").startswith("cuda:"):
                index = int(str(device).split(":", 1)[1] or 0)
            info["device"] = "cuda:{}".format(index)
            info["device_name"] = torch.cuda.get_device_name(index)
            info["accelerator"] = "gpu"
    except Exception as exc:  # torch chua cai (vd chay test)
        info["error"] = str(exc)
    return info


_runtime_info: Optional[Dict] = None


def runtime_info() -> Dict:
    global _runtime_info
    if _runtime_info is None:
        _runtime_info = detect_runtime()
    return _runtime_info


class LocalYoloBboxDetector:
    """YOLOv11 detector + ByteTrack chay local (GPU neu co)."""

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
        self.class_ids = class_ids or [COCO_CLASS_IDS["person"], COCO_CLASS_IDS["car"], COCO_CLASS_IDS["motorcycle"]]
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


app = FastAPI(title="Hitek AI Service (YOLOv11 + ByteTrack + Rule Engine)")
_detector: Optional[LocalYoloBboxDetector] = None
_detector_lock = threading.Lock()
_rule_engine: Optional[RuleEngine] = None
_rule_engine_lock = threading.Lock()
_motion = MotionEstimator(
    MotionSettings(window_seconds=MOTION_WINDOW_SECONDS, stationary_speed_ratio=MOTION_STATIONARY_SPEED_RATIO)
)
_motion_lock = threading.Lock()


def _parse_class_ids(value) -> List[int]:
    if value is None:
        return parse_coco_class_filter(DEFAULT_CLASSES)
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


def _get_rule_engine() -> Optional[RuleEngine]:
    global _rule_engine
    if not RULE_ENGINE_ENABLED:
        return None
    if _rule_engine is not None:
        return _rule_engine
    with _rule_engine_lock:
        if _rule_engine is None:
            _rule_engine = RuleEngine(
                config_provider=ZoneServiceConfigProvider(
                    ZONE_SERVICE_URL, ttl_seconds=RULE_CONFIG_TTL_SECONDS, service_api_key=SERVICE_API_KEY
                ),
                publisher=AiEventPublisher("{}/api/ai-events".format(ZONE_SERVICE_URL), service_api_key=SERVICE_API_KEY),
                settings=RuleEngineSettings(
                    heartbeat_seconds=RULE_EVENT_HEARTBEAT_SECONDS,
                    state_expire_seconds=RULE_STATE_EXPIRE_SECONDS,
                    timezone_offset_hours=RULE_TIMEZONE_OFFSET_HOURS,
                    model_name=os.path.splitext(os.path.basename(DEFAULT_MODEL))[0],
                ),
            )
    return _rule_engine


def analyze_frame(payload: Dict) -> Dict:
    """YOLO -> ByteTrack -> huong di chuyen -> Rule Engine cho 1 frame."""
    result = _get_detector().detect(payload)
    with _motion_lock:
        _motion.update(result)
    runtime = runtime_info()
    result["ai_runtime"] = {
        "host": runtime["host"],
        "accelerator": runtime["accelerator"],
        "device": runtime["device"],
        "device_name": runtime["device_name"],
    }
    engine = _get_rule_engine()
    if engine is None:
        result["rule_engine"] = {"enabled": False, "violations": []}
    else:
        result["rule_engine"] = engine.process(result)
    return result


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
        "mode": "local-yolo-bytetrack-rules",
        "model": DEFAULT_MODEL,
        "classes": DEFAULT_CLASSES.split(","),
        "device": DEFAULT_DEVICE or "auto",
        "runtime": runtime_info(),
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
        "motion": {
            "enabled": True,
            "window_seconds": MOTION_WINDOW_SECONDS,
            "stationary_speed_ratio": MOTION_STATIONARY_SPEED_RATIO,
        },
        "rule_engine": _rule_engine_status(),
        "timestamp": utc_iso(),
    }


def _rule_engine_status() -> Dict:
    if not RULE_ENGINE_ENABLED:
        return {"enabled": False}
    engine = _get_rule_engine()
    return {
        "enabled": True,
        "zone_service_url": ZONE_SERVICE_URL,
        "heartbeat_seconds": RULE_EVENT_HEARTBEAT_SECONDS,
        "engine": engine.snapshot(),
        "config": engine.config_provider.stats(),
        "publisher": engine.publisher.stats(),
    }


@app.get("/rules/status")
def rules_status():
    return _rule_engine_status()


@app.post("/rules/reload")
def rules_reload(camera_id: Optional[str] = None):
    """Xoa cache zone/rule de AI Service tai lai ngay (goi sau khi sua zone)."""
    engine = _get_rule_engine()
    if engine is None:
        raise HTTPException(status_code=409, detail="Rule engine is disabled.")
    engine.config_provider.invalidate(camera_id)
    return {"status": "ok", "camera_id": camera_id, "timestamp": utc_iso()}


@app.on_event("shutdown")
def _shutdown_rule_engine():
    if _rule_engine is not None:
        _rule_engine.publisher.close()


@app.post("/detect")
def detect(payload: Dict):
    try:
        payload = normalize_payload(payload)
        return analyze_frame(payload)
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
                result = analyze_frame(payload)
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
