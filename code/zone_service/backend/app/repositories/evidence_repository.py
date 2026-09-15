import sqlite3
import uuid
from typing import Dict, List, Optional

from ..database import Database
from ..time_utils import utc_iso


class EvidenceRepository:
    def __init__(self, connection: sqlite3.Connection, database: Optional[Database] = None) -> None:
        self.connection = connection
        self.database = database or _SqliteConnectionAdapter()

    def list(self, camera_id: Optional[str] = None, limit: int = 100) -> List[sqlite3.Row]:
        bounded_limit = max(1, min(int(limit), 500))
        if camera_id:
            return self.database.fetchall(
                self.connection,
                "SELECT * FROM evidence WHERE camera_id = ? ORDER BY captured_at DESC, created_at DESC LIMIT ?",
                (camera_id, bounded_limit),
            )
        return self.database.fetchall(
            self.connection,
            "SELECT * FROM evidence ORDER BY captured_at DESC, created_at DESC LIMIT ?",
            (bounded_limit,),
        )

    def list_by_event(self, ai_event_id: str) -> List[sqlite3.Row]:
        return self.database.fetchall(
            self.connection,
            "SELECT * FROM evidence WHERE ai_event_id = ? ORDER BY captured_at ASC, created_at ASC",
            (ai_event_id,),
        )

    def get(self, evidence_id: str) -> Optional[sqlite3.Row]:
        return self.database.fetchone(self.connection, "SELECT * FROM evidence WHERE id = ?", (evidence_id,))

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
                    mime_type, file_size, frame_id, sequence_number, captured_at, created_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                event["tenant_id"],
                payload["ai_event_id"],
                payload["camera_id"],
                payload.get("evidence_type", "snapshot"),
                payload["storage_key"],
                payload.get("mime_type", "image/jpeg"),
                payload.get("file_size"),
                payload.get("frame_id"),
                payload.get("sequence_number"),
                payload["captured_at"],
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
