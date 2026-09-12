import unittest
from unittest.mock import Mock, patch

import numpy as np

from local_ai.worker import AIWorker
from local_ai.detector import Detection, ModalYoloHttpDetector, parse_coco_class_filter, summarize_detections
from common.frame_job import FrameJob
from local_ai.frame_queue import FrameQueueManager
from common.image_codec import encode_jpeg
from common.models import FrameMetadata
from local_ai.result_store import MemoryResultStore
from common.time_utils import utc_now


class FakePersonDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        return [
            Detection(
                class_id=0,
                class_name="person",
                confidence=0.91,
                x1=10,
                y1=12,
                x2=60,
                y2=80,
            )
        ]


class AIWorkerDetectorTests(unittest.TestCase):
    def _job(self):
        metadata = FrameMetadata(
            frame_id="camera-1-000000000001",
            camera_id="camera-1",
            location_id="location-1",
            source_type="RTSP",
            source_url="rtsp://localhost:8554/camera1",
            timestamp=utc_now(),
            captured_at=utc_now(),
            received_at=utc_now(),
            sequence_number=1,
            source_width=160,
            source_height=120,
            frame_width=160,
            frame_height=120,
            target_fps=10.0,
            encoding="JPEG",
        )
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        return FrameJob(metadata=metadata, frame=frame, image_bytes=encode_jpeg(frame), received_at=utc_now())

    def test_worker_runs_person_detector_and_writes_annotated_frame(self):
        queue = FrameQueueManager()
        result_store = MemoryResultStore()
        detector = FakePersonDetector()
        queue.enqueue(self._job())
        worker = AIWorker(queue, result_store, detector=detector, worker_id="test-worker")

        worker.run(max_frames=1)

        result = result_store.get_latest("camera-1")
        self.assertEqual(1, detector.calls)
        self.assertIsNotNone(result)
        self.assertGreater(int(result.frame.sum()), 0)

    def test_yolo_class_filter_accepts_person_and_car(self):
        self.assertEqual([0, 2], parse_coco_class_filter("person,car"))
        self.assertEqual([0, 2], parse_coco_class_filter("0,2"))

    def test_detection_summary_counts_person_and_car(self):
        detections = [
            Detection(0, "person", 0.9, 1, 1, 10, 10),
            Detection(2, "car", 0.8, 20, 20, 40, 40),
            Detection(2, "car", 0.7, 50, 50, 70, 70),
        ]

        self.assertEqual("car 2 person 1", summarize_detections(detections))

    def test_modal_detector_posts_frame_job_and_parses_detections(self):
        detector = ModalYoloHttpDetector(
            endpoint_url="https://example.modal.run/detect",
            confidence_threshold=0.25,
            yolo_classes="person,car",
            timeout_seconds=5.0,
        )
        response = Mock()
        response.json.return_value = {
            "detections": [
                {
                    "class_id": 2,
                    "class_name": "car",
                    "confidence": 0.88,
                    "bbox_xyxy": [1, 2, 30, 40],
                }
            ]
        }

        with patch("local_ai.detector.httpx.post", return_value=response) as post:
            detections = detector.detect_job(self._job())

        post.assert_called_once()
        response.raise_for_status.assert_called_once()
        self.assertEqual(1, len(detections))
        self.assertEqual("car", detections[0].class_name)
        self.assertEqual((1, 2, 30, 40), (detections[0].x1, detections[0].y1, detections[0].x2, detections[0].y2))


if __name__ == "__main__":
    unittest.main()
