"""Tests for the get_week_view reporting function."""

import tempfile
import os
from datetime import date
from unittest.mock import patch

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
        "start_date": "2026-03-02",
        "end_date": "2026-03-15",
    }
    data.update(overrides)
    return engine.create_sprint(conn, data)


def _create_habit(conn, habit_id, name, category="health", weight=1,
                  target_per_week=5, sprint_id=None):
    """Helper to create a habit."""
    data = {
        "id": habit_id,
        "name": name,
        "category": category,
        "target_per_week": target_per_week,
        "weight": weight,
    }
    if sprint_id:
        data["sprint_id"] = sprint_id
    return engine.create_habit(conn, data)


def _log_entry(conn, habit_id, entry_date, value=1):
    """Helper to log an entry."""
    return engine.log_date(conn, {
        "habit_id": habit_id,
        "date": entry_date,
        "value": value,
    })


def _fake_today(d):
    """Return a patcher that makes date.today() return d in the reporting module."""
    class FakeDate(date):
        @classmethod
        def today(cls):
            return d

        @classmethod
        def fromisoformat(cls, s):
            return date.fromisoformat(s)

    return patch("habit_sprint.reporting.date", FakeDate)


class TestWeekViewBasic:
    """Basic week view with known data."""

    def test_returns_correct_structure(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sprint["id"])

        result = reporting.get_week_view(conn, {
            "week_start": "2026-03-02",
        })

        assert result["sprint_id"] == sprint["id"]
        assert result["week_start"] == "2026-03-02"
        assert result["week_end"] == "2026-03-08"
        assert "categories" in result
        assert "health" in result["categories"]
        habits = result["categories"]["health"]["habits"]
        assert len(habits) == 1
        h = habits[0]
        assert h["id"] == "running"
        assert h["name"] == "Running"
        assert h["target_per_week"] == 5
        assert h["weight"] == 1
        assert "daily_values" in h
        assert set(h["daily_values"].keys()) == {
            "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"
        }

    def test_daily_values_populated(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", sprint_id=sprint["id"])

        # Log Mon, Wed, Fri
        _log_entry(conn, "running", "2026-03-02")  # Mon
        _log_entry(conn, "running", "2026-03-04")  # Wed
        _log_entry(conn, "running", "2026-03-06")  # Fri

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        h = result["categories"]["health"]["habits"][0]

        assert h["daily_values"]["Mon"] == 1
        assert h["daily_values"]["Tue"] == 0
        assert h["daily_values"]["Wed"] == 1
        assert h["daily_values"]["Thu"] == 0
        assert h["daily_values"]["Fri"] == 1
        assert h["daily_values"]["Sat"] == 0
        assert h["daily_values"]["Sun"] == 0

    def test_week_actual_and_completion(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", target_per_week=5,
                      sprint_id=sprint["id"])

        # Log 3 of 5 target days
        _log_entry(conn, "running", "2026-03-02")
        _log_entry(conn, "running", "2026-03-04")
        _log_entry(conn, "running", "2026-03-06")

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        h = result["categories"]["health"]["habits"][0]

        assert h["week_actual"] == 3
        assert h["week_completion_pct"] == 60  # 3/5 * 100
        assert h["commitment_met"] is False

    def test_commitment_met_true(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", target_per_week=3,
                      sprint_id=sprint["id"])

        _log_entry(conn, "running", "2026-03-02")
        _log_entry(conn, "running", "2026-03-03")
        _log_entry(conn, "running", "2026-03-04")

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        h = result["categories"]["health"]["habits"][0]

        assert h["week_actual"] == 3
        assert h["commitment_met"] is True

    def test_completion_pct_capped_at_100(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", target_per_week=3,
                      sprint_id=sprint["id"])

        # Log 5 days — exceeds target of 3
        for d in ["2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06"]:
            _log_entry(conn, "running", d)

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        h = result["categories"]["health"]["habits"][0]

        assert h["week_actual"] == 5
        assert h["week_completion_pct"] == 100  # capped


class TestWeekViewCategories:
    """Test grouping habits by category."""

    def test_groups_by_category(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sprint["id"])
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      sprint_id=sprint["id"])
        _create_habit(conn, "meditation", "Meditation", category="health",
                      sprint_id=sprint["id"])

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})

        assert "health" in result["categories"]
        assert "cognitive" in result["categories"]
        health_ids = [h["id"] for h in result["categories"]["health"]["habits"]]
        assert "running" in health_ids
        assert "meditation" in health_ids
        cognitive_ids = [h["id"] for h in
                         result["categories"]["cognitive"]["habits"]]
        assert "reading" in cognitive_ids

    def test_multiple_habits_in_category(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sprint["id"])
        _create_habit(conn, "yoga", "Yoga", category="health",
                      sprint_id=sprint["id"])

        _log_entry(conn, "running", "2026-03-02")
        _log_entry(conn, "yoga", "2026-03-03")

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        health_habits = result["categories"]["health"]["habits"]

        assert len(health_habits) == 2
        running = next(h for h in health_habits if h["id"] == "running")
        yoga = next(h for h in health_habits if h["id"] == "yoga")
        assert running["week_actual"] == 1
        assert yoga["week_actual"] == 1


class TestWeekViewDefaultWeekStart:
    """Test that week_start defaults to current week's Monday."""

    def test_defaults_to_current_monday(self):
        conn = _fresh_conn()
        # Sprint covers Mar 2-15
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", sprint_id=sprint["id"])
        _log_entry(conn, "running", "2026-03-02")  # Monday

        # 2026-03-05 is Thursday, Monday = 2026-03-02
        with _fake_today(date(2026, 3, 5)):
            result = reporting.get_week_view(conn, {})

        assert result["week_start"] == "2026-03-02"
        assert result["week_end"] == "2026-03-08"

    def test_defaults_when_today_is_monday(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", sprint_id=sprint["id"])

        # 2026-03-02 is Monday
        with _fake_today(date(2026, 3, 2)):
            result = reporting.get_week_view(conn, {})

        assert result["week_start"] == "2026-03-02"

    def test_defaults_when_today_is_sunday(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", sprint_id=sprint["id"])

        # 2026-03-08 is Sunday, Monday = 2026-03-02
        with _fake_today(date(2026, 3, 8)):
            result = reporting.get_week_view(conn, {})

        assert result["week_start"] == "2026-03-02"


class TestWeekViewSprintBoundaries:
    """Days outside sprint range return 0 values."""

    def test_days_before_sprint_start_are_zero(self):
        conn = _fresh_conn()
        # Sprint starts Wed Mar 4
        sprint = _create_sprint(conn, start_date="2026-03-04",
                                end_date="2026-03-15")
        _create_habit(conn, "running", "Running", sprint_id=sprint["id"])

        # Log entries Mon-Fri (but Mon-Tue are before sprint start)
        for d in ["2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06"]:
            _log_entry(conn, "running", d)

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        h = result["categories"]["health"]["habits"][0]

        # Mon and Tue are outside sprint — should be 0
        assert h["daily_values"]["Mon"] == 0
        assert h["daily_values"]["Tue"] == 0
        # Wed-Fri are inside sprint — should have values
        assert h["daily_values"]["Wed"] == 1
        assert h["daily_values"]["Thu"] == 1
        assert h["daily_values"]["Fri"] == 1
        # week_actual only counts in-sprint days with value > 0
        assert h["week_actual"] == 3

    def test_days_after_sprint_end_are_zero(self):
        conn = _fresh_conn()
        # Sprint ends Thu Mar 5
        sprint = _create_sprint(conn, start_date="2026-03-02",
                                end_date="2026-03-05")
        _create_habit(conn, "running", "Running", sprint_id=sprint["id"])

        # Log entries Mon-Sun
        for d in ["2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06", "2026-03-07", "2026-03-08"]:
            _log_entry(conn, "running", d)

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        h = result["categories"]["health"]["habits"][0]

        # Mon-Thu in sprint
        assert h["daily_values"]["Mon"] == 1
        assert h["daily_values"]["Tue"] == 1
        assert h["daily_values"]["Wed"] == 1
        assert h["daily_values"]["Thu"] == 1
        # Fri-Sun outside sprint
        assert h["daily_values"]["Fri"] == 0
        assert h["daily_values"]["Sat"] == 0
        assert h["daily_values"]["Sun"] == 0
        assert h["week_actual"] == 4

    def test_week_entirely_outside_sprint(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-16",
                                end_date="2026-03-29")
        _create_habit(conn, "running", "Running", sprint_id=sprint["id"])

        # View week Mar 2-8 — entirely before sprint
        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        h = result["categories"]["health"]["habits"][0]

        for label in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            assert h["daily_values"][label] == 0
        assert h["week_actual"] == 0
        assert h["week_completion_pct"] == 0


class TestWeekViewSprintResolution:
    """Test sprint resolution — explicit vs active."""

    def test_explicit_sprint_id(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", sprint_id=sprint["id"])

        result = reporting.get_week_view(conn, {
            "sprint_id": sprint["id"],
            "week_start": "2026-03-02",
        })

        assert result["sprint_id"] == sprint["id"]

    def test_invalid_sprint_id_raises(self):
        conn = _fresh_conn()
        _create_sprint(conn)
        try:
            reporting.get_week_view(conn, {
                "sprint_id": "bogus",
                "week_start": "2026-03-02",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Sprint not found" in str(e)

    def test_no_active_sprint_raises(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        engine.archive_sprint(conn, {"sprint_id": sprint["id"]})

        try:
            reporting.get_week_view(conn, {"week_start": "2026-03-02"})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No active sprint" in str(e)


class TestWeekViewArchivedHabits:
    """Archived habits should be excluded."""

    def test_excludes_archived_habits(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sprint["id"])
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      sprint_id=sprint["id"])

        engine.archive_habit(conn, {"id": "reading"})

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})

        # Only health category should appear (reading is archived)
        assert "health" in result["categories"]
        assert "cognitive" not in result["categories"]


class TestWeekViewGlobalHabits:
    """Global habits (sprint_id IS NULL) should be included."""

    def test_includes_global_habits(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", sprint_id=sprint["id"])
        _create_habit(conn, "water", "Drink Water")  # global

        _log_entry(conn, "running", "2026-03-02")
        _log_entry(conn, "water", "2026-03-02")

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})

        all_habit_ids = []
        for cat_data in result["categories"].values():
            for h in cat_data["habits"]:
                all_habit_ids.append(h["id"])
        assert "running" in all_habit_ids
        assert "water" in all_habit_ids


class TestWeekViewEntryValues:
    """Test that actual entry values (not just 0/1) are returned."""

    def test_non_binary_values(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      sprint_id=sprint["id"])

        _log_entry(conn, "reading", "2026-03-02", value=3)
        _log_entry(conn, "reading", "2026-03-04", value=5)

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        h = result["categories"]["cognitive"]["habits"][0]

        assert h["daily_values"]["Mon"] == 3
        assert h["daily_values"]["Wed"] == 5
        assert h["daily_values"]["Tue"] == 0
        # week_actual counts days with value > 0
        assert h["week_actual"] == 2


class TestWeekViewNoHabits:
    """Test with no habits returns empty categories."""

    def test_no_habits(self):
        conn = _fresh_conn()
        _create_sprint(conn)

        result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})

        assert result["categories"] == {}
