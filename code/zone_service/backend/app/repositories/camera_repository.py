import sqlite3
import uuid
from typing import Dict, Iterable, List, Optional

from ..database import Database
from ..time_utils import utc_iso


class CameraRepository:
    def __init__(self, connection: sqlite3.Connection, database: Optional[Database] = None) -> None:
        self.connection = connection
        self.database = database or _SqliteConnectionAdapter()

    def ensure_tenant(self, tenant_id: str) -> str:
        now = utc_iso()
        normalized_id = self._tenant_uuid(tenant_id)
        self.database.execute(
            self.connection,
            """
            INSERT INTO tenant (id, name, code, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (normalized_id, "Demo Tenant", tenant_id, now, now),
        )
        row = self.database.fetchone(self.connection, "SELECT id FROM tenant WHERE code = ?", (tenant_id,))
        return str(row["id"])

    def ensure_location(self, tenant_id: str, location_id: str, name: str) -> None:
        now = utc_iso()
        code = "loc-{}".format(location_id[-12:])
        conflict_target = "(id)"
        self.database.execute(
            self.connection,
            """
            INSERT INTO location (id, tenant_id, name, code, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT{} DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            """.format(conflict_target),
            (location_id, tenant_id, name, code, now, now),
        )

    def upsert_camera(self, camera: Dict[str, str]) -> None:
        now = utc_iso()
        conflict_target = "(tenant_id, source_url)" if self.database.backend == "postgres" else "(id)"
        self.database.execute(
            self.connection,
            """
            INSERT INTO camera (id, tenant_id, location_id, name, source_type, source_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT{} DO UPDATE SET
                location_id = excluded.location_id,
                name = excluded.name,
                source_type = excluded.source_type,
                source_url = excluded.source_url,
                status = excluded.status,
                updated_at = excluded.updated_at
            """.format(conflict_target),
            (
                camera["id"],
                camera["tenant_id"],
                camera["location_id"],
                camera["name"],
                camera["source_type"],
                camera["source_url"],
                camera.get("status", "active").lower(),
                now,
                now,
            ),
        )

    def list_cameras(self) -> List[sqlite3.Row]:
        return self.database.fetchall(self.connection, "SELECT * FROM camera ORDER BY name ASC, id ASC")

    def get_camera(self, camera_id: str) -> Optional[sqlite3.Row]:
        return self.database.fetchone(self.connection, "SELECT * FROM camera WHERE id = ?", (camera_id,))

    def seed_from_config(self, tenant_id: str, cameras: Iterable[Dict[str, str]]) -> None:
        normalized_tenant_id = self.ensure_tenant(tenant_id)
        for camera in cameras:
            location_id = camera["location_id"]
            self.ensure_location(normalized_tenant_id, location_id, "Location {}".format(location_id[-4:]))
            self.upsert_camera({**camera, "tenant_id": normalized_tenant_id})

    def _tenant_uuid(self, tenant_id: str) -> str:
        if self.database.backend == "sqlite":
            return tenant_id
        try:
            return str(uuid.UUID(tenant_id))
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, "hitek-ai-iot:tenant:{}".format(tenant_id)))


class _SqliteConnectionAdapter:
    backend = "sqlite"

    def execute(self, connection, sql, params=()):
        return connection.execute(sql, tuple(params))

    def fetchone(self, connection, sql, params=()):
        cursor = self.execute(connection, sql, params)
        return cursor.fetchone()

    def fetchall(self, connection, sql, params=()):
        cursor = self.execute(connection, sql, params)
        return list(cursor.fetchall())
