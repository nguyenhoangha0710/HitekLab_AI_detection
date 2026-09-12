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
        self.assertIn('@web.websocket("/ws/results/shards/{shard_id}")', entrypoint)
        self.assertIn('@web.websocket("/ws/results")', entrypoint)
        self.assertIn('@web.post("/ingest"', entrypoint)
        self.assertIn("from modal_ai.runtime import app, frame_queues, image, result_queues, state_store", entrypoint)
        self.assertIn("from modal_ai.yolo import draw_and_detect", entrypoint)
        self.assertIn("shard_id_for_camera", entrypoint)
        self.assertIn("frame_queues[shard_id].put", entrypoint)
        self.assertIn("frame_queues[shard_id].get", entrypoint)
        self.assertIn("trim_frame_queue_for_put_async", entrypoint)
        self.assertIn("clear_runtime_data_async", entrypoint)
        self.assertIn('@web.post("/admin/clear-queues")', entrypoint)
        self.assertIn("result_queues[shard_id].get", entrypoint)
        self.assertIn("worker_active_key", entrypoint)
        self.assertIn("VIEWER_HTML", entrypoint)

        self.assertIn("modal.Image.debian_slim", runtime)
        self.assertIn('add_local_python_source("modal_ai")', runtime)
        self.assertIn("frame_queues = [", runtime)
        self.assertIn("result_queues = [", runtime)
        self.assertIn("modal.Queue.from_name(frame_queue_name(FRAME_QUEUE_PREFIX", runtime)
        self.assertIn("modal.Queue.from_name(frame_queue_name(RESULT_QUEUE_PREFIX", runtime)
        self.assertIn("modal.Dict.from_name(STATE_DICT_NAME", runtime)

        self.assertIn("def latest_results_snapshot", results)
        self.assertIn("def publish_result", results)
        self.assertIn("result_queue = result_queues[shard_id]", results)
        self.assertIn("result_queue.put", results)
        self.assertIn("RESULT_QUEUE_LIMIT", results)

        self.assertIn("def draw_and_detect", yolo)
        self.assertIn("model.predict", yolo)
        self.assertIn("NUM_SHARDS = 2", settings)
        self.assertIn("FRAME_QUEUE_LIMIT = 30", settings)
        self.assertIn("RESULT_QUEUE_LIMIT = 30", settings)
        self.assertIn("QUEUE_VERSION", settings)
        self.assertIn("FRAME_QUEUE_PREFIX", settings)
        self.assertIn("RESULT_QUEUE_PREFIX", settings)
        self.assertIn("person", settings)
        self.assertIn("car", settings)
        self.assertIn("Modal YOLOv11 Live Result Viewer", viewer)
        self.assertIn("/ws/results/shards/", viewer)
        self.assertIn("shard", viewer)


if __name__ == "__main__":
    unittest.main()
