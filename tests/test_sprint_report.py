"""Tests for the sprint_report reporting function."""

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


class TestSprintReportMetadata:
    """Test sprint metadata fields in the report."""

    def test_basic_metadata(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, theme="Focus Phase",
                                start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {})

        assert result["sprint_id"] == sprint["id"]
        assert result["start_date"] == "2026-03-01"
        assert result["end_date"] == "2026-03-14"
        assert result["theme"] == "Focus Phase"
        assert result["status"] == "active"
        assert result["total_days"] == 14
        assert result["num_weeks"] == 2

    def test_days_elapsed_and_remaining_mid_sprint(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        # Day 8 of 14-day sprint: elapsed=8, remaining=6
        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {})

        assert result["days_elapsed"] == 8
        assert result["days_remaining"] == 6

    def test_days_elapsed_first_day(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 1)):
            result = reporting.sprint_report(conn, {})

        assert result["days_elapsed"] == 1
        assert result["days_remaining"] == 13

    def test_days_elapsed_last_day(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 14)):
            result = reporting.sprint_report(conn, {})

        assert result["days_elapsed"] == 14
        assert result["days_remaining"] == 0

    def test_days_before_sprint_starts(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-10", end_date="2026-03-23")

        with _fake_today(date(2026, 3, 5)):
            result = reporting.sprint_report(conn, {"sprint_id": "2026-S01"})

        assert result["days_elapsed"] == 0
        assert result["days_remaining"] == 14

    def test_days_after_sprint_ends(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 20)):
            result = reporting.sprint_report(conn, {})

        assert result["days_elapsed"] == 14
        assert result["days_remaining"] == 0


class TestSprintReportScores:
    """Test weighted and unweighted score calculations."""

    def test_weighted_and_unweighted_scores(self):
        """Known data: 2-week sprint, 2 habits with different weights."""
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
            result = reporting.sprint_report(conn, {})

        # weighted = (4*2 + 7*1) / (6*2 + 10*1) = (8+7)/(12+10) = 15/22 = 68%
        assert result["weighted_score"] == 68
        # unweighted = (4 + 7) / (6 + 10) = 11/16 = 69%
        assert result["unweighted_score"] == 69

    def test_no_habits_gives_zero_scores(self):
        conn = _fresh_conn()
        _create_sprint(conn)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {})

        assert result["weighted_score"] == 0
        assert result["unweighted_score"] == 0
        assert result["habits"] == []
        assert result["categories"] == []

    def test_no_entries_gives_zero_scores(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", weight=2,
                      target_per_week=5, sprint_id=sprint["id"])

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {})

        assert result["weighted_score"] == 0
        assert result["unweighted_score"] == 0

    def test_perfect_score(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        sid = sprint["id"]

        # 1-week sprint, target=3/week
        _create_habit(conn, "running", "Running", weight=1,
                      target_per_week=3, sprint_id=sid)

        for d in ["2026-03-01", "2026-03-03", "2026-03-05"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 7)):
            result = reporting.sprint_report(conn, {})

        assert result["weighted_score"] == 100
        assert result["unweighted_score"] == 100


class TestSprintReportCategories:
    """Test category breakdown."""

    def test_categories_grouped_correctly(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=2, target_per_week=3, sprint_id=sid)
        _create_habit(conn, "yoga", "Yoga", category="health",
                      weight=1, target_per_week=3, sprint_id=sid)
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      weight=1, target_per_week=5, sprint_id=sid)

        # Log entries
        for d in ["2026-03-02", "2026-03-04", "2026-03-06"]:
            _log_entry(conn, "running", d)
        for d in ["2026-03-02", "2026-03-04"]:
            _log_entry(conn, "yoga", d)
        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            _log_entry(conn, "reading", d)

        with _fake_today(date(2026, 3, 10)):
            result = reporting.sprint_report(conn, {})

        cats = {c["category"]: c for c in result["categories"]}
        assert "health" in cats
        assert "cognitive" in cats

        # health: running actual=3, w=2 -> 6; yoga actual=2, w=1 -> 2; total wa=8
        #         running target=6, w=2 -> 12; yoga target=6, w=1 -> 6; total wt=18
        #         score = 8/18 = 44%
        assert cats["health"]["weighted_score"] == 44
        assert len(cats["health"]["habits"]) == 2

        # cognitive: reading actual=3, w=1 -> 3; target=10, w=1 -> 10; score=30%
        assert cats["cognitive"]["weighted_score"] == 30
        assert len(cats["cognitive"]["habits"]) == 1

    def test_category_with_no_entries(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=5, sprint_id=sprint["id"])

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {})

        assert len(result["categories"]) == 1
        assert result["categories"][0]["weighted_score"] == 0


class TestSprintReportPerHabitStats:
    """Test per-habit stats."""

    def test_habit_stats_fields(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=2, target_per_week=3, sprint_id=sid)

        for d in ["2026-03-02", "2026-03-04", "2026-03-06", "2026-03-08"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {})

        h = result["habits"][0]
        assert h["habit_id"] == "running"
        assert h["name"] == "Running"
        assert h["category"] == "health"
        assert h["weight"] == 2
        assert h["total_entries"] == 4
        assert h["expected_entries"] == 6  # 3/week * 2 weeks
        assert h["completion_pct"] == 67  # round(4/6 * 100)
        assert "current_streak" in h
        assert "longest_streak" in h
        assert "weekly_breakdown" in h

    def test_weekly_breakdown(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=3, sprint_id=sid)

        # Week 1 entries (Mar 1-7)
        for d in ["2026-03-02", "2026-03-04"]:
            _log_entry(conn, "running", d)
        # Week 2 entries (Mar 8-14)
        for d in ["2026-03-09", "2026-03-10", "2026-03-11"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 12)):
            result = reporting.sprint_report(conn, {})

        wb = result["habits"][0]["weekly_breakdown"]
        assert len(wb) == 2
        assert wb[0]["week_start"] == "2026-03-01"
        assert wb[0]["week_end"] == "2026-03-07"
        assert wb[0]["actual"] == 2
        assert wb[0]["target"] == 3
        assert wb[1]["week_start"] == "2026-03-08"
        assert wb[1]["week_end"] == "2026-03-14"
        assert wb[1]["actual"] == 3
        assert wb[1]["target"] == 3

    def test_streaks_in_sprint_report(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=7, sprint_id=sid)

        # 3-day streak ending on "today"
        for d in ["2026-03-06", "2026-03-07", "2026-03-08"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {})

        h = result["habits"][0]
        assert h["current_streak"] == 3
        assert h["longest_streak"] == 3


class TestSprintReportPartialWeeks:
    """Test sprints with partial weeks."""

    def test_partial_week_sprint(self):
        """10-day sprint should count as 2 weeks for target calculation."""
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-10")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=3, sprint_id=sid)

        with _fake_today(date(2026, 3, 5)):
            result = reporting.sprint_report(conn, {})

        assert result["num_weeks"] == 2  # ceil(10/7) = 2
        assert result["habits"][0]["expected_entries"] == 6  # 3 * 2


class TestSprintReportTrend:
    """Test trend_vs_last_sprint."""

    def test_no_prior_sprint_gives_null(self):
        conn = _fresh_conn()
        _create_sprint(conn)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {})

        assert result["trend_vs_last_sprint"] is None

    def test_trend_positive(self):
        conn = _fresh_conn()
        # Sprint 1: lower score
        s1 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        # Global habit so it's included in both sprints
        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=7)

        # Log 7 out of 14 for sprint 1 => 50%
        for d in ["2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04",
                   "2026-02-05", "2026-02-06", "2026-02-07"]:
            _log_entry(conn, "running", d)

        engine.archive_sprint(conn, {"sprint_id": s1["id"]})

        # Sprint 2: higher score
        s2 = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        # Log 10 out of 14 for sprint 2 => 71%
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06", "2026-03-07", "2026-03-08",
                   "2026-03-09", "2026-03-10"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 12)):
            result = reporting.sprint_report(conn, {})

        # 71 - 50 = 21
        assert result["trend_vs_last_sprint"] == 21

    def test_trend_negative(self):
        conn = _fresh_conn()
        s1 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        # Global habit so it's included in both sprints
        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=7)

        # Log 10 out of 14 for sprint 1 => 71%
        for d in ["2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04",
                   "2026-02-05", "2026-02-06", "2026-02-07", "2026-02-08",
                   "2026-02-09", "2026-02-10"]:
            _log_entry(conn, "running", d)

        engine.archive_sprint(conn, {"sprint_id": s1["id"]})

        s2 = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        # Log 7 out of 14 for sprint 2 => 50%
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06", "2026-03-07"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 12)):
            result = reporting.sprint_report(conn, {})

        # 50 - 71 = -21
        assert result["trend_vs_last_sprint"] == -21


class TestSprintReportSprintResolution:
    """Test sprint_id resolution."""

    def test_defaults_to_active_sprint(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {})

        assert result["sprint_id"] == sprint["id"]

    def test_explicit_sprint_id(self):
        conn = _fresh_conn()
        s1 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 8)):
            result = reporting.sprint_report(conn, {"sprint_id": s1["id"]})

        assert result["sprint_id"] == s1["id"]

    def test_invalid_sprint_id_raises(self):
        conn = _fresh_conn()
        import pytest
        with pytest.raises(ValueError, match="Sprint not found"):
            reporting.sprint_report(conn, {"sprint_id": "bogus"})

    def test_no_active_sprint_raises(self):
        conn = _fresh_conn()
        import pytest
        with pytest.raises(ValueError, match="No active sprint found"):
            reporting.sprint_report(conn, {})


class TestSprintReportArchivedHabits:
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
            result = reporting.sprint_report(conn, {})

        assert len(result["habits"]) == 1
        assert result["habits"][0]["habit_id"] == "running"


class TestSprintReportGlobalHabits:
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
            result = reporting.sprint_report(conn, {})

        assert len(result["habits"]) == 2
        habit_ids = {h["habit_id"] for h in result["habits"]}
        assert habit_ids == {"running", "water"}
