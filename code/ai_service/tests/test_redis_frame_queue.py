import os
import unittest
from uuid import uuid4

import numpy as np

from app.ai_worker import AIWorker
from app.frame_queue import FrameJob
from app.image_codec import encode_jpeg
from app.models import FrameMetadata
from app.redis_frame_queue import RedisFrameQueueManager, stable_shard_id
from app.result_store import RedisResultStore
from app.time_utils import utc_now


def redis_tests_enabled() -> bool:
    return os.getenv("RUN_REDIS_TESTS") == "1"


class RedisShardTests(unittest.TestCase):
    def test_stable_shard_id_is_deterministic(self):
        camera_id = "550e8400-e29b-41d4-a716-446655440001"

        first = stable_shard_id(camera_id, 4)
        second = stable_shard_id(camera_id, 4)

        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 4)


@unittest.skipUnless(redis_tests_enabled(), "set RUN_REDIS_TESTS=1 to run Redis integration tests")
class RedisFrameQueueManagerTests(unittest.TestCase):
    def setUp(self):
        self.prefix = "ai-test-{}".format(uuid4())
        self.queue = RedisFrameQueueManager(
            redis_url=os.getenv("AI_REDIS_URL", "redis://localhost:6379/0"),
            key_prefix=self.prefix,
            num_shards=4,
            latest_ttl_seconds=30,
            frame_buffer_size=5,
        )
        self.queue.clear()
        self.result_store = RedisResultStore(
            redis_url=os.getenv("AI_REDIS_URL", "redis://localhost:6379/0"),
            key_prefix=self.prefix,
        )
        self.result_store.clear()

    def tearDown(self):
        self.queue.clear()
        self.result_store.clear()

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
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        return FrameJob(
            metadata=metadata,
            frame=frame,
            image_bytes=encode_jpeg(frame),
            received_at=utc_now(),
        )

    def test_connects_to_redis(self):
        import redis

        client = redis.Redis.from_url(os.getenv("AI_REDIS_URL", "redis://localhost:6379/0"))
        self.assertTrue(client.ping())

    def test_latest_frame_buffer_trims_only_same_camera_when_full(self):
        self.queue.enqueue(self._job("camera-1", 1))
        self.queue.enqueue(self._job("camera-1", 2))
        self.queue.enqueue(self._job("camera-1", 3))
        self.queue.enqueue(self._job("camera-1", 4))
        self.queue.enqueue(self._job("camera-1", 5))
        self.queue.enqueue(self._job("camera-1", 6))
        self.queue.enqueue(self._job("camera-2", 1))

        stats = {item.camera_id: item for item in self.queue.list_cameras()}
        self.assertEqual(1, stats["camera-1"].dropped_frames)
        self.assertEqual(0, stats["camera-2"].dropped_frames)
        self.assertEqual(1, stats["camera-1"].queue_size)
        self.assertEqual(1, stats["camera-2"].queue_size)
        self.assertEqual(5, stats["camera-1"].buffered_frame_count)
        self.assertEqual(1, stats["camera-2"].buffered_frame_count)
        self.assertEqual(2, self.queue.pending_camera_count())

    def test_pending_camera_queue_is_deduplicated(self):
        self.queue.enqueue(self._job("camera-1", 1))
        self.queue.enqueue(self._job("camera-1", 2))
        self.queue.enqueue(self._job("camera-1", 3))

        stats = self.queue.list_cameras()[0]
        self.assertEqual(1, stats.queue_size)
        self.assertEqual(1, stats.enqueued_frames)
        self.assertEqual(0, stats.dropped_frames)
        self.assertEqual(3, stats.buffered_frame_count)

    def test_claim_next_reads_camera_from_its_shard(self):
        camera_id = "camera-1"
        self.queue.enqueue(self._job(camera_id, 1))
        shard_id = self.queue.shard_id(camera_id)

        job = self.queue.claim_next(shard_id=shard_id, timeout_seconds=1)

        self.assertIsNotNone(job)
        self.assertEqual(camera_id, job.metadata.camera_id)
        self.queue.complete(job.metadata.camera_id, job.metadata.sequence_number, job.metadata.frame_id)

    def test_claim_next_batch_reads_unconsumed_frames_in_sequence_order(self):
        camera_id = "camera-1"
        for sequence_number in range(1, 7):
            self.queue.enqueue(self._job(camera_id, sequence_number))
        shard_id = self.queue.shard_id(camera_id)

        jobs = self.queue.claim_next_batch(shard_id=shard_id, timeout_seconds=1)

        self.assertEqual([2, 3, 4, 5, 6], [job.metadata.sequence_number for job in jobs])
        latest = jobs[-1]
        self.queue.complete(latest.metadata.camera_id, latest.metadata.sequence_number, latest.metadata.frame_id)

    def test_dirty_camera_is_requeued_after_processing(self):
        self.queue.enqueue(self._job("camera-1", 1))
        shard_id = self.queue.shard_id("camera-1")
        processing = self.queue.claim_next(shard_id=shard_id, timeout_seconds=1)

        self.queue.enqueue(self._job("camera-1", 2))
        self.queue.complete(processing.metadata.camera_id, processing.metadata.sequence_number, processing.metadata.frame_id)

        requeued = self.queue.claim_next(shard_id=shard_id, timeout_seconds=1)
        self.assertIsNotNone(requeued)
        self.assertEqual(2, requeued.metadata.sequence_number)

    def test_worker_recovers_camera_stuck_in_processing_set(self):
        camera_id = "camera-1"
        self.queue.enqueue(self._job(camera_id, 1))
        shard_id = self.queue.shard_id(camera_id)

        stuck_jobs = self.queue.claim_next_batch(shard_id=shard_id, timeout_seconds=1)
        self.assertEqual([1], [job.metadata.sequence_number for job in stuck_jobs])
        self.queue.enqueue(self._job(camera_id, 2))

        worker = AIWorker(self.queue, self.result_store, shard_id=shard_id, worker_id="redis-worker")
        worker.run(max_frames=1)

        result = self.result_store.get_latest(camera_id)
        self.assertIsNotNone(result)
        self.assertEqual(2, result.metadata.sequence_number)
        stats = self.queue.list_cameras()[0]
        self.assertFalse(stats.is_processing)
        self.assertEqual(2, stats.last_consumed_sequence_number)

    def test_worker_processes_all_frames_buffered_for_camera(self):
        camera_id = "camera-1"
        for sequence_number in range(1, 6):
            self.queue.enqueue(self._job(camera_id, sequence_number))
        shard_id = self.queue.shard_id(camera_id)
        worker = AIWorker(self.queue, self.result_store, shard_id=shard_id, worker_id="redis-worker")

        worker.run(max_frames=5)

        result = self.result_store.get_latest(camera_id)
        self.assertIsNotNone(result)
        self.assertEqual(5, result.metadata.sequence_number)
        stats = self.queue.list_cameras()[0]
        self.assertEqual(0, stats.buffered_frame_count)
        self.assertEqual(5, stats.consumed_frames)
        self.assertEqual(5, stats.last_consumed_sequence_number)

    def test_claim_batch_size_keeps_camera_turns_fair(self):
        queue = RedisFrameQueueManager(
            redis_url=os.getenv("AI_REDIS_URL", "redis://localhost:6379/0"),
            key_prefix="ai-test-{}".format(uuid4()),
            num_shards=1,
            latest_ttl_seconds=30,
            frame_buffer_size=5,
            claim_batch_size=1,
        )
        queue.clear()
        try:
            for sequence_number in range(1, 4):
                queue.enqueue(self._job("camera-1", sequence_number))
                queue.enqueue(self._job("camera-2", sequence_number))

            first = queue.claim_next_batch(shard_id=0, timeout_seconds=1)
            queue.complete(first[-1].metadata.camera_id, first[-1].metadata.sequence_number, first[-1].metadata.frame_id)
            second = queue.claim_next_batch(shard_id=0, timeout_seconds=1)
            queue.complete(second[-1].metadata.camera_id, second[-1].metadata.sequence_number, second[-1].metadata.frame_id)
            third = queue.claim_next_batch(shard_id=0, timeout_seconds=1)
            queue.complete(third[-1].metadata.camera_id, third[-1].metadata.sequence_number, third[-1].metadata.frame_id)
            fourth = queue.claim_next_batch(shard_id=0, timeout_seconds=1)

            self.assertEqual(["camera-1"], [job.metadata.camera_id for job in first])
            self.assertEqual([1], [job.metadata.sequence_number for job in first])
            self.assertEqual(["camera-2"], [job.metadata.camera_id for job in second])
            self.assertEqual([1], [job.metadata.sequence_number for job in second])
            self.assertEqual(["camera-1"], [job.metadata.camera_id for job in third])
            self.assertEqual([2], [job.metadata.sequence_number for job in third])
            self.assertEqual(["camera-2"], [job.metadata.camera_id for job in fourth])
            self.assertEqual([2], [job.metadata.sequence_number for job in fourth])
        finally:
            queue.clear()

    def test_sequence_reset_reopens_camera_after_video_ingest_restart(self):
        camera_id = "camera-1"
        self.queue.enqueue(self._job(camera_id, 4530))
        shard_id = self.queue.shard_id(camera_id)
        old_jobs = self.queue.claim_next_batch(shard_id=shard_id, timeout_seconds=1)
        self.queue.complete(camera_id, old_jobs[-1].metadata.sequence_number, old_jobs[-1].metadata.frame_id)

        stats_before = self.queue.list_cameras()[0]
        self.assertEqual(4530, stats_before.last_consumed_sequence_number)

        self.queue.enqueue(self._job(camera_id, 1))
        stats_after_reset = self.queue.list_cameras()[0]
        self.assertIsNone(stats_after_reset.last_consumed_sequence_number)
        self.assertEqual(1, stats_after_reset.sequence_resets)

        new_jobs = self.queue.claim_next_batch(shard_id=shard_id, timeout_seconds=1)
        self.assertEqual([1], [job.metadata.sequence_number for job in new_jobs])

    def test_worker_consumes_redis_queue_and_writes_redis_result(self):
        camera_id = "camera-1"
        self.queue.enqueue(self._job(camera_id, 1))
        shard_id = self.queue.shard_id(camera_id)
        worker = AIWorker(self.queue, self.result_store, shard_id=shard_id, worker_id="redis-worker")

        worker.run(max_frames=1)

        result = self.result_store.get_latest(camera_id)
        self.assertIsNotNone(result)
        self.assertEqual(camera_id, result.metadata.camera_id)
        self.assertEqual("redis-worker", result.worker_id)
        self.assertEqual(1, result.metadata.sequence_number)

    def test_redis_result_store_streams_processed_frames_in_worker_order(self):
        camera_id = "camera-1"
        processed = np.zeros((120, 160, 3), dtype=np.uint8)

        self.result_store.update(self._job(camera_id, 1), processed, utc_now(), "redis-worker", 0)
        self.result_store.update(self._job(camera_id, 2), processed, utc_now(), "redis-worker", 0)
        self.result_store.update(self._job(camera_id, 3), processed, utc_now(), "redis-worker", 0)

        self.assertEqual(1, self.result_store.pop_next(camera_id).metadata.sequence_number)
        self.assertEqual(2, self.result_store.pop_next(camera_id).metadata.sequence_number)
        self.assertEqual(3, self.result_store.pop_next(camera_id).metadata.sequence_number)
        self.assertIsNone(self.result_store.pop_next(camera_id))

    def test_redis_result_store_reads_processed_frames_by_sequence_cursor(self):
        camera_id = "camera-1"
        processed = np.zeros((120, 160, 3), dtype=np.uint8)

        self.result_store.update(self._job(camera_id, 1), processed, utc_now(), "redis-worker", 0)
        self.result_store.update(self._job(camera_id, 2), processed, utc_now(), "redis-worker", 0)
        self.result_store.update(self._job(camera_id, 3), processed, utc_now(), "redis-worker", 0)

        self.assertEqual(1, self.result_store.get_after(camera_id).metadata.sequence_number)
        self.assertEqual(2, self.result_store.get_after(camera_id, 1).metadata.sequence_number)
        self.assertEqual(3, self.result_store.get_after(camera_id, 2).metadata.sequence_number)
        self.assertIsNone(self.result_store.get_after(camera_id, 3))

    def test_redis_result_store_clears_processed_stream_after_sequence_reset(self):
        camera_id = "camera-1"
        processed = np.zeros((120, 160, 3), dtype=np.uint8)

        self.result_store.update(self._job(camera_id, 4529), processed, utc_now(), "redis-worker", 0)
        self.result_store.update(self._job(camera_id, 4530), processed, utc_now(), "redis-worker", 0)
        self.result_store.update(self._job(camera_id, 1), processed, utc_now(), "redis-worker", 0)

        self.assertEqual(1, self.result_store.get_after(camera_id).metadata.sequence_number)
        self.assertIsNone(self.result_store.get_after(camera_id, 4530))


if __name__ == "__main__":
    unittest.main()
