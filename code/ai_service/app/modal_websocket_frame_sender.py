import base64
import json
import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse

from websockets.sync.client import connect

from .frame_queue import FrameJob
from .image_codec import frame_size
from .models import CameraQueueSummary
from .time_utils import to_iso_utc, utc_now


LOGGER = logging.getLogger(__name__)


@dataclass
class _SenderStats:
    camera_id: str
    location_id: str
    received_frames: int = 0
    accepted_frames: int = 0
    failed_frames: int = 0
    latest_frame_id: Optional[str] = None
    last_sent_at: Optional[str] = None
    sequence_number: Optional[int] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None


def to_websocket_ingest_url(url: str) -> str:
    """Chuyen Modal base/http ingest URL thanh WebSocket ingest URL."""
    if not url:
        raise ValueError("Modal WebSocket URL is required.")

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme == "https":
        scheme = "wss"
    elif scheme == "http":
        scheme = "ws"
    elif scheme not in ("ws", "wss"):
        raise ValueError("Unsupported Modal URL scheme: {}".format(parsed.scheme))

    path = parsed.path.rstrip("/")
    if path.endswith("/ingest"):
        return urlunparse((scheme, parsed.netloc, path, "", "", ""))
    if path.endswith("/ws"):
        path = path[: -len("/ws")]
    path = "{}/ws/ingest".format(path or "")

    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


class ModalWebSocketFrameSender:
    """Edge-side sender gui frame len Modal qua mot WebSocket connection dai han."""

    def __init__(
        self,
        websocket_url: str,
        timeout_seconds: float = 10.0,
        confidence_threshold: float = 0.35,
        yolo_classes: str = "person,car",
        tenant_id: Optional[str] = None,
        connector=connect,
    ) -> None:
        self.websocket_url = to_websocket_ingest_url(websocket_url)
        self.timeout_seconds = timeout_seconds
        self.confidence_threshold = confidence_threshold
        self.yolo_classes = [item.strip() for item in yolo_classes.split(",") if item.strip()]
        self.tenant_id = tenant_id
        self._connector = connector
        self._connection = None
        self._lock = threading.Lock()
        self._stats: Dict[str, _SenderStats] = {}

    def enqueue(self, job: FrameJob) -> CameraQueueSummary:
        metadata = job.metadata
        width, height = frame_size(job.frame)
        payload = self._build_payload(job)
        message = json.dumps(payload, separators=(",", ":"))

        with self._lock:
            stats = self._stats.setdefault(
                metadata.camera_id,
                _SenderStats(camera_id=metadata.camera_id, location_id=metadata.location_id),
            )
            stats.received_frames += 1
            stats.latest_frame_id = metadata.frame_id
            stats.sequence_number = metadata.sequence_number
            stats.image_width = width
            stats.image_height = height

            accepted = self._send_with_reconnect(message, metadata.camera_id, metadata.frame_id, metadata.sequence_number)
            stats.last_sent_at = to_iso_utc(utc_now())
            if accepted:
                stats.accepted_frames += 1
                if stats.accepted_frames % 30 == 0:
                    LOGGER.info(
                        "EDGE_MODAL_WS_SENT camera=%s seq=%s accepted_frames=%s url=%s",
                        metadata.camera_id,
                        metadata.sequence_number,
                        stats.accepted_frames,
                        self.websocket_url,
                    )
            else:
                stats.failed_frames += 1
            return self._summary(stats)

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                finally:
                    self._connection = None

    def _connect(self):
        if self._connection is None:
            LOGGER.info("Connecting Modal WebSocket %s", self.websocket_url)
            self._connection = self._connector(
                self.websocket_url,
                open_timeout=self.timeout_seconds,
                close_timeout=self.timeout_seconds,
                max_size=None,
            )
        return self._connection

    def _send_with_reconnect(self, message: str, camera_id: str, frame_id: str, sequence_number: int) -> bool:
        for attempt in range(1, 3):
            try:
                self._connect().send(message)
                return True
            except Exception as exc:
                LOGGER.warning(
                    "EDGE_MODAL_WS_SEND_FAILED attempt=%s camera=%s frame=%s seq=%s error=%s",
                    attempt,
                    camera_id,
                    frame_id,
                    sequence_number,
                    exc,
                )
                self._connection = None
        return False

    def _build_payload(self, job: FrameJob) -> dict:
        metadata = job.metadata
        tenant_id = self.tenant_id or getattr(metadata, "tenant_id", None)
        return {
            "tenant_id": tenant_id,
            "camera_id": metadata.camera_id,
            "location_id": metadata.location_id,
            "frame_id": metadata.frame_id,
            "sequence_number": metadata.sequence_number,
            "source_type": metadata.source_type,
            "source_url": metadata.source_url,
            "captured_at": to_iso_utc(metadata.captured_at or metadata.timestamp),
            "edge_received_at": to_iso_utc(metadata.received_at or job.received_at),
            "edge_sent_at": to_iso_utc(utc_now()),
            "frame_width": metadata.frame_width,
            "frame_height": metadata.frame_height,
            "target_fps": metadata.target_fps,
            "encoding": metadata.encoding,
            "classes": self.yolo_classes,
            "confidence": self.confidence_threshold,
            "image_b64": base64.b64encode(job.image_bytes).decode("ascii"),
        }

    def _summary(self, stats: _SenderStats) -> CameraQueueSummary:
        return CameraQueueSummary(
            camera_id=stats.camera_id,
            location_id=stats.location_id,
            shard_id=None,
            queue_size=0,
            max_queue_size=0,
            buffered_frame_count=0,
            frame_buffer_size=0,
            claim_batch_size=0,
            pending_camera_count=0,
            received_frames=stats.received_frames,
            enqueued_frames=stats.accepted_frames,
            dropped_frames=stats.failed_frames,
            consumed_frames=stats.accepted_frames,
            latest_frame_id=stats.latest_frame_id,
            last_enqueued_frame_id=stats.latest_frame_id,
            last_consumed_frame_id=stats.latest_frame_id,
            last_received_at=stats.last_sent_at,
            last_consumed_at=stats.last_sent_at,
            sequence_number=stats.sequence_number,
            last_consumed_sequence_number=stats.sequence_number,
            image_width=stats.image_width,
            image_height=stats.image_height,
        )
