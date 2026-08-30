import time
import unittest

import numpy as np

from app.camera_worker import CameraWorker
from app.config import CameraConfig, VideoServiceConfig
from app.frame_sink import FrameSink, QueuedFrameSink


class RecordingSink(FrameSink):
    def __init__(self) -> None:
        self.packets = []

    def send(self, packet):
        self.packets.append(packet)


class QueuedFrameSinkTests(unittest.TestCase):
    def _packet(self, sequence_number):
        camera = CameraConfig(
            camera_id="camera-1",
            location_id="location-1",
            name="Camera 1",
            source_type="RTSP",
            source_url="rtsp://localhost:8554/camera1",
            target_fps=10,
            frame_width=160,
            frame_height=120,
            encoding="JPEG",
        )
        config = VideoServiceConfig(
            reconnect_interval_seconds=0.01,
            read_retry_count=1,
            log_every_n_frames=1,
            outbound_queue_size_per_camera=2,
            http_sender_worker_count=1,
            ai_service_base_url=None,
            ai_frame_endpoint="/api/v1/ai/frames",
            ai_timeout_seconds=5,
            cameras=[camera],
        )
        worker = CameraWorker(camera, config, RecordingSink())
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        for _ in range(sequence_number):
            packet = worker._build_packet(frame)
        return packet

    def test_send_only_enqueues_until_sender_worker_starts(self):
        inner = RecordingSink()
        sink = QueuedFrameSink(inner, max_size_per_camera=2, sender_worker_count=1)

        sink.send(self._packet(1))

        self.assertEqual(0, len(inner.packets))
        stats = sink.stats()[0]
        self.assertEqual(1, stats.queue_size)
        self.assertEqual(1, stats.enqueued_frames)

    def test_queue_drops_oldest_frame_when_full(self):
        inner = RecordingSink()
        sink = QueuedFrameSink(inner, max_size_per_camera=2, sender_worker_count=1)

        sink.send(self._packet(1))
        sink.send(self._packet(2))
        sink.send(self._packet(3))

        stats = sink.stats()[0]
        self.assertEqual(2, stats.queue_size)
        self.assertEqual(1, stats.dropped_frames)

    def test_sender_worker_posts_frames_from_queue(self):
        inner = RecordingSink()
        sink = QueuedFrameSink(inner, max_size_per_camera=2, sender_worker_count=1)

        sink.start()
        try:
            sink.send(self._packet(1))
            time.sleep(0.1)
        finally:
            sink.stop()

        self.assertEqual(1, len(inner.packets))
        stats = sink.stats()[0]
        self.assertEqual(1, stats.sent_frames)
        self.assertEqual(0, stats.queue_size)


if __name__ == "__main__":
    unittest.main()
