import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from ..time_utils import utc_iso


class ZoneRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_by_camera(self, camera_id: str) -> List[sqlite3.Row]:
        cursor = self.connection.execute(
            "SELECT * FROM zone WHERE camera_id = ? ORDER BY created_at ASC",
            (camera_id,),
        )
        return list(cursor.fetchall())

    def get(self, zone_id: str) -> Optional[sqlite3.Row]:
        cursor = self.connection.execute("SELECT * FROM zone WHERE id = ?", (zone_id,))
        return cursor.fetchone()

    def create(self, camera_id: str, payload: Dict[str, Any]) -> sqlite3.Row:
        now = utc_iso()
        zone_id = str(uuid.uuid4())
        self.connection.execute(
            """
            INSERT INTO zone
                (id, camera_id, name, zone_type, polygon, frame_width, frame_height, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                zone_id,
                camera_id,
                payload["name"],
                payload["zone_type"],
                json.dumps(payload["polygon"], separators=(",", ":")),
                payload["frame_width"],
                payload["frame_height"],
                1 if payload.get("enabled", True) else 0,
                now,
                now,
            ),
        )
        return self.get(zone_id)

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

        self.connection.execute(
            """
            UPDATE zone
            SET name = ?, zone_type = ?, polygon = ?, frame_width = ?, frame_height = ?, enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                merged["name"],
                merged["zone_type"],
                json.dumps(merged["polygon"], separators=(",", ":")),
                merged["frame_width"],
                merged["frame_height"],
                1 if merged["enabled"] else 0,
                utc_iso(),
                zone_id,
            ),
        )
        return self.get(zone_id)

    def delete(self, zone_id: str) -> bool:
        cursor = self.connection.execute("DELETE FROM zone WHERE id = ?", (zone_id,))
        return cursor.rowcount > 0
