from typing import Dict


APP_NAME = "hitek-yolo11-async-ai-server"
FRAME_QUEUE_PREFIX = "hitek-yolo11-ws-frame-shard-queue-v1"
RESULT_QUEUE_NAME = "hitek-yolo11-ws-result-queue-v4"
STATE_DICT_NAME = "hitek-yolo11-ws-state-v4"

DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_CONFIDENCE = 0.35
DEFAULT_IMAGE_SIZE = 640
MAX_WORKER_DRAIN = 32
WORKER_SPAWN_EVERY_N_FRAMES = 4
API_WEBSOCKET_TIMEOUT_SECONDS = 3600
NUM_SHARDS = 2

COCO_CLASS_IDS: Dict[str, int] = {
    "person": 0,
    "car": 2,
}
