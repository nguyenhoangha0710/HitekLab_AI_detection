import modal

from .settings import (
    APP_NAME,
    FRAME_QUEUE_PREFIX,
    NUM_SHARDS,
    QUEUE_VERSION,
    RESULT_QUEUE_PREFIX,
    STATE_DICT_NAME,
    VIEWER_CAMERA_IDS,
)
from .sharding import frame_queue_name


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("fastapi[standard]", "opencv-python-headless", "numpy", "ultralytics")
    .env(
        {
            "YOLO_CONFIG_DIR": "/tmp/Ultralytics",
            "MODAL_QUEUE_VERSION_FIXED": QUEUE_VERSION,
            "MODAL_VIEWER_CAMERA_IDS": ",".join(VIEWER_CAMERA_IDS),
        }
    )
    .add_local_python_source("modal_ai")
)

app = modal.App(APP_NAME)
frame_queues = [
    modal.Queue.from_name(frame_queue_name(FRAME_QUEUE_PREFIX, shard_id), create_if_missing=True)
    for shard_id in range(NUM_SHARDS)
]
result_queues = [
    modal.Queue.from_name(frame_queue_name(RESULT_QUEUE_PREFIX, shard_id), create_if_missing=True)
    for shard_id in range(NUM_SHARDS)
]
state_store = modal.Dict.from_name(STATE_DICT_NAME, create_if_missing=True)
