import base64
import json
import logging
from typing import Optional

from .result_store import ProcessedFrame
from .time_utils import to_iso_utc


LOGGER = logging.getLogger(__name__)


def processed_frame_to_message(frame: ProcessedFrame) -> dict:
    """Đổi processed frame thành JSON message để gửi qua WebSocket."""
    return {
        "type": "processed_frame",
        "camera_id": frame.metadata.camera_id,
        "location_id": frame.metadata.location_id,
        "frame_id": frame.metadata.frame_id,
        "sequence_number": frame.metadata.sequence_number,
        "processed_at": to_iso_utc(frame.processed_at),
        "worker_id": frame.worker_id,
        "shard_id": frame.shard_id,
        "image_width": frame.metadata.frame_width,
        "image_height": frame.metadata.frame_height,
        "image_jpeg_base64": base64.b64encode(frame.image_bytes).decode("ascii"),
    }


class NoopResultPublisher:
    def publish(self, frame: ProcessedFrame) -> None:
        return

    def close(self) -> None:
        return


class RedisResultPublisher:
    """Publish kết quả worker lên Redis Pub/Sub cho AI API subscribe."""

    def __init__(self, redis_url: str, key_prefix: str = "ai", channel_name: Optional[str] = None) -> None:
        import redis

        self.redis_url = redis_url
        self.key_prefix = key_prefix.rstrip(":")
        self.channel_name = channel_name or "{}:processed_frames:pubsub".format(self.key_prefix)
        self._redis = redis.Redis.from_url(redis_url, decode_responses=False)
        self._redis.ping()

    def publish(self, frame: ProcessedFrame) -> None:
        # Worker và AI API là hai process khác nhau, nên dùng Redis Pub/Sub
        # làm kênh realtime trung gian trước khi AI API push xuống WebSocket.
        payload = json.dumps(processed_frame_to_message(frame), ensure_ascii=False).encode("utf-8")
        subscriber_count = self._redis.publish(self.channel_name, payload)
        LOGGER.info(
            "Published processed frame camera=%s seq=%s redis_subscribers=%s",
            frame.metadata.camera_id,
            frame.metadata.sequence_number,
            subscriber_count,
        )

    def close(self) -> None:
        self._redis.close()


def build_result_publisher(config):
    if config.backend == "redis":
        return RedisResultPublisher(config.redis_url, config.redis_key_prefix)
    return NoopResultPublisher()
