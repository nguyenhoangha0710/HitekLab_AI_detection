import logging
import threading
import time
from datetime import datetime
from typing import Optional

from .config import CameraIngestConfig, VideoIngestConfig
from .frame_queue import FrameJob
from .image_codec import encode_jpeg, frame_size, resize_frame
from .models import FrameMetadata
from .time_utils import utc_now
from .video_source import RtspVideoSource


LOGGER = logging.getLogger(__name__)


class VideoIngestWorker:
    """Đọc RTSP cho một camera và đưa frame đã chuẩn hóa vào Frame Broker.

    Reader thread luôn đọc RTSP liên tục để tránh dồn buffer. Sampler loop mới
    là nơi điều chỉnh target_fps và quyết định frame nào được đưa vào Redis.
    """

    def __init__(
        self,
        camera: CameraIngestConfig,
        ingest_config: VideoIngestConfig,
        frame_queue,
        stop_event: Optional[threading.Event] = None,
        source=None,
    ) -> None:
        self.camera = camera
        self.ingest_config = ingest_config
        self.frame_queue = frame_queue
        self.stop_event = stop_event or threading.Event()
        self.sequence_number = 0
        self.enqueued_frames = 0
        self._source = source or RtspVideoSource(camera.source_url)
        self._reader_stop_event = threading.Event()
        self._frame_condition = threading.Condition()
        self._latest_frame = None
        self._latest_frame_time: Optional[datetime] = None
        self._latest_decoded_sequence = 0

    def stop(self) -> None:
        self._reader_stop_event.set()
        self.stop_event.set()
        with self._frame_condition:
            self._frame_condition.notify_all()
        self._source.release()

    def run(self, max_frames: Optional[int] = None) -> None:
        emitted = 0
        last_sampled_decoded_sequence = 0
        frame_interval = 1.0 / max(0.001, self.camera.target_fps)
        next_sample_at = time.monotonic()
        self._reader_stop_event.clear()

        # Reader chỉ drain RTSP và cập nhật latest-frame slot trong RAM.
        # Không sleep ở reader, vì stream camera thật vẫn phát liên tục.
        reader_thread = threading.Thread(
            target=self._read_loop,
            name="video-ingest-reader-{}".format(self.camera.camera_id),
            daemon=True,
        )
        reader_thread.start()

        try:
            while not self.stop_event.is_set():
                wait_for_sample = next_sample_at - time.monotonic()
                if wait_for_sample > 0:
                    self.stop_event.wait(wait_for_sample)
                    continue

                frame, frame_time, decoded_sequence = self._wait_for_new_frame(last_sampled_decoded_sequence, timeout=1.0)
                if frame is None or frame_time is None or decoded_sequence is None:
                    continue

                # Chuyển dữ liệu từ latest-frame slot sang FrameJob.
                # Đây là điểm frame chính thức đi từ Video Ingest vào Redis Broker.
                job = self._build_job(frame, frame_time)
                summary = self.frame_queue.enqueue(job)
                emitted += 1
                self.enqueued_frames += 1
                last_sampled_decoded_sequence = decoded_sequence
                next_sample_at = time.monotonic() + frame_interval

                if job.metadata.sequence_number % max(1, self.ingest_config.log_every_n_frames) == 0:
                    LOGGER.info(
                        "Video ingest enqueued camera=%s seq=%s decoded_seq=%s buffered=%s dropped=%s pending=%s target_fps=%s",
                        job.metadata.camera_id,
                        job.metadata.sequence_number,
                        decoded_sequence,
                        summary.buffered_frame_count,
                        summary.dropped_frames,
                        summary.pending_camera_count,
                        job.metadata.target_fps,
                    )

                if max_frames is not None and emitted >= max_frames:
                    break
        finally:
            self._reader_stop_event.set()
            with self._frame_condition:
                self._frame_condition.notify_all()
            self._source.release()
            reader_thread.join(timeout=2.0)

    def _read_loop(self) -> None:
        """Đọc RTSP liên tục và chỉ giữ frame decode mới nhất trong RAM."""
        self._open_source_with_retry()
        while not self._should_stop():
            if not self._source.is_opened():
                self._open_source_with_retry()
                continue

            ok, frame = self._source.read()
            if not ok or frame is None:
                LOGGER.warning("Video ingest camera=%s read failed; reconnecting", self.camera.camera_id)
                self._source.release()
                self._wait(self.ingest_config.reconnect_interval_seconds)
                continue

            with self._frame_condition:
                # latest-frame slot chỉ có 1 phần tử: frame mới ghi đè frame cũ.
                # Frame bị ghi đè ở đây là sampling/overwrite, không phải Redis drop.
                self._latest_decoded_sequence += 1
                self._latest_frame = frame
                self._latest_frame_time = utc_now()
                self._frame_condition.notify_all()

    def _open_source_with_retry(self) -> None:
        for attempt in range(1, self.ingest_config.read_retry_count + 1):
            if self._should_stop():
                return
            if self._source.open():
                LOGGER.info("Video ingest camera=%s connected to %s", self.camera.camera_id, self.camera.source_url)
                return
            LOGGER.warning(
                "Video ingest camera=%s connection attempt %s/%s failed",
                self.camera.camera_id,
                attempt,
                self.ingest_config.read_retry_count,
            )
            self._wait(self.ingest_config.reconnect_interval_seconds)

        LOGGER.error("Video ingest camera=%s is offline", self.camera.camera_id)
        self._wait(self.ingest_config.reconnect_interval_seconds)

    def _wait_for_new_frame(self, last_decoded_sequence: int, timeout: float):
        """Sampler chờ reader tạo ra frame mới hơn frame đã lấy lần trước."""
        with self._frame_condition:
            if self._latest_decoded_sequence <= last_decoded_sequence and not self._should_stop():
                self._frame_condition.wait(timeout=timeout)

            if self._latest_frame is None or self._latest_decoded_sequence <= last_decoded_sequence:
                return None, None, None

            return self._latest_frame.copy(), self._latest_frame_time, self._latest_decoded_sequence

    def _should_stop(self) -> bool:
        return self.stop_event.is_set() or self._reader_stop_event.is_set()

    def _wait(self, timeout: float) -> None:
        self._reader_stop_event.wait(timeout)

    def _build_job(self, frame, frame_time: datetime) -> FrameJob:
        """Chuẩn hóa ảnh và metadata thành FrameJob để các tầng sau dùng chung."""
        source_width, source_height = frame_size(frame)
        processed = resize_frame(frame, self.camera.frame_width, self.camera.frame_height)
        image_bytes = encode_jpeg(processed, quality=self.ingest_config.jpeg_quality)
        received_at = utc_now()
        self.sequence_number += 1

        # Metadata kế thừa contract FramePacket ban đầu:
        # camera_id/location_id để map DB, timestamp/captured_at là thời gian frame,
        # received_at là thời gian frame được Video Ingest đưa vào broker.
        metadata = FrameMetadata(
            frame_id="{}-{:012d}".format(self.camera.camera_id, self.sequence_number),
            camera_id=self.camera.camera_id,
            location_id=self.camera.location_id,
            source_type=self.camera.source_type,
            source_url=self.camera.source_url,
            timestamp=frame_time,
            captured_at=frame_time,
            received_at=received_at,
            sequence_number=self.sequence_number,
            source_width=source_width,
            source_height=source_height,
            frame_width=self.camera.frame_width,
            frame_height=self.camera.frame_height,
            target_fps=self.camera.target_fps,
            fps=self.camera.target_fps,
            encoding=self.camera.encoding,
        )
        return FrameJob(metadata=metadata, frame=processed, image_bytes=image_bytes, received_at=received_at)
