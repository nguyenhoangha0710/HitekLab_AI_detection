from common.config import QueueBackendConfig

from .frame_queue import FrameQueueManager


def build_frame_queue(config: QueueBackendConfig):
    if config.backend == "memory":
        return FrameQueueManager()

    raise ValueError("Unsupported AI queue backend: {}".format(config.backend))
