import sqlite3
import uuid
from typing import Optional

from ..time_utils import utc_iso


class ReferenceFrameRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        camera_id: str,
        storage_key: str,
        mime_type: str,
        frame_width: int,
        frame_height: int,
        captured_at: str,
    ) -> sqlite3.Row:
        now = utc_iso()
        reference_id = str(uuid.uuid4())
        self.connection.execute(
            """
            INSERT INTO camera_reference_frame
                (id, camera_id, storage_key, mime_type, frame_width, frame_height, captured_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (reference_id, camera_id, storage_key, mime_type, frame_width, frame_height, captured_at, now),
        )
        return self.get_latest(camera_id)

    def get_latest(self, camera_id: str) -> Optional[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT * FROM camera_reference_frame
            WHERE camera_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (camera_id,),
        )
        return cursor.fetchone()
