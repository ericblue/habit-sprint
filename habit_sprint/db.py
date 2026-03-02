"""Database connection management and migration runner."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    """Return a configured SQLite connection with migrations applied.

    The connection is set up with WAL journal mode, foreign keys enabled,
    and row_factory set to sqlite3.Row.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply all pending SQL migrations from the migrations/ directory."""
    conn.execute(_SCHEMA_VERSION_DDL)
    conn.commit()

    applied: set[int] = {
        row[0] for row in conn.execute("SELECT version FROM schema_version")
    }

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    for path in migration_files:
        version = int(path.stem.split("_", 1)[0])
        if version in applied:
            continue
        sql = path.read_text()
        # executescript handles its own transaction management
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
