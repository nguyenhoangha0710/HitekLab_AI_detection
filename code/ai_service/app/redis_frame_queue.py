import hashlib
import json
import math
import base64
import logging
from datetime import datetime
from typing import Dict, List, Optional

from .frame_queue import FrameJob
from .image_codec import decode_image, frame_size
from .models import CameraQueueSummary, FrameMetadata
from .time_utils import to_iso_utc, utc_now


LOGGER = logging.getLogger(__name__)


def stable_shard_id(camera_id: str, num_shards: int) -> int:
    digest = hashlib.sha256(camera_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % max(1, num_shards)


class RedisFrameQueueManager:
    """Frame Broker dùng Redis List/Set/Hash để nối Video Ingest và AI Worker.

    Thiết kế có hai lớp: frame buffer theo camera và ready/pending camera queue
    theo shard. Pending queue chỉ chứa camera_id, không chứa từng frame.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "ai",
        num_shards: int = 4,
        latest_ttl_seconds: int = 10,
        frame_buffer_size: int = 5,
        claim_batch_size: Optional[int] = None,
    ) -> None:
        self.redis_url = redis_url
        self.key_prefix = key_prefix.rstrip(":")
        self.num_shards = max(1, num_shards)
        self.latest_ttl_seconds = max(1, latest_ttl_seconds)
        self.frame_buffer_size = max(1, frame_buffer_size)
        self.claim_batch_size = max(1, claim_batch_size or frame_buffer_size)
        import redis

        self._redis = redis.Redis.from_url(redis_url, decode_responses=False)
        self._redis.ping()

    def clear(self) -> None:
        keys = list(self._redis.scan_iter("{}:*".format(self.key_prefix)))
        if keys:
            self._redis.delete(*keys)

    def enqueue(self, job: FrameJob) -> CameraQueueSummary:
        """Nhận FrameJob từ Video Ingest và ghi vào Redis buffer của camera."""
        camera_id = job.metadata.camera_id
        shard_id = self.shard_id(camera_id)
        stats_key = self._stats_key(camera_id)
        latest_key = self._latest_frames_key(camera_id)
        now_iso = to_iso_utc(job.received_at)

        oldest_seq = self._oldest_sequence_number(camera_id)
        buffered_count = int(self._redis.llen(latest_key))
        last_received_seq = self._int_or_none(self._redis.hget(stats_key, "sequence_number"))
        processing_seq = self._int_or_none(self._redis.hget(stats_key, "processing_sequence_number"))
        sequence_reset = last_received_seq is not None and job.metadata.sequence_number < last_received_seq

        pipe = self._redis.pipeline()
        pipe.sadd(self._cameras_key(), camera_id)
        pipe.hincrby(stats_key, "received_frames", 1)
        if sequence_reset:
            # Khi Video Ingest restart, sequence có thể quay về số nhỏ.
            # Reset state cũ để worker không so với last_consumed_sequence cũ.
            pipe.delete(latest_key)
            pipe.hdel(
                stats_key,
                "last_consumed_sequence_number",
                "last_consumed_frame_id",
                "last_consumed_at",
                "processing_sequence_number",
            )
            pipe.hincrby(stats_key, "sequence_resets", 1)
            pipe.lrem(self._pending_queue_key(shard_id), 0, camera_id)
            pipe.srem(self._pending_set_key(shard_id), camera_id)
            pipe.srem(self._processing_set_key(shard_id), camera_id)
            pipe.srem(self._dirty_set_key(shard_id), camera_id)
            buffered_count = 0
            oldest_seq = None
            processing_seq = None

        if not sequence_reset and buffered_count >= self.frame_buffer_size and oldest_seq is not None and oldest_seq != processing_seq:
            # Buffer đầy: drop frame cũ nhất của chính camera này.
            # Camera khác không bị ảnh hưởng dù cùng shard.
            pipe.hincrby(stats_key, "dropped_frames", 1)
            LOGGER.warning(
                "AI_REDIS_FRAME_DROP camera=%s dropped_oldest_seq=%s incoming_seq=%s buffer_size=%s total_buffered_before=%s",
                camera_id,
                oldest_seq,
                job.metadata.sequence_number,
                self.frame_buffer_size,
                buffered_count,
            )

        # Redis List lưu raw frame buffer theo camera.
        # RPUSH thêm frame mới vào cuối list, LTRIM giữ N frame mới nhất.
        pipe.rpush(latest_key, self._encode_frame_job(job))
        pipe.ltrim(latest_key, -self.frame_buffer_size, -1)
        pipe.expire(latest_key, self.latest_ttl_seconds)
        pipe.hset(
            stats_key,
            mapping={
                "camera_id": camera_id,
                "location_id": job.metadata.location_id,
                "shard_id": shard_id,
                "latest_frame_id": job.metadata.frame_id,
                "last_enqueued_frame_id": job.metadata.frame_id,
                "last_received_at": now_iso,
                "sequence_number": job.metadata.sequence_number,
                "image_width": frame_size(job.frame)[0],
                "image_height": frame_size(job.frame)[1],
            },
        )
        pipe.execute()

        if self._redis.sismember(self._processing_set_key(shard_id), camera_id):
            # Camera đang được worker xử lý; đánh dấu dirty để xử lý lại sau lượt này.
            self._redis.sadd(self._dirty_set_key(shard_id), camera_id)
        elif self._redis.sadd(self._pending_set_key(shard_id), camera_id):
            # Pending Set chống duplicate camera trong ready queue.
            # Một camera FPS cao chỉ được có 1 slot trong queue.
            self._redis.rpush(self._pending_queue_key(shard_id), camera_id)
            self._redis.hincrby(stats_key, "enqueued_frames", 1)

        return self._summary(camera_id)

    def consume(self, camera_id: str) -> Optional[FrameJob]:
        # Hàm tiện ích cho endpoint debug: lấy 1 frame của camera rồi complete ngay.
        # AI Worker chính không đi qua hàm này mà dùng claim_next_batch().
        job = self.claim_camera(camera_id)
        if job is None:
            return None
        self.complete(job.metadata.camera_id, job.metadata.sequence_number, job.metadata.frame_id)
        return job

    def consume_batch(self, camera_id: str) -> List[FrameJob]:
        # Phiên bản batch cho debug/manual consume theo camera_id.
        # Lấy xong sẽ complete luôn nên không phù hợp nếu cần xử lý AI lâu.
        jobs = self.claim_camera_batch(camera_id)
        if not jobs:
            return []
        latest = jobs[-1]
        self.complete(latest.metadata.camera_id, latest.metadata.sequence_number, latest.metadata.frame_id)
        return jobs

    def claim_camera(self, camera_id: str) -> Optional[FrameJob]:
        # Claim trực tiếp một camera cụ thể, bỏ qua thứ tự ready queue.
        # Dùng cho debug/API theo camera; worker realtime nên dùng claim_next_batch().
        jobs = self.claim_camera_batch(camera_id)
        if not jobs:
            return None
        return jobs[-1]

    def claim_camera_batch(self, camera_id: str) -> List[FrameJob]:
        # Claim frame của một camera cụ thể và đánh dấu camera đang processing.
        # Nếu camera đang được worker khác xử lý thì không claim để tránh xử lý trùng.
        shard_id = self.shard_id(camera_id)
        if self._redis.sismember(self._processing_set_key(shard_id), camera_id):
            return []

        # Lấy frame cũ nhất còn trong buffer của camera, tối đa claim_batch_size.
        jobs = self._claim_queued_jobs(camera_id)
        if not jobs:
            return []

        # Vì camera đã được claim trực tiếp, xóa nó khỏi ready queue/pending set nếu có.
        self._redis.lrem(self._pending_queue_key(shard_id), 0, camera_id)
        self._redis.srem(self._pending_set_key(shard_id), camera_id)
        # Xóa dirty cũ trước khi xử lý batch hiện tại; frame mới đến trong lúc xử lý
        # sẽ được enqueue() đánh dấu dirty lại.
        self._redis.srem(self._dirty_set_key(shard_id), camera_id)
        # processing_set là khóa mềm theo camera để không có hai worker xử lý cùng camera.
        self._redis.sadd(self._processing_set_key(shard_id), camera_id)
        # Lưu sequence đang xử lý để debug và để logic drop không xóa nhầm frame đang process.
        self._redis.hset(self._stats_key(camera_id), "processing_sequence_number", jobs[-1].metadata.sequence_number)
        return jobs

    def claim_next(self, shard_id: int = 0, timeout_seconds: Optional[float] = None) -> Optional[FrameJob]:
        # API lấy 1 frame tiếp theo theo thứ tự ready queue của shard.
        # Nội bộ vẫn gọi claim_next_batch để giữ một đường xử lý thống nhất.
        jobs = self.claim_next_batch(shard_id=shard_id, timeout_seconds=timeout_seconds)
        if not jobs:
            return None
        return jobs[-1]

    def claim_next_batch(self, shard_id: int = 0, timeout_seconds: Optional[float] = None) -> List[FrameJob]:
        """Worker lấy camera_id tiếp theo từ ready queue rồi claim frame của camera đó."""
        queue_key = self._pending_queue_key(shard_id)
        timeout = 0 if timeout_seconds is None else max(1, int(math.ceil(timeout_seconds)))
        # BLPOP giúp worker block/chờ việc mới thay vì polling liên tục.
        item = self._redis.blpop(queue_key, timeout=timeout) # hoạt động giống FIFO
        if item is None:
            return []

        camera_id = self._decode(item[1])
        self._redis.srem(self._pending_set_key(shard_id), camera_id)
        if self._redis.sismember(self._processing_set_key(shard_id), camera_id):
            return []

        jobs = self._claim_queued_jobs(camera_id)
        if not jobs:
            return []

        self._redis.srem(self._dirty_set_key(shard_id), camera_id)
        self._redis.sadd(self._processing_set_key(shard_id), camera_id)
        self._redis.hset(self._stats_key(camera_id), "processing_sequence_number", jobs[-1].metadata.sequence_number)
        return jobs

    def complete(self, camera_id: str, sequence_number: int, frame_id: str, consumed_count: int = 1) -> CameraQueueSummary:
        """Worker báo đã xử lý xong frame; broker quyết định có requeue camera không."""
        shard_id = self.shard_id(camera_id)
        stats_key = self._stats_key(camera_id)
        now_iso = to_iso_utc(utc_now())

        pipe = self._redis.pipeline()
        pipe.srem(self._processing_set_key(shard_id), camera_id)
        pipe.hdel(stats_key, "processing_sequence_number")
        pipe.hincrby(stats_key, "consumed_frames", max(1, consumed_count))
        pipe.hset(
            stats_key,
            mapping={
                "last_consumed_frame_id": frame_id,
                "last_consumed_sequence_number": sequence_number,
                "last_consumed_at": now_iso,
            },
        )
        pipe.execute()

        has_queued_frames = int(self._redis.llen(self._latest_frames_key(camera_id))) > 0
        was_dirty = self._redis.sismember(self._dirty_set_key(shard_id), camera_id)
        if has_queued_frames or was_dirty:
            # Nếu camera vẫn còn frame trong buffer hoặc có frame mới khi đang xử lý,
            # đưa camera về cuối ready queue để giữ round-robin fairness.
            self._redis.srem(self._dirty_set_key(shard_id), camera_id)
            if self._redis.sadd(self._pending_set_key(shard_id), camera_id):
                self._redis.rpush(self._pending_queue_key(shard_id), camera_id)
                self._redis.hincrby(stats_key, "enqueued_frames", 1)
                if was_dirty:
                    self._redis.hincrby(stats_key, "dirty_requeues", 1)
        else:
            self._redis.srem(self._dirty_set_key(shard_id), camera_id)

        return self._summary(camera_id)

    def recover_processing(self, shard_id: int = 0) -> int:
        """Khôi phục camera bị kẹt processing khi worker cũ chết/restart giữa chừng."""
        processing_key = self._processing_set_key(shard_id)
        camera_ids = [self._decode(item) for item in self._redis.smembers(processing_key)]
        recovered_count = 0

        for camera_id in camera_ids:
            stats_key = self._stats_key(camera_id)
            has_queued_frames = int(self._redis.llen(self._latest_frames_key(camera_id))) > 0

            pipe = self._redis.pipeline()
            pipe.srem(processing_key, camera_id)
            pipe.hdel(stats_key, "processing_sequence_number")
            pipe.srem(self._dirty_set_key(shard_id), camera_id)
            pipe.execute()

            if not has_queued_frames:
                continue

            if self._redis.sadd(self._pending_set_key(shard_id), camera_id):
                self._redis.rpush(self._pending_queue_key(shard_id), camera_id)
                self._redis.hincrby(stats_key, "enqueued_frames", 1)
            recovered_count += 1

        return recovered_count

    def list_cameras(self) -> List[CameraQueueSummary]:
        camera_ids = sorted(self._decode(item) for item in self._redis.smembers(self._cameras_key()))
        return [self._summary(camera_id) for camera_id in camera_ids]

    def pending_camera_count(self) -> int:
        return sum(int(self._redis.llen(self._pending_queue_key(shard_id))) for shard_id in range(self.num_shards))

    def shard_id(self, camera_id: str) -> int:
        """Shard ổn định theo camera_id để cùng camera luôn về cùng worker group."""
        return stable_shard_id(camera_id, self.num_shards)

    def _latest_job(self, camera_id: str) -> Optional[FrameJob]:
        jobs = self._latest_jobs(camera_id)
        if not jobs:
            return None
        return jobs[-1]

    def _latest_jobs(self, camera_id: str) -> List[FrameJob]:
        raw_items = self._redis.lrange(self._latest_frames_key(camera_id), 0, -1)
        jobs = [self._decode_frame_job(item) for item in raw_items]
        return sorted(jobs, key=lambda job: job.metadata.sequence_number)

    def _claim_queued_jobs(self, camera_id: str) -> List[FrameJob]:
        key = self._latest_frames_key(camera_id)
        # Lấy frame cũ nhất còn tồn tại trong buffer, tối đa claim_batch_size frame.
        # claim_batch_size=1 giúp mỗi camera chỉ xử lý 1 frame/lượt rồi nhường camera khác.
        raw_items = self._redis.lrange(key, 0, self.claim_batch_size - 1)
        if not raw_items:
            return []
        # Xóa đúng các frame vừa claim khỏi buffer để worker không xử lý lại.
        self._redis.ltrim(key, len(raw_items), -1)
        jobs = [self._decode_frame_job(item) for item in raw_items]
        return sorted(jobs, key=lambda job: job.metadata.sequence_number)

    def _latest_sequence_number(self, camera_id: str) -> Optional[int]:
        raw = self._redis.lindex(self._latest_frames_key(camera_id), -1)
        if raw is None:
            return None
        return self._decode_frame_job(raw).metadata.sequence_number

    def _oldest_sequence_number(self, camera_id: str) -> Optional[int]:
        raw = self._redis.lindex(self._latest_frames_key(camera_id), 0)
        if raw is None:
            return None
        return self._decode_frame_job(raw).metadata.sequence_number

    def _is_unconsumed(self, camera_id: str, sequence_number: int) -> bool:
        last_consumed = self._int_or_none(self._redis.hget(self._stats_key(camera_id), "last_consumed_sequence_number"))
        return last_consumed is None or sequence_number > last_consumed

    def _summary(self, camera_id: str) -> CameraQueueSummary:
        stats = self._hgetall_text(self._stats_key(camera_id))
        shard_id = int(stats.get("shard_id", self.shard_id(camera_id)))
        is_pending = bool(self._redis.sismember(self._pending_set_key(shard_id), camera_id))
        is_processing = bool(self._redis.sismember(self._processing_set_key(shard_id), camera_id))
        is_dirty = bool(self._redis.sismember(self._dirty_set_key(shard_id), camera_id))
        pending_count = self.pending_camera_count()

        return CameraQueueSummary(
            camera_id=camera_id,
            location_id=stats.get("location_id", ""),
            shard_id=shard_id,
            queue_size=1 if is_pending else 0,
            max_queue_size=1,
            buffered_frame_count=int(self._redis.llen(self._latest_frames_key(camera_id))),
            frame_buffer_size=self.frame_buffer_size,
            claim_batch_size=self.claim_batch_size,
            pending_camera_count=pending_count,
            received_frames=int(stats.get("received_frames", 0)),
            enqueued_frames=int(stats.get("enqueued_frames", 0)),
            dropped_frames=int(stats.get("dropped_frames", 0)),
            consumed_frames=int(stats.get("consumed_frames", 0)),
            dirty_requeues=int(stats.get("dirty_requeues", 0)),
            sequence_resets=int(stats.get("sequence_resets", 0)),
            latest_frame_id=stats.get("latest_frame_id"),
            last_enqueued_frame_id=stats.get("last_enqueued_frame_id"),
            last_consumed_frame_id=stats.get("last_consumed_frame_id"),
            last_received_at=stats.get("last_received_at"),
            last_consumed_at=stats.get("last_consumed_at"),
            sequence_number=self._int_text(stats.get("sequence_number")),
            last_consumed_sequence_number=self._int_text(stats.get("last_consumed_sequence_number")),
            image_width=self._int_text(stats.get("image_width")),
            image_height=self._int_text(stats.get("image_height")),
            is_pending=is_pending,
            is_processing=is_processing,
            is_dirty=is_dirty,
        )

    def _metadata_to_json(self, metadata: FrameMetadata) -> str:
        if hasattr(metadata, "model_dump"):
            return json.dumps(metadata.model_dump(mode="json"), ensure_ascii=False)
        return metadata.json()

    def _encode_frame_job(self, job: FrameJob) -> bytes:
        payload = {
            "metadata_json": self._metadata_to_json(job.metadata),
            "image_bytes_b64": base64.b64encode(job.image_bytes).decode("ascii"),
            "received_at": to_iso_utc(job.received_at),
        }
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _decode_frame_job(self, raw) -> FrameJob:
        payload = json.loads(self._decode(raw))
        metadata = FrameMetadata(**json.loads(payload["metadata_json"]))
        image_bytes = base64.b64decode(payload["image_bytes_b64"])
        frame = decode_image(image_bytes)
        received_at = self._datetime_from_iso(payload["received_at"]) if payload.get("received_at") else metadata.received_at or utc_now()
        return FrameJob(metadata=metadata, frame=frame, image_bytes=image_bytes, received_at=received_at)

    def _datetime_from_iso(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _hgetall_text(self, key: str) -> Dict[str, str]:
        return {self._decode(field): self._decode(value) for field, value in self._redis.hgetall(key).items()}

    def _decode(self, value) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def _int_or_none(self, value) -> Optional[int]:
        if value is None:
            return None
        return int(self._decode(value))

    def _int_text(self, value: Optional[str]) -> Optional[int]:
        if value is None or value == "":
            return None
        return int(value)

    def _latest_frames_key(self, camera_id: str) -> str:
        return "{}:latest_frames:{}".format(self.key_prefix, camera_id)

    def _stats_key(self, camera_id: str) -> str:
        return "{}:camera_stats:{}".format(self.key_prefix, camera_id)

    def _cameras_key(self) -> str:
        return "{}:cameras".format(self.key_prefix)

    def _pending_queue_key(self, shard_id: int) -> str:
        return "{}:pending_cameras:queue:{}".format(self.key_prefix, shard_id)

    def _pending_set_key(self, shard_id: int) -> str:
        return "{}:pending_cameras:pending:{}".format(self.key_prefix, shard_id)

    def _processing_set_key(self, shard_id: int) -> str:
        return "{}:pending_cameras:processing:{}".format(self.key_prefix, shard_id)

    def _dirty_set_key(self, shard_id: int) -> str:
        return "{}:pending_cameras:dirty:{}".format(self.key_prefix, shard_id)
