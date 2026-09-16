import sqlite3
import uuid
from typing import Dict, List, Optional

from ..database import Database
from ..time_utils import utc_iso


class EvidenceRepository:
    def __init__(self, connection: sqlite3.Connection, database: Optional[Database] = None) -> None:
        self.connection = connection
        self.database = database or _SqliteConnectionAdapter()

    def list(
        self,
        camera_id: Optional[str] = None,
        limit: int = 100,
        evidence_type: Optional[str] = None,
        event_type: Optional[str] = None,
        status: Optional[str] = None,
        from_time: Optional[str] = None,
        to_time: Optional[str] = None,
        zone_id: Optional[str] = None,
        object_type: Optional[str] = None,
    ) -> List[sqlite3.Row]:
        bounded_limit = max(1, min(int(limit), 500))
        clauses = []
        params = []
        if camera_id:
            clauses.append("evidence.camera_id = ?")
            params.append(camera_id)
        if evidence_type:
            clauses.append("evidence.evidence_type = ?")
            params.append(evidence_type)
        if status:
            clauses.append("evidence.status = ?")
            params.append(status)
        if from_time:
            clauses.append("evidence.captured_at >= ?")
            params.append(from_time)
        if to_time:
            clauses.append("evidence.captured_at <= ?")
            params.append(to_time)
        if event_type:
            clauses.append("ai_event.event_type = ?")
            params.append(event_type)
        if zone_id:
            clauses.append("ai_event.zone_id = ?")
            params.append(zone_id)
        if object_type:
            clauses.append("ai_event.object_type = ?")
            params.append(object_type)

        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(bounded_limit)
        return self.database.fetchall(
            self.connection,
            """
            SELECT evidence.*
            FROM evidence
            LEFT JOIN ai_event ON ai_event.id = evidence.ai_event_id
            {}
            ORDER BY evidence.captured_at DESC, evidence.created_at DESC
            LIMIT ?
            """.format(where_sql),
            tuple(params),
        )

    def list_by_event(self, ai_event_id: str) -> List[sqlite3.Row]:
        return self.database.fetchall(
            self.connection,
            "SELECT * FROM evidence WHERE ai_event_id = ? ORDER BY captured_at ASC, created_at ASC",
            (ai_event_id,),
        )

    def get(self, evidence_id: str) -> Optional[sqlite3.Row]:
        return self.database.fetchone(self.connection, "SELECT * FROM evidence WHERE id = ?", (evidence_id,))

    def exists_for_alert(self, alert_id: Optional[str]) -> bool:
        if not alert_id:
            return False
        row = self.database.fetchone(
            self.connection,
            "SELECT id FROM evidence WHERE alert_id = ?",
            (alert_id,),
        )
        return row is not None

    def latest_for_alert(self, alert_id: Optional[str]) -> Optional[sqlite3.Row]:
        if not alert_id:
            return None
        return self.database.fetchone(
            self.connection,
            "SELECT * FROM evidence WHERE alert_id = ? ORDER BY captured_at DESC, created_at DESC LIMIT 1",
            (alert_id,),
        )

    def exists_for_event(self, ai_event_id: str, frame_id: Optional[str]) -> bool:
        if frame_id:
            row = self.database.fetchone(
                self.connection,
                "SELECT id FROM evidence WHERE ai_event_id = ? AND frame_id = ?",
                (ai_event_id, frame_id),
            )
        else:
            row = self.database.fetchone(
                self.connection,
                "SELECT id FROM evidence WHERE ai_event_id = ?",
                (ai_event_id,),
            )
        return row is not None

    def create(self, payload: Dict) -> sqlite3.Row:
        event = self.database.fetchone(
            self.connection,
            "SELECT tenant_id FROM ai_event WHERE id = ?",
            (payload["ai_event_id"],),
        )
        if event is None:
            return None

        evidence_id = str(uuid.uuid4())
        now = utc_iso()
        self.database.execute(
            self.connection,
            """
            INSERT INTO evidence
                (
                    id, tenant_id, ai_event_id, camera_id, evidence_type, storage_key,
                    alert_id, mime_type, file_size, frame_id, sequence_number, captured_at,
                    started_at, ended_at, duration_seconds, codec, fps, frame_width,
                    frame_height, status, created_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                event["tenant_id"],
                payload["ai_event_id"],
                payload["camera_id"],
                payload.get("evidence_type", "snapshot"),
                payload["storage_key"],
                payload.get("alert_id"),
                payload.get("mime_type", "image/jpeg"),
                payload.get("file_size"),
                payload.get("frame_id"),
                payload.get("sequence_number"),
                payload["captured_at"],
                payload.get("started_at"),
                payload.get("ended_at"),
                payload.get("duration_seconds"),
                payload.get("codec"),
                payload.get("fps"),
                payload.get("frame_width"),
                payload.get("frame_height"),
                payload.get("status"),
                now,
            ),
        )
        return self.get(evidence_id)


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
