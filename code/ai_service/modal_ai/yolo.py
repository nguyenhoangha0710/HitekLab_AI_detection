import base64
import time
from typing import List

from .settings import COCO_CLASS_IDS, DEFAULT_CONFIDENCE, DEFAULT_IMAGE_SIZE, DEFAULT_MODEL
from .time_utils import utc_iso


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
