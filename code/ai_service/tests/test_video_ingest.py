import threading
import unittest

import numpy as np

from edge_gateway.config import CameraIngestConfig, VideoIngestConfig, load_video_ingest_config
from edge_gateway.video_ingest import VideoIngestWorker


class FakeSource:
    def __init__(self):
        self.opened = False
        self.released = False
        self.read_count = 0

    def open(self):
        self.opened = True
        return True

    def is_opened(self):
        return self.opened

    def read(self):
        self.read_count += 1
        return True, np.zeros((720, 1280, 3), dtype=np.uint8)

    def release(self):
        self.released = True
        self.opened = False


class FakeQueue:
    def __init__(self):
        self.jobs = []

    def enqueue(self, job):
        self.jobs.append(job)
        return type(
            "Summary",
            (),
            {
                "buffered_frame_count": len(self.jobs),
                "dropped_frames": 0,
                "pending_camera_count": 1,
            },
        )()


class VideoIngestTests(unittest.TestCase):
    def _camera(self):
        return CameraIngestConfig(
            camera_id="camera-1",
            location_id="location-1",
            name="Camera 1",
            source_type="RTSP",
            source_url="rtsp://localhost:8554/camera1",
            target_fps=30,
            frame_width=640,
            frame_height=360,
            encoding="JPEG",
        )

    def _config(self):
        return VideoIngestConfig(
            reconnect_interval_seconds=0.01,
            read_retry_count=1,
            log_every_n_frames=30,
            jpeg_quality=80,
            cameras=[self._camera()],
        )

    def test_loads_video_ingest_config(self):
        config = load_video_ingest_config("config.yaml")

        self.assertEqual(2, len(config.cameras))
        self.assertEqual(15, config.cameras[0].target_fps)
        self.assertEqual(640, config.cameras[0].frame_width)
        self.assertEqual(360, config.cameras[0].frame_height)

    def test_video_ingest_worker_enqueues_frame_jobs(self):
        queue = FakeQueue()
        source = FakeSource()
        worker = VideoIngestWorker(
            camera=self._camera(),
            ingest_config=self._config(),
            frame_queue=queue,
            stop_event=threading.Event(),
            source=source,
        )

        worker.run(max_frames=2)

        self.assertEqual(2, len(queue.jobs))
        self.assertGreater(source.read_count, len(queue.jobs))
        self.assertTrue(source.released)
        self.assertEqual([1, 2], [job.metadata.sequence_number for job in queue.jobs])
        self.assertEqual("camera-1-000000000001", queue.jobs[0].metadata.frame_id)
        self.assertEqual("RTSP", queue.jobs[0].metadata.source_type)
        self.assertEqual("rtsp://localhost:8554/camera1", queue.jobs[0].metadata.source_url)
        self.assertEqual(640, queue.jobs[0].metadata.frame_width)
        self.assertEqual(360, queue.jobs[0].metadata.frame_height)
        self.assertEqual((360, 640, 3), queue.jobs[0].frame.shape)
        self.assertTrue(queue.jobs[0].image_bytes)


if __name__ == "__main__":
    unittest.main()
