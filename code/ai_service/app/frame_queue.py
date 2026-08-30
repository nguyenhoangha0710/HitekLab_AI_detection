import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, List, Optional

import numpy as np

from .image_codec import frame_size
from .models import CameraQueueSummary, FrameMetadata
from .time_utils import to_iso_utc


@dataclass(frozen=True)
class FrameJob:
    metadata: FrameMetadata
    frame: np.ndarray
    image_bytes: bytes
    received_at: datetime


@dataclass
class _CameraQueueStats:
    camera_id: str
    location_id: str
    received_frames: int = 0
    enqueued_frames: int = 0
    dropped_frames: int = 0
    consumed_frames: int = 0
    last_enqueued_frame_id: Optional[str] = None
    last_consumed_frame_id: Optional[str] = None
    last_received_at: Optional[datetime] = None
    last_consumed_at: Optional[datetime] = None
    sequence_number: Optional[int] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None


class FrameQueueManager:
    def __init__(self, max_size_per_camera: int = 2) -> None:
        self.max_size_per_camera = max(1, max_size_per_camera)
        self._lock = threading.Lock()
        self._queues: Dict[str, Deque[FrameJob]] = {}
        self._stats: Dict[str, _CameraQueueStats] = {}

    def clear(self) -> None:
        with self._lock:
            self._queues.clear()
            self._stats.clear()

    def enqueue(self, job: FrameJob) -> CameraQueueSummary:
        with self._lock:
            camera_id = job.metadata.camera_id
            queue = self._queues.setdefault(camera_id, deque())
            stats = self._stats.setdefault(
                camera_id,
                _CameraQueueStats(camera_id=camera_id, location_id=job.metadata.location_id),
            )

            stats.received_frames += 1
            if len(queue) >= self.max_size_per_camera:
                queue.popleft()
                stats.dropped_frames += 1

            queue.append(job)
            stats.enqueued_frames += 1
            stats.location_id = job.metadata.location_id
            stats.last_enqueued_frame_id = job.metadata.frame_id
            stats.last_received_at = job.received_at
            stats.sequence_number = job.metadata.sequence_number
            stats.image_width, stats.image_height = frame_size(job.frame)

            return self._summary(camera_id, queue, stats)

    def consume(self, camera_id: str) -> Optional[FrameJob]:
        with self._lock:
            queue = self._queues.get(camera_id)
            if not queue:
                return None

            job = queue.popleft()
            stats = self._stats[job.metadata.camera_id]
            stats.consumed_frames += 1
            stats.last_consumed_frame_id = job.metadata.frame_id
            stats.last_consumed_at = datetime.utcnow()
            return job

    def list_cameras(self) -> List[CameraQueueSummary]:
        with self._lock:
            summaries = []
            for camera_id, stats in self._stats.items():
                queue = self._queues.get(camera_id, deque())
                summaries.append(self._summary(camera_id, queue, stats))
            return sorted(summaries, key=lambda item: item.camera_id)

    def _summary(self, camera_id: str, queue: Deque[FrameJob], stats: _CameraQueueStats) -> CameraQueueSummary:
        return CameraQueueSummary(
            camera_id=camera_id,
            location_id=stats.location_id,
            queue_size=len(queue),
            max_queue_size=self.max_size_per_camera,
            received_frames=stats.received_frames,
            enqueued_frames=stats.enqueued_frames,
            dropped_frames=stats.dropped_frames,
            consumed_frames=stats.consumed_frames,
            last_enqueued_frame_id=stats.last_enqueued_frame_id,
            last_consumed_frame_id=stats.last_consumed_frame_id,
            last_received_at=to_iso_utc(stats.last_received_at) if stats.last_received_at else None,
            last_consumed_at=to_iso_utc(stats.last_consumed_at) if stats.last_consumed_at else None,
            sequence_number=stats.sequence_number,
            image_width=stats.image_width,
            image_height=stats.image_height,
        )
