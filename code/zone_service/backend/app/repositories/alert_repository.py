import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..database import Database
from ..time_utils import utc_iso


ALERT_DEDUP_WINDOW_SECONDS = 120


class AlertRepository:
    def __init__(self, connection: sqlite3.Connection, database: Optional[Database] = None) -> None:
        self.connection = connection
        self.database = database or _SqliteConnectionAdapter()

    def list(self, camera_id: Optional[str] = None, limit: int = 100) -> List[sqlite3.Row]:
        bounded_limit = max(1, min(int(limit), 500))
        if camera_id:
            return self.database.fetchall(
                self.connection,
                "SELECT * FROM alert WHERE camera_id = ? ORDER BY last_seen_at DESC, created_at DESC LIMIT ?",
                (camera_id, bounded_limit),
            )
        return self.database.fetchall(
            self.connection,
            "SELECT * FROM alert ORDER BY last_seen_at DESC, created_at DESC LIMIT ?",
            (bounded_limit,),
        )

    def get(self, alert_id: str) -> Optional[sqlite3.Row]:
        return self.database.fetchone(self.connection, "SELECT * FROM alert WHERE id = ?", (alert_id,))

    def upsert_for_violation(self, payload: Dict[str, Any]) -> Optional[sqlite3.Row]:
        camera = self.database.fetchone(
            self.connection,
            "SELECT tenant_id FROM camera WHERE id = ?",
            (payload["camera_id"],),
        )
        if camera is None:
            return None

        dedup_key = self.dedup_key(payload)
        now = utc_iso()
        last_seen_at = payload.get("last_seen_at") or payload["started_at"]
        current = self._latest_active_by_dedup_key(dedup_key)
        if current is not None and self._is_inside_dedup_window(current["last_seen_at"], last_seen_at):
            self.database.execute(
                self.connection,
                """
                UPDATE alert
                SET active_source_count = active_source_count + 1,
                    last_sequence_number = ?,
                    last_seen_at = ?,
                    payload = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.get("last_sequence_number"),
                    last_seen_at,
                    self._payload_param(self._alert_payload(payload)),
                    now,
                    current["id"],
                ),
            )
            return self.get(str(current["id"]))

        alert_id = str(uuid.uuid4())
        self.database.execute(
            self.connection,
            """
            INSERT INTO alert
                (
                    id, tenant_id, dedup_key, camera_id, zone_id, rule_config_id,
                    rule_type, object_type, risk_level, lifecycle_status,
                    active_source_count, first_sequence_number, last_sequence_number,
                    started_at, last_seen_at, ended_at, payload, created_at, updated_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                camera["tenant_id"],
                dedup_key,
                payload["camera_id"],
                payload.get("zone_id"),
                payload.get("rule_config_id"),
                payload["event_type"],
                payload.get("object_type"),
                self._risk_level(payload["event_type"]),
                "active",
                1,
                payload.get("first_sequence_number"),
                payload.get("last_sequence_number"),
                payload["started_at"],
                last_seen_at,
                None,
                self._payload_param(self._alert_payload(payload)),
                now,
                now,
            ),
        )
        return self.get(alert_id)

    def _latest_active_by_dedup_key(self, dedup_key: str) -> Optional[sqlite3.Row]:
        return self.database.fetchone(
            self.connection,
            """
            SELECT * FROM alert
            WHERE dedup_key = ? AND lifecycle_status = 'active'
            ORDER BY last_seen_at DESC, created_at DESC
            LIMIT 1
            """,
            (dedup_key,),
        )

    def _is_inside_dedup_window(self, previous_seen_at, current_seen_at) -> bool:
        previous = self._parse_time(previous_seen_at)
        current = self._parse_time(current_seen_at)
        if previous is None or current is None:
            return True
        return abs((current - previous).total_seconds()) <= ALERT_DEDUP_WINDOW_SECONDS

    def dedup_key(self, payload: Dict[str, Any]) -> str:
        return "|".join(
            [
                str(payload.get("camera_id") or ""),
                str(payload.get("zone_id") or ""),
                str(payload.get("event_type") or ""),
                str(payload.get("object_type") or ""),
            ]
        )

    def _risk_level(self, rule_type: str) -> str:
        if rule_type in {"person_intrusion", "vehicle_intrusion"}:
            return "high"
        if rule_type == "crowd_limit":
            return "medium"
        return "low"

    def _alert_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event_payload = payload.get("payload") or {}
        return {
            "source_event_id": payload.get("source_event_id"),
            "track_id": payload.get("track_id"),
            "frame_id": event_payload.get("frame_id"),
            "sequence_number": payload.get("last_sequence_number"),
            "zone_name": event_payload.get("zone_name"),
            "zone_type": event_payload.get("zone_type"),
            "elapsed_seconds": event_payload.get("elapsed_seconds"),
        }

    def _payload_param(self, payload: Dict[str, Any]):
        if self.database.backend == "postgres":
            from psycopg.types.json import Jsonb

            return Jsonb(payload)
        return json.dumps(payload, separators=(",", ":"))

    def _parse_time(self, value) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        text = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
