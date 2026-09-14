import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import ZoneServiceSettings
from backend.app.database import Database
from backend.app.repositories.camera_repository import CameraRepository
from backend.app.repositories.reference_frame_repository import ReferenceFrameRepository
from backend.app.repositories.rule_config_repository import RuleConfigRepository
from backend.app.repositories.zone_repository import ZoneRepository
from backend.app.routers.cameras import create_camera_router
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
            camera_config_path=self.root / "missing.yaml",
            edge_gateway_base_url="http://localhost:8002",
            tenant_id="tenant-1",
        )
        camera_router = create_camera_router(self.database, settings)
        zone_router = create_zone_router(self.database)
        paths = {route.path for route in camera_router.routes + zone_router.routes}

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

    def test_camera_response_uses_zone_service_urls(self):
        from backend.app.serializers import camera_out

        with self.database.session() as connection:
            row = CameraRepository(connection).get_camera("camera-1")

        output = camera_out(row, "http://localhost:8002")

        self.assertEqual("/api/cameras/camera-1/mjpeg", output.live_stream_url)
        self.assertEqual("/api/cameras/camera-1/latest.jpg", output.latest_frame_url)
        self.assertEqual("/api/cameras/camera-1/detections/stream", output.detection_stream_url)

    def test_main_app_registers_detect_page(self):
        from backend.app.main import create_app

        app = create_app()
        paths = {route.path for route in app.routes}

        self.assertIn("/", paths)
        self.assertIn("/detect", paths)


if __name__ == "__main__":
    unittest.main()
