import os
from typing import Dict


APP_NAME = "hitek-yolo11-async-ai-server"
QUEUE_VERSION = os.getenv("MODAL_QUEUE_VERSION", "v10")
FRAME_QUEUE_PREFIX = "hitek-yolo11-ws-frame-shard-queue-{}".format(QUEUE_VERSION)
RESULT_QUEUE_PREFIX = "hitek-yolo11-ws-result-shard-queue-{}".format(QUEUE_VERSION)
STATE_DICT_NAME = "hitek-yolo11-ws-state-{}".format(QUEUE_VERSION)

DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_CONFIDENCE = 0.35
DEFAULT_IMAGE_SIZE = 640
MAX_WORKER_DRAIN = 32
WORKER_SPAWN_EVERY_N_FRAMES = 4
FRAME_QUEUE_LIMIT = 30
RESULT_QUEUE_LIMIT = 30
API_WEBSOCKET_TIMEOUT_SECONDS = 3600
NUM_SHARDS = 2

COCO_CLASS_IDS: Dict[str, int] = {
    "person": 0,
    "car": 2,
}
