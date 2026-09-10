from .config import QueueBackendConfig
from .frame_queue import FrameQueueManager


def build_frame_queue(config: QueueBackendConfig):
    # Chọn hạ tầng queue theo môi trường chạy:
    # memory dùng cho unit test/local nhanh, redis dùng cho pipeline nhiều process.
    if config.backend == "memory":
        return FrameQueueManager()

    if config.backend == "redis":
        try:
            from .redis_frame_queue import RedisFrameQueueManager
        except ImportError as exc:
            raise RuntimeError("Redis backend requires the 'redis' package. Run: pip install -r requirements.txt") from exc

        return RedisFrameQueueManager(
            redis_url=config.redis_url,
            key_prefix=config.redis_key_prefix,
            num_shards=config.redis_num_shards,
            latest_ttl_seconds=config.redis_latest_ttl_seconds,
            frame_buffer_size=config.redis_frame_buffer_size,
            claim_batch_size=config.redis_claim_batch_size,
        )

    raise ValueError("Unsupported AI queue backend: {}".format(config.backend))
