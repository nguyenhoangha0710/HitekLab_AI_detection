import unittest
from unittest.mock import Mock

import numpy as np

from app.frame_queue import FrameJob
from app.image_codec import encode_jpeg
from app.modal_frame_sender import ModalFrameSender
from app.models import FrameMetadata
from app.time_utils import utc_now


class ModalFrameSenderTests(unittest.TestCase):
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

    def test_enqueue_posts_frame_packet_to_modal_ingest(self):
        response = Mock()
        http_client = Mock()
        http_client.post.return_value = response
        sender = ModalFrameSender(
            ingest_url="https://example.modal.run/ingest",
            confidence_threshold=0.25,
            yolo_classes="person,car",
            tenant_id="tenant-1",
            http_client=http_client,
        )

        summary = sender.enqueue(self._job())

        http_client.post.assert_called_once()
        _, kwargs = http_client.post.call_args
        payload = kwargs["json"]
        self.assertEqual("tenant-1", payload["tenant_id"])
        self.assertEqual("camera-1", payload["camera_id"])
        self.assertEqual("camera-1-000000000001", payload["frame_id"])
        self.assertEqual(["person", "car"], payload["classes"])
        self.assertEqual(0.25, payload["confidence"])
        self.assertTrue(payload["image_b64"])
        self.assertEqual(1, summary.enqueued_frames)
        self.assertEqual(0, summary.dropped_frames)


if __name__ == "__main__":
    unittest.main()
