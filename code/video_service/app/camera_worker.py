import logging
import threading
import time
from typing import Optional

from .config import CameraConfig, VideoServiceConfig
from .frame_encoder import encode_jpeg, frame_size, resize_frame
from .frame_sink import FrameSink
from .models import FrameMetadata, FramePacket
from .time_utils import utc_now
from .video_source import RtspVideoSource


LOGGER = logging.getLogger(__name__)


class CameraWorker:
    def __init__(
        self,
        camera: CameraConfig,
        service_config: VideoServiceConfig,
        sink: FrameSink,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        self.camera = camera
        self.service_config = service_config
        self.sink = sink
        self.stop_event = stop_event or threading.Event()
        self.sequence_number = 0
        self.status = "OFFLINE"
        self.last_seen_at = None
        self._source = RtspVideoSource(camera.source_url)

    def stop(self) -> None:
        self.stop_event.set()
        self._source.release()

    def run(self, max_frames: Optional[int] = None) -> None:
        emitted = 0
        self._open_source_with_retry()
        frame_interval = 1.0 / max(0.001, self.camera.target_fps)

        while not self.stop_event.is_set():
            start = time.monotonic()

            if not self._source.is_opened():
                self._open_source_with_retry()
                continue

            ok, frame = self._source.read()
            if not ok or frame is None:
                LOGGER.warning("Camera %s read failed; reconnecting", self.camera.camera_id)
                self.status = "RECONNECTING"
                self._source.release()
                self.stop_event.wait(self.service_config.reconnect_interval_seconds)
                continue

            frame_time = utc_now()
            packet = self._build_packet(frame, frame_time)
            self.sink.send(packet)
            emitted += 1

            if max_frames is not None and emitted >= max_frames:
                break

            elapsed = time.monotonic() - start
            sleep_for = frame_interval - elapsed
            if sleep_for > 0:
                self.stop_event.wait(sleep_for)

        self._source.release()

    def _open_source_with_retry(self) -> None:
        self.status = "RECONNECTING"
        for attempt in range(1, self.service_config.read_retry_count + 1):
            if self.stop_event.is_set():
                return
            if self._source.open():
                self.status = "ONLINE"
                LOGGER.info("Camera %s connected to %s", self.camera.camera_id, self.camera.source_url)
                return
            LOGGER.warning(
                "Camera %s connection attempt %s/%s failed",
                self.camera.camera_id,
                attempt,
                self.service_config.read_retry_count,
            )
            self.stop_event.wait(self.service_config.reconnect_interval_seconds)
        self.status = "OFFLINE"
        LOGGER.error("Camera %s is offline", self.camera.camera_id)
        self.stop_event.wait(self.service_config.reconnect_interval_seconds)

    def _build_packet(self, frame, frame_time=None) -> FramePacket:
        source_width, source_height = frame_size(frame)
        processed = resize_frame(frame, self.camera.frame_width, self.camera.frame_height)
        image_bytes = encode_jpeg(processed)

        now = frame_time or utc_now()
        self.sequence_number += 1
        self.last_seen_at = now
        self.status = "ONLINE"

        metadata = FrameMetadata(
            frame_id="{}-{:012d}".format(self.camera.camera_id, self.sequence_number),
            camera_id=self.camera.camera_id,
            location_id=self.camera.location_id,
            source_type=self.camera.source_type,
            source_url=self.camera.source_url,
            timestamp=now,
            captured_at=now,
            received_at=now,
            sequence_number=self.sequence_number,
            source_width=source_width,
            source_height=source_height,
            frame_width=self.camera.frame_width,
            frame_height=self.camera.frame_height,
            target_fps=self.camera.target_fps,
            encoding=self.camera.encoding,
        )
        return FramePacket(metadata=metadata, image_bytes=image_bytes)
