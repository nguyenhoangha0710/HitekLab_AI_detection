from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModalBboxServiceTests(unittest.TestCase):
    def test_bbox_service_exposes_detect_endpoint(self):
        source = (ROOT / "modal_bbox_service.py").read_text(encoding="utf-8")

        self.assertIn('@web.post("/detect")', source)
        self.assertIn('@web.websocket("/ws/detect")', source)
        self.assertIn("class Yolo11BboxDetector", source)
        self.assertIn("detections", source)
        self.assertNotIn("image_b64\": annotated", source)

    def test_bbox_service_returns_metadata_not_processed_image(self):
        source = (ROOT / "modal_bbox_service.py").read_text(encoding="utf-8")

        self.assertIn('"bbox_xyxy"', source)
        self.assertIn('"inference_ms"', source)
        self.assertNotIn("cv2.imencode", source)


if __name__ == "__main__":
    unittest.main()
