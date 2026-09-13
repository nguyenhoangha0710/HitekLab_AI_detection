from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModalPassthroughServiceTests(unittest.TestCase):
    def test_passthrough_service_has_ingest_and_viewer_routes(self):
        source = (ROOT / "modal_passthrough_service.py").read_text(encoding="utf-8")

        self.assertIn('@web.websocket("/ingest")', source)
        self.assertIn('@web.websocket("/ws/ingest")', source)
        self.assertIn('@web.websocket("/ws/results/shards/{shard_id}")', source)
        self.assertIn('@web.get("/viewer")', source)
        self.assertIn("make_passthrough_result", source)

    def test_passthrough_service_does_not_load_yolo_or_gpu(self):
        source = (ROOT / "modal_passthrough_service.py").read_text(encoding="utf-8")

        self.assertNotIn("from ultralytics import YOLO", source)
        self.assertNotIn("draw_and_detect", source)
        self.assertNotIn('gpu="', source)


if __name__ == "__main__":
    unittest.main()
