"""Test luong ALERT_MODE=backend: Zone Service -> Backend API /api/v1/events."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import ZoneServiceSettings
from backend.app.database import Database
from backend.app.repositories.ai_event_repository import AiEventRepository
from backend.app.repositories.alert_repository import AlertRepository
from backend.app.repositories.camera_repository import CameraRepository
from backend.app.repositories.evidence_repository import EvidenceRepository
from backend.app.routers.ai_events import _upsert_via_backend, build_backend_event_payload
from backend.app.services.backend_event_client import BackendEventClient, BackendEventResult
from backend.app.services.evidence_policy_service import should_capture_alert_evidence


ALERT_ID = "11111111-2222-3333-4444-555555555555"


class FakeBackendClient:
    def __init__(self, database, results):
        self.database = database
        self.results = list(results)
        self.payloads = []
        self.saw_committed_event = []

    def send_event(self, payload):
        self.payloads.append(payload)
        # Backend doc ai_event tu DB -> ai_event phai duoc commit truoc khi goi.
        with self.database.session() as connection:
            row = AiEventRepository(connection, self.database).get(payload["aiEventId"])
            self.saw_committed_event.append(row is not None)
        return self.results.pop(0)

    def status(self):
        return {}


def event(seq=10, last_seen="2026-10-30T03:00:05Z", **overrides):
    data = {
        "source_event_id": "camera-1|zone|rule|person-1|10",
        "camera_id": "camera-1",
        "zone_id": None,
        "rule_config_id": None,
        "event_type": "person_intrusion",
        "object_type": "person",
        "track_id": "person-1",
        "confidence": 0.91,
        "lifecycle_status": "active",
        "first_sequence_number": 10,
        "last_sequence_number": seq,
        "started_at": "2026-10-30T03:00:00Z",
        "last_seen_at": last_seen,
        "ended_at": None,
        "payload": {"frame_id": "frame-{}".format(seq)},
    }
    data.update(overrides)
    return data


class BackendFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.database = Database(root / "zone.db")
        self.database.initialize()
        with self.database.session() as connection:
            CameraRepository(connection).seed_from_config(
                "tenant-1",
                [{
                    "id": "camera-1",
                    "location_id": "location-1",
                    "name": "Camera 1",
                    "source_type": "RTSP",
                    "source_url": "rtsp://localhost:8554/camera1",
                    "status": "ACTIVE",
                }],
            )
        self.settings = ZoneServiceSettings(
            database_path=root / "zone.db",
            reference_frame_dir=root / "ref",
            evidence_dir=root / "evidence",
            camera_config_path=root / "missing.yaml",
            edge_gateway_base_url="http://127.0.0.1:9",  # khong ton tai -> bo qua chup anh
            tenant_id="tenant-1",
            evidence_video_enabled=False,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_event_committed_before_backend_call_and_alert_id_linked(self):
        client = FakeBackendClient(self.database, [BackendEventResult(ok=True, status_code=202, alert_id=ALERT_ID)])
        row = _upsert_via_backend(self.database, self.settings, client, event())

        self.assertEqual([True], client.saw_committed_event)
        self.assertEqual(ALERT_ID, str(row["alert_id"]))
        sent = client.payloads[0]
        self.assertEqual("camera-1", sent["cameraId"])
        self.assertEqual("location-1", sent["areaId"])
        self.assertEqual("person", sent["objectType"])
        self.assertEqual(0.91, sent["confidence"])
        self.assertEqual("2026-10-30T03:00:05Z", sent["occurredAt"])
        self.assertEqual(str(row["id"]), sent["aiEventId"])
        self.assertNotIn("eventType", sent)
        with self.database.session() as connection:
            alert = AlertRepository(connection, self.database).get(ALERT_ID)
        self.assertEqual("backend:" + ALERT_ID, alert["dedup_key"])

    def test_heartbeat_keeps_alert_id_when_backend_returns_null(self):
        client = FakeBackendClient(
            self.database,
            [
                BackendEventResult(ok=True, status_code=202, alert_id=ALERT_ID),
                BackendEventResult(ok=True, status_code=202, alert_id=None),
            ],
        )
        first = _upsert_via_backend(self.database, self.settings, client, event())
        second = _upsert_via_backend(self.database, self.settings, client, event(seq=20, last_seen="2026-10-30T03:00:06Z"))

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(ALERT_ID, str(second["alert_id"]))
        self.assertEqual(first["id"], client.payloads[1]["aiEventId"])
        self.assertEqual("2026-10-30T03:00:06Z", client.payloads[1]["occurredAt"])

    def test_backend_failure_still_stores_ai_event(self):
        client = FakeBackendClient(
            self.database, [BackendEventResult(ok=False, error_code="BACKEND_UNREACHABLE", error_message="refused")]
        )
        row = _upsert_via_backend(self.database, self.settings, client, event())
        self.assertIsNone(row["alert_id"])
        with self.database.session() as connection:
            self.assertIsNotNone(AiEventRepository(connection, self.database).get(str(row["id"])))
            self.assertEqual([], AlertRepository(connection, self.database).list())

    def test_no_local_alert_created_in_backend_mode_without_alert_id(self):
        client = FakeBackendClient(self.database, [BackendEventResult(ok=True, status_code=202, alert_id=None)])
        _upsert_via_backend(self.database, self.settings, client, event())
        with self.database.session() as connection:
            self.assertEqual([], AlertRepository(connection, self.database).list())

    def test_crowd_event_without_confidence_uses_min_object_confidence(self):
        data = event(
            confidence=None,
            event_type="crowd_limit",
            payload={"contract": {"objects": [{"confidence": 0.8}, {"confidence": 0.65}]}},
        )
        payload = build_backend_event_payload({"id": "e1", "camera_id": "camera-1"}, data, "location-1")
        self.assertEqual(0.65, payload["confidence"])

    def test_evidence_interval_falls_back_to_ai_event_when_no_alert(self):
        client = FakeBackendClient(self.database, [BackendEventResult(ok=True, status_code=202, alert_id=None)])
        row = _upsert_via_backend(self.database, self.settings, client, event())
        with self.database.session() as connection:
            repository = EvidenceRepository(connection, self.database)
            repository.create(
                {
                    "ai_event_id": str(row["id"]),
                    "camera_id": "camera-1",
                    "storage_key": "x.jpg",
                    "frame_id": "frame-10",
                    "captured_at": "2026-10-30T03:00:05Z",
                }
            )
            soon = should_capture_alert_evidence(repository, None, {"last_seen_at": "2026-10-30T03:00:06Z"}, 120, str(row["id"]))
            later = should_capture_alert_evidence(repository, None, {"last_seen_at": "2026-10-30T03:03:00Z"}, 120, str(row["id"]))
        self.assertFalse(soon)
        self.assertTrue(later)


class BackendEventClientTests(unittest.TestCase):
    def make_client(self, responses, now=1000.0):
        self.calls = []
        self.now = now

        def post(url, payload, headers, timeout):
            self.calls.append((url.rsplit("/api/v1/", 1)[-1], payload, headers))
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        return BackendEventClient("http://backend:5250/", "ai-service", "secret", http_post=post, clock=lambda: self.now)

    def test_token_is_cached_and_sent_as_bearer(self):
        client = self.make_client(
            [(200, {"accessToken": "t1"}), (202, {"alertId": ALERT_ID}), (202, {"alertId": None})]
        )
        first = client.send_event({"aiEventId": "a"})
        second = client.send_event({"aiEventId": "a"})
        self.assertEqual(ALERT_ID, first.alert_id)
        self.assertTrue(second.ok)
        self.assertIsNone(second.alert_id)
        self.assertEqual(["auth/token", "events", "events"], [c[0] for c in self.calls])
        self.assertEqual({"clientId": "ai-service", "clientSecret": "secret"}, self.calls[0][1])
        self.assertEqual("Bearer t1", self.calls[1][2]["Authorization"])

    def test_401_refreshes_token_once(self):
        client = self.make_client(
            [(200, {"accessToken": "old"}), (401, {}), (200, {"accessToken": "new"}), (202, {"alertId": ALERT_ID})]
        )
        result = client.send_event({"aiEventId": "a"})
        self.assertTrue(result.ok)
        self.assertEqual("Bearer new", self.calls[-1][2]["Authorization"])
        self.assertEqual(2, client.status()["token_requests"])

    def test_token_expires_after_ttl(self):
        client = self.make_client(
            [(200, {"accessToken": "t1", "expiresIn": 3600}), (202, {}), (200, {"accessToken": "t2"}), (202, {})]
        )
        client.send_event({})
        self.now += 3600
        client.send_event({})
        self.assertEqual("Bearer t2", self.calls[-1][2]["Authorization"])

    def test_400_error_code_is_reported(self):
        client = self.make_client(
            [(200, {"accessToken": "t"}), (400, {"error": {"code": "AI_EVENT_NOT_FOUND", "message": "missing"}})]
        )
        result = client.send_event({"aiEventId": "a"})
        self.assertFalse(result.ok)
        self.assertEqual("AI_EVENT_NOT_FOUND", result.error_code)
        self.assertEqual({"AI_EVENT_NOT_FOUND": 1}, client.status()["error_codes"])

    def test_unreachable_backend_does_not_raise(self):
        client = self.make_client([OSError("connection refused")])
        result = client.send_event({"aiEventId": "a"})
        self.assertFalse(result.ok)
        self.assertEqual("AUTH_FAILED", result.error_code)


if __name__ == "__main__":
    unittest.main()
