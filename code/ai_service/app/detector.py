from dataclasses import dataclass
from typing import List, Optional, Sequence

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


class NoopPersonDetector:
    def detect(self, frame: np.ndarray) -> List[Detection]:
        return []


class UltralyticsYoloPersonDetector:
    """Wrapper YOLO chỉ detect class person để phục vụ cảnh báo người."""

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.35,
        device: Optional[str] = None,
    ) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("YOLO mode requires ultralytics. Run: pip install -r requirements.txt") from exc

        self.model = YOLO(model_path)
        self.confidence_threshold = confidence_threshold
        self.device = device

    def detect(self, frame: np.ndarray) -> List[Detection]:
        # classes=[0] là class person trong COCO dataset của YOLO.
        kwargs = {
            "conf": self.confidence_threshold,
            "classes": [0],
            "verbose": False,
        }
        if self.device:
            kwargs["device"] = self.device

        # Inference YOLO chạy tại đây. Output được chuẩn hóa về dataclass Detection
        # để các tầng sau không phụ thuộc trực tiếp vào object của Ultralytics.
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


def draw_detections(frame: np.ndarray, detections: Sequence[Detection]) -> np.ndarray:
    display = frame.copy()
    for detection in detections:
        color = (32, 220, 80)
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


def build_person_detector(mode: str = "debug", model_path: str = "yolov8n.pt", confidence_threshold: float = 0.35, device: Optional[str] = None):
    normalized = mode.strip().lower()
    if normalized in ("debug", "none", "noop"):
        return NoopPersonDetector()
    if normalized == "yolo":
        return UltralyticsYoloPersonDetector(model_path, confidence_threshold, device)
    raise ValueError("Unsupported detector mode: {}".format(mode))
