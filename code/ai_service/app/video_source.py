from typing import Optional, Tuple

import cv2
import numpy as np


class RtspVideoSource:
    def __init__(self, source_url: str) -> None:
        self.source_url = source_url
        self._capture: Optional[cv2.VideoCapture] = None

    def open(self) -> bool:
        self.release()
        self._capture = cv2.VideoCapture(self.source_url, cv2.CAP_FFMPEG)
        return self.is_opened()

    def is_opened(self) -> bool:
        return bool(self._capture is not None and self._capture.isOpened())

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._capture is None:
            return False, None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            return False, None
        return True, frame

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
