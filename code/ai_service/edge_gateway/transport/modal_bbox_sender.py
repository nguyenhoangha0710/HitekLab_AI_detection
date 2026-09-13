import base64
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse

import httpx
from websockets.sync.client import connect

from common.frame_job import FrameJob
from common.image_codec import frame_size
from common.models import CameraQueueSummary
from common.time_utils import to_iso_utc, utc_now

from edge_gateway.live_viewer import DetectionHub


LOGGER = logging.getLogger(__name__)


@dataclass
class _BboxSenderStats:
    camera_id: str
    location_id: str
    received_frames: int = 0
    accepted_frames: int = 0
    failed_frames: int = 0
    dropped_frames: int = 0
    latest_frame_id: Optional[str] = None
    last_sent_at: Optional[str] = None
    sequence_number: Optional[int] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None


def to_websocket_bbox_url(url: str) -> str:
    if not url:
        raise ValueError("Modal bbox WebSocket URL is required.")

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme == "https":
        scheme = "wss"
    elif scheme == "http":
        scheme = "ws"
    elif scheme not in ("ws", "wss"):
        raise ValueError("Unsupported Modal URL scheme: {}".format(parsed.scheme))

    path = parsed.path.rstrip("/")
    if path.endswith("/ws/detect"):
        return urlunparse((scheme, parsed.netloc, path, "", "", ""))
    if path.endswith("/detect"):
        path = path[: -len("/detect")]
    path = "{}/ws/detect".format(path or "")
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


class AsyncModalBboxSender:
    """Gui sampled frame len Modal bbox service ma khong lam cham live viewer.

    Queue nay nam o Edge Gateway, chi de cach ly network/Modal latency khoi luong
    MJPEG local. Khi queue day, frame cu bi drop de AI bam sat live hon.
    """

    def __init__(
        self,
        detect_url: str,
        detection_hub: DetectionHub,
        timeout_seconds: float = 10.0,
        confidence_threshold: float = 0.35,
        yolo_classes: str = "person,car",
        tenant_id: Optional[str] = None,
        max_queue_size: int = 4,
        target_fps: float = 5.0,
        http_client=None,
        start_thread: bool = True,
    ) -> None:
        if not detect_url:
            raise ValueError("Modal bbox detect URL is required.")
        self.detect_url = detect_url
        self.detection_hub = detection_hub
        self.timeout_seconds = timeout_seconds
        self.confidence_threshold = confidence_threshold
        self.yolo_classes = [item.strip() for item in yolo_classes.split(",") if item.strip()]
        self.tenant_id = tenant_id
        self.target_fps = max(0.001, target_fps)
        self._frame_interval = 1.0 / self.target_fps
        self._queue: "queue.Queue[FrameJob]" = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._stats: Dict[str, _BboxSenderStats] = {}
        self._last_enqueued_at: Dict[str, float] = {}
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=4),
        )
        self._thread = threading.Thread(target=self._send_loop, name="edge-modal-bbox-sender", daemon=True)
        if start_thread:
            self._thread.start()

    def enqueue(self, job: FrameJob) -> CameraQueueSummary:
        metadata = job.metadata
        width, height = frame_size(job.frame)
        should_enqueue = True
        with self._lock:
            stats = self._stats.setdefault(
                metadata.camera_id,
                _BboxSenderStats(camera_id=metadata.camera_id, location_id=metadata.location_id),
            )
            stats.received_frames += 1
            stats.latest_frame_id = metadata.frame_id
            stats.sequence_number = metadata.sequence_number
            stats.image_width = width
            stats.image_height = height
            now = time.monotonic()
            last_enqueued_at = self._last_enqueued_at.get(metadata.camera_id)
            if last_enqueued_at is not None and now - last_enqueued_at < self._frame_interval:
                should_enqueue = False
            else:
                self._last_enqueued_at[metadata.camera_id] = now

        if not should_enqueue:
            return self._summary(metadata.camera_id)

        if self._queue.full():
            try:
                dropped = self._queue.get_nowait()
                self._mark_dropped(dropped)
            except queue.Empty:
                pass

        try:
            self._queue.put_nowait(job)
        except queue.Full:
            self._mark_dropped(job)

        return self._summary(metadata.camera_id)

    def close(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        if self._owns_client:
            self._client.close()

    def _send_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            metadata = job.metadata
            try:
                response = self._client.post(self.detect_url, json=self._build_payload(job))
                response.raise_for_status()
                result = response.json()
                self.detection_hub.update(result)
                self._mark_accepted(job)
                if metadata.sequence_number % 30 == 0:
                    LOGGER.info(
                        "EDGE_MODAL_BBOX_ACCEPTED camera=%s seq=%s detections=%s inference_ms=%s",
                        metadata.camera_id,
                        metadata.sequence_number,
                        result.get("detection_count"),
                        result.get("inference_ms"),
                    )
            except Exception as exc:
                self._mark_failed(job)
                LOGGER.warning(
                    "EDGE_MODAL_BBOX_FAILED camera=%s frame=%s seq=%s error=%s",
                    metadata.camera_id,
                    metadata.frame_id,
                    metadata.sequence_number,
                    exc,
                )

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

    def _mark_accepted(self, job: FrameJob) -> None:
        with self._lock:
            stats = self._stats[job.metadata.camera_id]
            stats.accepted_frames += 1
            stats.last_sent_at = to_iso_utc(utc_now())

    def _mark_failed(self, job: FrameJob) -> None:
        with self._lock:
            stats = self._stats[job.metadata.camera_id]
            stats.failed_frames += 1
            stats.last_sent_at = to_iso_utc(utc_now())

    def _mark_dropped(self, job: FrameJob) -> None:
        with self._lock:
            stats = self._stats.setdefault(
                job.metadata.camera_id,
                _BboxSenderStats(camera_id=job.metadata.camera_id, location_id=job.metadata.location_id),
            )
            stats.dropped_frames += 1

    def _summary(self, camera_id: str) -> CameraQueueSummary:
        with self._lock:
            stats = self._stats[camera_id]
            return CameraQueueSummary(
                camera_id=stats.camera_id,
                location_id=stats.location_id,
                queue_size=self._queue.qsize(),
                max_queue_size=self._queue.maxsize,
                buffered_frame_count=self._queue.qsize(),
                frame_buffer_size=self._queue.maxsize,
                claim_batch_size=1,
                pending_camera_count=self._queue.qsize(),
                received_frames=stats.received_frames,
                enqueued_frames=stats.accepted_frames,
                dropped_frames=stats.dropped_frames,
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


class WebSocketModalBboxSender(AsyncModalBboxSender):
    """Gui frame len Modal bbox service qua WebSocket va nhan bbox tren cung ket noi."""

    def __init__(
        self,
        websocket_url: str,
        detection_hub: DetectionHub,
        timeout_seconds: float = 10.0,
        confidence_threshold: float = 0.35,
        yolo_classes: str = "person,car",
        tenant_id: Optional[str] = None,
        max_queue_size: int = 4,
        target_fps: float = 5.0,
        connector=connect,
    ) -> None:
        super().__init__(
            detect_url=to_websocket_bbox_url(websocket_url),
            detection_hub=detection_hub,
            timeout_seconds=timeout_seconds,
            confidence_threshold=confidence_threshold,
            yolo_classes=yolo_classes,
            tenant_id=tenant_id,
            max_queue_size=max_queue_size,
            target_fps=target_fps,
            start_thread=False,
        )
        if self._owns_client:
            self._client.close()
        self._owns_client = False
        self._client = None
        self._connector = connector
        self._connection = None
        self._thread = threading.Thread(target=self._send_loop, name="edge-modal-bbox-ws-sender", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    def _connect(self):
        if self._connection is None:
            LOGGER.info("Connecting Modal bbox WebSocket %s", self.detect_url)
            self._connection = self._connector(
                self.detect_url,
                open_timeout=self.timeout_seconds,
                close_timeout=self.timeout_seconds,
                max_size=None,
            )
        return self._connection

    def _send_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            metadata = job.metadata
            try:
                connection = self._connect()
                connection.send(json.dumps(self._build_payload(job), separators=(",", ":")))
                raw_response = connection.recv(timeout=self.timeout_seconds)
                message = json.loads(raw_response)
                if message.get("type") == "error":
                    raise RuntimeError(message.get("detail", "Modal bbox WebSocket error"))
                result = message.get("result")
                if not isinstance(result, dict):
                    raise RuntimeError("Modal bbox WebSocket returned invalid result.")

                self.detection_hub.update(result)
                self._mark_accepted(job)
                if metadata.sequence_number % 30 == 0:
                    LOGGER.info(
                        "EDGE_MODAL_BBOX_WS_ACCEPTED camera=%s seq=%s detections=%s inference_ms=%s",
                        metadata.camera_id,
                        metadata.sequence_number,
                        result.get("detection_count"),
                        result.get("inference_ms"),
                    )
            except Exception as exc:
                self._connection = None
                self._mark_failed(job)
                LOGGER.warning(
                    "EDGE_MODAL_BBOX_WS_FAILED camera=%s frame=%s seq=%s error=%s",
                    metadata.camera_id,
                    metadata.frame_id,
                    metadata.sequence_number,
                    exc,
                )


class FanOutFrameSink:
    """Fan-out cung mot FrameJob sang AI bbox va viewer local.

    AI duoc enqueue truoc de lay dung frame can detect; viewer van duoc cap nhat
    ngay sau do va khong cho Modal xu ly xong.
    """

    def __init__(self, primary, secondary=None) -> None:
        self.primary = primary
        self.secondary = secondary

    def enqueue(self, job: FrameJob) -> CameraQueueSummary:
        if self.secondary is not None:
            try:
                self.secondary.enqueue(job)
            except Exception as exc:
                LOGGER.warning(
                    "EDGE_MODAL_BBOX_ENQUEUE_FAILED camera=%s seq=%s error=%s",
                    job.metadata.camera_id,
                    job.metadata.sequence_number,
                    exc,
                )
        return self.primary.enqueue(job)

    def close(self) -> None:
        self.primary.close()
        if self.secondary is not None:
            self.secondary.close()
