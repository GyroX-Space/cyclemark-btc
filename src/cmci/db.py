"""SQLite connection and schema bootstrap."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .timeutils import utc_now_iso

SCHEMA_DIR = Path(__file__).parent
MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "schema.sql", "P0-1 core schema"),
    (2, "schema_v2.sql", "P0-2 raw, normalized, ingestion, quality"),
    (3, "schema_v3.sql", "P0-3 research datasets and L5 partitions"),
)


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
        """Apply every pending migration and record its version."""
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL, description TEXT NOT NULL)"
        )
        applied = {
            row["version"] for row in self.conn.execute("SELECT version FROM schema_migrations")
        }
        for version, filename, description in MIGRATIONS:
            if version in applied:
                continue
            sql = (SCHEMA_DIR / filename).read_text(encoding="utf-8")
            self.conn.executescript(sql)
            with self.conn:
                self.conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at_utc, description) "
                    "VALUES (?, ?, ?)",
                    (version, utc_now_iso(), description),
                )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()