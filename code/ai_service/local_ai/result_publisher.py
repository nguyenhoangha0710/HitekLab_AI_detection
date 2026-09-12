import base64
import logging

from common.time_utils import to_iso_utc

from .result_store import ProcessedFrame


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


def build_result_publisher(config):
    return NoopResultPublisher()
