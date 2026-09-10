import base64
import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional

import httpx

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


class ModalFrameSender:
    """Edge-side sender: nhan FrameJob tu Video Ingest va day len Modal /ingest.

    Lop nay co cung interface enqueue(job) voi RedisFrameQueueManager de
    VideoIngestWorker co the tai su dung ma khong can biet dich den la Redis hay Modal.
    """

    def __init__(
        self,
        ingest_url: str,
        timeout_seconds: float = 10.0,
        confidence_threshold: float = 0.35,
        yolo_classes: str = "person,car",
        tenant_id: Optional[str] = None,
        http_client=None,
    ) -> None:
        if not ingest_url:
            raise ValueError("Modal ingest URL is required.")
        self.ingest_url = ingest_url
        self.timeout_seconds = timeout_seconds
        self.confidence_threshold = confidence_threshold
        self.yolo_classes = [item.strip() for item in yolo_classes.split(",") if item.strip()]
        self.tenant_id = tenant_id
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=20),
        )
        self._lock = threading.Lock()
        self._stats: Dict[str, _SenderStats] = {}

    def enqueue(self, job: FrameJob) -> CameraQueueSummary:
        metadata = job.metadata
        width, height = frame_size(job.frame)
        payload = self._build_payload(job)

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

        try:
            # Dung persistent HTTP client de tai su dung TCP/TLS connection.
            # Neu moi frame tao mot client/request rieng, latency internet len Modal se rat cao.
            response = self._client.post(self.ingest_url, json=payload)
            response.raise_for_status()
            accepted = True
        except Exception as exc:
            accepted = False
            LOGGER.warning(
                "EDGE_MODAL_SEND_FAILED camera=%s frame=%s seq=%s error=%s",
                metadata.camera_id,
                metadata.frame_id,
                metadata.sequence_number,
                exc,
            )

        with self._lock:
            stats = self._stats[metadata.camera_id]
            stats.last_sent_at = to_iso_utc(utc_now())
            if accepted:
                stats.accepted_frames += 1
            else:
                stats.failed_frames += 1
            return self._summary(stats)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

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
