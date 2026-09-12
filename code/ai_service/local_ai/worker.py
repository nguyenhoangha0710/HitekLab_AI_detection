import logging
import threading
from typing import Optional

from common.image_codec import draw_debug_overlay
from common.time_utils import utc_now

from .detector import NoopPersonDetector, draw_detections, summarize_detections


LOGGER = logging.getLogger(__name__)


class AIWorker:
    """Lấy frame từ Frame Broker, chạy detector và phát kết quả cho UI/module sau."""

    def __init__(
        self,
        frame_queue,
        result_store,
        result_publisher=None,
        detector=None,
        shard_id: int = 0,
        worker_id: Optional[str] = None,
        poll_timeout_seconds: float = 1.0,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        self.frame_queue = frame_queue
        self.result_store = result_store
        self.result_publisher = result_publisher
        self.detector = detector or NoopPersonDetector()
        self.shard_id = shard_id
        self.worker_id = worker_id or "ai-worker-{}".format(shard_id)
        self.poll_timeout_seconds = poll_timeout_seconds
        self.stop_event = stop_event or threading.Event()
        self.processed_frames = 0

    def run(self, max_frames: Optional[int] = None) -> None:
        LOGGER.info("AI worker %s started for shard %s", self.worker_id, self.shard_id)
        self._recover_processing()
        while not self.stop_event.is_set():
            # Claim camera/frame từ broker hiện tại. Với rollback này, local API dùng
            # memory broker; Modal cloud dùng Modal Queue trong modal_yolo11_service.py.
            jobs = self._claim_next_batch()
            if not jobs:
                continue

            for index, job in enumerate(jobs, start=1):
                # Detector co the chay local YOLO hoac goi Modal endpoint.
                if hasattr(self.detector, "detect_job"):
                    detections = self.detector.detect_job(job)
                else:
                    detections = self.detector.detect(job.frame)
                detected_frame = draw_detections(job.frame, detections)
                detection_summary = summarize_detections(detections)
                label = "{} | worker {} | seq {} | {} | batch {}/{}".format(
                    job.metadata.camera_id,
                    self.worker_id,
                    job.metadata.sequence_number,
                    detection_summary,
                    index,
                    len(jobs),
                )
                processed_frame = draw_debug_overlay(detected_frame, label)
                # Result Store giữ latest/processed stream để debug và phục hồi viewer.
                result = self.result_store.update(job, processed_frame, utc_now(), self.worker_id, self.shard_id)
                if self.result_publisher is not None:
                    self.result_publisher.publish(result)
                LOGGER.info(
                    "AI worker %s wrote processed frame camera=%s seq=%s detections=%s batch=%s/%s",
                    self.worker_id,
                    job.metadata.camera_id,
                    job.metadata.sequence_number,
                    detection_summary,
                    index,
                    len(jobs),
                )

            latest = jobs[-1]
            try:
                # Báo broker đã xử lý xong để broker xóa processing state.
                self.frame_queue.complete(
                    latest.metadata.camera_id,
                    latest.metadata.sequence_number,
                    latest.metadata.frame_id,
                    consumed_count=len(jobs),
                )
            except TypeError:
                self.frame_queue.complete(latest.metadata.camera_id, latest.metadata.sequence_number, latest.metadata.frame_id)
            self.processed_frames += len(jobs)

            if max_frames is not None and self.processed_frames >= max_frames:
                break

        LOGGER.info("AI worker %s stopped after %s frames", self.worker_id, self.processed_frames)

    def stop(self) -> None:
        self.stop_event.set()

    def _claim_next_batch(self):
        try:
            return self.frame_queue.claim_next_batch(shard_id=self.shard_id, timeout_seconds=self.poll_timeout_seconds)
        except TypeError:
            return self.frame_queue.claim_next_batch(timeout_seconds=self.poll_timeout_seconds)
        except AttributeError:
            try:
                job = self.frame_queue.claim_next(shard_id=self.shard_id, timeout_seconds=self.poll_timeout_seconds)
            except TypeError:
                job = self.frame_queue.claim_next(timeout_seconds=self.poll_timeout_seconds)
            return [job] if job is not None else []

    def _recover_processing(self) -> None:
        recover = getattr(self.frame_queue, "recover_processing", None)
        if recover is None:
            return

        recovered = recover(shard_id=self.shard_id)
        if recovered:
            LOGGER.warning(
                "AI worker %s recovered %s stuck camera(s) for shard %s",
                self.worker_id,
                recovered,
                self.shard_id,
            )
