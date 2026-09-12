import os
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueBackendConfig:
    backend: str
    processed_stream_buffer_size: int


def load_queue_config() -> QueueBackendConfig:
    return QueueBackendConfig(
        backend=os.getenv("AI_QUEUE_BACKEND", "memory").strip().lower(),
        processed_stream_buffer_size=max(1, int(os.getenv("AI_PROCESSED_STREAM_BUFFER_SIZE", "120"))),
    )
