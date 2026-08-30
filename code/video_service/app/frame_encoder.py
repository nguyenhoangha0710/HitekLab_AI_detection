from typing import Tuple

import cv2
import numpy as np


def resize_frame(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    if frame.shape[1] == width and frame.shape[0] == height:
        return frame
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def encode_jpeg(frame: np.ndarray, quality: int = 85) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("Failed to encode frame as JPEG")
    return buffer.tobytes()


def frame_size(frame: np.ndarray) -> Tuple[int, int]:
    return int(frame.shape[1]), int(frame.shape[0])
