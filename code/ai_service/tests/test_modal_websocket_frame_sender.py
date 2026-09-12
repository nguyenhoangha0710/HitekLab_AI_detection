import unittest
from unittest.mock import Mock

import numpy as np

from common.frame_job import FrameJob
from common.image_codec import encode_jpeg
from edge_gateway.transport.modal_websocket_sender import ModalWebSocketFrameSender, to_websocket_ingest_url
from common.models import FrameMetadata
from common.time_utils import utc_now


class ModalWebSocketFrameSenderTests(unittest.TestCase):
    def _job(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
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
            target_fps=5.0,
            encoding="JPEG",
        )
        return FrameJob(metadata=metadata, frame=frame, image_bytes=encode_jpeg(frame), received_at=utc_now())

    def test_to_websocket_ingest_url_accepts_modal_base_url(self):
        url = to_websocket_ingest_url("https://example--api-dev.modal.run")
        self.assertEqual("wss://example--api-dev.modal.run/ws/ingest", url)

    def test_to_websocket_ingest_url_accepts_http_ingest_url(self):
        url = to_websocket_ingest_url("https://example--api-dev.modal.run/ingest")
        self.assertEqual("wss://example--api-dev.modal.run/ingest", url)

    def test_enqueue_sends_frame_packet_over_websocket(self):
        connection = Mock()
        connector = Mock(return_value=connection)
        sender = ModalWebSocketFrameSender(
            websocket_url="https://example--api-dev.modal.run/ingest",
            confidence_threshold=0.25,
            yolo_classes="person,car",
            tenant_id="tenant-1",
            connector=connector,
        )

        summary = sender.enqueue(self._job())

        connector.assert_called_once()
        connection.send.assert_called_once()
        message = connection.send.call_args.args[0]
        self.assertIn('"tenant_id":"tenant-1"', message)
        self.assertIn('"camera_id":"camera-1"', message)
        self.assertIn('"classes":["person","car"]', message)
        self.assertEqual(1, summary.enqueued_frames)
        self.assertEqual(0, summary.dropped_frames)


if __name__ == "__main__":
    unittest.main()
