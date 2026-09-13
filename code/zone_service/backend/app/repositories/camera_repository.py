import sqlite3
from typing import Dict, Iterable, List, Optional

from ..time_utils import utc_iso


class CameraRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ensure_tenant(self, tenant_id: str) -> None:
        now = utc_iso()
        self.connection.execute(
            """
            INSERT INTO tenant (id, name, code, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (tenant_id, "Demo Tenant", tenant_id, now, now),
        )

    def ensure_location(self, tenant_id: str, location_id: str, name: str) -> None:
        now = utc_iso()
        code = "loc-{}".format(location_id[-12:])
        self.connection.execute(
            """
            INSERT INTO location (id, tenant_id, name, code, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                tenant_id = excluded.tenant_id,
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (location_id, tenant_id, name, code, now, now),
        )

    def upsert_camera(self, camera: Dict[str, str]) -> None:
        now = utc_iso()
        self.connection.execute(
            """
            INSERT INTO camera (id, location_id, name, source_type, source_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                location_id = excluded.location_id,
                name = excluded.name,
                source_type = excluded.source_type,
                source_url = excluded.source_url,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                camera["id"],
                camera["location_id"],
                camera["name"],
                camera["source_type"],
                camera["source_url"],
                camera.get("status", "ACTIVE"),
                now,
                now,
            ),
        )

    def list_cameras(self) -> List[sqlite3.Row]:
        cursor = self.connection.execute("SELECT * FROM camera ORDER BY name ASC, id ASC")
        return list(cursor.fetchall())

    def get_camera(self, camera_id: str) -> Optional[sqlite3.Row]:
        cursor = self.connection.execute("SELECT * FROM camera WHERE id = ?", (camera_id,))
        return cursor.fetchone()

    def seed_from_config(self, tenant_id: str, cameras: Iterable[Dict[str, str]]) -> None:
        self.ensure_tenant(tenant_id)
        for camera in cameras:
            location_id = camera["location_id"]
            self.ensure_location(tenant_id, location_id, "Location {}".format(location_id[-4:]))
            self.upsert_camera(camera)
