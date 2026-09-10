import json
import threading
import base64
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, List, Optional

import numpy as np

from .frame_queue import FrameJob
from .image_codec import decode_image, encode_jpeg, frame_size
from .models import FrameMetadata, ProcessedFrameSummary
from .time_utils import to_iso_utc


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


class RedisResultStore:
    """Lưu kết quả đã xử lý để debug/viewer, tách biệt với input frame broker."""

    def __init__(self, redis_url: str, key_prefix: str = "ai", processed_stream_buffer_size: int = 120) -> None:
        import redis

        self.redis_url = redis_url
        self.key_prefix = key_prefix.rstrip(":")
        self.processed_stream_buffer_size = max(1, processed_stream_buffer_size)
        self._redis = redis.Redis.from_url(redis_url, decode_responses=False)
        self._redis.ping()

    def clear(self) -> None:
        keys = list(self._redis.scan_iter("{}:processed_*".format(self.key_prefix)))
        if keys:
            self._redis.delete(*keys)

    def update(self, job: FrameJob, processed_frame: np.ndarray, processed_at: datetime, worker_id: str, shard_id: int) -> ProcessedFrame:
        image_bytes = encode_jpeg(processed_frame)
        metadata_json = json.dumps(job.metadata.model_dump(mode="json"), ensure_ascii=False)
        previous_metadata_json = self._redis.hget(self._frame_key(job.metadata.camera_id), "metadata_json")
        if previous_metadata_json is not None:
            previous_metadata = FrameMetadata(**json.loads(self._decode(previous_metadata_json)))
            if job.metadata.sequence_number < previous_metadata.sequence_number:
                self._redis.delete(self._stream_key(job.metadata.camera_id))
        # processed_frame:{camera_id} giữ latest result để viewer mới kết nối có ảnh ngay.
        self._redis.hset(
            self._frame_key(job.metadata.camera_id),
            mapping={
                "metadata_json": metadata_json,
                "image_bytes": image_bytes,
                "processed_at": to_iso_utc(processed_at),
                "worker_id": worker_id,
                "shard_id": shard_id,
            },
        )
        # processed_stream:{camera_id} giữ lịch sử ngắn các frame đã xử lý để debug.
        self._redis.rpush(
            self._stream_key(job.metadata.camera_id),
            self._encode_processed_frame(job, image_bytes, processed_at, worker_id, shard_id),
        )
        self._redis.ltrim(self._stream_key(job.metadata.camera_id), -self.processed_stream_buffer_size, -1)
        self._redis.sadd(self._cameras_key(), job.metadata.camera_id)
        return ProcessedFrame(job.metadata, processed_frame, image_bytes, processed_at, worker_id, shard_id)

    def get_latest(self, camera_id: str) -> Optional[ProcessedFrame]:
        raw = self._redis.hgetall(self._frame_key(camera_id))
        if not raw:
            return None
        data = {self._decode(key): value for key, value in raw.items()}
        metadata = FrameMetadata(**json.loads(self._decode(data["metadata_json"])))
        image_bytes = data["image_bytes"]
        frame = decode_image(image_bytes)
        processed_at = datetime.fromisoformat(self._decode(data["processed_at"]).replace("Z", "+00:00"))
        return ProcessedFrame(
            metadata=metadata,
            frame=frame,
            image_bytes=image_bytes,
            processed_at=processed_at,
            worker_id=self._decode(data["worker_id"]),
            shard_id=int(self._decode(data["shard_id"])),
        )

    def list_cameras(self) -> List[ProcessedFrameSummary]:
        camera_ids = sorted(self._decode(item) for item in self._redis.smembers(self._cameras_key()))
        summaries = []
        for camera_id in camera_ids:
            frame = self.get_latest(camera_id)
            if frame is not None:
                summaries.append(self._summary(frame))
        return summaries

    def pop_next(self, camera_id: str, timeout_seconds: float = 0.0) -> Optional[ProcessedFrame]:
        raw = None
        if timeout_seconds > 0:
            item = self._redis.blpop(self._stream_key(camera_id), timeout=max(1, int(timeout_seconds)))
            if item is not None:
                raw = item[1]
        else:
            raw = self._redis.lpop(self._stream_key(camera_id))

        if raw is None:
            return None
        return self._decode_processed_frame(raw)

    def get_after(self, camera_id: str, after_sequence_number: Optional[int] = None) -> Optional[ProcessedFrame]:
        raw_items = self._redis.lrange(self._stream_key(camera_id), 0, -1)
        for raw in raw_items:
            frame = self._decode_processed_frame(raw)
            if after_sequence_number is None or frame.metadata.sequence_number > after_sequence_number:
                return frame

        latest = self.get_latest(camera_id)
        if latest is not None and (
            after_sequence_number is None or latest.metadata.sequence_number > after_sequence_number
        ):
            return latest
        return None

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

    def _frame_key(self, camera_id: str) -> str:
        return "{}:processed_frame:{}".format(self.key_prefix, camera_id)

    def _stream_key(self, camera_id: str) -> str:
        return "{}:processed_stream:{}".format(self.key_prefix, camera_id)

    def _cameras_key(self) -> str:
        return "{}:processed_cameras".format(self.key_prefix)

    def _encode_processed_frame(
        self,
        job: FrameJob,
        image_bytes: bytes,
        processed_at: datetime,
        worker_id: str,
        shard_id: int,
    ) -> bytes:
        payload = {
            "metadata_json": json.dumps(job.metadata.model_dump(mode="json"), ensure_ascii=False),
            "image_bytes_b64": base64.b64encode(image_bytes).decode("ascii"),
            "processed_at": to_iso_utc(processed_at),
            "worker_id": worker_id,
            "shard_id": shard_id,
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _decode_processed_frame(self, raw) -> ProcessedFrame:
        payload = json.loads(self._decode(raw))
        metadata = FrameMetadata(**json.loads(payload["metadata_json"]))
        image_bytes = base64.b64decode(payload["image_bytes_b64"])
        frame = decode_image(image_bytes)
        processed_at = datetime.fromisoformat(payload["processed_at"].replace("Z", "+00:00"))
        return ProcessedFrame(
            metadata=metadata,
            frame=frame,
            image_bytes=image_bytes,
            processed_at=processed_at,
            worker_id=payload["worker_id"],
            shard_id=int(payload["shard_id"]),
        )

    def _decode(self, value) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)
