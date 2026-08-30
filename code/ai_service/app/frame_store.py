import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from .image_codec import encode_jpeg, frame_size
from .models import CameraFrameSummary, FrameMetadata
from .time_utils import to_iso_utc


@dataclass(frozen=True)
class StoredFrame:
    metadata: FrameMetadata
    frame: np.ndarray
    image_bytes: bytes
    received_at: datetime
    frame_count: int


class FrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest_by_camera: Dict[str, StoredFrame] = {}
        self._counts_by_camera: Dict[str, int] = {}

    def clear(self) -> None:
        with self._lock:
            self._latest_by_camera.clear()
            self._counts_by_camera.clear()

    def update(self, metadata: FrameMetadata, frame: np.ndarray, image_bytes: bytes, received_at: datetime) -> StoredFrame:
        with self._lock:
            count = self._counts_by_camera.get(metadata.camera_id, 0) + 1
            self._counts_by_camera[metadata.camera_id] = count
            stored = StoredFrame(
                metadata=metadata,
                frame=frame,
                image_bytes=image_bytes,
                received_at=received_at,
                frame_count=count,
            )
            self._latest_by_camera[metadata.camera_id] = stored
            return stored

    def get_latest(self, camera_id: str) -> Optional[StoredFrame]:
        with self._lock:
            return self._latest_by_camera.get(camera_id)

    def list_cameras(self) -> List[CameraFrameSummary]:
        with self._lock:
            frames = list(self._latest_by_camera.values())

        summaries = []
        for stored in frames:
            width, height = frame_size(stored.frame)
            summaries.append(
                CameraFrameSummary(
                    camera_id=stored.metadata.camera_id,
                    location_id=stored.metadata.location_id,
                    last_frame_id=stored.metadata.frame_id,
                    last_received_at=to_iso_utc(stored.received_at),
                    sequence_number=stored.metadata.sequence_number,
                    frame_count=stored.frame_count,
                    image_width=width,
                    image_height=height,
                )
            )
        return sorted(summaries, key=lambda item: item.camera_id)

    def latest_jpeg(self, camera_id: str) -> Optional[bytes]:
        stored = self.get_latest(camera_id)
        if stored is None:
            return None
        return encode_jpeg(stored.frame)
