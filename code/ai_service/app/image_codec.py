from typing import Tuple

import cv2
import numpy as np


def decode_image(image_bytes: bytes) -> np.ndarray:
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("image cannot be decoded")
    return frame


def encode_jpeg(frame: np.ndarray, quality: int = 85) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("failed to encode image as JPEG")
    return buffer.tobytes()


def frame_size(frame: np.ndarray) -> Tuple[int, int]:
    return int(frame.shape[1]), int(frame.shape[0])


def draw_debug_overlay(frame: np.ndarray, label: str) -> np.ndarray:
    display = frame.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.55
    thickness = 1
    padding_x = 8
    padding_y = 6
    x = 10
    y = 24
    label = label[:120]
    text_size, _ = cv2.getTextSize(label, font, font_scale, thickness)
    box_width = min(text_size[0] + padding_x * 2, display.shape[1] - 20)
    box_height = text_size[1] + padding_y * 2
    overlay = display.copy()
    cv2.rectangle(overlay, (x, y - text_size[1] - padding_y), (x + box_width, y - text_size[1] - padding_y + box_height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.38, display, 0.62, 0, display)
    cv2.putText(display, label, (x + padding_x, y - 4), font, font_scale, (245, 245, 245), thickness, cv2.LINE_AA)
    return display
