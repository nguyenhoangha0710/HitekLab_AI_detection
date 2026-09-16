import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import ZoneServiceSettings
from backend.app.database import Database
from backend.app.repositories.ai_event_repository import AiEventRepository
from backend.app.repositories.alert_repository import AlertRepository
from backend.app.repositories.camera_repository import CameraRepository
from backend.app.repositories.evidence_repository import EvidenceRepository
from backend.app.repositories.reference_frame_repository import ReferenceFrameRepository
from backend.app.repositories.rule_config_repository import RuleConfigRepository
from backend.app.repositories.zone_repository import ZoneRepository
from backend.app.routers.ai_events import _should_capture_alert_evidence
from backend.app.routers.cameras import create_camera_router
from backend.app.routers.ai_events import create_ai_event_router
from backend.app.routers.zones import create_zone_router


class ZoneServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = Database(self.root / "zone.db")
        self.database.initialize()
        self.camera = {
            "id": "camera-1",
            "location_id": "location-1",
            "name": "Camera 1",
            "source_type": "RTSP",
            "source_url": "rtsp://localhost:8554/camera1",
            "status": "ACTIVE",
        }
        with self.database.session() as connection:
            CameraRepository(connection).seed_from_config("tenant-1", [self.camera])

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seed_camera_from_config(self):
        with self.database.session() as connection:
            row = CameraRepository(connection).get_camera("camera-1")

        self.assertIsNotNone(row)
        self.assertEqual("Camera 1", row["name"])
        self.assertEqual("location-1", row["location_id"])

    def test_create_update_delete_zone(self):
        payload = {
            "name": "Door Area",
            "zone_type": "restricted_area",
            "polygon": {"points": [{"x": 1, "y": 2}, {"x": 3, "y": 2}, {"x": 2, "y": 5}]},
            "frame_width": 640,
            "frame_height": 360,
            "enabled": True,
        }

        with self.database.session() as connection:
            repository = ZoneRepository(connection)
            created = repository.create("camera-1", payload)
            updated = repository.update(created["id"], {"name": "Updated Door Area"})
            zones = repository.list_by_camera("camera-1")
            rules = RuleConfigRepository(connection).list_by_zone(created["id"])
            deleted = repository.delete(created["id"])

        self.assertEqual("Door Area", created["name"])
        self.assertEqual("Updated Door Area", updated["name"])
        self.assertEqual(1, len(zones))
        self.assertEqual({"person_intrusion", "vehicle_intrusion"}, {rule["rule_type"] for rule in rules})
        self.assertTrue(deleted)

    def test_reference_frame_metadata(self):
        with self.database.session() as connection:
            row = ReferenceFrameRepository(connection).create(
                camera_id="camera-1",
                storage_key="camera-1/reference.jpg",
                mime_type="image/jpeg",
                frame_width=640,
                frame_height=360,
                captured_at="2026-09-13T00:00:00Z",
            )

        self.assertEqual("camera-1", row["camera_id"])
        self.assertEqual(640, row["frame_width"])

    def test_zone_routes_are_registered(self):
        settings = ZoneServiceSettings(
            database_path=self.root / "zone.db",
            reference_frame_dir=self.root / "reference_frames",
            evidence_dir=self.root / "evidence",
            camera_config_path=self.root / "missing.yaml",
            edge_gateway_base_url="http://localhost:8002",
            tenant_id="tenant-1",
        )
        camera_router = create_camera_router(self.database, settings)
        ai_event_router = create_ai_event_router(self.database, settings)
        zone_router = create_zone_router(self.database)
        paths = {route.path for route in camera_router.routes + zone_router.routes + ai_event_router.routes}

        self.assertIn("/api/cameras", paths)
        self.assertIn("/api/cameras/{camera_id}/mjpeg", paths)
        self.assertIn("/api/cameras/{camera_id}/latest.jpg", paths)
        self.assertIn("/api/cameras/{camera_id}/frames/{frame_id}.jpg", paths)
        self.assertIn("/api/cameras/{camera_id}/reference-frame", paths)
        self.assertIn("/api/cameras/{camera_id}/detections/stream", paths)
        self.assertIn("/api/cameras/{camera_id}/zones", paths)
        self.assertIn("/api/zones/{zone_id}/rules", paths)
        self.assertIn("/api/zones/{zone_id}", paths)
        self.assertIn("/api/rules/{rule_id}", paths)
        self.assertIn("/api/ai-events", paths)
        self.assertIn("/api/alerts", paths)
        self.assertIn("/api/evidence", paths)
        self.assertIn("/api/evidence/video", paths)

    def test_camera_response_uses_zone_service_urls(self):
        from backend.app.serializers import camera_out

        with self.database.session() as connection:
            row = CameraRepository(connection).get_camera("camera-1")

        output = camera_out(row, "http://localhost:8002")

        self.assertEqual("/api/cameras/camera-1/mjpeg", output.live_stream_url)
        self.assertEqual("/api/cameras/camera-1/latest.jpg", output.latest_frame_url)
        self.assertEqual("/api/cameras/camera-1/detections/stream", output.detection_stream_url)

    def test_ai_event_upsert_deduplicates_by_source_event_id(self):
        zone_payload = {
            "name": "Standing Area",
            "zone_type": "controlled_area",
            "polygon": {"points": [{"x": 1, "y": 2}, {"x": 3, "y": 2}, {"x": 2, "y": 5}]},
            "frame_width": 640,
            "frame_height": 360,
            "enabled": True,
        }

        with self.database.session() as connection:
            zone = ZoneRepository(connection).create("camera-1", zone_payload)
            rule = RuleConfigRepository(connection).list_by_zone(zone["id"])[0]
            repository = AiEventRepository(connection)
            created = repository.upsert(
                {
                    "source_event_id": "camera-1|zone-1|rule-1|person-1|10",
                    "camera_id": "camera-1",
                    "zone_id": zone["id"],
                    "rule_config_id": rule["id"],
                    "event_type": "loitering",
                    "object_type": "person",
                    "track_id": "person-1",
                    "confidence": 0.9,
                    "lifecycle_status": "active",
                    "first_sequence_number": 10,
                    "last_sequence_number": 10,
                    "started_at": "2026-09-15T00:00:00Z",
                    "last_seen_at": "2026-09-15T00:00:00Z",
                    "payload": {"sequence_number": 10},
                }
            )
            updated = repository.upsert(
                {
                    "source_event_id": "camera-1|zone-1|rule-1|person-1|10",
                    "camera_id": "camera-1",
                    "zone_id": zone["id"],
                    "rule_config_id": rule["id"],
                    "event_type": "loitering",
                    "object_type": "person",
                    "track_id": "person-1",
                    "confidence": 0.8,
                    "lifecycle_status": "active",
                    "first_sequence_number": 10,
                    "last_sequence_number": 20,
                    "started_at": "2026-09-15T00:00:00Z",
                    "last_seen_at": "2026-09-15T00:00:01Z",
                    "payload": {"sequence_number": 20},
                }
            )
            events = repository.list(camera_id="camera-1")

        self.assertEqual(created["id"], updated["id"])
        self.assertEqual(1, len(events))
        self.assertEqual(20, updated["last_sequence_number"])

    def test_alert_deduplicates_same_rule_context(self):
        zone_payload = {
            "name": "Dedup Area",
            "zone_type": "controlled_area",
            "polygon": {"points": [{"x": 1, "y": 2}, {"x": 3, "y": 2}, {"x": 2, "y": 5}]},
            "frame_width": 640,
            "frame_height": 360,
            "enabled": True,
        }

        with self.database.session() as connection:
            zone = ZoneRepository(connection).create("camera-1", zone_payload)
            rule = RuleConfigRepository(connection).list_by_zone(zone["id"])[0]
            repository = AlertRepository(connection)
            first = repository.upsert_for_violation(
                {
                    "source_event_id": "event-1",
                    "camera_id": "camera-1",
                    "zone_id": zone["id"],
                    "rule_config_id": rule["id"],
                    "event_type": "loitering",
                    "object_type": "person",
                    "track_id": "person-1",
                    "first_sequence_number": 10,
                    "last_sequence_number": 10,
                    "started_at": "2026-09-15T00:00:00Z",
                    "last_seen_at": "2026-09-15T00:00:00Z",
                    "payload": {"zone_name": "Dedup Area", "frame_id": "frame-10"},
                }
            )
            second = repository.upsert_for_violation(
                {
                    "source_event_id": "event-2",
                    "camera_id": "camera-1",
                    "zone_id": zone["id"],
                    "rule_config_id": rule["id"],
                    "event_type": "loitering",
                    "object_type": "person",
                    "track_id": "person-9",
                    "first_sequence_number": 11,
                    "last_sequence_number": 20,
                    "started_at": "2026-09-15T00:00:10Z",
                    "last_seen_at": "2026-09-15T00:00:10Z",
                    "payload": {"zone_name": "Dedup Area", "frame_id": "frame-20"},
                }
            )
            alerts = repository.list(camera_id="camera-1")

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(1, len(alerts))
        self.assertEqual(2, second["active_source_count"])
        self.assertEqual(20, second["last_sequence_number"])

    def test_alert_lifecycle_resolves_stale_active_alert(self):
        with self.database.session() as connection:
            repository = AlertRepository(connection)
            alert = repository.upsert_for_violation(
                {
                    "source_event_id": "event-stale",
                    "camera_id": "camera-1",
                    "zone_id": None,
                    "rule_config_id": None,
                    "event_type": "loitering",
                    "object_type": "person",
                    "track_id": "person-1",
                    "first_sequence_number": 1,
                    "last_sequence_number": 1,
                    "started_at": "2026-09-15T00:00:00Z",
                    "last_seen_at": "2026-09-15T00:00:00Z",
                    "payload": {"frame_id": "frame-1"},
                }
            )
            resolved_count = repository.resolve_stale(30, now="2026-09-15T00:00:31Z")
            resolved = repository.get(alert["id"])

        self.assertEqual(1, resolved_count)
        self.assertEqual("resolved", resolved["lifecycle_status"])
        self.assertEqual("2026-09-15T00:00:31Z", resolved["ended_at"])

    def test_evidence_interval_allows_periodic_snapshots_for_same_alert(self):
        with self.database.session() as connection:
            alert_repository = AlertRepository(connection)
            alert = alert_repository.upsert_for_violation(
                {
                    "source_event_id": "event-evidence-1",
                    "camera_id": "camera-1",
                    "zone_id": None,
                    "rule_config_id": None,
                    "event_type": "loitering",
                    "object_type": "person",
                    "track_id": "person-1",
                    "first_sequence_number": 1,
                    "last_sequence_number": 1,
                    "started_at": "2026-09-15T00:00:00Z",
                    "last_seen_at": "2026-09-15T00:00:00Z",
                    "payload": {"frame_id": "frame-1"},
                }
            )
            ai_event = AiEventRepository(connection).upsert(
                {
                    "alert_id": alert["id"],
                    "source_event_id": "event-evidence-1",
                    "camera_id": "camera-1",
                    "event_type": "loitering",
                    "object_type": "person",
                    "track_id": "person-1",
                    "first_sequence_number": 1,
                    "last_sequence_number": 1,
                    "started_at": "2026-09-15T00:00:00Z",
                    "last_seen_at": "2026-09-15T00:00:00Z",
                    "payload": {"frame_id": "frame-1"},
                }
            )
            evidence_repository = EvidenceRepository(connection)
            evidence_repository.create(
                {
                    "ai_event_id": ai_event["id"],
                    "alert_id": alert["id"],
                    "camera_id": "camera-1",
                    "evidence_type": "snapshot",
                    "storage_key": "camera-1/event-evidence-1/frame-1.jpg",
                    "mime_type": "image/jpeg",
                    "file_size": 100,
                    "frame_id": "frame-1",
                    "sequence_number": 1,
                    "captured_at": "2026-09-15T00:00:00Z",
                }
            )

            should_skip = _should_capture_alert_evidence(
                evidence_repository,
                alert["id"],
                {"started_at": "2026-09-15T00:00:00Z", "last_seen_at": "2026-09-15T00:01:00Z"},
                120,
            )
            should_capture = _should_capture_alert_evidence(
                evidence_repository,
                alert["id"],
                {"started_at": "2026-09-15T00:00:00Z", "last_seen_at": "2026-09-15T00:02:01Z"},
                120,
            )

        self.assertFalse(should_skip)
        self.assertTrue(should_capture)

    def test_rule_update_persists_duration_and_active_time(self):
        zone_payload = {
            "name": "Rule Edit Area",
            "zone_type": "restricted_area",
            "polygon": {"points": [{"x": 1, "y": 2}, {"x": 3, "y": 2}, {"x": 2, "y": 5}]},
            "frame_width": 640,
            "frame_height": 360,
            "enabled": True,
        }

        with self.database.session() as connection:
            zone = ZoneRepository(connection).create("camera-1", zone_payload)
            repository = RuleConfigRepository(connection)
            rule = repository.list_by_zone(zone["id"])[0]
            updated = repository.update(
                rule["id"],
                {
                    "duration_threshold": 33,
                    "use_active_time": True,
                    "active_start_time": "08:30",
                    "active_end_time": "17:45",
                },
            )
            reloaded = repository.get(rule["id"])

        self.assertEqual(33, updated["duration_threshold"])
        self.assertEqual(33, reloaded["duration_threshold"])
        self.assertTrue(bool(reloaded["use_active_time"]))
        self.assertEqual("08:30", reloaded["active_start_time"])
        self.assertEqual("17:45", reloaded["active_end_time"])

    def test_main_app_registers_detect_page(self):
        from backend.app.main import create_app

        app = create_app()
        paths = {route.path for route in app.routes}

        self.assertIn("/", paths)
        self.assertIn("/detect", paths)


if __name__ == "__main__":
    unittest.main()
