import unittest
from pathlib import Path

from app.config import load_config


class ConfigTests(unittest.TestCase):
    def test_loads_two_database_mapped_cameras(self):
        config_path = Path(__file__).resolve().parents[1] / "config.yaml"
        config = load_config(str(config_path))

        self.assertEqual(2, len(config.cameras))
        self.assertEqual("RTSP", config.cameras[0].source_type)
        self.assertEqual(2, config.outbound_queue_size_per_camera)
        self.assertEqual(2, config.http_sender_worker_count)
        self.assertTrue(config.cameras[0].source_url.startswith("rtsp://localhost:8554/"))
        self.assertTrue(config.cameras[0].simulator_video_path.endswith("dummy_video_1.mp4"))
        self.assertTrue(config.cameras[1].simulator_video_path.endswith("dummy_video_2.mp4"))


if __name__ == "__main__":
    unittest.main()
