import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, List, Optional

import numpy as np

from common.frame_job import FrameJob
from common.image_codec import encode_jpeg, frame_size
from common.models import FrameMetadata, ProcessedFrameSummary
from common.time_utils import to_iso_utc


@dataclass(frozen=True)
class ProcessedFrame:
    metadata: FrameMetadata
    frame: np.ndarray
    image_bytes: bytes
    processed_at: datetime
    worker_id: str
    shard_id: int


class MemoryResultStore:
    def __init__(self, processed_stream_buffer_size: int = 120) -> None:
        self._lock = threading.Lock()
        self._frames: Dict[str, ProcessedFrame] = {}
        self._streams: Dict[str, Deque[ProcessedFrame]] = {}
        self.processed_stream_buffer_size = max(1, processed_stream_buffer_size)

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()
            self._streams.clear()

    def update(self, job: FrameJob, processed_frame: np.ndarray, processed_at: datetime, worker_id: str, shard_id: int) -> ProcessedFrame:
        image_bytes = encode_jpeg(processed_frame)
        frame = ProcessedFrame(job.metadata, processed_frame, image_bytes, processed_at, worker_id, shard_id)
        with self._lock:
            previous = self._frames.get(job.metadata.camera_id)
            if previous is not None and job.metadata.sequence_number < previous.metadata.sequence_number:
                self._streams.pop(job.metadata.camera_id, None)
            self._frames[job.metadata.camera_id] = frame
            stream = self._streams.setdefault(
                job.metadata.camera_id,
                deque(maxlen=self.processed_stream_buffer_size),
            )
            stream.append(frame)
        return frame

    def get_latest(self, camera_id: str) -> Optional[ProcessedFrame]:
        with self._lock:
            return self._frames.get(camera_id)

    def pop_next(self, camera_id: str) -> Optional[ProcessedFrame]:
        with self._lock:
            stream = self._streams.get(camera_id)
            if not stream:
                return None
            return stream.popleft()

    def get_after(self, camera_id: str, after_sequence_number: Optional[int] = None) -> Optional[ProcessedFrame]:
        with self._lock:
            stream = self._streams.get(camera_id)
            if stream:
                for frame in stream:
                    if after_sequence_number is None or frame.metadata.sequence_number > after_sequence_number:
                        return frame

            latest = self._frames.get(camera_id)
            if latest is not None and (
                after_sequence_number is None or latest.metadata.sequence_number > after_sequence_number
            ):
                return latest
            return None

    def list_cameras(self) -> List[ProcessedFrameSummary]:
        with self._lock:
            frames = list(self._frames.values())
        return sorted([self._summary(frame) for frame in frames], key=lambda item: item.camera_id)

    def _summary(self, frame: ProcessedFrame) -> ProcessedFrameSummary:
        width, height = frame_size(frame.frame)
        return ProcessedFrameSummary(
            camera_id=frame.metadata.camera_id,
            location_id=frame.metadata.location_id,
            frame_id=frame.metadata.frame_id,
            sequence_number=frame.metadata.sequence_number,
            processed_at=to_iso_utc(frame.processed_at),
            worker_id=frame.worker_id,
            shard_id=frame.shard_id,
            image_width=width,
            image_height=height,
        )
