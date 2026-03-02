"""Tests for the sprint_dashboard reporting function."""

import tempfile
import os
from datetime import date
from unittest.mock import patch

import pytest

from habit_sprint.db import get_connection
from habit_sprint import engine, reporting


def _fresh_conn():
    """Return a connection to a fresh temporary database with migrations applied."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return get_connection(path)


def _create_sprint(conn, **overrides):
    data = {
        "start_date": "2026-03-01",
        "end_date": "2026-03-14",
    }
    data.update(overrides)
    return engine.create_sprint(conn, data)


def _create_habit(conn, habit_id, name, category="health", weight=1,
                  target_per_week=5, sprint_id=None):
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
    return engine.log_date(conn, {"habit_id": habit_id, "date": entry_date, "value": value})


def _fake_today(d):
    """Patch date.today() in the reporting module."""
    class FakeDate(date):
        @classmethod
        def today(cls):
            return d

        @classmethod
        def fromisoformat(cls, s):
            return date.fromisoformat(s)

    return patch("habit_sprint.reporting.date", FakeDate)


class TestSprintDashboardMetadata:
    """Test sprint metadata in the dashboard response."""

    def test_basic_metadata(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, theme="Focus Phase",
                                start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        s = result["sprint"]
        assert s["id"] == sprint["id"]
        assert s["start_date"] == "2026-03-01"
        assert s["end_date"] == "2026-03-14"
        assert s["theme"] == "Focus Phase"
        assert s["status"] == "active"
        assert s["days_elapsed"] == 8
        assert s["days_remaining"] == 6

    def test_focus_goals_parsed(self):
        conn = _fresh_conn()
        _create_sprint(conn, focus_goals=["Goal A", "Goal B"])

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        assert result["sprint"]["focus_goals"] == ["Goal A", "Goal B"]

    def test_days_before_sprint(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-10", end_date="2026-03-23")

        with _fake_today(date(2026, 3, 5)):
            result = reporting.sprint_dashboard(conn, {"sprint_id": "2026-S01"})

        assert result["sprint"]["days_elapsed"] == 0
        assert result["sprint"]["days_remaining"] == 14

    def test_days_after_sprint(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 20)):
            result = reporting.sprint_dashboard(conn, {})

        assert result["sprint"]["days_elapsed"] == 14
        assert result["sprint"]["days_remaining"] == 0


class TestSprintDashboardResolution:
    """Test sprint_id resolution."""

    def test_defaults_to_active_sprint(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        assert result["sprint"]["id"] == sprint["id"]

    def test_explicit_sprint_id(self):
        conn = _fresh_conn()
        s1 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {"sprint_id": s1["id"]})

        assert result["sprint"]["id"] == s1["id"]

    def test_invalid_sprint_id_raises(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError, match="Sprint not found"):
            reporting.sprint_dashboard(conn, {"sprint_id": "bogus"})

    def test_no_active_sprint_raises(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError, match="No active sprint found"):
            reporting.sprint_dashboard(conn, {})


class TestSprintDashboardCategories:
    """Test categories with habits and daily values."""

    def test_categories_grouped_with_daily_values(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=2, target_per_week=3, sprint_id=sid)
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      weight=1, target_per_week=5, sprint_id=sid)

        _log_entry(conn, "running", "2026-03-02")
        _log_entry(conn, "running", "2026-03-04")
        _log_entry(conn, "reading", "2026-03-01")

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        cats = {c["category"]: c for c in result["categories"]}
        assert "health" in cats
        assert "cognitive" in cats

        # Check daily values for running
        running = cats["health"]["habits"][0]
        assert running["habit_id"] == "running"
        assert running["daily"]["2026-03-02"] == 1
        assert running["daily"]["2026-03-04"] == 1
        assert running["daily"]["2026-03-01"] == 0
        assert running["week_actual"] == 2

        # Check daily values for reading
        reading = cats["cognitive"]["habits"][0]
        assert reading["daily"]["2026-03-01"] == 1
        assert reading["week_actual"] == 1

    def test_daily_values_use_iso_date_keys(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=3, sprint_id=sprint["id"])

        with _fake_today(date(2026, 3, 5)):
            result = reporting.sprint_dashboard(conn, {})

        habit = result["categories"][0]["habits"][0]
        # Keys should be ISO dates, not day names
        assert "2026-03-01" in habit["daily"]
        assert "2026-03-07" in habit["daily"]
        assert len(habit["daily"]) == 7

    def test_category_weighted_score(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        # health: running w=2 t=3, yoga w=1 t=3
        _create_habit(conn, "running", "Running", category="health",
                      weight=2, target_per_week=3, sprint_id=sid)
        _create_habit(conn, "yoga", "Yoga", category="health",
                      weight=1, target_per_week=3, sprint_id=sid)

        # Log 3 running entries and 2 yoga entries
        for d in ["2026-03-02", "2026-03-04", "2026-03-06"]:
            _log_entry(conn, "running", d)
        for d in ["2026-03-02", "2026-03-04"]:
            _log_entry(conn, "yoga", d)

        with _fake_today(date(2026, 3, 10)):
            result = reporting.sprint_dashboard(conn, {})

        cats = {c["category"]: c for c in result["categories"]}
        # health: running actual=3, w=2 -> wa=6; yoga actual=2, w=1 -> wa=2; total wa=8
        #         running target=6, w=2 -> wt=12; yoga target=6, w=1 -> wt=6; total wt=18
        #         score = round(8/18 * 100) = 44
        assert cats["health"]["category_weighted_score"] == 44

    def test_completion_pct_and_commitment(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=3, sprint_id=sid)

        # Log 6 entries over 2-week sprint (target = 3*2 = 6)
        for d in ["2026-03-01", "2026-03-03", "2026-03-05",
                   "2026-03-08", "2026-03-10", "2026-03-12"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 14)):
            result = reporting.sprint_dashboard(conn, {})

        habit = result["categories"][0]["habits"][0]
        assert habit["week_actual"] == 6
        assert habit["week_completion_pct"] == 100
        assert habit["commitment_met"] is True

    def test_completion_pct_capped_at_100(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=3, sprint_id=sid)

        # Log all 7 days (target = 3)
        for i in range(7):
            d = f"2026-03-0{i+1}"
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 7)):
            result = reporting.sprint_dashboard(conn, {})

        habit = result["categories"][0]["habits"][0]
        assert habit["week_completion_pct"] == 100


class TestSprintDashboardDailyTotals:
    """Test daily_totals computation."""

    def test_daily_totals_structure(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=2, target_per_week=3,
                      sprint_id=sid)
        _create_habit(conn, "reading", "Reading", weight=1, target_per_week=5,
                      sprint_id=sid)

        _log_entry(conn, "running", "2026-03-01")
        _log_entry(conn, "reading", "2026-03-01")

        with _fake_today(date(2026, 3, 5)):
            result = reporting.sprint_dashboard(conn, {})

        dt = result["daily_totals"]
        assert len(dt) == 7  # 7 days in sprint

        # Day with both habits completed
        day1 = dt["2026-03-01"]
        assert day1["points"] == 3  # 1*2 + 1*1
        assert day1["max"] == 3     # 2 + 1
        assert day1["pct"] == 100

        # Day with no entries
        day2 = dt["2026-03-02"]
        assert day2["points"] == 0
        assert day2["max"] == 3
        assert day2["pct"] == 0

    def test_daily_totals_partial_completion(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=2, target_per_week=3,
                      sprint_id=sid)
        _create_habit(conn, "reading", "Reading", weight=1, target_per_week=5,
                      sprint_id=sid)

        # Only running completed on day 1
        _log_entry(conn, "running", "2026-03-01")

        with _fake_today(date(2026, 3, 5)):
            result = reporting.sprint_dashboard(conn, {})

        day1 = result["daily_totals"]["2026-03-01"]
        assert day1["points"] == 2  # 1*2
        assert day1["max"] == 3     # 2 + 1
        assert day1["pct"] == 67    # round(2/3 * 100)

    def test_daily_totals_no_habits(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")

        with _fake_today(date(2026, 3, 5)):
            result = reporting.sprint_dashboard(conn, {})

        dt = result["daily_totals"]
        assert len(dt) == 7
        for ds, day in dt.items():
            assert day["points"] == 0
            assert day["max"] == 0
            assert day["pct"] == 0


class TestSprintDashboardSummary:
    """Test sprint_summary computation."""

    def test_weighted_and_unweighted_scores(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        # running: weight=2, target=3/week -> expected=6 over 2 weeks
        _create_habit(conn, "running", "Running", category="health",
                      weight=2, target_per_week=3, sprint_id=sid)
        # reading: weight=1, target=5/week -> expected=10 over 2 weeks
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      weight=1, target_per_week=5, sprint_id=sid)

        # Log 4 running entries
        for d in ["2026-03-02", "2026-03-04", "2026-03-06", "2026-03-08"]:
            _log_entry(conn, "running", d)
        # Log 7 reading entries
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06", "2026-03-07"]:
            _log_entry(conn, "reading", d)

        with _fake_today(date(2026, 3, 10)):
            result = reporting.sprint_dashboard(conn, {})

        summary = result["sprint_summary"]
        # weighted = (4*2 + 7*1) / (6*2 + 10*1) = 15/22 = 68%
        assert summary["weighted_score"] == 68
        # unweighted = (4 + 7) / (6 + 10) = 11/16 = 69%
        assert summary["unweighted_score"] == 69

    def test_per_habit_breakdown(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=2,
                      target_per_week=3, sprint_id=sid)

        for d in ["2026-03-02", "2026-03-04", "2026-03-06", "2026-03-08"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 10)):
            result = reporting.sprint_dashboard(conn, {})

        ph = result["sprint_summary"]["per_habit"]
        assert len(ph) == 1
        assert ph[0]["habit_id"] == "running"
        assert ph[0]["actual"] == 4
        assert ph[0]["target"] == 6  # 3/week * 2 weeks
        assert ph[0]["pct"] == 67    # round(4/6 * 100)

    def test_zero_scores_no_habits(self):
        conn = _fresh_conn()
        _create_sprint(conn)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        assert result["sprint_summary"]["weighted_score"] == 0
        assert result["sprint_summary"]["unweighted_score"] == 0
        assert result["sprint_summary"]["per_habit"] == []

    def test_zero_scores_no_entries(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", weight=2,
                      target_per_week=5, sprint_id=sprint["id"])

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        assert result["sprint_summary"]["weighted_score"] == 0
        assert result["sprint_summary"]["unweighted_score"] == 0


class TestSprintDashboardRetro:
    """Test retro data in the dashboard."""

    def test_no_retro_returns_null(self):
        conn = _fresh_conn()
        _create_sprint(conn)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        assert result["retro"] is None

    def test_retro_included_when_exists(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        sid = sprint["id"]

        engine.add_retro(conn, {
            "sprint_id": sid,
            "what_went_well": "Good consistency",
            "what_to_improve": "Need more sleep",
            "ideas": "Try morning workouts",
        })

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        retro = result["retro"]
        assert retro is not None
        assert retro["sprint_id"] == sid
        assert retro["what_went_well"] == "Good consistency"
        assert retro["what_to_improve"] == "Need more sleep"
        assert retro["ideas"] == "Try morning workouts"


class TestSprintDashboardWeekFilter:
    """Test optional week parameter (1 or 2)."""

    def test_week_1_filter(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=3, sprint_id=sid)

        # Week 1 entries (Mar 1-7)
        for d in ["2026-03-02", "2026-03-04"]:
            _log_entry(conn, "running", d)
        # Week 2 entries (Mar 8-14)
        for d in ["2026-03-09", "2026-03-10", "2026-03-11"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 14)):
            result = reporting.sprint_dashboard(conn, {"week": 1})

        # Only week 1 dates in daily_totals
        dt = result["daily_totals"]
        assert len(dt) == 7
        assert "2026-03-01" in dt
        assert "2026-03-07" in dt
        assert "2026-03-08" not in dt

        # Only week 1 entries counted in habit data
        habit = result["categories"][0]["habits"][0]
        assert habit["week_actual"] == 2
        assert len(habit["daily"]) == 7

        # Summary reflects week 1 only (target = 3 for 1 week)
        ph = result["sprint_summary"]["per_habit"][0]
        assert ph["actual"] == 2
        assert ph["target"] == 3

    def test_week_2_filter(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=3, sprint_id=sid)

        # Week 1 entries (Mar 1-7)
        for d in ["2026-03-02", "2026-03-04"]:
            _log_entry(conn, "running", d)
        # Week 2 entries (Mar 8-14)
        for d in ["2026-03-09", "2026-03-10", "2026-03-11"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 14)):
            result = reporting.sprint_dashboard(conn, {"week": 2})

        # Only week 2 dates in daily_totals
        dt = result["daily_totals"]
        assert len(dt) == 7
        assert "2026-03-08" in dt
        assert "2026-03-14" in dt
        assert "2026-03-07" not in dt

        # Only week 2 entries counted
        habit = result["categories"][0]["habits"][0]
        assert habit["week_actual"] == 3
        assert habit["commitment_met"] is True

        # Summary reflects week 2 only
        ph = result["sprint_summary"]["per_habit"][0]
        assert ph["actual"] == 3
        assert ph["target"] == 3
        assert ph["pct"] == 100

    def test_no_week_filter_shows_full_sprint(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=3, sprint_id=sid)

        for d in ["2026-03-02", "2026-03-04", "2026-03-09", "2026-03-10", "2026-03-11"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 14)):
            result = reporting.sprint_dashboard(conn, {})

        dt = result["daily_totals"]
        assert len(dt) == 14  # Full sprint

        habit = result["categories"][0]["habits"][0]
        assert habit["week_actual"] == 5
        assert len(habit["daily"]) == 14

    def test_week_2_partial_sprint(self):
        """10-day sprint: week 2 is only 3 days."""
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-10")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=3, sprint_id=sid)

        _log_entry(conn, "running", "2026-03-08")
        _log_entry(conn, "running", "2026-03-09")

        with _fake_today(date(2026, 3, 10)):
            result = reporting.sprint_dashboard(conn, {"week": 2})

        dt = result["daily_totals"]
        assert len(dt) == 3  # Only Mar 8-10
        assert "2026-03-08" in dt
        assert "2026-03-10" in dt

    def test_week_metadata_still_shows_full_sprint(self):
        """Sprint metadata should always reflect full sprint, not filtered week."""
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {"week": 1})

        s = result["sprint"]
        assert s["start_date"] == "2026-03-01"
        assert s["end_date"] == "2026-03-14"
        assert s["days_elapsed"] == 8
        assert s["days_remaining"] == 6


class TestSprintDashboardArchivedHabits:
    """Test that archived habits are excluded."""

    def test_excludes_archived_habits(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=5, sprint_id=sid)
        _create_habit(conn, "reading", "Reading", weight=1,
                      target_per_week=5, sprint_id=sid)
        engine.archive_habit(conn, {"id": "reading"})

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        all_habits = []
        for cat in result["categories"]:
            all_habits.extend(cat["habits"])
        assert len(all_habits) == 1
        assert all_habits[0]["habit_id"] == "running"


class TestSprintDashboardGlobalHabits:
    """Test that global habits (sprint_id IS NULL) are included."""

    def test_includes_global_habits(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=5, sprint_id=sprint["id"])
        _create_habit(conn, "water", "Drink Water", weight=1,
                      target_per_week=7)

        for d in ["2026-03-01", "2026-03-02"]:
            _log_entry(conn, "running", d)
            _log_entry(conn, "water", d)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        all_habit_ids = set()
        for cat in result["categories"]:
            for h in cat["habits"]:
                all_habit_ids.add(h["habit_id"])
        assert all_habit_ids == {"running", "water"}


class TestSprintDashboardResponseStructure:
    """Test that the response has all required top-level keys."""

    def test_top_level_keys(self):
        conn = _fresh_conn()
        _create_sprint(conn)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        assert "sprint" in result
        assert "categories" in result
        assert "daily_totals" in result
        assert "sprint_summary" in result
        assert "retro" in result

    def test_sprint_keys(self):
        conn = _fresh_conn()
        _create_sprint(conn, theme="Test")

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        s = result["sprint"]
        assert "id" in s
        assert "start_date" in s
        assert "end_date" in s
        assert "theme" in s
        assert "focus_goals" in s
        assert "status" in s
        assert "days_elapsed" in s
        assert "days_remaining" in s

    def test_summary_keys(self):
        conn = _fresh_conn()
        _create_sprint(conn)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_dashboard(conn, {})

        summary = result["sprint_summary"]
        assert "weighted_score" in summary
        assert "unweighted_score" in summary
        assert "per_habit" in summary


class TestSprintDashboardExecutor:
    """Test sprint_dashboard through the executor."""

    def test_via_executor(self):
        from habit_sprint.executor import execute
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        # Create sprint via executor
        execute({"action": "create_sprint", "payload": {
            "id": "2026-S01",
            "start_date": "2026-03-01", "end_date": "2026-03-14",
            "theme": "Test Sprint",
        }}, path)

        with _fake_today(date(2026, 3, 8)):
            result = execute({"action": "sprint_dashboard", "payload": {}}, path)

        assert result["status"] == "success"
        assert result["data"]["sprint"]["theme"] == "Test Sprint"

    def test_validation_rejects_invalid_week(self):
        from habit_sprint.executor import execute
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        result = execute({"action": "sprint_dashboard", "payload": {
            "week": 3,
        }}, path)

        assert result["status"] == "error"
