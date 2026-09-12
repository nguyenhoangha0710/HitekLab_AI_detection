import unittest

import numpy as np

from common.frame_job import FrameJob
from common.image_codec import decode_image
from common.models import FrameMetadata
from local_ai.result_store import MemoryResultStore
from common.time_utils import utc_now


class ResultStoreTests(unittest.TestCase):
    def _job(self, sequence_number: int = 1) -> FrameJob:
        metadata = FrameMetadata(
            frame_id="camera-1-{:012d}".format(sequence_number),
            camera_id="camera-1",
            location_id="location-1",
            source_type="RTSP",
            source_url="rtsp://localhost:8554/camera1",
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
            image_bytes=b"raw",
            received_at=utc_now(),
        )

    def test_memory_result_store_saves_latest_processed_frame(self):
        store = MemoryResultStore()
        job = self._job()
        processed = np.zeros((120, 160, 3), dtype=np.uint8)

        store.update(job, processed, utc_now(), "worker-0", 0)

        latest = store.get_latest("camera-1")
        self.assertIsNotNone(latest)
        self.assertEqual("camera-1", latest.metadata.camera_id)
        self.assertEqual("worker-0", latest.worker_id)
        self.assertEqual((160, 120), (latest.frame.shape[1], latest.frame.shape[0]))
        self.assertEqual((160, 120), (decode_image(latest.image_bytes).shape[1], decode_image(latest.image_bytes).shape[0]))

        summaries = store.list_cameras()
        self.assertEqual(1, len(summaries))
        self.assertEqual("camera-1", summaries[0].camera_id)

    def test_memory_result_store_streams_processed_frames_in_worker_order(self):
        store = MemoryResultStore(processed_stream_buffer_size=3)
        processed = np.zeros((120, 160, 3), dtype=np.uint8)

        store.update(self._job(1), processed, utc_now(), "worker-0", 0)
        store.update(self._job(2), processed, utc_now(), "worker-0", 0)
        store.update(self._job(3), processed, utc_now(), "worker-0", 0)

        self.assertEqual(1, store.pop_next("camera-1").metadata.sequence_number)
        self.assertEqual(2, store.pop_next("camera-1").metadata.sequence_number)
        self.assertEqual(3, store.pop_next("camera-1").metadata.sequence_number)
        self.assertIsNone(store.pop_next("camera-1"))

    def test_memory_result_store_reads_processed_frames_by_sequence_cursor(self):
        store = MemoryResultStore(processed_stream_buffer_size=3)
        processed = np.zeros((120, 160, 3), dtype=np.uint8)

        store.update(self._job(1), processed, utc_now(), "worker-0", 0)
        store.update(self._job(2), processed, utc_now(), "worker-0", 0)
        store.update(self._job(3), processed, utc_now(), "worker-0", 0)

        self.assertEqual(1, store.get_after("camera-1").metadata.sequence_number)
        self.assertEqual(2, store.get_after("camera-1", 1).metadata.sequence_number)
        self.assertEqual(3, store.get_after("camera-1", 2).metadata.sequence_number)
        self.assertIsNone(store.get_after("camera-1", 3))

    def test_memory_result_store_processed_stream_drops_oldest_when_full(self):
        store = MemoryResultStore(processed_stream_buffer_size=2)
        processed = np.zeros((120, 160, 3), dtype=np.uint8)

        store.update(self._job(1), processed, utc_now(), "worker-0", 0)
        store.update(self._job(2), processed, utc_now(), "worker-0", 0)
        store.update(self._job(3), processed, utc_now(), "worker-0", 0)

        self.assertEqual(2, store.pop_next("camera-1").metadata.sequence_number)
        self.assertEqual(3, store.pop_next("camera-1").metadata.sequence_number)
        self.assertIsNone(store.pop_next("camera-1"))


if __name__ == "__main__":
    unittest.main()
