"""Test phan quyen theo tenant + location."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import jwt_utils
from backend.app.access_control import AccessControl, AccessDenied, AuthError
from backend.app.config import ZoneServiceSettings
from backend.app.database import Database
from backend.app.repositories.ai_event_repository import AiEventRepository
from backend.app.repositories.camera_repository import CameraRepository
from backend.app.repositories.evidence_repository import EvidenceRepository
from backend.app.repositories.rule_config_repository import RuleConfigRepository
from backend.app.repositories.zone_repository import ZoneRepository

SECRET = "test-secret"
NOW = 1_800_000_000.0
CAM_KHO, CAM_CONG = "cam-kho", "cam-cong"
LOC_KHO, LOC_CONG = "loc-kho", "loc-cong"


class AccessControlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.database = Database(root / "zone.db")
        self.database.initialize()
        with self.database.session() as c:
            CameraRepository(c).seed_from_config(
                "demo-tenant",
                [
                    {"id": CAM_KHO, "location_id": LOC_KHO, "name": "Kho", "source_type": "RTSP",
                     "source_url": "rtsp://x/1", "status": "ACTIVE"},
                    {"id": CAM_CONG, "location_id": LOC_CONG, "name": "Cong", "source_type": "RTSP",
                     "source_url": "rtsp://x/2", "status": "ACTIVE"},
                ],
            )
            self.tenant_id = str(c.execute("SELECT id FROM tenant WHERE code = 'demo-tenant'").fetchone()["id"])
            self._user(c, "u-owner", "owner@demo.local", "owner", {})
            self._user(c, "u-kho", "kho@demo.local", "operator", {LOC_KHO: "operator"})
            self._user(c, "u-cong", "cong@demo.local", "viewer", {LOC_CONG: "viewer"})
            self._user(c, "u-off", "off@demo.local", "operator", {LOC_KHO: "admin"}, status="disabled")
            zone = ZoneRepository(c).create(CAM_KHO, {
                "name": "Z", "zone_type": "controlled_area",
                "polygon": {"points": [{"x": 0, "y": 0}, {"x": 5, "y": 0}, {"x": 5, "y": 5}]},
                "frame_width": 640, "frame_height": 360, "enabled": True,
            })
            self.zone_id = str(zone["id"])
            self.rule_id = str(RuleConfigRepository(c).list_by_zone(self.zone_id)[0]["id"])
            for cam in (CAM_KHO, CAM_CONG):
                AiEventRepository(c).upsert({
                    "source_event_id": "ev-" + cam, "camera_id": cam, "event_type": "loitering",
                    "started_at": "2026-10-30T03:00:00Z", "payload": {},
                })
        self.settings = ZoneServiceSettings(
            database_path=root / "zone.db", reference_frame_dir=root / "r", evidence_dir=root / "e",
            camera_config_path=root / "x.yaml", edge_gateway_base_url="http://x", tenant_id="demo-tenant",
            auth_mode="jwt", jwt_secret=SECRET, service_api_key="svc-key", auth_dev_login=True,
        )
        self.access = AccessControl(self.database, self.settings, clock=lambda: NOW)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _user(self, c, user_id, email, role, locations, status="active"):
        c.execute("INSERT INTO app_user (id, email, full_name, status) VALUES (?, ?, ?, ?)", (user_id, email, email, status))
        member_id = "m-" + user_id
        c.execute("INSERT INTO tenant_member (id, tenant_id, user_id, role, status) VALUES (?, ?, ?, ?, 'active')",
                  (member_id, self.tenant_id, user_id, role))
        for loc, level in locations.items():
            c.execute("INSERT INTO user_location_access (id, tenant_id, tenant_member_id, location_id, permission_level) "
                      "VALUES (?, ?, ?, ?, ?)", ("a-" + user_id + loc, self.tenant_id, member_id, loc, level))

    def token(self, sub, tenant=None, **extra):
        claims = {"sub": sub, "tenant_id": tenant or self.tenant_id, "exp": NOW + 3600}
        claims.update(extra)
        return jwt_utils.encode_hs256(claims, SECRET)

    def login(self, sub, **kw):
        return self.access.authenticate("Bearer " + self.token(sub, **kw), None, None)

    def allowed(self, principal):
        with self.database.session() as c:
            return self.access.allowed_camera_ids(principal, c)

    def check(self, principal, fn, *args):
        with self.database.session() as c:
            return fn(principal, c, *args)

    # ------------------------------------------------------------ xac thuc
    def test_auth_off_is_unrestricted(self):
        settings = ZoneServiceSettings(**{**self.settings.__dict__, "auth_mode": "off"})
        principal = AccessControl(self.database, settings).authenticate(None, None, None)
        self.assertTrue(principal.is_unrestricted)

    def test_missing_bad_and_expired_tokens_are_rejected(self):
        with self.assertRaises(AuthError):
            self.access.authenticate(None, None, None)
        with self.assertRaises(AuthError):
            self.access.authenticate("Bearer " + jwt_utils.encode_hs256({"sub": "u-owner", "tenant_id": self.tenant_id}, "wrong"), None, None)
        with self.assertRaises(AuthError):
            self.access.authenticate("Bearer " + self.token("u-owner", exp=NOW - 3600), None, None)

    def test_service_key_is_unrestricted(self):
        principal = self.access.authenticate(None, None, "svc-key")
        self.assertEqual("service", principal.kind)
        self.assertIsNone(self.allowed(principal))
        with self.assertRaises(AuthError):
            self.access.authenticate(None, None, "wrong-key")

    def test_token_in_query_param_for_img_and_eventsource(self):
        principal = self.access.authenticate(None, self.token("u-kho"), None)
        self.assertEqual("operator", principal.role)

    def test_tenant_claim_can_be_code_and_subject_can_be_email(self):
        principal = self.access.authenticate("Bearer " + self.token("kho@demo.local", tenant="demo-tenant"), None, None)
        self.assertEqual("u-kho", principal.subject)

    def test_disabled_user_is_rejected(self):
        with self.assertRaises(AuthError):
            self.login("u-off")

    def test_user_from_other_tenant_is_rejected(self):
        with self.assertRaises(AuthError):
            self.login("u-kho", tenant="other-tenant")

    # ------------------------------------------------------------ pham vi location
    def test_owner_sees_all_locations_as_admin(self):
        owner = self.login("u-owner")
        self.assertEqual({CAM_KHO, CAM_CONG}, set(self.allowed(owner)))
        self.check(owner, self.access.require_camera, CAM_CONG, "admin")

    def test_operator_only_sees_assigned_location(self):
        kho = self.login("u-kho")
        self.assertEqual([CAM_KHO], self.allowed(kho))
        self.check(kho, self.access.require_camera, CAM_KHO, "operator")
        with self.assertRaises(AccessDenied) as ctx:
            self.check(kho, self.access.require_camera, CAM_CONG)
        self.assertEqual(404, ctx.exception.status_code)  # khong lo camera ton tai

    def test_operator_cannot_edit_zone_or_rule(self):
        kho = self.login("u-kho")
        self.check(kho, self.access.require_via, "zone", self.zone_id)
        with self.assertRaises(AccessDenied) as ctx:
            self.check(kho, self.access.require_via, "zone", self.zone_id, "admin")
        self.assertEqual(403, ctx.exception.status_code)
        with self.assertRaises(AccessDenied):
            self.check(kho, self.access.require_rule, self.rule_id, "admin")

    def test_viewer_of_other_location_cannot_see_zone(self):
        cong = self.login("u-cong")
        with self.assertRaises(AccessDenied) as ctx:
            self.check(cong, self.access.require_via, "zone", self.zone_id)
        self.assertEqual(404, ctx.exception.status_code)

    def test_lists_are_filtered_by_location(self):
        kho, cong = self.login("u-kho"), self.login("u-cong")
        with self.database.session() as c:
            repo = AiEventRepository(c, self.database)
            self.assertEqual({CAM_KHO}, {r["camera_id"] for r in repo.list(allowed_camera_ids=self.access.allowed_camera_ids(kho, c))})
            self.assertEqual({CAM_CONG}, {r["camera_id"] for r in repo.list(allowed_camera_ids=self.access.allowed_camera_ids(cong, c))})
            self.assertEqual(2, len(repo.list(allowed_camera_ids=None)))
            self.assertEqual([], repo.list(allowed_camera_ids=[]))
            self.assertEqual([], EvidenceRepository(c, self.database).list(allowed_camera_ids=[]))

    def test_tenant_admin_check(self):
        self.access.require_tenant_admin(self.login("u-owner"))
        with self.assertRaises(AccessDenied):
            self.access.require_tenant_admin(self.login("u-kho"))

    def test_access_change_applies_after_cache_expiry(self):
        clock = [NOW]
        access = AccessControl(self.database, self.settings, clock=lambda: clock[0])
        token = "Bearer " + self.token("u-cong")
        self.assertEqual([LOC_CONG], access.authenticate(token, None, None).allowed_location_ids())
        with self.database.session() as c:
            c.execute("INSERT INTO user_location_access (id, tenant_id, tenant_member_id, location_id, permission_level) "
                      "VALUES ('new', ?, 'm-u-cong', ?, 'viewer')", (self.tenant_id, LOC_KHO))
        self.assertEqual([LOC_CONG], access.authenticate(token, None, None).allowed_location_ids())  # con cache
        clock[0] += 31
        self.assertEqual(sorted([LOC_CONG, LOC_KHO]), access.authenticate(token, None, None).allowed_location_ids())

    # ------------------------------------------------------------ dev login
    def test_dev_login_issues_valid_token(self):
        token = self.access.issue_dev_token("kho@demo.local")
        principal = self.access.authenticate("Bearer " + token, None, None)
        self.assertEqual("u-kho", principal.subject)
        emails = [u["email"] for u in self.access.dev_users()]
        self.assertIn("cong@demo.local", emails)
        self.assertNotIn("off@demo.local", emails)

    def test_dev_login_disabled(self):
        settings = ZoneServiceSettings(**{**self.settings.__dict__, "auth_dev_login": False})
        with self.assertRaises(AccessDenied):
            AccessControl(self.database, settings).issue_dev_token("kho@demo.local")


if __name__ == "__main__":
    unittest.main()
