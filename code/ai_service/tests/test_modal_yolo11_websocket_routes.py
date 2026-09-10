import unittest
from pathlib import Path


class ModalYolo11WebSocketRouteTests(unittest.TestCase):
    def test_modal_service_keeps_websocket_ingest_and_result_routes(self):
        source_path = Path(__file__).resolve().parents[1] / "modal_yolo11_service.py"
        source = source_path.read_text(encoding="utf-8")

        self.assertIn('@web.websocket("/ws/ingest")', source)
        self.assertIn('@web.websocket("/ingest")', source)
        self.assertIn('@web.websocket("/ws/results")', source)
        self.assertIn('@web.post("/ingest"', source)
        self.assertIn("frame_queue.put", source)
        self.assertIn("frame_queue.get", source)
        self.assertIn("result_queue.put", source)


if __name__ == "__main__":
    unittest.main()
