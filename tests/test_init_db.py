"""Integration tests for database initialization via get_connection().

These tests exercise the full flow: calling get_connection() on a
non-existent file creates the DB, applies the real 001_initial_schema.sql
migration, and configures WAL mode + foreign keys.
"""

import sqlite3
from pathlib import Path

import pytest

from habit_sprint.db import get_connection


EXPECTED_TABLES = {"sprints", "habits", "entries", "retros"}
EXPECTED_INDEXES = {
    "idx_entries_date",
    "idx_entries_habit_date",
    "idx_habits_sprint",
    "idx_habits_category",
    "idx_sprints_status",
}


@pytest.fixture()
def fresh_db(tmp_path: Path) -> sqlite3.Connection:
    """Return a connection from get_connection() on a brand-new DB file."""
    conn = get_connection(str(tmp_path / "habit_sprint.db"))
    yield conn
    conn.close()


class TestDatabaseCreation:
    def test_db_file_created(self, tmp_path: Path) -> None:
        db_file = tmp_path / "new.db"
        assert not db_file.exists()
        conn = get_connection(str(db_file))
        assert db_file.exists()
        conn.close()

    def test_all_four_tables_exist(self, fresh_db: sqlite3.Connection) -> None:
        tables = {
            row[0]
            for row in fresh_db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name != 'schema_version'"
            ).fetchall()
        }
        assert tables == EXPECTED_TABLES

    def test_all_five_indexes_exist(self, fresh_db: sqlite3.Connection) -> None:
        indexes = {
            row[0]
            for row in fresh_db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert EXPECTED_INDEXES.issubset(indexes)

    def test_schema_version_records_v1(self, fresh_db: sqlite3.Connection) -> None:
        rows = fresh_db.execute("SELECT version FROM schema_version").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1

    def test_schema_version_has_applied_at(self, fresh_db: sqlite3.Connection) -> None:
        row = fresh_db.execute(
            "SELECT applied_at FROM schema_version WHERE version = 1"
        ).fetchone()
        assert row is not None
        assert row[0] is not None  # ISO timestamp string


class TestConnectionPragmas:
    def test_wal_mode_enabled(self, fresh_db: sqlite3.Connection) -> None:
        mode = fresh_db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_enabled(self, fresh_db: sqlite3.Connection) -> None:
        fk = fresh_db.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1


class TestIdempotency:
    def test_second_get_connection_no_error(self, tmp_path: Path) -> None:
        db_file = str(tmp_path / "idempotent.db")
        conn1 = get_connection(db_file)
        conn1.close()
        # Second call on the same DB must not raise
        conn2 = get_connection(db_file)
        conn2.close()

    def test_second_call_still_version_1(self, tmp_path: Path) -> None:
        db_file = str(tmp_path / "idempotent.db")
        conn1 = get_connection(db_file)
        conn1.close()
        conn2 = get_connection(db_file)
        rows = conn2.execute("SELECT version FROM schema_version").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1
        conn2.close()

    def test_tables_unchanged_after_second_call(self, tmp_path: Path) -> None:
        db_file = str(tmp_path / "idempotent.db")
        conn1 = get_connection(db_file)
        conn1.close()
        conn2 = get_connection(db_file)
        tables = {
            row[0]
            for row in conn2.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name != 'schema_version'"
            ).fetchall()
        }
        assert tables == EXPECTED_TABLES
        conn2.close()
