import json
import unittest
from uuid import uuid4

import numpy as np
from fastapi.testclient import TestClient

from app.image_codec import encode_jpeg
from app.main import app, frame_queue


class FrameEndpointTests(unittest.TestCase):
    def setUp(self):
        frame_queue.clear()

    def _metadata(self, sequence_number=1):
        return {
            "frame_id": "550e8400-e29b-41d4-a716-446655440001-{:012d}".format(sequence_number),
            "camera_id": "550e8400-e29b-41d4-a716-446655440001",
            "location_id": "550e8400-e29b-41d4-a716-446655440101",
            "source_type": "RTSP",
            "source_url": "rtsp://localhost:8554/camera1",
            "timestamp": "2026-08-30T09:15:22.120Z",
            "captured_at": "2026-08-30T09:15:22.120Z",
            "received_at": "2026-08-30T09:15:22.120Z",
            "sequence_number": sequence_number,
            "source_width": 160,
            "source_height": 120,
            "frame_width": 160,
            "frame_height": 120,
            "target_fps": 10.0,
            "encoding": "JPEG",
        }

    def _post_frame(self, client, sequence_number=1):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        return client.post(
            "/api/v1/ai/frames",
            data={"metadata": json.dumps(self._metadata(sequence_number))},
            files={"image": ("frame.jpg", encode_jpeg(frame), "image/jpeg")},
        )

    def test_receive_frame_accepts_video_service_multipart_contract(self):
        client = TestClient(app)
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        correlation_id = str(uuid4())

        response = client.post(
            "/api/v1/ai/frames",
            data={"metadata": json.dumps(self._metadata())},
            files={"image": ("frame.jpg", encode_jpeg(frame), "image/jpeg")},
            headers={"X-Correlation-ID": correlation_id},
        )

        self.assertEqual(202, response.status_code)
        body = response.json()
        self.assertEqual("ACCEPTED", body["status"])
        self.assertEqual(self._metadata()["frame_id"], body["frame_id"])
        self.assertEqual(self._metadata()["camera_id"], body["camera_id"])
        self.assertEqual(correlation_id, body["correlation_id"])
        self.assertEqual(160, body["image_width"])
        self.assertEqual(120, body["image_height"])
        self.assertEqual(1, body["queue_size"])
        self.assertEqual(0, body["dropped_frames"])

    def test_camera_list_contains_queue_stats(self):
        client = TestClient(app)
        self._post_frame(client)

        response = client.get("/api/v1/ai/cameras")

        self.assertEqual(200, response.status_code)
        self.assertTrue(any(item["camera_id"] == self._metadata()["camera_id"] for item in response.json()))

    def test_queue_drops_oldest_when_full(self):
        client = TestClient(app)
        self._post_frame(client, sequence_number=1)
        self._post_frame(client, sequence_number=2)
        response = self._post_frame(client, sequence_number=3)

        body = response.json()
        self.assertEqual(2, body["queue_size"])
        self.assertEqual(1, body["dropped_frames"])

        stats = client.get("/api/v1/ai/queues").json()[0]
        self.assertEqual(3, stats["received_frames"])
        self.assertEqual(1, stats["dropped_frames"])
        self.assertEqual(2, stats["queue_size"])

    def test_latest_frame_consumes_one_frame_from_queue(self):
        client = TestClient(app)
        camera_id = self._metadata()["camera_id"]
        self._post_frame(client, sequence_number=1)

        response = client.get("/api/v1/ai/cameras/{}/latest.jpg".format(camera_id))
        self.assertEqual(200, response.status_code)
        self.assertEqual("image/jpeg", response.headers["content-type"])

        stats = client.get("/api/v1/ai/queues").json()[0]
        self.assertEqual(0, stats["queue_size"])
        self.assertEqual(1, stats["consumed_frames"])

    def test_rejects_invalid_metadata_json(self):
        client = TestClient(app)
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        response = client.post(
            "/api/v1/ai/frames",
            data={"metadata": "{invalid"},
            files={"image": ("frame.jpg", encode_jpeg(frame), "image/jpeg")},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("VALIDATION_ERROR", response.json()["error"]["code"])

    def test_rejects_invalid_image(self):
        client = TestClient(app)

        response = client.post(
            "/api/v1/ai/frames",
            data={"metadata": json.dumps(self._metadata())},
            files={"image": ("frame.jpg", b"not an image", "image/jpeg")},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual("VALIDATION_ERROR", response.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
