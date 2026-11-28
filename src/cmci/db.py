"""SQLite connection and schema bootstrap."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .timeutils import utc_now_iso

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


class Database:
    """Thin wrapper around a SQLite connection with CMCI pragmas applied."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    def initialize(self) -> None:
        """Apply the idempotent schema and record the schema version."""
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.conn:
            self.conn.executescript(sql)
            self.conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at_utc, description) "
                "VALUES (?, ?, ?)",
                (SCHEMA_VERSION, utc_now_iso(), "P0-1 core schema"),
            )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()