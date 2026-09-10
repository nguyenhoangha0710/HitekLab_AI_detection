import unittest

import numpy as np

from app.ai_worker import AIWorker
from app.detector import Detection
from app.frame_queue import FrameJob, FrameQueueManager
from app.image_codec import encode_jpeg
from app.models import FrameMetadata
from app.result_store import MemoryResultStore
from app.time_utils import utc_now


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


if __name__ == "__main__":
    unittest.main()
