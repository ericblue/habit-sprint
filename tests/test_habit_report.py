"""Tests for habit_report reporting function."""

import tempfile
import os
from datetime import date, timedelta
from unittest.mock import patch

from habit_sprint.db import get_connection
from habit_sprint import engine, reporting


def _fresh_conn():
    """Return a connection to a fresh temporary database with migrations applied."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return get_connection(path)


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


def _setup_sprint_and_habit(
    conn,
    habit_id="reading",
    habit_name="Reading",
    target_per_week=5,
    sprint_start="2026-01-05",
    sprint_end="2026-01-18",
):
    """Create a sprint and habit for testing. Default sprint is 2 weeks Mon-Sun aligned."""
    engine.create_sprint(conn, {
        "start_date": sprint_start,
        "end_date": sprint_end,
    })
    return engine.create_habit(conn, {
        "id": habit_id,
        "name": habit_name,
        "category": "cognitive",
        "target_per_week": target_per_week,
    })


class TestBasicHabitReport:
    def test_returns_required_fields(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn)

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["habit_id"] == "reading"
        assert result["habit_name"] == "Reading"
        assert result["period"] == "current_sprint"
        assert result["start_date"] == "2026-01-05"
        assert result["end_date"] == "2026-01-18"
        assert "total_entries" in result
        assert "expected_entries" in result
        assert "completion_pct" in result
        assert "current_streak" in result
        assert "longest_streak" in result
        assert "rolling_7_day_avg" in result
        assert "trend_vs_prior_period" in result
        assert "weekly_history" in result

    def test_completion_with_entries(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, target_per_week=5)
        # Sprint: 2026-01-05 (Mon) to 2026-01-18 (Sun) = 2 weeks
        # Log 3 entries in week 1, 4 entries in week 2
        for d in ["2026-01-05", "2026-01-06", "2026-01-07"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})
        for d in ["2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 1, 15)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["total_entries"] == 7
        assert result["expected_entries"] == 10  # 2 weeks * 5/week
        assert result["completion_pct"] == 70  # 7/10 * 100

    def test_no_entries_returns_zeros(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, target_per_week=5)

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["total_entries"] == 0
        assert result["completion_pct"] == 0
        assert result["current_streak"] == 0
        assert result["longest_streak"] == 0
        assert result["rolling_7_day_avg"] == 0.0

    def test_completion_pct_capped_at_100(self):
        conn = _fresh_conn()
        # target 3/week but log every day for 2 weeks
        _setup_sprint_and_habit(conn, target_per_week=3)
        current = date(2026, 1, 5)
        end = date(2026, 1, 18)
        while current <= end:
            engine.log_date(conn, {"habit_id": "reading", "date": current.isoformat()})
            current += timedelta(days=1)

        with _fake_today(date(2026, 1, 18)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["completion_pct"] == 100


class TestHabitNotFound:
    def test_raises_for_missing_habit(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn)
        import pytest
        with pytest.raises(ValueError, match="Habit not found"):
            reporting.habit_report(conn, {"habit_id": "nonexistent"})


class TestPeriodSupport:
    def test_current_sprint_period(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-05", sprint_end="2026-01-18")

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {
                "habit_id": "reading",
                "period": "current_sprint",
            })

        assert result["period"] == "current_sprint"
        assert result["start_date"] == "2026-01-05"
        assert result["end_date"] == "2026-01-18"

    def test_specific_sprint_id(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-05", sprint_end="2026-01-18")
        # The auto-generated sprint_id will be "2026-S01"

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {
                "habit_id": "reading",
                "sprint_id": "2026-S01",
            })

        assert result["period"] == "2026-S01"
        assert result["start_date"] == "2026-01-05"
        assert result["end_date"] == "2026-01-18"

    def test_sprint_id_not_found(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn)
        import pytest
        with pytest.raises(ValueError, match="Sprint not found"):
            reporting.habit_report(conn, {
                "habit_id": "reading",
                "sprint_id": "nonexistent",
            })

    def test_no_active_sprint_raises(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn)
        # Archive the sprint
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        import pytest
        with pytest.raises(ValueError, match="No active sprint found"):
            reporting.habit_report(conn, {"habit_id": "reading"})

    def test_last_4_weeks_period(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-01", sprint_end="2026-12-31")

        # "today" is Thursday 2026-03-05 => current Monday is 2026-03-02
        # last_4_weeks: start = 2026-03-02 - 3 weeks = 2026-02-09, end = 2026-03-08
        with _fake_today(date(2026, 3, 5)):
            result = reporting.habit_report(conn, {
                "habit_id": "reading",
                "period": "last_4_weeks",
            })

        assert result["period"] == "last_4_weeks"
        assert result["start_date"] == "2026-02-09"
        assert result["end_date"] == "2026-03-08"
        assert len(result["weekly_history"]) == 4

    def test_last_8_weeks_period(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-01", sprint_end="2026-12-31")

        with _fake_today(date(2026, 3, 5)):
            result = reporting.habit_report(conn, {
                "habit_id": "reading",
                "period": "last_8_weeks",
            })

        assert result["period"] == "last_8_weeks"
        assert len(result["weekly_history"]) == 8


class TestWeeklyHistory:
    def test_weekly_history_structure(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, target_per_week=5,
                                sprint_start="2026-01-05", sprint_end="2026-01-18")
        # Log entries in week 1 only
        for d in ["2026-01-05", "2026-01-06", "2026-01-07"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 1, 15)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert len(result["weekly_history"]) == 2
        week1 = result["weekly_history"][0]
        assert week1["week_start"] == "2026-01-05"
        assert week1["actual"] == 3
        assert week1["target"] == 5
        assert week1["completion_pct"] == 60

        week2 = result["weekly_history"][1]
        assert week2["week_start"] == "2026-01-12"
        assert week2["actual"] == 0
        assert week2["target"] == 5
        assert week2["completion_pct"] == 0

    def test_weekly_completion_pct_capped_at_100(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, target_per_week=3,
                                sprint_start="2026-01-05", sprint_end="2026-01-11")
        # Log all 7 days but target is 3
        for i in range(7):
            d = date(2026, 1, 5) + timedelta(days=i)
            engine.log_date(conn, {"habit_id": "reading", "date": d.isoformat()})

        with _fake_today(date(2026, 1, 11)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["weekly_history"][0]["completion_pct"] == 100


class TestRolling7DayAvg:
    def test_rolling_avg_with_entries(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-01", sprint_end="2026-12-31")
        # Log 5 of the last 7 days (today=2026-01-10, range: 2026-01-04 to 2026-01-10)
        for d in ["2026-01-04", "2026-01-05", "2026-01-07", "2026-01-09", "2026-01-10"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["rolling_7_day_avg"] == round(5 / 7, 2)

    def test_rolling_avg_zero_when_no_recent_entries(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-01", sprint_end="2026-12-31")
        # Log entries outside the 7-day window
        engine.log_date(conn, {"habit_id": "reading", "date": "2026-01-01"})

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["rolling_7_day_avg"] == 0.0

    def test_rolling_avg_perfect_week(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-01", sprint_end="2026-12-31")
        # Log all 7 days
        for i in range(7):
            d = date(2026, 1, 4) + timedelta(days=i)
            engine.log_date(conn, {"habit_id": "reading", "date": d.isoformat()})

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["rolling_7_day_avg"] == 1.0


class TestTrendVsPriorPeriod:
    def test_positive_trend(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, target_per_week=7,
                                sprint_start="2026-01-12", sprint_end="2026-01-18")
        # Sprint is 1 week: 2026-01-12 (Mon) to 2026-01-18 (Sun)
        # Prior period: 2026-01-05 to 2026-01-11
        # Log 2 entries in prior period
        for d in ["2026-01-05", "2026-01-06"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})
        # Log 5 entries in current period
        for d in ["2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 1, 16)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        # current: 5/7 = 71%, prior: 2/7 = 28%, delta = +43%
        assert result["trend_vs_prior_period"] == "+43%"

    def test_negative_trend(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, target_per_week=7,
                                sprint_start="2026-01-12", sprint_end="2026-01-18")
        # Log 5 in prior, 2 in current
        for d in ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})
        for d in ["2026-01-12", "2026-01-13"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 1, 16)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        # current: 2/7 = 28%, prior: 5/7 = 71%, delta = -43%
        assert result["trend_vs_prior_period"] == "-43%"

    def test_zero_trend_when_equal(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, target_per_week=7,
                                sprint_start="2026-01-12", sprint_end="2026-01-18")
        # Same entries in both periods
        for d in ["2026-01-05", "2026-01-06", "2026-01-07"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})
        for d in ["2026-01-12", "2026-01-13", "2026-01-14"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 1, 16)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["trend_vs_prior_period"] == "+0%"

    def test_trend_with_no_prior_data(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, target_per_week=7,
                                sprint_start="2026-01-12", sprint_end="2026-01-18")
        # Only current period entries
        for d in ["2026-01-12", "2026-01-13", "2026-01-14"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 1, 16)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        # current: 3/7 = 42%, prior: 0%, delta = +42%
        assert result["trend_vs_prior_period"] == "+42%"


class TestStreaks:
    def test_streak_ending_today(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-01", sprint_end="2026-12-31")
        for d in ["2026-01-08", "2026-01-09", "2026-01-10"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["current_streak"] == 3

    def test_longest_streak_in_past(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-01", sprint_end="2026-12-31")
        # Old 5-day streak
        for d in ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})
        # Current 2-day streak
        for d in ["2026-01-09", "2026-01-10"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["current_streak"] == 2
        assert result["longest_streak"] == 5

    def test_no_streak_when_broken(self):
        conn = _fresh_conn()
        _setup_sprint_and_habit(conn, sprint_start="2026-01-01", sprint_end="2026-12-31")
        # Entry 3 days ago only
        engine.log_date(conn, {"habit_id": "reading", "date": "2026-01-07"})

        with _fake_today(date(2026, 1, 10)):
            result = reporting.habit_report(conn, {"habit_id": "reading"})

        assert result["current_streak"] == 0
