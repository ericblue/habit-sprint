"""Tests for the daily_score reporting function."""

import tempfile
import os

from habit_sprint.db import get_connection
from habit_sprint import engine, reporting


def _fresh_conn():
    """Return a connection to a fresh temporary database with migrations applied."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return get_connection(path)


def _create_sprint(conn, **overrides):
    """Helper to create a sprint."""
    data = {
        "start_date": "2026-03-01",
        "end_date": "2026-03-14",
    }
    data.update(overrides)
    return engine.create_sprint(conn, data)


def _create_habit(conn, habit_id, name, category="health", weight=1, sprint_id=None):
    """Helper to create a habit."""
    data = {
        "id": habit_id,
        "name": name,
        "category": category,
        "target_per_week": 5,
        "weight": weight,
    }
    if sprint_id:
        data["sprint_id"] = sprint_id
    return engine.create_habit(conn, data)


def _log_entry(conn, habit_id, date, value=1):
    """Helper to log an entry."""
    return engine.log_date(conn, {"habit_id": habit_id, "date": date, "value": value})


class TestDailyScoreMixed:
    """Test with some completed and some missed habits."""

    def test_mixed_completion(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        _create_habit(conn, "running", "Running", weight=2, sprint_id=sprint["id"])
        _create_habit(conn, "reading", "Reading", weight=1, sprint_id=sprint["id"])
        _create_habit(conn, "meditation", "Meditation", weight=3, sprint_id=sprint["id"])

        # Log entries for running and reading, skip meditation
        _log_entry(conn, "running", "2026-03-02", value=1)
        _log_entry(conn, "reading", "2026-03-02", value=1)

        result = reporting.daily_score(conn, {"date": "2026-03-02"})

        assert result["date"] == "2026-03-02"
        assert result["sprint_id"] == sprint["id"]
        # running: 1*2=2, reading: 1*1=1, total=3
        assert result["total_points"] == 3
        # max = 2+1+3 = 6
        assert result["max_possible"] == 6
        assert result["completion_pct"] == 50  # round(3/6*100) = 50
        assert len(result["habits_completed"]) == 2
        assert len(result["habits_missed"]) == 1
        assert result["habits_missed"][0]["id"] == "meditation"

    def test_completed_habit_fields(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", weight=2, sprint_id=sprint["id"])
        _log_entry(conn, "running", "2026-03-02", value=3)

        result = reporting.daily_score(conn, {"date": "2026-03-02"})

        completed = result["habits_completed"][0]
        assert completed["id"] == "running"
        assert completed["name"] == "Running"
        assert completed["value"] == 3
        assert completed["weight"] == 2
        assert completed["points"] == 6  # 3 * 2

    def test_missed_habit_fields(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", weight=2, sprint_id=sprint["id"])

        result = reporting.daily_score(conn, {"date": "2026-03-02"})

        missed = result["habits_missed"][0]
        assert missed["id"] == "running"
        assert missed["name"] == "Running"
        assert missed["weight"] == 2
        assert missed["points_possible"] == 2


class TestDailyScoreAllCompleted:
    """Test with all habits completed."""

    def test_all_completed(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        _create_habit(conn, "running", "Running", weight=2, sprint_id=sprint["id"])
        _create_habit(conn, "reading", "Reading", weight=1, sprint_id=sprint["id"])

        _log_entry(conn, "running", "2026-03-02", value=1)
        _log_entry(conn, "reading", "2026-03-02", value=1)

        result = reporting.daily_score(conn, {"date": "2026-03-02"})

        assert result["total_points"] == 3  # 1*2 + 1*1
        assert result["max_possible"] == 3
        assert result["completion_pct"] == 100
        assert len(result["habits_completed"]) == 2
        assert len(result["habits_missed"]) == 0


class TestDailyScoreNoEntries:
    """Test with no entries (all missed)."""

    def test_no_entries(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        _create_habit(conn, "running", "Running", weight=2, sprint_id=sprint["id"])
        _create_habit(conn, "reading", "Reading", weight=1, sprint_id=sprint["id"])

        result = reporting.daily_score(conn, {"date": "2026-03-02"})

        assert result["total_points"] == 0
        assert result["max_possible"] == 3
        assert result["completion_pct"] == 0
        assert len(result["habits_completed"]) == 0
        assert len(result["habits_missed"]) == 2

    def test_no_habits_gives_zero(self):
        conn = _fresh_conn()
        _create_sprint(conn)

        result = reporting.daily_score(conn, {"date": "2026-03-02"})

        assert result["total_points"] == 0
        assert result["max_possible"] == 0
        assert result["completion_pct"] == 0
        assert len(result["habits_completed"]) == 0
        assert len(result["habits_missed"]) == 0


class TestDailyScoreArchivedHabits:
    """Test that archived habits are excluded."""

    def test_excludes_archived_habits(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        _create_habit(conn, "running", "Running", weight=2, sprint_id=sprint["id"])
        _create_habit(conn, "reading", "Reading", weight=1, sprint_id=sprint["id"])

        # Archive reading
        engine.archive_habit(conn, {"id": "reading"})

        _log_entry(conn, "running", "2026-03-02", value=1)

        result = reporting.daily_score(conn, {"date": "2026-03-02"})

        # Only running should be counted (reading is archived)
        assert result["max_possible"] == 2
        assert result["total_points"] == 2
        assert result["completion_pct"] == 100
        assert len(result["habits_completed"]) == 1
        assert len(result["habits_missed"]) == 0


class TestDailyScoreWithSprintId:
    """Test with explicit sprint_id."""

    def test_specific_sprint_id(self):
        conn = _fresh_conn()
        sprint1 = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        # Archive sprint1 so we can create sprint2 without overlap
        engine.archive_sprint(conn, {"sprint_id": sprint1["id"]})
        sprint2 = _create_sprint(conn, start_date="2026-03-15", end_date="2026-03-28")

        _create_habit(conn, "running", "Running", weight=2, sprint_id=sprint1["id"])
        _create_habit(conn, "reading", "Reading", weight=1, sprint_id=sprint2["id"])

        _log_entry(conn, "running", "2026-03-02", value=1)

        # Query sprint1 explicitly — should only see running
        result = reporting.daily_score(conn, {
            "date": "2026-03-02",
            "sprint_id": sprint1["id"],
        })

        assert result["sprint_id"] == sprint1["id"]
        assert result["max_possible"] == 2
        assert len(result["habits_completed"]) == 1
        assert result["habits_completed"][0]["id"] == "running"
        assert len(result["habits_missed"]) == 0

    def test_invalid_sprint_id_raises(self):
        conn = _fresh_conn()
        try:
            reporting.daily_score(conn, {"date": "2026-03-02", "sprint_id": "bogus"})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Sprint not found" in str(e)


class TestDailyScoreGlobalHabits:
    """Test that global habits (sprint_id IS NULL) are included."""

    def test_includes_global_habits(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        # Sprint-scoped habit
        _create_habit(conn, "running", "Running", weight=2, sprint_id=sprint["id"])
        # Global habit (no sprint_id)
        _create_habit(conn, "water", "Drink Water", weight=1)

        _log_entry(conn, "running", "2026-03-02", value=1)
        _log_entry(conn, "water", "2026-03-02", value=1)

        result = reporting.daily_score(conn, {"date": "2026-03-02"})

        assert result["max_possible"] == 3  # 2 + 1
        assert result["total_points"] == 3
        assert result["completion_pct"] == 100
        assert len(result["habits_completed"]) == 2


class TestDailyScoreValueWeighting:
    """Test that value * weight scoring works correctly."""

    def test_higher_value_increases_points(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        _create_habit(conn, "reading", "Reading", weight=2, sprint_id=sprint["id"])
        # Log a value of 3 (e.g., 3 pages)
        _log_entry(conn, "reading", "2026-03-02", value=3)

        result = reporting.daily_score(conn, {"date": "2026-03-02"})

        assert result["total_points"] == 6  # 3 * 2
        assert result["max_possible"] == 2
        assert result["completion_pct"] == 300  # over 100% is fine with high values
