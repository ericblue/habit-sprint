"""Tests for weekly_completion reporting function."""

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


def _setup_habit(conn, habit_id="reading", target_per_week=5):
    """Create a sprint and habit for testing."""
    engine.create_sprint(conn, {
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
    })
    return engine.create_habit(conn, {
        "id": habit_id,
        "name": "Reading",
        "category": "cognitive",
        "target_per_week": target_per_week,
    })


def _fake_today(d):
    """Return a patcher that makes date.today() return d in the reporting module."""
    # We need to patch date in the reporting module's namespace
    class FakeDate(date):
        @classmethod
        def today(cls):
            return d

        @classmethod
        def fromisoformat(cls, s):
            return date.fromisoformat(s)

    return patch("habit_sprint.reporting.date", FakeDate)


class TestBasicCompletion:
    def test_completion_with_entries(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=5)
        # Log 3 days in the week of 2026-03-02 (Mon) to 2026-03-08 (Sun)
        for d in ["2026-03-02", "2026-03-04", "2026-03-06"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["actual_days"] == 3
        assert result["target_per_week"] == 5
        assert result["completion_pct"] == 60  # 3/5 * 100 = 60
        assert result["week_start"] == "2026-03-02"
        assert result["week_end"] == "2026-03-08"

    def test_full_completion_capped_at_100(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=3)
        # Log 5 days in the week — exceeds target of 3
        for d in ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 3, 6)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["actual_days"] == 5
        assert result["completion_pct"] == 100  # capped

    def test_zero_value_entries_not_counted(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=5)
        engine.log_date(conn, {"habit_id": "reading", "date": "2026-03-02", "value": 0})
        engine.log_date(conn, {"habit_id": "reading", "date": "2026-03-03", "value": 1})

        with _fake_today(date(2026, 3, 3)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["actual_days"] == 1


class TestCommitmentMet:
    def test_commitment_met_true(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=3)
        for d in ["2026-03-02", "2026-03-03", "2026-03-04"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["commitment_met"] is True

    def test_commitment_met_false(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=5)
        for d in ["2026-03-02", "2026-03-03"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["commitment_met"] is False


class TestCurrentStreak:
    def test_streak_ending_today(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=7)
        # 3-day streak ending on "today" (2026-03-05)
        for d in ["2026-03-03", "2026-03-04", "2026-03-05"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["current_streak"] == 3

    def test_streak_ending_yesterday(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=7)
        # 2-day streak ending yesterday (2026-03-04), no entry today
        for d in ["2026-03-03", "2026-03-04"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["current_streak"] == 2

    def test_streak_broken_two_days_ago(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=7)
        # Entry only 2 days ago — no entry today or yesterday
        engine.log_date(conn, {"habit_id": "reading", "date": "2026-03-03"})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["current_streak"] == 0


class TestLongestStreak:
    def test_longest_streak_in_past(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=7)
        # Old 4-day streak
        for d in ["2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})
        # Current 2-day streak
        for d in ["2026-03-04", "2026-03-05"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["longest_streak"] == 4
        assert result["current_streak"] == 2

    def test_single_entry_streak(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=7)
        engine.log_date(conn, {"habit_id": "reading", "date": "2026-03-05"})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["longest_streak"] == 1
        assert result["current_streak"] == 1


class TestNoEntries:
    def test_no_entries_returns_zeros(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=5)

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-03-02",
            })

        assert result["actual_days"] == 0
        assert result["completion_pct"] == 0
        assert result["commitment_met"] is False
        assert result["current_streak"] == 0
        assert result["longest_streak"] == 0


class TestWeekStartParameter:
    def test_explicit_week_start(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=5)
        # Entries in week of Feb 23
        for d in ["2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26"]:
            engine.log_date(conn, {"habit_id": "reading", "date": d})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
                "week_start": "2026-02-23",
            })

        assert result["week_start"] == "2026-02-23"
        assert result["week_end"] == "2026-03-01"
        assert result["actual_days"] == 4
        assert result["completion_pct"] == 80

    def test_default_week_start_is_current_monday(self):
        conn = _fresh_conn()
        _setup_habit(conn, target_per_week=5)
        # 2026-03-05 is a Thursday, so Monday = 2026-03-02
        engine.log_date(conn, {"habit_id": "reading", "date": "2026-03-02"})

        with _fake_today(date(2026, 3, 5)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "reading",
            })

        assert result["week_start"] == "2026-03-02"
        assert result["week_end"] == "2026-03-08"
        assert result["actual_days"] == 1

    def test_habit_not_found(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        import pytest
        with pytest.raises(ValueError, match="Habit not found"):
            reporting.weekly_completion(conn, {
                "habit_id": "nonexistent",
                "week_start": "2026-03-02",
            })
