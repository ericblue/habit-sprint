"""Tests for entry management functions in engine.py."""

import tempfile
import os

from habit_sprint.db import get_connection
from habit_sprint import engine


def _fresh_conn():
    """Return a connection to a fresh temporary database with migrations applied."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return get_connection(path)


def _setup_habit(conn, habit_id="reading"):
    """Create a sprint and habit for entry tests."""
    engine.create_sprint(conn, {
        "start_date": "2026-03-01",
        "end_date": "2026-03-14",
    })
    return engine.create_habit(conn, {
        "id": habit_id,
        "name": "Reading",
        "category": "cognitive",
        "target_per_week": 5,
    })


class TestLogDate:
    def test_creates_new_entry(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        result = engine.log_date(conn, {
            "habit_id": "reading",
            "date": "2026-03-01",
        })
        assert result["created"] is True
        assert result["habit_id"] == "reading"
        assert result["date"] == "2026-03-01"
        assert result["value"] == 1
        assert result["created_at"] is not None

    def test_upserts_existing_entry(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.log_date(conn, {
            "habit_id": "reading",
            "date": "2026-03-01",
            "value": 1,
        })
        result = engine.log_date(conn, {
            "habit_id": "reading",
            "date": "2026-03-01",
            "value": 2,
            "note": "updated",
        })
        assert result["created"] is False
        assert result["value"] == 2
        assert result["note"] == "updated"

    def test_rejects_archived_habit(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.archive_habit(conn, {"id": "reading"})
        try:
            engine.log_date(conn, {
                "habit_id": "reading",
                "date": "2026-03-01",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "archived" in str(e).lower()

    def test_rejects_nonexistent_habit(self):
        conn = _fresh_conn()
        try:
            engine.log_date(conn, {
                "habit_id": "nonexistent",
                "date": "2026-03-01",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not found" in str(e).lower()

    def test_rejects_invalid_date(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        try:
            engine.log_date(conn, {
                "habit_id": "reading",
                "date": "not-a-date",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "invalid date" in str(e).lower()

    def test_with_custom_value_and_note(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        result = engine.log_date(conn, {
            "habit_id": "reading",
            "date": "2026-03-05",
            "value": 30,
            "note": "30 pages",
        })
        assert result["value"] == 30
        assert result["note"] == "30 pages"


class TestLogRange:
    def test_creates_entries_for_date_range(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        result = engine.log_range(conn, {
            "habit_id": "reading",
            "start_date": "2026-03-01",
            "end_date": "2026-03-05",
        })
        assert result["count"] == 5
        assert result["dates"] == [
            "2026-03-01", "2026-03-02", "2026-03-03",
            "2026-03-04", "2026-03-05",
        ]
        # Verify entries exist in DB
        rows = conn.execute(
            "SELECT * FROM entries WHERE habit_id = ? ORDER BY date",
            ("reading",),
        ).fetchall()
        assert len(rows) == 5

    def test_single_day_range(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        result = engine.log_range(conn, {
            "habit_id": "reading",
            "start_date": "2026-03-01",
            "end_date": "2026-03-01",
        })
        assert result["count"] == 1

    def test_rejects_archived_habit(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.archive_habit(conn, {"id": "reading"})
        try:
            engine.log_range(conn, {
                "habit_id": "reading",
                "start_date": "2026-03-01",
                "end_date": "2026-03-05",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "archived" in str(e).lower()

    def test_rejects_end_before_start(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        try:
            engine.log_range(conn, {
                "habit_id": "reading",
                "start_date": "2026-03-05",
                "end_date": "2026-03-01",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "end_date" in str(e).lower()


class TestBulkSet:
    def test_creates_entries_for_specific_dates(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        result = engine.bulk_set(conn, {
            "habit_id": "reading",
            "dates": ["2026-03-01", "2026-03-03", "2026-03-07"],
        })
        assert result["count"] == 3
        assert result["dates"] == ["2026-03-01", "2026-03-03", "2026-03-07"]
        # Verify entries exist in DB
        rows = conn.execute(
            "SELECT * FROM entries WHERE habit_id = ? ORDER BY date",
            ("reading",),
        ).fetchall()
        assert len(rows) == 3

    def test_rejects_archived_habit(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.archive_habit(conn, {"id": "reading"})
        try:
            engine.bulk_set(conn, {
                "habit_id": "reading",
                "dates": ["2026-03-01"],
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "archived" in str(e).lower()

    def test_rejects_invalid_date_in_list(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        try:
            engine.bulk_set(conn, {
                "habit_id": "reading",
                "dates": ["2026-03-01", "bad-date"],
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "invalid date" in str(e).lower()


class TestDeleteEntry:
    def test_deletes_existing_entry(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.log_date(conn, {
            "habit_id": "reading",
            "date": "2026-03-01",
        })
        result = engine.delete_entry(conn, {
            "habit_id": "reading",
            "date": "2026-03-01",
        })
        assert result["deleted"] is True
        # Verify entry is gone
        row = conn.execute(
            "SELECT * FROM entries WHERE habit_id = ? AND date = ?",
            ("reading", "2026-03-01"),
        ).fetchone()
        assert row is None

    def test_returns_false_for_nonexistent_entry(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        result = engine.delete_entry(conn, {
            "habit_id": "reading",
            "date": "2026-03-01",
        })
        assert result["deleted"] is False

    def test_rejects_nonexistent_habit(self):
        conn = _fresh_conn()
        try:
            engine.delete_entry(conn, {
                "habit_id": "nonexistent",
                "date": "2026-03-01",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not found" in str(e).lower()

    def test_rejects_archived_habit(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.log_date(conn, {
            "habit_id": "reading",
            "date": "2026-03-01",
        })
        engine.archive_habit(conn, {"id": "reading"})
        try:
            engine.delete_entry(conn, {
                "habit_id": "reading",
                "date": "2026-03-01",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "archived" in str(e).lower()
