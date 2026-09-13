import os
import uuid
from datetime import datetime, timezone
from typing import Dict


def _new_queue_version() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
    suffix = uuid.uuid4().hex[:4]
    return "r{}{}".format(timestamp, suffix)


APP_NAME = "hitek-yolo11-async-ai-server"
QUEUE_VERSION = os.getenv("MODAL_QUEUE_VERSION_FIXED") or _new_queue_version()
FRAME_QUEUE_PREFIX = "hitek-yolo11-ws-frame-shard-queue-{}".format(QUEUE_VERSION)
RESULT_QUEUE_PREFIX = "hitek-yolo11-ws-result-shard-queue-{}".format(QUEUE_VERSION)
STATE_DICT_NAME = "hitek-yolo11-ws-state-{}".format(QUEUE_VERSION)
VIEWER_CAMERA_IDS = [
    camera_id.strip()
    for camera_id in os.getenv(
        "MODAL_VIEWER_CAMERA_IDS",
        "550e8400-e29b-41d4-a716-446655440001,550e8400-e29b-41d4-a716-446655440002",
    ).split(",")
    if camera_id.strip()
]

DEFAULT_MODEL = "yolo11n.pt"
DEFAULT_CONFIDENCE = 0.35
DEFAULT_IMAGE_SIZE = 640
SHARD_WORKER_IDLE_TIMEOUT_SECONDS = 30.0
SHARD_WORKER_POLL_TIMEOUT_SECONDS = 1.0
FRAME_QUEUE_LIMIT = 30
RESULT_QUEUE_LIMIT = 30
API_WEBSOCKET_TIMEOUT_SECONDS = 3600
NUM_SHARDS = 2

COCO_CLASS_IDS: Dict[str, int] = {
    "person": 0,
    "car": 2,
}
