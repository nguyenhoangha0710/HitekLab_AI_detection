import unittest

import numpy as np

from common.frame_job import FrameJob
from common.image_codec import encode_jpeg
from common.models import FrameMetadata
from common.time_utils import utc_now
from edge_gateway.config import CameraIngestConfig
from edge_gateway.live_viewer import LiveFrameHub, create_live_viewer_app
from edge_gateway.transport.modal_bbox_sender import FanOutFrameSink, to_websocket_bbox_url


class EdgeLiveViewerTests(unittest.TestCase):
    def _camera(self):
        return CameraIngestConfig(
            camera_id="camera-1",
            location_id="location-1",
            name="Camera 1",
            source_type="RTSP",
            source_url="rtsp://localhost:8554/camera1",
            target_fps=15,
            frame_width=320,
            frame_height=180,
            encoding="JPEG",
        )

    def _job(self, sequence_number: int):
        frame = np.zeros((180, 320, 3), dtype=np.uint8)
        now = utc_now()
        metadata = FrameMetadata(
            frame_id="camera-1-{:012d}".format(sequence_number),
            camera_id="camera-1",
            location_id="location-1",
            source_type="RTSP",
            source_url="rtsp://localhost:8554/camera1",
            timestamp=now,
            captured_at=now,
            received_at=now,
            sequence_number=sequence_number,
            source_width=320,
            source_height=180,
            frame_width=320,
            frame_height=180,
            target_fps=15,
            fps=15,
            encoding="JPEG",
        )
        return FrameJob(metadata=metadata, frame=frame, image_bytes=encode_jpeg(frame), received_at=now)

    def test_live_frame_hub_keeps_latest_and_recent_history_per_camera(self):
        hub = LiveFrameHub([self._camera()], history_size_per_camera=1)

        first_summary = hub.enqueue(self._job(1))
        second_summary = hub.enqueue(self._job(2))
        latest = hub.latest("camera-1")

        self.assertEqual(1, first_summary.sequence_number)
        self.assertEqual(2, second_summary.sequence_number)
        self.assertIsNotNone(latest)
        self.assertEqual(2, latest.sequence_number)
        self.assertEqual("camera-1-000000000002", latest.frame_id)
        self.assertEqual(1, second_summary.queue_size)
        self.assertIsNone(hub.frame_by_id("camera-1", "camera-1-000000000001"))
        self.assertEqual(2, hub.frame_by_id("camera-1", "camera-1-000000000002").sequence_number)

    def test_create_live_viewer_app_registers_routes(self):
        app = create_live_viewer_app(LiveFrameHub([self._camera()]), [self._camera()])
        paths = {route.path for route in app.routes}

        self.assertIn("/viewer", paths)
        self.assertIn("/viewer/live", paths)
        self.assertIn("/viewer/sync", paths)
        self.assertIn("/api/cameras", paths)
        self.assertIn("/api/cameras/{camera_id}/mjpeg", paths)
        self.assertIn("/api/cameras/{camera_id}/frames/{frame_id}.jpg", paths)
        self.assertIn("/api/cameras/{camera_id}/detections", paths)
        self.assertIn("/api/cameras/{camera_id}/detections/stream", paths)

    def test_fanout_sink_sends_ai_before_viewer_and_returns_viewer_summary(self):
        calls = []

        class PrimarySink(LiveFrameHub):
            def enqueue(self, job):
                calls.append("viewer")
                return super().enqueue(job)

        class SecondarySink:
            def __init__(self):
                self.jobs = []

            def enqueue(self, job):
                calls.append("ai")
                self.jobs.append(job)

            def close(self):
                pass

        primary = PrimarySink([self._camera()])
        secondary = SecondarySink()
        sink = FanOutFrameSink(primary, secondary)

        summary = sink.enqueue(self._job(1))

        self.assertEqual(["ai", "viewer"], calls)
        self.assertEqual(1, summary.sequence_number)
        self.assertEqual(1, len(secondary.jobs))
        self.assertEqual(1, primary.latest("camera-1").sequence_number)

    def test_to_websocket_bbox_url_accepts_detect_or_base_url(self):
        self.assertEqual(
            "wss://example--api-dev.modal.run/ws/detect",
            to_websocket_bbox_url("https://example--api-dev.modal.run"),
        )
        self.assertEqual(
            "wss://example--api-dev.modal.run/ws/detect",
            to_websocket_bbox_url("https://example--api-dev.modal.run/detect"),
        )
        self.assertEqual(
            "wss://example--api-dev.modal.run/ws/detect",
            to_websocket_bbox_url("wss://example--api-dev.modal.run/ws/detect"),
        )


if __name__ == "__main__":
    unittest.main()
