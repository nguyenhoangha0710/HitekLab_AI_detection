import json
import unittest
from uuid import uuid4

import numpy as np
from fastapi.testclient import TestClient

from app.ai_worker import AIWorker
from app.frame_queue import FrameJob
from app.image_codec import encode_jpeg
from app.main import app, frame_queue, result_store
from app.models import FrameMetadata
from app.time_utils import utc_now


class FrameEndpointTests(unittest.TestCase):
    def setUp(self):
        frame_queue.clear()
        result_store.clear()

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

    def _job(self, sequence_number=1):
        metadata = FrameMetadata(**self._metadata(sequence_number))
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        return FrameJob(
            metadata=metadata,
            frame=frame,
            image_bytes=encode_jpeg(frame),
            received_at=utc_now(),
        )

    def test_receive_frame_accepts_video_ingest_multipart_contract(self):
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

    def test_latest_frame_overwrites_previous_unconsumed_frame(self):
        client = TestClient(app)
        self._post_frame(client, sequence_number=1)
        self._post_frame(client, sequence_number=2)
        response = self._post_frame(client, sequence_number=3)

        body = response.json()
        self.assertEqual(1, body["queue_size"])
        self.assertEqual(2, body["dropped_frames"])

        stats = client.get("/api/v1/ai/queues").json()[0]
        self.assertEqual(3, stats["received_frames"])
        self.assertEqual(2, stats["dropped_frames"])
        self.assertEqual(1, stats["queue_size"])
        self.assertEqual(1, stats["max_queue_size"])
        self.assertEqual(3, stats["sequence_number"])

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
        self.assertFalse(stats["is_pending"])

    def test_ai_worker_writes_processed_result_for_viewer(self):
        client = TestClient(app)
        self._post_frame(client, sequence_number=1)
        worker = AIWorker(frame_queue, result_store, shard_id=0, worker_id="test-worker")

        worker.run(max_frames=1)

        response = client.get("/api/v1/ai/results")
        self.assertEqual(200, response.status_code)
        results = response.json()
        self.assertEqual(1, len(results))
        self.assertEqual(self._metadata()["camera_id"], results[0]["camera_id"])
        self.assertEqual("test-worker", results[0]["worker_id"])

        image_response = client.get("/api/v1/ai/results/{}/latest.jpg".format(self._metadata()["camera_id"]))
        self.assertEqual(200, image_response.status_code)
        self.assertEqual("image/jpeg", image_response.headers["content-type"])

    def test_next_result_frame_reads_processed_frames_by_sequence_cursor(self):
        client = TestClient(app)
        processed = np.zeros((120, 160, 3), dtype=np.uint8)
        camera_id = self._metadata()["camera_id"]

        result_store.update(self._job(1), processed, utc_now(), "test-worker", 0)
        result_store.update(self._job(2), processed, utc_now(), "test-worker", 0)

        first = client.get("/api/v1/ai/results/{}/next.jpg?fallback_latest=true".format(camera_id))
        self.assertEqual(200, first.status_code)
        self.assertEqual("image/jpeg", first.headers["content-type"])
        self.assertEqual("1", first.headers["x-sequence-number"])

        second = client.get("/api/v1/ai/results/{}/next.jpg?after_sequence_number=1".format(camera_id))
        self.assertEqual(200, second.status_code)
        self.assertEqual("2", second.headers["x-sequence-number"])

        third = client.get("/api/v1/ai/results/{}/next.jpg?after_sequence_number=2".format(camera_id))
        self.assertEqual(204, third.status_code)

    def test_viewer_contains_dynamic_queue_ui(self):
        client = TestClient(app)

        response = client.get("/viewer")

        self.assertEqual(200, response.status_code)
        self.assertIn("/ws/ai/results", response.text)
        self.assertIn("new WebSocket", response.text)
        self.assertIn("camera-grid", response.text)
        self.assertIn("WebSocket receiving frames", response.text)
        self.assertIn("return state", response.text)
        self.assertIn("processed seq", response.text)
        self.assertNotIn("{{", response.text)

    def test_websocket_receives_latest_processed_frame_on_connect(self):
        client = TestClient(app)
        processed = np.zeros((120, 160, 3), dtype=np.uint8)
        result_store.update(self._job(7), processed, utc_now(), "test-worker", 0)

        with client.websocket_connect("/ws/ai/results") as websocket:
            message = websocket.receive_json()

        self.assertEqual("processed_frame", message["type"])
        self.assertEqual(self._metadata()["camera_id"], message["camera_id"])
        self.assertEqual(7, message["sequence_number"])
        self.assertEqual("test-worker", message["worker_id"])
        self.assertTrue(message["image_jpeg_base64"])

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
