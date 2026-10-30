from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int


COCO_CLASS_IDS: Dict[str, int] = {
    "person": 0,
    "bicycle": 1,
    "car": 2,
    "motorcycle": 3,
    "bus": 5,
    "truck": 7,
}


class NoopPersonDetector:
    def detect(self, frame: np.ndarray) -> List[Detection]:
        return []


def parse_coco_class_filter(value: str) -> List[int]:
    """Parse class filter tu CLI, vi du: "person,car" hoac "0,2"."""
    class_ids: List[int] = []
    for raw_item in value.split(","):
        item = raw_item.strip().lower()
        if not item:
            continue
        if item.isdigit():
            class_id = int(item)
        elif item in COCO_CLASS_IDS:
            class_id = COCO_CLASS_IDS[item]
        else:
            supported = ", ".join(sorted(COCO_CLASS_IDS))
            raise ValueError("Unsupported YOLO class '{}'. Supported names: {} or numeric class ids.".format(item, supported))
        if class_id not in class_ids:
            class_ids.append(class_id)
    if not class_ids:
        raise ValueError("At least one YOLO class must be configured.")
    return class_ids


class UltralyticsYoloObjectDetector:
    """Wrapper YOLOv11/Ultralytics, mac dinh chi detect person va car."""

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence_threshold: float = 0.35,
        class_ids: Optional[Iterable[int]] = None,
        device: Optional[str] = None,
    ) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("YOLO mode requires ultralytics. Run: pip install -r requirements-yolo.txt") from exc

        self.model = YOLO(model_path)
        self.confidence_threshold = confidence_threshold
        self.class_ids = list(class_ids or [COCO_CLASS_IDS["person"], COCO_CLASS_IDS["car"]])
        self.device = device

    def detect(self, frame: np.ndarray) -> List[Detection]:
        # COCO class filter: person=0, car=2. YOLO chi tra ve cac class nay.
        kwargs = {
            "conf": self.confidence_threshold,
            "classes": self.class_ids,
            "verbose": False,
        }
        if self.device:
            kwargs["device"] = self.device

        # Inference YOLO chay tai day. Output duoc chuan hoa thanh Detection
        # de cac tang sau khong phu thuoc truc tiep vao object cua Ultralytics.
        results = self.model.predict(frame, **kwargs)
        detections: List[Detection] = []
        if not results:
            return detections

        result = results[0]
        names = result.names or {}
        if result.boxes is None:
            return detections

        for box in result.boxes:
            class_id = int(box.cls[0].item())
            confidence = float(box.conf[0].item())
            x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
            detections.append(
                Detection(
                    class_id=class_id,
                    class_name=str(names.get(class_id, class_id)),
                    confidence=confidence,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                )
            )
        return detections


def summarize_detections(detections: Sequence[Detection]) -> str:
    counts: Dict[str, int] = {}
    for detection in detections:
        counts[detection.class_name] = counts.get(detection.class_name, 0) + 1
    if not counts:
        return "objects 0"
    return " ".join("{} {}".format(name, counts[name]) for name in sorted(counts))


def draw_detections(frame: np.ndarray, detections: Sequence[Detection]) -> np.ndarray:
    display = frame.copy()
    for detection in detections:
        color = (32, 220, 80) if detection.class_name == "person" else (40, 170, 255)
        cv2.rectangle(display, (detection.x1, detection.y1), (detection.x2, detection.y2), color, 2)
        label = "{} {:.2f}".format(detection.class_name, detection.confidence)
        text_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        label_y = max(18, detection.y1)
        cv2.rectangle(
            display,
            (detection.x1, label_y - text_size[1] - 6),
            (detection.x1 + text_size[0] + 8, label_y + 2),
            color,
            -1,
        )
        cv2.putText(
            display,
            label,
            (detection.x1 + 4, label_y - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    return display


def build_person_detector(
    mode: str = "debug",
    model_path: str = "yolo11n.pt",
    confidence_threshold: float = 0.35,
    device: Optional[str] = None,
    yolo_classes: str = "person,car,motorcycle",
):
    normalized = mode.strip().lower()
    if normalized in ("debug", "none", "noop"):
        return NoopPersonDetector()
    if normalized == "yolo":
        return UltralyticsYoloObjectDetector(
            model_path=model_path,
            confidence_threshold=confidence_threshold,
            class_ids=parse_coco_class_filter(yolo_classes),
            device=device,
        )
    raise ValueError("Unsupported detector mode: {}".format(mode))
