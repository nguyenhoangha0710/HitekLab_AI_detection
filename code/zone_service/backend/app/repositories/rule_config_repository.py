import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from ..database import Database
from ..time_utils import utc_iso


class RuleConfigRepository:
    def __init__(self, connection: sqlite3.Connection, database: Optional[Database] = None) -> None:
        self.connection = connection
        self.database = database or _SqliteConnectionAdapter()

    def list_by_zone(self, zone_id: str) -> List[sqlite3.Row]:
        return self.database.fetchall(
            self.connection,
            "SELECT * FROM rule_config WHERE zone_id = ? ORDER BY rule_type ASC",
            (zone_id,),
        )

    def get(self, rule_id: str) -> Optional[sqlite3.Row]:
        return self.database.fetchone(self.connection, "SELECT * FROM rule_config WHERE id = ?", (rule_id,))

    def create_defaults_for_zone(self, zone) -> None:
        zone_type = zone["zone_type"]
        if zone_type == "restricted_area":
            defaults = [
                {
                    "rule_type": "person_intrusion",
                    "object_type": "person",
                    "duration_threshold": 15,
                    "people_threshold": None,
                    "confidence_threshold": 0.6,
                    "use_active_time": True,
                    "active_start_time": "23:00",
                    "active_end_time": "06:00",
                },
                {
                    "rule_type": "vehicle_intrusion",
                    "object_type": "car",
                    "duration_threshold": 15,
                    "people_threshold": None,
                    "confidence_threshold": 0.6,
                    "use_active_time": True,
                    "active_start_time": "23:00",
                    "active_end_time": "06:00",
                },
            ]
        elif zone_type == "controlled_area":
            defaults = [
                {
                    "rule_type": "crowd_limit",
                    "object_type": "person",
                    "duration_threshold": 15,
                    "people_threshold": 5,
                    "confidence_threshold": 0.6,
                    "use_active_time": False,
                    "active_start_time": None,
                    "active_end_time": None,
                },
                {
                    "rule_type": "loitering",
                    "object_type": "person",
                    "duration_threshold": 15,
                    "people_threshold": None,
                    "confidence_threshold": 0.6,
                    "use_active_time": False,
                    "active_start_time": None,
                    "active_end_time": None,
                },
                {
                    "rule_type": "vehicle_stopping",
                    "object_type": "car",
                    "duration_threshold": 15,
                    "people_threshold": None,
                    "confidence_threshold": 0.6,
                    "use_active_time": False,
                    "active_start_time": None,
                    "active_end_time": None,
                },
            ]
        else:
            defaults = []

        for payload in defaults:
            self.create(
                zone_id=zone["id"],
                tenant_id=zone["tenant_id"],
                payload={**payload, "enabled": True},
            )

    def create(self, zone_id: str, tenant_id: str, payload: Dict[str, Any]) -> sqlite3.Row:
        rule_id = str(uuid.uuid4())
        now = utc_iso()
        self.database.execute(
            self.connection,
            """
            INSERT INTO rule_config
                (
                    id, tenant_id, zone_id, rule_type, enabled, object_type,
                    duration_threshold, people_threshold, confidence_threshold,
                    use_active_time, active_start_time, active_end_time,
                    created_at, updated_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule_id,
                tenant_id,
                zone_id,
                payload["rule_type"],
                bool(payload.get("enabled", True)),
                payload.get("object_type"),
                payload.get("duration_threshold"),
                payload.get("people_threshold"),
                payload.get("confidence_threshold"),
                bool(payload.get("use_active_time", False)),
                payload.get("active_start_time"),
                payload.get("active_end_time"),
                now,
                now,
            ),
        )
        return self.get(rule_id)

    def update(self, rule_id: str, payload: Dict[str, Any]) -> Optional[sqlite3.Row]:
        current = self.get(rule_id)
        if current is None:
            return None

        merged = {
            "enabled": bool(current["enabled"]),
            "object_type": current["object_type"],
            "duration_threshold": current["duration_threshold"],
            "people_threshold": current["people_threshold"],
            "confidence_threshold": current["confidence_threshold"],
            "use_active_time": bool(current["use_active_time"]),
            "active_start_time": current["active_start_time"],
            "active_end_time": current["active_end_time"],
        }
        for key, value in payload.items():
            merged[key] = value

        self.database.execute(
            self.connection,
            """
            UPDATE rule_config
            SET enabled = ?, object_type = ?, duration_threshold = ?, people_threshold = ?,
                confidence_threshold = ?, use_active_time = ?, active_start_time = ?,
                active_end_time = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                bool(merged["enabled"]),
                merged["object_type"],
                merged["duration_threshold"],
                merged["people_threshold"],
                merged["confidence_threshold"],
                bool(merged["use_active_time"]),
                merged["active_start_time"],
                merged["active_end_time"],
                utc_iso(),
                rule_id,
            ),
        )
        return self.get(rule_id)


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
