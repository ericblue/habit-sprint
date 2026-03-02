"""Comprehensive integration tests for engine + executor operations.

Uses executor.execute() as the primary entry point to exercise the full
validation -> routing -> handler -> envelope pipeline.  Falls back to
direct engine calls for actions where the validation schema field names
diverge from the engine parameter names (update_sprint, archive_sprint).
"""

import os
import tempfile

import pytest

from habit_sprint import engine
from habit_sprint.db import get_connection
from habit_sprint.executor import execute


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path):
    """Return a path to a fresh temporary database."""
    return str(tmp_path / "test.db")


@pytest.fixture()
def conn(tmp_path):
    """Return a connection to a fresh temporary database with migrations."""
    return get_connection(str(tmp_path / "test.db"))


def _exec(action, payload, db_path):
    """Shorthand for executor.execute with standard envelope."""
    return execute({"action": action, "payload": payload}, db_path)


def _ok(result):
    """Assert the result is a success envelope and return data."""
    assert result["status"] == "success", f"Expected success, got: {result['error']}"
    assert result["error"] is None
    assert result["data"] is not None
    return result["data"]


def _err(result):
    """Assert the result is an error envelope and return error message."""
    assert result["status"] == "error", f"Expected error, got success: {result['data']}"
    assert result["data"] is None
    assert result["error"] is not None
    return result["error"]


# ---------------------------------------------------------------------------
# Sprint CRUD — happy paths via executor
# ---------------------------------------------------------------------------

class TestSprintCreateViaExecutor:
    def test_create_sprint_happy_path(self, db_path):
        data = _ok(_exec("create_sprint", {
            "id": "ignored",
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        }, db_path))
        assert data["id"] == "2026-S01"
        assert data["status"] == "active"
        assert data["start_date"] == "2026-03-01"
        assert data["end_date"] == "2026-03-14"
        assert data["focus_goals"] == []
        assert data["created_at"] is not None
        assert data["updated_at"] is not None

    def test_create_sprint_with_theme_and_goals(self, db_path):
        data = _ok(_exec("create_sprint", {
            "id": "x",
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
            "theme": "Deep Work",
            "focus_goals": ["Read 1h daily", "No social media"],
        }, db_path))
        assert data["theme"] == "Deep Work"
        assert data["focus_goals"] == ["Read 1h daily", "No social media"]

    def test_create_sprint_invalid_dates_reversed(self, db_path):
        err = _err(_exec("create_sprint", {
            "id": "x",
            "start_date": "2026-03-14",
            "end_date": "2026-03-01",
        }, db_path))
        assert "end_date must be after start_date" in err

    def test_create_sprint_equal_dates(self, db_path):
        err = _err(_exec("create_sprint", {
            "id": "x",
            "start_date": "2026-03-01",
            "end_date": "2026-03-01",
        }, db_path))
        assert "end_date must be after start_date" in err

    def test_create_sprint_bad_start_date_format(self, db_path):
        err = _err(_exec("create_sprint", {
            "id": "x",
            "start_date": "not-a-date",
            "end_date": "2026-03-14",
        }, db_path))
        assert "ISO date" in err or "Invalid" in err

    def test_create_sprint_bad_end_date_format(self, db_path):
        err = _err(_exec("create_sprint", {
            "id": "x",
            "start_date": "2026-03-01",
            "end_date": "nope",
        }, db_path))
        assert "ISO date" in err or "Invalid" in err


class TestSprintListViaExecutor:
    def test_list_empty(self, db_path):
        data = _ok(_exec("list_sprints", {}, db_path))
        assert data["sprints"] == []

    def test_list_all(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-01-01", "end_date": "2026-01-14",
        }, db_path))
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-02-01", "end_date": "2026-02-14",
        }, db_path))
        data = _ok(_exec("list_sprints", {}, db_path))
        assert len(data["sprints"]) == 2

    def test_list_filter_active(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-01-01", "end_date": "2026-01-14",
        }, db_path))
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-02-01", "end_date": "2026-02-14",
        }, db_path))
        # Archive the first sprint directly (schema mismatch prevents executor)
        conn = get_connection(db_path)
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        conn.close()

        data = _ok(_exec("list_sprints", {"status": "active"}, db_path))
        assert len(data["sprints"]) == 1
        assert data["sprints"][0]["id"] == "2026-S02"

    def test_list_filter_archived(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-01-01", "end_date": "2026-01-14",
        }, db_path))
        conn = get_connection(db_path)
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        conn.close()
        data = _ok(_exec("list_sprints", {"status": "archived"}, db_path))
        assert len(data["sprints"]) == 1
        assert data["sprints"][0]["status"] == "archived"

    def test_list_ordered_by_start_date(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-06-01", "end_date": "2026-06-14",
        }, db_path))
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-01-01", "end_date": "2026-01-14",
        }, db_path))
        data = _ok(_exec("list_sprints", {}, db_path))
        assert data["sprints"][0]["start_date"] == "2026-01-01"
        assert data["sprints"][1]["start_date"] == "2026-06-01"


class TestSprintGetActiveViaExecutor:
    def test_get_active_happy(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
            "theme": "Focus",
        }, db_path))
        data = _ok(_exec("get_active_sprint", {}, db_path))
        assert data["id"] == "2026-S01"
        assert data["status"] == "active"
        assert data["theme"] == "Focus"

    def test_get_active_no_sprints(self, db_path):
        err = _err(_exec("get_active_sprint", {}, db_path))
        assert "No active sprint found" in err

    def test_get_active_all_archived(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        conn = get_connection(db_path)
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        conn.close()
        err = _err(_exec("get_active_sprint", {}, db_path))
        assert "No active sprint found" in err

    def test_get_active_returns_earliest(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-04-01", "end_date": "2026-04-14",
        }, db_path))
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-01-01", "end_date": "2026-01-14",
        }, db_path))
        data = _ok(_exec("get_active_sprint", {}, db_path))
        assert data["id"] == "2026-S02"  # earlier start_date


# Sprint update and archive tested directly (schema field name mismatch)
class TestSprintUpdateDirect:
    def test_update_theme(self, conn):
        engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Old",
        })
        result = engine.update_sprint(conn, {
            "sprint_id": "2026-S01", "theme": "New Theme",
        })
        assert result["theme"] == "New Theme"

    def test_update_focus_goals(self, conn):
        engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        result = engine.update_sprint(conn, {
            "sprint_id": "2026-S01", "focus_goals": ["A", "B"],
        })
        assert result["focus_goals"] == ["A", "B"]

    def test_update_nonexistent_raises(self, conn):
        with pytest.raises(ValueError, match="Sprint not found"):
            engine.update_sprint(conn, {"sprint_id": "2099-S99", "theme": "x"})

    def test_update_no_changes_returns_current(self, conn):
        created = engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Same",
        })
        result = engine.update_sprint(conn, {"sprint_id": "2026-S01"})
        assert result["theme"] == "Same"

    def test_update_changes_updated_at(self, conn):
        created = engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        updated = engine.update_sprint(conn, {
            "sprint_id": "2026-S01", "theme": "Changed",
        })
        assert updated["updated_at"] >= created["updated_at"]


class TestSprintArchiveDirect:
    def test_archive_sets_status(self, conn):
        engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        result = engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        assert result["status"] == "archived"

    def test_archive_updates_timestamp(self, conn):
        created = engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        archived = engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        assert archived["updated_at"] >= created["updated_at"]

    def test_archive_nonexistent_raises(self, conn):
        with pytest.raises(ValueError, match="Sprint not found"):
            engine.archive_sprint(conn, {"sprint_id": "2099-S01"})


# ---------------------------------------------------------------------------
# Habit CRUD — via executor
# ---------------------------------------------------------------------------

class TestHabitCreateViaExecutor:
    def test_create_habit_happy_path(self, db_path):
        data = _ok(_exec("create_habit", {
            "id": "reading",
            "name": "Reading",
            "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        assert data["id"] == "reading"
        assert data["name"] == "Reading"
        assert data["category"] == "cognitive"
        assert data["target_per_week"] == 5
        assert data["weight"] == 1
        assert data["unit"] == "count"
        assert data["sprint_id"] is None
        assert data["archived"] == 0

    def test_create_habit_all_fields(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        data = _ok(_exec("create_habit", {
            "id": "daily-walk",
            "name": "Daily Walk",
            "category": "health",
            "target_per_week": 7,
            "weight": 3,
            "unit": "minutes",
            "sprint_id": "2026-S01",
        }, db_path))
        assert data["weight"] == 3
        assert data["unit"] == "minutes"
        assert data["sprint_id"] == "2026-S01"

    def test_create_habit_invalid_slug_uppercase(self, db_path):
        err = _err(_exec("create_habit", {
            "id": "Reading",
            "name": "Reading",
            "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        assert "Invalid habit id" in err

    def test_create_habit_invalid_slug_numbers(self, db_path):
        err = _err(_exec("create_habit", {
            "id": "habit123",
            "name": "H",
            "category": "c",
            "target_per_week": 5,
        }, db_path))
        assert "Invalid habit id" in err

    def test_create_habit_invalid_slug_underscores(self, db_path):
        err = _err(_exec("create_habit", {
            "id": "daily_walk",
            "name": "W",
            "category": "c",
            "target_per_week": 5,
        }, db_path))
        assert "Invalid habit id" in err

    def test_create_habit_invalid_unit(self, db_path):
        err = _err(_exec("create_habit", {
            "id": "reading",
            "name": "Reading",
            "category": "cognitive",
            "target_per_week": 5,
            "unit": "kilometers",
        }, db_path))
        assert "unit" in err.lower()

    def test_create_habit_target_too_low(self, db_path):
        err = _err(_exec("create_habit", {
            "id": "reading",
            "name": "Reading",
            "category": "cognitive",
            "target_per_week": 0,
        }, db_path))
        assert "target_per_week" in err or ">=" in err

    def test_create_habit_target_too_high(self, db_path):
        err = _err(_exec("create_habit", {
            "id": "reading",
            "name": "Reading",
            "category": "cognitive",
            "target_per_week": 8,
        }, db_path))
        assert "target_per_week" in err or "<=" in err

    def test_create_habit_weight_too_low(self, db_path):
        err = _err(_exec("create_habit", {
            "id": "reading",
            "name": "Reading",
            "category": "cognitive",
            "target_per_week": 5,
            "weight": 0,
        }, db_path))
        assert "weight" in err or ">=" in err

    def test_create_habit_weight_too_high(self, db_path):
        err = _err(_exec("create_habit", {
            "id": "reading",
            "name": "Reading",
            "category": "cognitive",
            "target_per_week": 5,
            "weight": 4,
        }, db_path))
        assert "weight" in err or "<=" in err

    def test_create_habit_duplicate_id(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "A", "category": "c", "target_per_week": 1,
        }, db_path))
        err = _err(_exec("create_habit", {
            "id": "reading", "name": "B", "category": "c", "target_per_week": 1,
        }, db_path))
        assert err  # UNIQUE constraint violation


class TestHabitUpdateViaExecutor:
    def test_update_name(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        data = _ok(_exec("update_habit", {
            "id": "reading", "name": "Deep Reading",
        }, db_path))
        assert data["name"] == "Deep Reading"
        assert data["category"] == "cognitive"  # unchanged

    def test_update_multiple_fields(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        data = _ok(_exec("update_habit", {
            "id": "reading", "name": "Speed Reading",
            "target_per_week": 3, "weight": 2,
        }, db_path))
        assert data["name"] == "Speed Reading"
        assert data["target_per_week"] == 3
        assert data["weight"] == 2

    def test_update_no_changes_returns_current(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        data = _ok(_exec("update_habit", {"id": "reading"}, db_path))
        assert data["name"] == "Reading"

    def test_update_nonexistent_raises(self, db_path):
        err = _err(_exec("update_habit", {
            "id": "nope", "name": "X",
        }, db_path))
        assert "not found" in err.lower()

    def test_update_archived_habit_raises(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        _ok(_exec("archive_habit", {"id": "reading"}, db_path))
        err = _err(_exec("update_habit", {
            "id": "reading", "name": "Nope",
        }, db_path))
        assert "archived" in err.lower()

    def test_update_changes_updated_at(self, db_path):
        created = _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        updated = _ok(_exec("update_habit", {
            "id": "reading", "name": "New",
        }, db_path))
        assert updated["updated_at"] >= created["updated_at"]


class TestHabitArchiveViaExecutor:
    def test_archive_sets_flag(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        data = _ok(_exec("archive_habit", {"id": "reading"}, db_path))
        assert data["archived"] == 1

    def test_archive_nonexistent_raises(self, db_path):
        err = _err(_exec("archive_habit", {"id": "nope"}, db_path))
        assert "not found" in err.lower()

    def test_archive_updates_timestamp(self, db_path):
        created = _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        archived = _ok(_exec("archive_habit", {"id": "reading"}, db_path))
        assert archived["updated_at"] >= created["updated_at"]


class TestHabitListViaExecutor:
    def test_list_empty(self, db_path):
        data = _ok(_exec("list_habits", {}, db_path))
        assert data["habits"] == []

    def test_list_all_active(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "exercise", "name": "Exercise", "category": "health",
            "target_per_week": 3,
        }, db_path))
        data = _ok(_exec("list_habits", {}, db_path))
        assert len(data["habits"]) == 2

    def test_list_excludes_archived_by_default(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "exercise", "name": "Exercise", "category": "health",
            "target_per_week": 3,
        }, db_path))
        _ok(_exec("archive_habit", {"id": "exercise"}, db_path))
        data = _ok(_exec("list_habits", {}, db_path))
        assert len(data["habits"]) == 1
        assert data["habits"][0]["id"] == "reading"

    def test_list_include_archived(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        _ok(_exec("archive_habit", {"id": "reading"}, db_path))
        data = _ok(_exec("list_habits", {"include_archived": True}, db_path))
        assert len(data["habits"]) == 1
        assert data["habits"][0]["archived"] == 1

    def test_list_filter_by_category(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "exercise", "name": "Exercise", "category": "health",
            "target_per_week": 3,
        }, db_path))
        data = _ok(_exec("list_habits", {"category": "health"}, db_path))
        assert len(data["habits"]) == 1
        assert data["habits"][0]["id"] == "exercise"

    def test_list_filter_by_sprint_includes_global(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        # Global habit
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        # Sprint-scoped habit
        _ok(_exec("create_habit", {
            "id": "sprint-task", "name": "Sprint Task", "category": "projects",
            "target_per_week": 3, "sprint_id": "2026-S01",
        }, db_path))
        data = _ok(_exec("list_habits", {"sprint_id": "2026-S01"}, db_path))
        ids = [h["id"] for h in data["habits"]]
        assert "reading" in ids
        assert "sprint-task" in ids

    def test_list_combined_sprint_and_category(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5,
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "exercise", "name": "Exercise", "category": "health",
            "target_per_week": 3,
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "study", "name": "Study", "category": "cognitive",
            "target_per_week": 4, "sprint_id": "2026-S01",
        }, db_path))
        data = _ok(_exec("list_habits", {
            "sprint_id": "2026-S01", "category": "cognitive",
        }, db_path))
        ids = [h["id"] for h in data["habits"]]
        assert "reading" in ids    # global + cognitive
        assert "study" in ids      # sprint + cognitive
        assert "exercise" not in ids  # wrong category


# ---------------------------------------------------------------------------
# Entry management — via executor
# ---------------------------------------------------------------------------

def _setup_habit_via_exec(db_path, habit_id="reading"):
    """Create a sprint and habit through executor, return habit data."""
    _ok(_exec("create_sprint", {
        "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
    }, db_path))
    return _ok(_exec("create_habit", {
        "id": habit_id,
        "name": "Reading",
        "category": "cognitive",
        "target_per_week": 5,
    }, db_path))


class TestLogDateViaExecutor:
    def test_log_date_happy_path(self, db_path):
        _setup_habit_via_exec(db_path)
        data = _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01", "value": 1,
        }, db_path))
        assert data["created"] is True
        assert data["habit_id"] == "reading"
        assert data["date"] == "2026-03-01"
        assert data["value"] == 1

    def test_log_date_with_value_and_note(self, db_path):
        _setup_habit_via_exec(db_path)
        data = _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-05",
            "value": 30, "note": "30 pages",
        }, db_path))
        assert data["value"] == 30
        assert data["note"] == "30 pages"

    def test_log_date_nonexistent_habit(self, db_path):
        err = _err(_exec("log_date", {
            "habit_id": "nope", "date": "2026-03-01", "value": 1,
        }, db_path))
        assert "not found" in err.lower()

    def test_log_date_archived_habit(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("archive_habit", {"id": "reading"}, db_path))
        err = _err(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01", "value": 1,
        }, db_path))
        assert "archived" in err.lower()

    def test_log_date_invalid_date(self, db_path):
        _setup_habit_via_exec(db_path)
        err = _err(_exec("log_date", {
            "habit_id": "reading", "date": "bad-date", "value": 1,
        }, db_path))
        assert "date" in err.lower()


class TestLogRangeViaExecutor:
    def test_log_range_happy_path(self, db_path):
        _setup_habit_via_exec(db_path)
        data = _ok(_exec("log_range", {
            "habit_id": "reading",
            "start_date": "2026-03-01",
            "end_date": "2026-03-05",
        }, db_path))
        assert data["count"] == 5
        assert len(data["dates"]) == 5
        assert data["dates"][0] == "2026-03-01"
        assert data["dates"][-1] == "2026-03-05"

    def test_log_range_single_day(self, db_path):
        _setup_habit_via_exec(db_path)
        data = _ok(_exec("log_range", {
            "habit_id": "reading",
            "start_date": "2026-03-01",
            "end_date": "2026-03-01",
        }, db_path))
        assert data["count"] == 1

    def test_log_range_with_value(self, db_path):
        _setup_habit_via_exec(db_path)
        data = _ok(_exec("log_range", {
            "habit_id": "reading",
            "start_date": "2026-03-01",
            "end_date": "2026-03-03",
            "value": 45,
        }, db_path))
        assert data["count"] == 3
        # Verify values via direct DB read
        conn = get_connection(db_path)
        rows = conn.execute(
            "SELECT value FROM entries WHERE habit_id = ?", ("reading",)
        ).fetchall()
        conn.close()
        assert all(r["value"] == 45 for r in rows)

    def test_log_range_end_before_start(self, db_path):
        _setup_habit_via_exec(db_path)
        err = _err(_exec("log_range", {
            "habit_id": "reading",
            "start_date": "2026-03-10",
            "end_date": "2026-03-01",
        }, db_path))
        assert "end_date" in err.lower()

    def test_log_range_archived_habit(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("archive_habit", {"id": "reading"}, db_path))
        err = _err(_exec("log_range", {
            "habit_id": "reading",
            "start_date": "2026-03-01",
            "end_date": "2026-03-05",
        }, db_path))
        assert "archived" in err.lower()


class TestBulkSetViaExecutor:
    def test_bulk_set_happy_path(self, db_path):
        _setup_habit_via_exec(db_path)
        data = _ok(_exec("bulk_set", {
            "habit_id": "reading",
            "dates": ["2026-03-01", "2026-03-03", "2026-03-07"],
        }, db_path))
        assert data["count"] == 3
        assert data["dates"] == ["2026-03-01", "2026-03-03", "2026-03-07"]

    def test_bulk_set_with_value(self, db_path):
        _setup_habit_via_exec(db_path)
        data = _ok(_exec("bulk_set", {
            "habit_id": "reading",
            "dates": ["2026-03-01", "2026-03-02"],
            "value": 99,
        }, db_path))
        assert data["count"] == 2
        conn = get_connection(db_path)
        rows = conn.execute(
            "SELECT value FROM entries WHERE habit_id = ?", ("reading",)
        ).fetchall()
        conn.close()
        assert all(r["value"] == 99 for r in rows)

    def test_bulk_set_invalid_date_in_list(self, db_path):
        _setup_habit_via_exec(db_path)
        err = _err(_exec("bulk_set", {
            "habit_id": "reading",
            "dates": ["2026-03-01", "not-a-date"],
        }, db_path))
        assert "date" in err.lower()

    def test_bulk_set_archived_habit(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("archive_habit", {"id": "reading"}, db_path))
        err = _err(_exec("bulk_set", {
            "habit_id": "reading",
            "dates": ["2026-03-01"],
        }, db_path))
        assert "archived" in err.lower()

    def test_bulk_set_empty_dates(self, db_path):
        _setup_habit_via_exec(db_path)
        data = _ok(_exec("bulk_set", {
            "habit_id": "reading",
            "dates": [],
        }, db_path))
        assert data["count"] == 0


class TestDeleteEntryViaExecutor:
    def test_delete_existing_entry(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01", "value": 1,
        }, db_path))
        data = _ok(_exec("delete_entry", {
            "habit_id": "reading", "date": "2026-03-01",
        }, db_path))
        assert data["deleted"] is True

    def test_delete_nonexistent_entry_returns_false(self, db_path):
        _setup_habit_via_exec(db_path)
        data = _ok(_exec("delete_entry", {
            "habit_id": "reading", "date": "2026-03-01",
        }, db_path))
        assert data["deleted"] is False

    def test_delete_entry_nonexistent_habit(self, db_path):
        err = _err(_exec("delete_entry", {
            "habit_id": "nope", "date": "2026-03-01",
        }, db_path))
        assert "not found" in err.lower()

    def test_delete_entry_archived_habit(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01", "value": 1,
        }, db_path))
        _ok(_exec("archive_habit", {"id": "reading"}, db_path))
        err = _err(_exec("delete_entry", {
            "habit_id": "reading", "date": "2026-03-01",
        }, db_path))
        assert "archived" in err.lower()

    def test_delete_then_verify_gone(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01", "value": 1,
        }, db_path))
        _ok(_exec("delete_entry", {
            "habit_id": "reading", "date": "2026-03-01",
        }, db_path))
        # Verify entry is gone via direct DB
        conn = get_connection(db_path)
        row = conn.execute(
            "SELECT * FROM entries WHERE habit_id = ? AND date = ?",
            ("reading", "2026-03-01"),
        ).fetchone()
        conn.close()
        assert row is None


# ---------------------------------------------------------------------------
# Retrospectives — via executor
# ---------------------------------------------------------------------------

class TestAddRetroViaExecutor:
    def test_add_retro_happy_path(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        data = _ok(_exec("add_retro", {
            "sprint_id": "2026-S01",
            "what_went_well": "Consistent daily reading",
            "what_to_improve": "Wake up earlier",
            "ideas": "Try sleep timer",
        }, db_path))
        assert data["sprint_id"] == "2026-S01"
        assert data["what_went_well"] == "Consistent daily reading"
        assert data["what_to_improve"] == "Wake up earlier"
        assert data["ideas"] == "Try sleep timer"

    def test_add_retro_optional_fields(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        data = _ok(_exec("add_retro", {
            "sprint_id": "2026-S01",
            "what_went_well": "Only this",
        }, db_path))
        assert data["what_went_well"] == "Only this"
        assert data["what_to_improve"] is None
        assert data["ideas"] is None

    def test_add_retro_all_fields_empty(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        data = _ok(_exec("add_retro", {
            "sprint_id": "2026-S01",
        }, db_path))
        assert data["what_went_well"] is None
        assert data["what_to_improve"] is None
        assert data["ideas"] is None

    def test_add_retro_nonexistent_sprint(self, db_path):
        err = _err(_exec("add_retro", {
            "sprint_id": "2099-S01",
            "what_went_well": "Nothing",
        }, db_path))
        assert "Sprint not found" in err


class TestGetRetroViaExecutor:
    def test_get_retro_happy_path(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        _ok(_exec("add_retro", {
            "sprint_id": "2026-S01",
            "what_went_well": "Great week",
            "what_to_improve": "Sleep",
            "ideas": "Alarms",
        }, db_path))
        data = _ok(_exec("get_retro", {"sprint_id": "2026-S01"}, db_path))
        assert data["what_went_well"] == "Great week"
        assert data["what_to_improve"] == "Sleep"
        assert data["ideas"] == "Alarms"

    def test_get_retro_not_found(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        err = _err(_exec("get_retro", {"sprint_id": "2026-S01"}, db_path))
        assert "No retrospective found" in err

    def test_get_retro_nonexistent_sprint(self, db_path):
        err = _err(_exec("get_retro", {"sprint_id": "2099-S01"}, db_path))
        assert "No retrospective found" in err


# ---------------------------------------------------------------------------
# Idempotent operations
# ---------------------------------------------------------------------------

class TestIdempotentLogDate:
    """log_date uses INSERT OR REPLACE — calling twice on same (habit_id, date)
    should upsert rather than fail."""

    def test_log_date_twice_same_date(self, db_path):
        _setup_habit_via_exec(db_path)
        first = _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01", "value": 1,
        }, db_path))
        assert first["created"] is True

        second = _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01", "value": 2,
        }, db_path))
        assert second["created"] is False
        assert second["value"] == 2

    def test_log_date_twice_preserves_single_row(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01", "value": 1,
        }, db_path))
        _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01", "value": 5,
        }, db_path))
        conn = get_connection(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE habit_id = ? AND date = ?",
            ("reading", "2026-03-01"),
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_log_date_upsert_updates_note(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01",
            "value": 1, "note": "original",
        }, db_path))
        data = _ok(_exec("log_date", {
            "habit_id": "reading", "date": "2026-03-01",
            "value": 1, "note": "updated note",
        }, db_path))
        assert data["note"] == "updated note"


class TestIdempotentAddRetro:
    """add_retro uses ON CONFLICT(sprint_id) DO UPDATE — calling twice
    should upsert to a single row."""

    def test_add_retro_twice_upserts(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        _ok(_exec("add_retro", {
            "sprint_id": "2026-S01",
            "what_went_well": "Original",
        }, db_path))
        data = _ok(_exec("add_retro", {
            "sprint_id": "2026-S01",
            "what_went_well": "Updated",
            "what_to_improve": "Added later",
        }, db_path))
        assert data["what_went_well"] == "Updated"
        assert data["what_to_improve"] == "Added later"

    def test_add_retro_twice_single_row(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        _ok(_exec("add_retro", {"sprint_id": "2026-S01", "what_went_well": "A"}, db_path))
        _ok(_exec("add_retro", {"sprint_id": "2026-S01", "what_went_well": "B"}, db_path))
        conn = get_connection(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM retros WHERE sprint_id = ?", ("2026-S01",)
        ).fetchone()[0]
        conn.close()
        assert count == 1


class TestIdempotentLogRange:
    """log_range also uses INSERT OR REPLACE — overlapping ranges should not
    create duplicate entries."""

    def test_log_range_overlap_no_duplicates(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("log_range", {
            "habit_id": "reading",
            "start_date": "2026-03-01", "end_date": "2026-03-05",
        }, db_path))
        _ok(_exec("log_range", {
            "habit_id": "reading",
            "start_date": "2026-03-03", "end_date": "2026-03-07",
        }, db_path))
        conn = get_connection(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE habit_id = ?", ("reading",)
        ).fetchone()[0]
        conn.close()
        # 2026-03-01 through 2026-03-07 = 7 unique dates
        assert count == 7


class TestIdempotentBulkSet:
    """bulk_set also uses INSERT OR REPLACE."""

    def test_bulk_set_twice_same_dates(self, db_path):
        _setup_habit_via_exec(db_path)
        _ok(_exec("bulk_set", {
            "habit_id": "reading",
            "dates": ["2026-03-01", "2026-03-02"],
            "value": 1,
        }, db_path))
        _ok(_exec("bulk_set", {
            "habit_id": "reading",
            "dates": ["2026-03-01", "2026-03-02"],
            "value": 5,
        }, db_path))
        conn = get_connection(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE habit_id = ?", ("reading",)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT value FROM entries WHERE habit_id = ? ORDER BY date", ("reading",)
        ).fetchall()
        conn.close()
        assert count == 2
        assert all(r["value"] == 5 for r in rows)


# ---------------------------------------------------------------------------
# Sprint overlap edge cases
# ---------------------------------------------------------------------------

class TestSprintOverlapEdgeCases:
    def test_adjacent_sprints_no_overlap(self, conn):
        """Sprint A ends 2026-03-14, Sprint B starts 2026-03-15 — no overlap."""
        engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-15", "end_date": "2026-03-28",
        })
        assert result["id"] == "2026-S02"

    def test_adjacent_sprints_same_day_boundary(self, conn):
        """Sprint A ends on day X, Sprint B starts on day X — this IS overlap
        because the overlap check uses NOT (start > end OR end < start)."""
        engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-14", "end_date": "2026-03-28",
            })

    def test_one_day_overlap(self, conn):
        """Sprints that overlap by a single day in the middle."""
        engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-13", "end_date": "2026-03-28",
            })

    def test_complete_overlap(self, conn):
        """New sprint entirely contained within an existing sprint."""
        engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-31",
        })
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-10", "end_date": "2026-03-20",
            })

    def test_enclosing_overlap(self, conn):
        """New sprint completely encloses an existing sprint."""
        engine.create_sprint(conn, {
            "start_date": "2026-03-10", "end_date": "2026-03-20",
        })
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-01", "end_date": "2026-03-31",
            })

    def test_archived_sprint_allows_overlap(self, conn):
        """Archiving a sprint should let you create an overlapping one."""
        engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-05", "end_date": "2026-03-20",
        })
        assert result["status"] == "active"

    def test_no_overlap_with_gap(self, conn):
        """Sprints with a gap between them — no overlap."""
        engine.create_sprint(conn, {
            "start_date": "2026-01-01", "end_date": "2026-01-14",
        })
        result = engine.create_sprint(conn, {
            "start_date": "2026-02-01", "end_date": "2026-02-14",
        })
        assert result["id"] == "2026-S02"

    def test_overlap_error_includes_sprint_info(self, conn):
        """Error message should include the conflicting sprint ID and dates."""
        engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        with pytest.raises(ValueError) as exc_info:
            engine.create_sprint(conn, {
                "start_date": "2026-03-10", "end_date": "2026-03-20",
            })
        err = str(exc_info.value)
        assert "2026-S01" in err
        assert "2026-03-01" in err
        assert "2026-03-14" in err


# ---------------------------------------------------------------------------
# Habit carry-forward across sprint boundaries
# ---------------------------------------------------------------------------

class TestHabitCarryForward:
    """Verify that habits remain accessible across sprint boundaries."""

    def test_global_habit_accessible_across_sprints(self, conn):
        """A habit without sprint_id should appear in all sprint queries."""
        engine.create_sprint(conn, {
            "start_date": "2026-01-01", "end_date": "2026-01-14",
        })
        engine.create_sprint(conn, {
            "start_date": "2026-02-01", "end_date": "2026-02-14",
        })
        engine.create_habit(conn, {
            "id": "reading", "name": "Reading",
            "category": "cognitive", "target_per_week": 5,
        })
        # Should appear when filtering by either sprint
        s1_habits = engine.list_habits(conn, {"sprint_id": "2026-S01"})
        s2_habits = engine.list_habits(conn, {"sprint_id": "2026-S02"})
        assert any(h["id"] == "reading" for h in s1_habits["habits"])
        assert any(h["id"] == "reading" for h in s2_habits["habits"])

    def test_sprint_scoped_habit_only_in_its_sprint(self, conn):
        """A sprint-scoped habit should NOT appear in other sprint queries."""
        engine.create_sprint(conn, {
            "start_date": "2026-01-01", "end_date": "2026-01-14",
        })
        engine.create_sprint(conn, {
            "start_date": "2026-02-01", "end_date": "2026-02-14",
        })
        engine.create_habit(conn, {
            "id": "sprint-one-task", "name": "S1 Task",
            "category": "projects", "target_per_week": 3,
            "sprint_id": "2026-S01",
        })
        s1_habits = engine.list_habits(conn, {"sprint_id": "2026-S01"})
        s2_habits = engine.list_habits(conn, {"sprint_id": "2026-S02"})
        assert any(h["id"] == "sprint-one-task" for h in s1_habits["habits"])
        assert not any(h["id"] == "sprint-one-task" for h in s2_habits["habits"])

    def test_habit_entries_persist_after_sprint_archive(self, conn):
        """Entries logged during sprint 1 should still be queryable after archiving."""
        engine.create_sprint(conn, {
            "start_date": "2026-01-01", "end_date": "2026-01-14",
        })
        engine.create_habit(conn, {
            "id": "reading", "name": "Reading",
            "category": "cognitive", "target_per_week": 5,
        })
        engine.log_date(conn, {
            "habit_id": "reading", "date": "2026-01-05", "value": 1,
        })
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})

        # Create new sprint
        engine.create_sprint(conn, {
            "start_date": "2026-02-01", "end_date": "2026-02-14",
        })
        # Old entries still in DB
        row = conn.execute(
            "SELECT * FROM entries WHERE habit_id = ? AND date = ?",
            ("reading", "2026-01-05"),
        ).fetchone()
        assert row is not None
        assert row["value"] == 1

    def test_habit_still_loggable_in_new_sprint(self, conn):
        """Global habit should remain loggable after creating a new sprint."""
        engine.create_sprint(conn, {
            "start_date": "2026-01-01", "end_date": "2026-01-14",
        })
        engine.create_habit(conn, {
            "id": "reading", "name": "Reading",
            "category": "cognitive", "target_per_week": 5,
        })
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        engine.create_sprint(conn, {
            "start_date": "2026-02-01", "end_date": "2026-02-14",
        })
        # Can still log to the habit
        result = engine.log_date(conn, {
            "habit_id": "reading", "date": "2026-02-05", "value": 1,
        })
        assert result["created"] is True

    def test_multiple_sprints_habit_appears_in_all(self, conn):
        """Create 3 sprints, 1 global habit — habit appears in all sprint queries."""
        for i, (sd, ed) in enumerate([
            ("2026-01-01", "2026-01-14"),
            ("2026-02-01", "2026-02-14"),
            ("2026-03-01", "2026-03-14"),
        ], 1):
            engine.create_sprint(conn, {"start_date": sd, "end_date": ed})

        engine.create_habit(conn, {
            "id": "reading", "name": "Reading",
            "category": "cognitive", "target_per_week": 5,
        })
        for sid in ["2026-S01", "2026-S02", "2026-S03"]:
            habits = engine.list_habits(conn, {"sprint_id": sid})
            assert any(h["id"] == "reading" for h in habits["habits"]), (
                f"Global habit should appear for sprint {sid}"
            )


# ---------------------------------------------------------------------------
# Global habits
# ---------------------------------------------------------------------------

class TestGlobalHabits:
    def test_global_habit_has_null_sprint_id(self, db_path):
        data = _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading",
            "category": "cognitive", "target_per_week": 5,
        }, db_path))
        assert data["sprint_id"] is None

    def test_global_habit_appears_in_sprint_query(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading",
            "category": "cognitive", "target_per_week": 5,
        }, db_path))
        data = _ok(_exec("list_habits", {"sprint_id": "2026-S01"}, db_path))
        assert any(h["id"] == "reading" for h in data["habits"])

    def test_global_habit_appears_without_sprint_filter(self, db_path):
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading",
            "category": "cognitive", "target_per_week": 5,
        }, db_path))
        data = _ok(_exec("list_habits", {}, db_path))
        assert len(data["habits"]) == 1
        assert data["habits"][0]["sprint_id"] is None

    def test_global_and_sprint_habits_coexist(self, db_path):
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading",
            "category": "cognitive", "target_per_week": 5,
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "sprint-focus", "name": "Sprint Focus",
            "category": "projects", "target_per_week": 3,
            "sprint_id": "2026-S01",
        }, db_path))
        data = _ok(_exec("list_habits", {"sprint_id": "2026-S01"}, db_path))
        ids = [h["id"] for h in data["habits"]]
        assert "reading" in ids
        assert "sprint-focus" in ids

    def test_global_habit_not_in_wrong_sprint(self, db_path):
        """Global habits appear in all sprint queries; sprint-scoped only in theirs."""
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
        }, db_path))
        _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-04-01", "end_date": "2026-04-14",
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "global-habit", "name": "Global",
            "category": "cognitive", "target_per_week": 5,
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "s-one-only", "name": "S1 Only",
            "category": "projects", "target_per_week": 3,
            "sprint_id": "2026-S01",
        }, db_path))
        s1 = _ok(_exec("list_habits", {"sprint_id": "2026-S01"}, db_path))
        s2 = _ok(_exec("list_habits", {"sprint_id": "2026-S02"}, db_path))
        s1_ids = [h["id"] for h in s1["habits"]]
        s2_ids = [h["id"] for h in s2["habits"]]
        assert "global-habit" in s1_ids
        assert "global-habit" in s2_ids
        assert "s-one-only" in s1_ids
        assert "s-one-only" not in s2_ids


# ---------------------------------------------------------------------------
# Executor envelope correctness
# ---------------------------------------------------------------------------

class TestExecutorEnvelope:
    def test_missing_action_key(self, db_path):
        result = execute({}, db_path)
        assert result["status"] == "error"
        assert result["data"] is None
        assert "Missing required field: action" in result["error"]

    def test_unknown_action(self, db_path):
        result = execute({"action": "nonexistent"}, db_path)
        assert result["status"] == "error"
        assert "Unknown action: nonexistent" in result["error"]

    def test_success_envelope_shape(self, db_path):
        result = _exec("list_sprints", {}, db_path)
        assert set(result.keys()) == {"status", "data", "error"}
        assert result["status"] == "success"
        assert result["error"] is None
        assert isinstance(result["data"], dict)

    def test_error_envelope_shape(self, db_path):
        result = execute({"action": "unknown_xyz"}, db_path)
        assert set(result.keys()) == {"status", "data", "error"}
        assert result["status"] == "error"
        assert result["data"] is None
        assert isinstance(result["error"], str)

    def test_validation_error_returns_envelope(self, db_path):
        result = _exec("create_habit", {"id": 123}, db_path)
        err = _err(result)
        assert err is not None

    def test_payload_defaults_to_empty_dict(self, db_path):
        result = execute({"action": "list_sprints"}, db_path)
        data = _ok(result)
        assert data["sprints"] == []


# ---------------------------------------------------------------------------
# Sprint ID generation
# ---------------------------------------------------------------------------

class TestSprintIdGeneration:
    def test_sequential_ids(self, conn):
        engine.create_sprint(conn, {
            "start_date": "2026-01-01", "end_date": "2026-01-14",
        })
        engine.create_sprint(conn, {
            "start_date": "2026-01-15", "end_date": "2026-01-28",
        })
        s3 = engine.create_sprint(conn, {
            "start_date": "2026-02-01", "end_date": "2026-02-14",
        })
        assert s3["id"] == "2026-S03"

    def test_year_boundary_resets(self, conn):
        engine.create_sprint(conn, {
            "start_date": "2025-12-01", "end_date": "2025-12-14",
        })
        s = engine.create_sprint(conn, {
            "start_date": "2026-01-01", "end_date": "2026-01-14",
        })
        assert s["id"] == "2026-S01"

    def test_id_format(self, conn):
        import re
        s = engine.create_sprint(conn, {
            "start_date": "2026-03-01", "end_date": "2026-03-14",
        })
        assert re.match(r"^\d{4}-S\d{2}$", s["id"])


# ---------------------------------------------------------------------------
# Validation boundary tests (via executor)
# ---------------------------------------------------------------------------

class TestValidationBoundaries:
    def test_target_per_week_min_boundary(self, db_path):
        data = _ok(_exec("create_habit", {
            "id": "a", "name": "A", "category": "c", "target_per_week": 1,
        }, db_path))
        assert data["target_per_week"] == 1

    def test_target_per_week_max_boundary(self, db_path):
        data = _ok(_exec("create_habit", {
            "id": "a", "name": "A", "category": "c", "target_per_week": 7,
        }, db_path))
        assert data["target_per_week"] == 7

    def test_weight_min_boundary(self, db_path):
        data = _ok(_exec("create_habit", {
            "id": "a", "name": "A", "category": "c",
            "target_per_week": 1, "weight": 1,
        }, db_path))
        assert data["weight"] == 1

    def test_weight_max_boundary(self, db_path):
        data = _ok(_exec("create_habit", {
            "id": "a", "name": "A", "category": "c",
            "target_per_week": 1, "weight": 3,
        }, db_path))
        assert data["weight"] == 3

    def test_all_valid_units(self, db_path):
        for i, unit in enumerate(["count", "minutes", "reps", "pages"]):
            data = _ok(_exec("create_habit", {
                "id": f"habit-{chr(97 + i)}",
                "name": f"H{i}",
                "category": "c",
                "target_per_week": 1,
                "unit": unit,
            }, db_path))
            assert data["unit"] == unit

    def test_valid_slug_formats(self, db_path):
        for slug in ["a", "reading", "daily-walk", "my-long-habit-name"]:
            data = _ok(_exec("create_habit", {
                "id": slug, "name": "N", "category": "c", "target_per_week": 1,
            }, db_path))
            assert data["id"] == slug

    def test_invalid_slug_formats(self, db_path):
        for bad_slug in ["A", "123", "a_b", "a b", "-abc", "abc-", "a--b"]:
            result = _exec("create_habit", {
                "id": bad_slug, "name": "N", "category": "c", "target_per_week": 1,
            }, db_path)
            assert result["status"] == "error", (
                f"Slug '{bad_slug}' should have been rejected"
            )


# ---------------------------------------------------------------------------
# Combined workflow integration test
# ---------------------------------------------------------------------------

class TestFullWorkflow:
    """End-to-end workflow exercising multiple operations sequentially."""

    def test_complete_sprint_lifecycle(self, db_path):
        # 1. Create sprint
        sprint = _ok(_exec("create_sprint", {
            "id": "x", "start_date": "2026-03-01", "end_date": "2026-03-14",
            "theme": "Focus Sprint",
            "focus_goals": ["Read daily", "Exercise 3x"],
        }, db_path))
        assert sprint["status"] == "active"

        # 2. Create habits
        _ok(_exec("create_habit", {
            "id": "reading", "name": "Reading", "category": "cognitive",
            "target_per_week": 5, "sprint_id": sprint["id"],
        }, db_path))
        _ok(_exec("create_habit", {
            "id": "exercise", "name": "Exercise", "category": "health",
            "target_per_week": 3, "weight": 2, "unit": "minutes",
        }, db_path))

        # 3. Log entries
        for day in range(1, 8):
            _ok(_exec("log_date", {
                "habit_id": "reading",
                "date": f"2026-03-{day:02d}",
                "value": 1,
            }, db_path))
        _ok(_exec("log_range", {
            "habit_id": "exercise",
            "start_date": "2026-03-01", "end_date": "2026-03-03",
            "value": 30,
        }, db_path))

        # 4. Add retrospective
        _ok(_exec("add_retro", {
            "sprint_id": sprint["id"],
            "what_went_well": "Consistent reading",
            "what_to_improve": "Earlier mornings",
        }, db_path))

        # 5. Verify data
        retro = _ok(_exec("get_retro", {"sprint_id": sprint["id"]}, db_path))
        assert retro["what_went_well"] == "Consistent reading"

        habits = _ok(_exec("list_habits", {"sprint_id": sprint["id"]}, db_path))
        assert len(habits["habits"]) == 2

        # 6. Archive sprint
        conn = get_connection(db_path)
        archived = engine.archive_sprint(conn, {"sprint_id": sprint["id"]})
        conn.close()
        assert archived["status"] == "archived"

        # 7. Entries persist
        conn = get_connection(db_path)
        rows = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        conn.close()
        assert rows == 10  # 7 reading + 3 exercise
