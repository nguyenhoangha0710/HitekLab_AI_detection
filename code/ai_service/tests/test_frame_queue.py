import unittest

import numpy as np

from common.frame_job import FrameJob
from local_ai.frame_queue import FrameQueueManager
from common.models import FrameMetadata
from common.time_utils import utc_now


class FrameQueueManagerTests(unittest.TestCase):
    def _job(self, camera_id: str, sequence_number: int) -> FrameJob:
        metadata = FrameMetadata(
            frame_id="{}-{:012d}".format(camera_id, sequence_number),
            camera_id=camera_id,
            location_id="location-{}".format(camera_id),
            source_type="RTSP",
            source_url="rtsp://localhost:8554/{}".format(camera_id),
            timestamp=utc_now(),
            captured_at=utc_now(),
            received_at=utc_now(),
            sequence_number=sequence_number,
            source_width=160,
            source_height=120,
            frame_width=160,
            frame_height=120,
            target_fps=10.0,
            encoding="JPEG",
        )
        return FrameJob(
            metadata=metadata,
            frame=np.zeros((120, 160, 3), dtype=np.uint8),
            image_bytes=b"jpeg",
            received_at=utc_now(),
        )

    def test_high_fps_camera_overwrites_only_its_own_latest_frame(self):
        queue = FrameQueueManager()

        queue.enqueue(self._job("camera-1", 1))
        queue.enqueue(self._job("camera-1", 2))
        queue.enqueue(self._job("camera-1", 3))
        queue.enqueue(self._job("camera-2", 1))

        stats = {item.camera_id: item for item in queue.list_cameras()}
        self.assertEqual(2, stats["camera-1"].dropped_frames)
        self.assertEqual(0, stats["camera-2"].dropped_frames)
        self.assertEqual(1, stats["camera-1"].queue_size)
        self.assertEqual(1, stats["camera-2"].queue_size)

    def test_pending_queue_deduplicates_camera_ids_for_fairness(self):
        queue = FrameQueueManager()

        queue.enqueue(self._job("camera-1", 1))
        queue.enqueue(self._job("camera-1", 2))
        queue.enqueue(self._job("camera-1", 3))
        queue.enqueue(self._job("camera-2", 1))

        first = queue.claim_next()
        self.assertEqual("camera-1", first.metadata.camera_id)
        self.assertEqual(3, first.metadata.sequence_number)
        queue.complete(first.metadata.camera_id, first.metadata.sequence_number, first.metadata.frame_id)

        second = queue.claim_next()
        self.assertEqual("camera-2", second.metadata.camera_id)
        self.assertEqual(1, second.metadata.sequence_number)

    def test_dirty_camera_is_requeued_after_processing_without_cutting_line(self):
        queue = FrameQueueManager()

        queue.enqueue(self._job("camera-1", 1))
        queue.enqueue(self._job("camera-2", 1))
        processing = queue.claim_next()
        self.assertEqual("camera-1", processing.metadata.camera_id)

        queue.enqueue(self._job("camera-1", 2))
        queue.complete(processing.metadata.camera_id, processing.metadata.sequence_number, processing.metadata.frame_id)

        next_camera = queue.claim_next()
        self.assertEqual("camera-2", next_camera.metadata.camera_id)
        queue.complete(next_camera.metadata.camera_id, next_camera.metadata.sequence_number, next_camera.metadata.frame_id)

        requeued = queue.claim_next()
        self.assertEqual("camera-1", requeued.metadata.camera_id)
        self.assertEqual(2, requeued.metadata.sequence_number)


if __name__ == "__main__":
    unittest.main()
