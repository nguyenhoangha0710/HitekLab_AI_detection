import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, List, Optional, Set

import numpy as np

from .image_codec import frame_size
from .models import CameraQueueSummary, FrameMetadata
from .time_utils import to_iso_utc, utc_now


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
    dirty_requeues: int = 0
    latest_frame_id: Optional[str] = None
    last_consumed_frame_id: Optional[str] = None
    last_received_at: Optional[datetime] = None
    last_consumed_at: Optional[datetime] = None
    sequence_number: Optional[int] = None
    last_consumed_sequence_number: Optional[int] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None


class FrameQueueManager:
    """In-memory latest-frame store plus fair pending-camera queue.

    This backend is intentionally small for local tests and old local demos.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._latest_by_camera: Dict[str, FrameJob] = {}
        self._stats: Dict[str, _CameraQueueStats] = {}
        self._pending_queue: Deque[str] = deque()
        self._pending_set: Set[str] = set()
        self._processing_set: Set[str] = set()
        self._dirty_set: Set[str] = set()

    def clear(self) -> None:
        with self._condition:
            self._latest_by_camera.clear()
            self._stats.clear()
            self._pending_queue.clear()
            self._pending_set.clear()
            self._processing_set.clear()
            self._dirty_set.clear()
            self._condition.notify_all()

    def enqueue(self, job: FrameJob) -> CameraQueueSummary:
        with self._condition:
            camera_id = job.metadata.camera_id
            stats = self._stats.setdefault(
                camera_id,
                _CameraQueueStats(camera_id=camera_id, location_id=job.metadata.location_id),
            )

            previous = self._latest_by_camera.get(camera_id)
            if previous is not None and self._is_unconsumed(stats, previous):
                stats.dropped_frames += 1

            self._latest_by_camera[camera_id] = job
            stats.received_frames += 1
            stats.location_id = job.metadata.location_id
            stats.latest_frame_id = job.metadata.frame_id
            stats.last_received_at = job.received_at
            stats.sequence_number = job.metadata.sequence_number
            stats.image_width, stats.image_height = frame_size(job.frame)

            if camera_id in self._processing_set:
                self._dirty_set.add(camera_id)
            elif camera_id not in self._pending_set:
                self._add_pending(camera_id, stats)

            self._condition.notify_all()
            return self._summary(camera_id, stats)

    def consume(self, camera_id: str) -> Optional[FrameJob]:
        job = self.claim_camera(camera_id)
        if job is None:
            return None
        self.complete(job.metadata.camera_id, job.metadata.sequence_number, job.metadata.frame_id)
        return job

    def consume_batch(self, camera_id: str) -> List[FrameJob]:
        jobs = self.claim_camera_batch(camera_id)
        if not jobs:
            return []
        latest = jobs[-1]
        self.complete(latest.metadata.camera_id, latest.metadata.sequence_number, latest.metadata.frame_id)
        return jobs

    def claim_camera(self, camera_id: str) -> Optional[FrameJob]:
        jobs = self.claim_camera_batch(camera_id)
        if not jobs:
            return None
        return jobs[-1]

    def claim_camera_batch(self, camera_id: str) -> List[FrameJob]:
        with self._condition:
            if camera_id in self._processing_set:
                return []

            job = self._latest_by_camera.get(camera_id)
            stats = self._stats.get(camera_id)
            if job is None or stats is None or not self._is_unconsumed(stats, job):
                return []

            self._remove_pending(camera_id)
            self._dirty_set.discard(camera_id)
            self._processing_set.add(camera_id)
            return [job]

    def claim_next(self, timeout_seconds: Optional[float] = None) -> Optional[FrameJob]:
        jobs = self.claim_next_batch(timeout_seconds=timeout_seconds)
        if not jobs:
            return None
        return jobs[-1]

    def claim_next_batch(self, timeout_seconds: Optional[float] = None) -> List[FrameJob]:
        with self._condition:
            if timeout_seconds is None:
                while not self._pending_queue:
                    self._condition.wait()
            elif timeout_seconds > 0 and not self._pending_queue:
                self._condition.wait(timeout=timeout_seconds)

            while self._pending_queue:
                camera_id = self._pending_queue.popleft()
                self._pending_set.discard(camera_id)
                if camera_id in self._processing_set:
                    continue

                job = self._latest_by_camera.get(camera_id)
                stats = self._stats.get(camera_id)
                if job is None or stats is None or not self._is_unconsumed(stats, job):
                    continue

                self._dirty_set.discard(camera_id)
                self._processing_set.add(camera_id)
                return [job]

            return []

    def complete(self, camera_id: str, sequence_number: int, frame_id: str) -> CameraQueueSummary:
        with self._condition:
            stats = self._stats[camera_id]
            self._processing_set.discard(camera_id)
            stats.consumed_frames += 1
            stats.last_consumed_frame_id = frame_id
            stats.last_consumed_sequence_number = sequence_number
            stats.last_consumed_at = utc_now()

            latest = self._latest_by_camera.get(camera_id)
            has_newer_frame = latest is not None and latest.metadata.sequence_number > sequence_number
            if camera_id in self._dirty_set and has_newer_frame:
                self._dirty_set.discard(camera_id)
                self._add_pending(camera_id, stats)
                stats.dirty_requeues += 1
            else:
                self._dirty_set.discard(camera_id)

            self._condition.notify_all()
            return self._summary(camera_id, stats)

    def list_cameras(self) -> List[CameraQueueSummary]:
        with self._condition:
            return [self._summary(camera_id, stats) for camera_id, stats in sorted(self._stats.items())]

    def pending_camera_count(self) -> int:
        with self._condition:
            return len(self._pending_queue)

    def _add_pending(self, camera_id: str, stats: _CameraQueueStats) -> None:
        self._pending_set.add(camera_id)
        self._pending_queue.append(camera_id)
        stats.enqueued_frames += 1

    def _remove_pending(self, camera_id: str) -> None:
        if camera_id not in self._pending_set:
            return
        self._pending_set.discard(camera_id)
        try:
            self._pending_queue.remove(camera_id)
        except ValueError:
            pass

    def _is_unconsumed(self, stats: _CameraQueueStats, job: FrameJob) -> bool:
        return (
            stats.last_consumed_sequence_number is None
            or job.metadata.sequence_number > stats.last_consumed_sequence_number
        )

    def _summary(self, camera_id: str, stats: _CameraQueueStats) -> CameraQueueSummary:
        return CameraQueueSummary(
            camera_id=camera_id,
            location_id=stats.location_id,
            shard_id=0,
            queue_size=1 if camera_id in self._pending_set else 0,
            max_queue_size=1,
            buffered_frame_count=1 if stats.latest_frame_id else 0,
            frame_buffer_size=1,
            claim_batch_size=1,
            pending_camera_count=len(self._pending_queue),
            received_frames=stats.received_frames,
            enqueued_frames=stats.enqueued_frames,
            dropped_frames=stats.dropped_frames,
            consumed_frames=stats.consumed_frames,
            dirty_requeues=stats.dirty_requeues,
            latest_frame_id=stats.latest_frame_id,
            last_enqueued_frame_id=stats.latest_frame_id,
            last_consumed_frame_id=stats.last_consumed_frame_id,
            last_received_at=to_iso_utc(stats.last_received_at) if stats.last_received_at else None,
            last_consumed_at=to_iso_utc(stats.last_consumed_at) if stats.last_consumed_at else None,
            sequence_number=stats.sequence_number,
            last_consumed_sequence_number=stats.last_consumed_sequence_number,
            image_width=stats.image_width,
            image_height=stats.image_height,
            is_pending=camera_id in self._pending_set,
            is_processing=camera_id in self._processing_set,
            is_dirty=camera_id in self._dirty_set,
        )
