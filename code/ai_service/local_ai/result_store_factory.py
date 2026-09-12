from common.config import QueueBackendConfig

from .result_store import MemoryResultStore


def build_result_store(config: QueueBackendConfig):
    return MemoryResultStore(config.processed_stream_buffer_size)
