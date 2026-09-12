import unittest
from pathlib import Path


class ModalYolo11WebSocketRouteTests(unittest.TestCase):
    def test_modal_service_keeps_websocket_ingest_and_result_routes(self):
        service_dir = Path(__file__).resolve().parents[1]
        entrypoint = (service_dir / "modal_yolo11_service.py").read_text(encoding="utf-8")
        runtime = (service_dir / "modal_ai" / "runtime.py").read_text(encoding="utf-8")
        results = (service_dir / "modal_ai" / "results.py").read_text(encoding="utf-8")
        yolo = (service_dir / "modal_ai" / "yolo.py").read_text(encoding="utf-8")
        settings = (service_dir / "modal_ai" / "settings.py").read_text(encoding="utf-8")
        viewer = (service_dir / "modal_ai" / "viewer.py").read_text(encoding="utf-8")

        self.assertIn('@web.websocket("/ws/ingest")', entrypoint)
        self.assertIn('@web.websocket("/ingest")', entrypoint)
        self.assertIn('@web.websocket("/ws/results")', entrypoint)
        self.assertIn('@web.post("/ingest"', entrypoint)
        self.assertIn("from modal_ai.runtime import app, frame_queue, image, result_queue, state_store", entrypoint)
        self.assertIn("from modal_ai.yolo import draw_and_detect", entrypoint)
        self.assertIn("frame_queue.put", entrypoint)
        self.assertIn("frame_queue.get", entrypoint)
        self.assertIn("VIEWER_HTML", entrypoint)

        self.assertIn("modal.Image.debian_slim", runtime)
        self.assertIn('add_local_python_source("modal_ai")', runtime)
        self.assertIn("modal.Queue.from_name(FRAME_QUEUE_NAME", runtime)
        self.assertIn("modal.Queue.from_name(RESULT_QUEUE_NAME", runtime)
        self.assertIn("modal.Dict.from_name(STATE_DICT_NAME", runtime)

        self.assertIn("def latest_results_snapshot", results)
        self.assertIn("def publish_result", results)
        self.assertIn("result_queue.put", results)

        self.assertIn("def draw_and_detect", yolo)
        self.assertIn("model.predict", yolo)
        self.assertIn("person", settings)
        self.assertIn("car", settings)
        self.assertIn("Modal YOLOv11 Live Result Viewer", viewer)


if __name__ == "__main__":
    unittest.main()
