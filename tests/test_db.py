"""Tests for habit_sprint.db module."""

import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from habit_sprint.db import get_connection, migrate, MIGRATIONS_DIR


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture()
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    return d


def _write_migration(migrations_dir: Path, filename: str, sql: str) -> None:
    (migrations_dir / filename).write_text(sql)


class TestGetConnection:
    def test_returns_connection(self, db_path: str) -> None:
        conn = get_connection(db_path)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_wal_mode(self, db_path: str) -> None:
        conn = get_connection(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_foreign_keys_enabled(self, db_path: str) -> None:
        conn = get_connection(db_path)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        conn.close()

    def test_row_factory(self, db_path: str) -> None:
        conn = get_connection(db_path)
        assert conn.row_factory is sqlite3.Row
        conn.close()


class TestSchemaVersion:
    def test_table_created(self, db_path: str) -> None:
        conn = get_connection(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchall()
        assert len(tables) == 1
        conn.close()

    def test_table_columns(self, db_path: str) -> None:
        conn = get_connection(db_path)
        cols = conn.execute("PRAGMA table_info(schema_version)").fetchall()
        col_names = {c["name"] for c in cols}
        assert col_names == {"version", "applied_at"}
        conn.close()


class TestMigrate:
    def test_applies_migrations_in_order(
        self, db_path: str, migrations_dir: Path
    ) -> None:
        _write_migration(
            migrations_dir,
            "001_create_habits.sql",
            "CREATE TABLE habits (id INTEGER PRIMARY KEY, name TEXT NOT NULL);",
        )
        _write_migration(
            migrations_dir,
            "002_add_description.sql",
            "ALTER TABLE habits ADD COLUMN description TEXT;",
        )

        with mock.patch("habit_sprint.db.MIGRATIONS_DIR", migrations_dir):
            conn = get_connection(db_path)

        # Both tables should exist
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "habits" in tables

        # Check description column exists
        cols = conn.execute("PRAGMA table_info(habits)").fetchall()
        col_names = {c["name"] for c in cols}
        assert "description" in col_names

        # Both versions recorded
        versions = {
            row[0]
            for row in conn.execute("SELECT version FROM schema_version").fetchall()
        }
        assert versions == {1, 2}
        conn.close()

    def test_idempotent(self, db_path: str, migrations_dir: Path) -> None:
        _write_migration(
            migrations_dir,
            "001_create_habits.sql",
            "CREATE TABLE habits (id INTEGER PRIMARY KEY, name TEXT NOT NULL);",
        )

        with mock.patch("habit_sprint.db.MIGRATIONS_DIR", migrations_dir):
            conn = get_connection(db_path)
            # Run migrate again — should not error
            migrate(conn)

        versions = conn.execute("SELECT version FROM schema_version").fetchall()
        assert len(versions) == 1
        conn.close()

    def test_skips_applied_migrations(
        self, db_path: str, migrations_dir: Path
    ) -> None:
        _write_migration(
            migrations_dir,
            "001_create_habits.sql",
            "CREATE TABLE habits (id INTEGER PRIMARY KEY);",
        )

        with mock.patch("habit_sprint.db.MIGRATIONS_DIR", migrations_dir):
            conn = get_connection(db_path)

        # Now add a second migration and re-run
        _write_migration(
            migrations_dir,
            "002_add_col.sql",
            "ALTER TABLE habits ADD COLUMN name TEXT;",
        )

        with mock.patch("habit_sprint.db.MIGRATIONS_DIR", migrations_dir):
            migrate(conn)

        versions = sorted(
            row[0]
            for row in conn.execute("SELECT version FROM schema_version").fetchall()
        )
        assert versions == [1, 2]
        conn.close()

    def test_no_migrations_dir_files(self, db_path: str, migrations_dir: Path) -> None:
        with mock.patch("habit_sprint.db.MIGRATIONS_DIR", migrations_dir):
            conn = get_connection(db_path)

        versions = conn.execute("SELECT version FROM schema_version").fetchall()
        assert len(versions) == 0
        conn.close()

    def test_records_applied_at(self, db_path: str, migrations_dir: Path) -> None:
        _write_migration(
            migrations_dir,
            "001_test.sql",
            "CREATE TABLE test_tbl (id INTEGER PRIMARY KEY);",
        )

        with mock.patch("habit_sprint.db.MIGRATIONS_DIR", migrations_dir):
            conn = get_connection(db_path)

        row = conn.execute("SELECT applied_at FROM schema_version WHERE version=1").fetchone()
        assert row is not None
        assert row["applied_at"] is not None
        conn.close()
