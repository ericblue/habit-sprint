"""Tests for the initial database schema (migration 001)."""

import sqlite3
from pathlib import Path

import pytest

MIGRATION_FILE = Path(__file__).resolve().parent.parent / "migrations" / "001_initial_schema.sql"


@pytest.fixture
def db():
    """Create an in-memory SQLite DB with the initial schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    sql = MIGRATION_FILE.read_text()
    conn.executescript(sql)
    yield conn
    conn.close()


def _get_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r[0] for r in rows}


def _get_indexes(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r[0] for r in rows}


def _get_columns(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [
        {"name": r[1], "type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": r[5]}
        for r in rows
    ]


class TestTablesExist:
    def test_all_four_tables_created(self, db):
        tables = _get_tables(db)
        assert tables == {"sprints", "habits", "entries", "retros"}


class TestSprintsTable:
    def test_columns(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "sprints")}
        expected = [
            "id", "start_date", "end_date", "theme",
            "focus_goals", "status", "created_at", "updated_at",
        ]
        assert list(cols.keys()) == expected

    def test_primary_key(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "sprints")}
        assert cols["id"]["pk"] == 1
        assert cols["id"]["type"] == "TEXT"

    def test_not_null_constraints(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "sprints")}
        for col in ["start_date", "end_date", "status", "created_at", "updated_at"]:
            assert cols[col]["notnull"], f"{col} should be NOT NULL"
        assert not cols["theme"]["notnull"], "theme should be nullable"

    def test_defaults(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "sprints")}
        assert cols["focus_goals"]["default"] == "'[]'"
        assert cols["status"]["default"] == "'active'"


class TestHabitsTable:
    def test_columns(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "habits")}
        expected = [
            "id", "name", "category", "target_per_week", "weight",
            "unit", "sprint_id", "archived", "created_at", "updated_at",
        ]
        assert list(cols.keys()) == expected

    def test_primary_key(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "habits")}
        assert cols["id"]["pk"] == 1
        assert cols["id"]["type"] == "TEXT"

    def test_not_null_constraints(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "habits")}
        for col in ["name", "category", "target_per_week", "weight", "unit", "archived", "created_at", "updated_at"]:
            assert cols[col]["notnull"], f"{col} should be NOT NULL"
        assert not cols["sprint_id"]["notnull"], "sprint_id should be nullable"

    def test_defaults(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "habits")}
        assert cols["weight"]["default"] == "1"
        assert cols["unit"]["default"] == "'count'"
        assert cols["archived"]["default"] == "0"

    def test_types(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "habits")}
        assert cols["target_per_week"]["type"] == "INTEGER"
        assert cols["weight"]["type"] == "INTEGER"
        assert cols["archived"]["type"] == "INTEGER"

    def test_foreign_key_to_sprints(self, db):
        fks = db.execute("PRAGMA foreign_key_list(habits)").fetchall()
        assert len(fks) == 1
        assert fks[0][2] == "sprints"  # referenced table
        assert fks[0][3] == "sprint_id"  # from column
        assert fks[0][4] == "id"  # to column


class TestEntriesTable:
    def test_columns(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "entries")}
        expected = ["habit_id", "date", "value", "note", "created_at", "updated_at"]
        assert list(cols.keys()) == expected

    def test_composite_primary_key(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "entries")}
        assert cols["habit_id"]["pk"] == 1
        assert cols["date"]["pk"] == 2

    def test_not_null_constraints(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "entries")}
        for col in ["habit_id", "date", "value", "created_at", "updated_at"]:
            assert cols[col]["notnull"], f"{col} should be NOT NULL"
        assert not cols["note"]["notnull"], "note should be nullable"

    def test_defaults(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "entries")}
        assert cols["value"]["default"] == "1"

    def test_value_type_is_real(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "entries")}
        assert cols["value"]["type"] == "REAL"

    def test_foreign_key_to_habits(self, db):
        fks = db.execute("PRAGMA foreign_key_list(entries)").fetchall()
        assert len(fks) == 1
        assert fks[0][2] == "habits"
        assert fks[0][3] == "habit_id"
        assert fks[0][4] == "id"


class TestRetrosTable:
    def test_columns(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "retros")}
        expected = [
            "id", "sprint_id", "what_went_well",
            "what_to_improve", "ideas", "created_at", "updated_at",
        ]
        assert list(cols.keys()) == expected

    def test_primary_key_autoincrement(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "retros")}
        assert cols["id"]["pk"] == 1
        assert cols["id"]["type"] == "INTEGER"

    def test_sprint_id_unique_and_not_null(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "retros")}
        assert cols["sprint_id"]["notnull"]
        # Verify UNIQUE via index
        indexes = db.execute("PRAGMA index_list(retros)").fetchall()
        unique_indexes = [i for i in indexes if i[2] == 1]  # i[2] is unique flag
        unique_cols = []
        for idx in unique_indexes:
            info = db.execute(f"PRAGMA index_info({idx[1]})").fetchall()
            unique_cols.extend(r[2] for r in info)
        assert "sprint_id" in unique_cols

    def test_nullable_text_fields(self, db):
        cols = {c["name"]: c for c in _get_columns(db, "retros")}
        for col in ["what_went_well", "what_to_improve", "ideas"]:
            assert not cols[col]["notnull"], f"{col} should be nullable"

    def test_foreign_key_to_sprints(self, db):
        fks = db.execute("PRAGMA foreign_key_list(retros)").fetchall()
        assert len(fks) == 1
        assert fks[0][2] == "sprints"
        assert fks[0][3] == "sprint_id"
        assert fks[0][4] == "id"


class TestIndexes:
    def test_all_five_indexes_created(self, db):
        indexes = _get_indexes(db)
        expected = {
            "idx_entries_date",
            "idx_entries_habit_date",
            "idx_habits_sprint",
            "idx_habits_category",
            "idx_sprints_status",
        }
        # Filter to only our named indexes (exclude auto-generated ones)
        assert expected.issubset(indexes)

    def test_idx_entries_date(self, db):
        info = db.execute("PRAGMA index_info(idx_entries_date)").fetchall()
        cols = [r[2] for r in info]
        assert cols == ["date"]

    def test_idx_entries_habit_date(self, db):
        info = db.execute("PRAGMA index_info(idx_entries_habit_date)").fetchall()
        cols = [r[2] for r in info]
        assert cols == ["habit_id", "date"]

    def test_idx_habits_sprint(self, db):
        info = db.execute("PRAGMA index_info(idx_habits_sprint)").fetchall()
        cols = [r[2] for r in info]
        assert cols == ["sprint_id"]

    def test_idx_habits_category(self, db):
        info = db.execute("PRAGMA index_info(idx_habits_category)").fetchall()
        cols = [r[2] for r in info]
        assert cols == ["category"]

    def test_idx_sprints_status(self, db):
        info = db.execute("PRAGMA index_info(idx_sprints_status)").fetchall()
        cols = [r[2] for r in info]
        assert cols == ["status"]
