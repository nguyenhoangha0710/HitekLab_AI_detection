import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tenant (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    code TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS location (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS camera (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES location(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    status TEXT NOT NULL,
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, source_url),
    UNIQUE (location_id, name)
);

CREATE TABLE IF NOT EXISTS camera_reference_frame (
    id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL REFERENCES camera(id) ON DELETE CASCADE,
    storage_key TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    frame_width INTEGER NOT NULL,
    frame_height INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zone (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    camera_id TEXT NOT NULL REFERENCES camera(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    zone_type TEXT NOT NULL,
    polygon TEXT NOT NULL,
    frame_width INTEGER NOT NULL,
    frame_height INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rule_config (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    zone_id TEXT NOT NULL REFERENCES zone(id) ON DELETE CASCADE,
    rule_type TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    duration_threshold INTEGER,
    people_threshold INTEGER,
    confidence_threshold REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_location_tenant_id ON location(tenant_id);
CREATE INDEX IF NOT EXISTS idx_camera_location_id ON camera(location_id);
CREATE INDEX IF NOT EXISTS idx_zone_camera_id ON zone(camera_id);
CREATE INDEX IF NOT EXISTS idx_reference_frame_camera_id ON camera_reference_frame(camera_id);
"""


class Database:
    def __init__(self, path: Path, url: Optional[str] = None) -> None:
        self.path = Path(path)
        self.url = url
        self.backend = "postgres" if url else "sqlite"

    def initialize(self) -> None:
        if self.backend == "postgres":
            with self.connect() as connection:
                for path in sorted(_postgres_init_dir().glob("*.sql")):
                    with path.open("r", encoding="utf-8") as handle:
                        connection.execute(handle.read())
            return

        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_sqlite(connection)

    def connect(self):
        if self.backend == "postgres":
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("psycopg is required when DATABASE_URL is configured") from exc
            return psycopg.connect(self.url, row_factory=dict_row)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def session(self) -> Iterator[Any]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def execute(self, connection, sql: str, params: Iterable[Any] = ()):
        return connection.execute(self.sql(sql), tuple(params))

    def fetchone(self, connection, sql: str, params: Iterable[Any] = ()):
        cursor = self.execute(connection, sql, params)
        return cursor.fetchone()

    def fetchall(self, connection, sql: str, params: Iterable[Any] = ()):
        cursor = self.execute(connection, sql, params)
        return list(cursor.fetchall())

    def sql(self, sql: str) -> str:
        if self.backend == "postgres":
            return sql.replace("?", "%s")
        return sql

    def _migrate_sqlite(self, connection: sqlite3.Connection) -> None:
        self._add_sqlite_column_if_missing(connection, "camera", "tenant_id", "TEXT")
        self._add_sqlite_column_if_missing(connection, "zone", "tenant_id", "TEXT")
        self._add_sqlite_column_if_missing(connection, "rule_config", "tenant_id", "TEXT")
        connection.execute(
            """
            UPDATE camera
            SET tenant_id = (
                SELECT tenant_id FROM location WHERE location.id = camera.location_id
            )
            WHERE tenant_id IS NULL
            """
        )
        connection.execute(
            """
            UPDATE zone
            SET tenant_id = (
                SELECT tenant_id
                FROM camera
                WHERE camera.id = zone.camera_id
            )
            WHERE tenant_id IS NULL
            """
        )
        connection.execute(
            """
            UPDATE rule_config
            SET tenant_id = (
                SELECT tenant_id
                FROM zone
                WHERE zone.id = rule_config.zone_id
            )
            WHERE tenant_id IS NULL
            """
        )

    def _add_sqlite_column_if_missing(self, connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        cursor = connection.execute("PRAGMA table_info({})".format(table))
        columns = {row["name"] for row in cursor.fetchall()}
        if column not in columns:
            connection.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, column, definition))


def _postgres_init_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "database" / "postgres" / "init"
