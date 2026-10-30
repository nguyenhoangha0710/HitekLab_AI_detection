from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class LocalBboxServiceTests(unittest.TestCase):
    def test_local_bbox_service_exposes_same_bbox_contract(self):
        source = (ROOT / "local_bbox_service.py").read_text(encoding="utf-8")

        self.assertIn('@app.post("/detect")', source)
        self.assertIn('@app.websocket("/ws/detect")', source)
        self.assertIn("class LocalYoloBboxDetector", source)
        self.assertIn('"bbox_xyxy"', source)
        self.assertIn("MultiCameraByteTracker", source)
        self.assertIn('"inference_ms"', source)

    def test_local_bbox_service_runs_rule_engine_after_tracking(self):
        source = (ROOT / "local_bbox_service.py").read_text(encoding="utf-8")

        self.assertNotIn("modal", source.lower())
        self.assertIn("def analyze_frame", source)
        self.assertIn('result["rule_engine"] = engine.process(result)', source)
        self.assertIn('@app.get("/rules/status")', source)
        self.assertIn('@app.post("/rules/reload")', source)

    def test_modal_branch_is_removed(self):
        self.assertFalse((ROOT / "modal_ai").exists())
        self.assertFalse((ROOT / "modal_yolo11_service.py").exists())
        self.assertFalse((ROOT / "edge_gateway" / "transport" / "modal_bbox_sender.py").exists())

    def test_tracker_keeps_camera_state_separate(self):
        from local_ai.byte_tracker import MultiCameraByteTracker

        tracker = MultiCameraByteTracker()
        detection = {
            "class_name": "person",
            "confidence": 0.9,
            "bbox_xyxy": [10, 10, 50, 80],
        }

        cam_a_first = tracker.update("camera-a", [detection], sequence_number=1)[0]
        cam_a_second = tracker.update("camera-a", [detection], sequence_number=2)[0]
        cam_b_first = tracker.update("camera-b", [detection], sequence_number=1)[0]

        self.assertEqual(cam_a_first["track_id"], cam_a_second["track_id"])
        self.assertEqual(1, cam_b_first["track_id"])


if __name__ == "__main__":
    unittest.main()
