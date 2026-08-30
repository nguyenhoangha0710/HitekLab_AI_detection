import unittest
from datetime import timezone

import numpy as np

from app.camera_worker import CameraWorker
from app.config import CameraConfig, VideoServiceConfig
from app.frame_sink import MemoryFrameSink


class FrameMetadataTests(unittest.TestCase):
    def _worker(self):
        camera = CameraConfig(
            camera_id="550e8400-e29b-41d4-a716-446655440001",
            location_id="550e8400-e29b-41d4-a716-446655440101",
            name="Camera 01",
            source_type="RTSP",
            source_url="rtsp://localhost:8554/camera1",
            target_fps=10,
            frame_width=640,
            frame_height=360,
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
        return CameraWorker(camera, config, MemoryFrameSink())

    def test_metadata_matches_database_contract_without_session_or_loop(self):
        worker = self._worker()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        packet = worker._build_packet(frame)
        metadata = packet.metadata.to_dict()

        self.assertNotIn("session_id", metadata)
        self.assertNotIn("loop_index", metadata)
        self.assertEqual("550e8400-e29b-41d4-a716-446655440001", metadata["camera_id"])
        self.assertEqual("550e8400-e29b-41d4-a716-446655440101", metadata["location_id"])
        self.assertEqual("RTSP", metadata["source_type"])
        self.assertEqual("rtsp://localhost:8554/camera1", metadata["source_url"])
        self.assertEqual(1, metadata["sequence_number"])
        self.assertEqual(1280, metadata["source_width"])
        self.assertEqual(720, metadata["source_height"])
        self.assertEqual(640, metadata["frame_width"])
        self.assertEqual(360, metadata["frame_height"])
        self.assertTrue(metadata["timestamp"].endswith("Z"))
        self.assertTrue(metadata["captured_at"].endswith("Z"))
        self.assertTrue(metadata["received_at"].endswith("Z"))

    def test_sequence_number_increases_per_camera_worker(self):
        worker = self._worker()
        frame = np.zeros((10, 10, 3), dtype=np.uint8)

        first = worker._build_packet(frame).metadata
        second = worker._build_packet(frame).metadata

        self.assertEqual(1, first.sequence_number)
        self.assertEqual(2, second.sequence_number)
        self.assertNotEqual(first.frame_id, second.frame_id)
        self.assertIsNotNone(first.timestamp.tzinfo)
        self.assertEqual(timezone.utc, first.timestamp.tzinfo)

    def test_frame_is_encoded_as_jpeg_bytes(self):
        worker = self._worker()
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        packet = worker._build_packet(frame)

        self.assertGreater(len(packet.image_bytes), 0)
        self.assertEqual(b"\xff\xd8", packet.image_bytes[:2])


if __name__ == "__main__":
    unittest.main()
