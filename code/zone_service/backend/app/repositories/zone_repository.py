import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from ..database import Database
from .rule_config_repository import RuleConfigRepository
from ..time_utils import utc_iso


class ZoneRepository:
    def __init__(self, connection: sqlite3.Connection, database: Optional[Database] = None) -> None:
        self.connection = connection
        self.database = database or _SqliteConnectionAdapter()

    def list_by_camera(self, camera_id: str) -> List[sqlite3.Row]:
        return self.database.fetchall(
            self.connection,
            "SELECT * FROM zone WHERE camera_id = ? ORDER BY created_at ASC",
            (camera_id,),
        )

    def get(self, zone_id: str) -> Optional[sqlite3.Row]:
        return self.database.fetchone(self.connection, "SELECT * FROM zone WHERE id = ?", (zone_id,))

    def create(self, camera_id: str, payload: Dict[str, Any]) -> sqlite3.Row:
        now = utc_iso()
        zone_id = str(uuid.uuid4())
        camera = self.database.fetchone(self.connection, "SELECT tenant_id FROM camera WHERE id = ?", (camera_id,))
        if camera is None:
            return None
        self.database.execute(
            self.connection,
            """
            INSERT INTO zone
                (id, tenant_id, camera_id, name, zone_type, polygon, frame_width, frame_height, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                zone_id,
                camera["tenant_id"],
                camera_id,
                payload["name"],
                payload["zone_type"],
                self._polygon_param(payload["polygon"]),
                payload["frame_width"],
                payload["frame_height"],
                bool(payload.get("enabled", True)),
                now,
                now,
            ),
        )
        row = self.get(zone_id)
        RuleConfigRepository(self.connection, self.database).create_defaults_for_zone(row)
        return row

    def update(self, zone_id: str, payload: Dict[str, Any]) -> Optional[sqlite3.Row]:
        current = self.get(zone_id)
        if current is None:
            return None

        merged = {
            "name": current["name"],
            "zone_type": current["zone_type"],
            "polygon": json.loads(current["polygon"]),
            "frame_width": current["frame_width"],
            "frame_height": current["frame_height"],
            "enabled": bool(current["enabled"]),
        }
        for key, value in payload.items():
            if value is not None:
                merged[key] = value

        self.database.execute(
            self.connection,
            """
            UPDATE zone
            SET name = ?, zone_type = ?, polygon = ?, frame_width = ?, frame_height = ?, enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                merged["name"],
                merged["zone_type"],
                self._polygon_param(merged["polygon"]),
                merged["frame_width"],
                merged["frame_height"],
                bool(merged["enabled"]),
                utc_iso(),
                zone_id,
            ),
        )
        return self.get(zone_id)

    def delete(self, zone_id: str) -> bool:
        cursor = self.database.execute(self.connection, "DELETE FROM zone WHERE id = ?", (zone_id,))
        return cursor.rowcount > 0

    def _polygon_param(self, polygon: Dict[str, Any]):
        if self.database.backend == "postgres":
            from psycopg.types.json import Jsonb

            return Jsonb(polygon)
        return json.dumps(polygon, separators=(",", ":"))


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
