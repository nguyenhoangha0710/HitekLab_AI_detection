from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LocalBboxServiceTests(unittest.TestCase):
    def test_local_bbox_service_exposes_same_bbox_contract(self):
        source = (ROOT / "local_bbox_service.py").read_text(encoding="utf-8")

        self.assertIn('@app.post("/detect")', source)
        self.assertIn('@app.websocket("/ws/detect")', source)
        self.assertIn("class LocalYoloBboxDetector", source)
        self.assertIn('"bbox_xyxy"', source)
        self.assertIn('"inference_ms"', source)

    def test_local_bbox_service_does_not_depend_on_modal(self):
        source = (ROOT / "local_bbox_service.py").read_text(encoding="utf-8")

        self.assertNotIn("import modal", source)
        self.assertNotIn("@app.cls", source)
        self.assertNotIn(".remote", source)


if __name__ == "__main__":
    unittest.main()
