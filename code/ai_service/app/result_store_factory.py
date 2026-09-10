from .config import QueueBackendConfig
from .result_store import MemoryResultStore, RedisResultStore


def build_result_store(config: QueueBackendConfig):
    # Result Store đi cùng backend queue để Worker và AI API có thể chia sẻ kết quả.
    if config.backend == "redis":
        return RedisResultStore(config.redis_url, config.redis_key_prefix, config.processed_stream_buffer_size)
    return MemoryResultStore(config.processed_stream_buffer_size)
