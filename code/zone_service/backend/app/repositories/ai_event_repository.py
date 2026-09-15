import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from ..database import Database
from ..time_utils import utc_iso


class AiEventRepository:
    def __init__(self, connection: sqlite3.Connection, database: Optional[Database] = None) -> None:
        self.connection = connection
        self.database = database or _SqliteConnectionAdapter()

    def list(self, camera_id: Optional[str] = None, limit: int = 100) -> List[sqlite3.Row]:
        bounded_limit = max(1, min(int(limit), 500))
        if camera_id:
            return self.database.fetchall(
                self.connection,
                "SELECT * FROM ai_event WHERE camera_id = ? ORDER BY started_at DESC, created_at DESC LIMIT ?",
                (camera_id, bounded_limit),
            )
        return self.database.fetchall(
            self.connection,
            "SELECT * FROM ai_event ORDER BY started_at DESC, created_at DESC LIMIT ?",
            (bounded_limit,),
        )

    def get_by_source_event_id(self, source_event_id: str) -> Optional[sqlite3.Row]:
        return self.database.fetchone(
            self.connection,
            "SELECT * FROM ai_event WHERE source_event_id = ?",
            (source_event_id,),
        )

    def upsert(self, payload: Dict[str, Any]) -> sqlite3.Row:
        camera = self.database.fetchone(
            self.connection,
            "SELECT tenant_id FROM camera WHERE id = ?",
            (payload["camera_id"],),
        )
        if camera is None:
            return None

        now = utc_iso()
        event_id = str(uuid.uuid4())
        last_seen_at = payload.get("last_seen_at") or payload["started_at"]
        values = (
            event_id,
            camera["tenant_id"],
            payload.get("alert_id"),
            payload["source_event_id"],
            payload["camera_id"],
            payload.get("zone_id"),
            payload.get("rule_config_id"),
            payload["event_type"],
            payload.get("object_type"),
            payload.get("track_id"),
            payload.get("confidence"),
            payload.get("lifecycle_status", "active"),
            payload.get("first_sequence_number"),
            payload.get("last_sequence_number"),
            payload["started_at"],
            last_seen_at,
            payload.get("ended_at"),
            self._payload_param(payload.get("payload") or {}),
            now,
            now,
        )
        self.database.execute(
            self.connection,
            """
            INSERT INTO ai_event
                (
                    id, tenant_id, alert_id, source_event_id, camera_id, zone_id, rule_config_id,
                    event_type, object_type, track_id, confidence, lifecycle_status,
                    first_sequence_number, last_sequence_number, started_at, last_seen_at,
                    ended_at, payload, created_at, updated_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_event_id) DO UPDATE SET
                alert_id = excluded.alert_id,
                lifecycle_status = excluded.lifecycle_status,
                last_sequence_number = excluded.last_sequence_number,
                last_seen_at = excluded.last_seen_at,
                ended_at = excluded.ended_at,
                confidence = excluded.confidence,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            values,
        )
        return self.get_by_source_event_id(payload["source_event_id"])

    def _payload_param(self, payload: Dict[str, Any]):
        if self.database.backend == "postgres":
            from psycopg.types.json import Jsonb

            return Jsonb(payload)
        return json.dumps(payload, separators=(",", ":"))


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
