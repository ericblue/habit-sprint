"""Tests for the streak_leaderboard and progress_summary actions."""

import tempfile
import os
from datetime import date, timedelta
from unittest.mock import patch

from habit_sprint.db import get_connection
from habit_sprint import engine, reporting
from habit_sprint.executor import execute
from habit_sprint.formatters import format_progress_summary


def _fresh_db():
    """Return (conn, db_path) for a fresh temporary database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = get_connection(path)
    return conn, path


def _fresh_conn():
    conn, _ = _fresh_db()
    return conn


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


# ---------------------------------------------------------------------------
# streak_leaderboard
# ---------------------------------------------------------------------------

class TestStreakLeaderboard:

    def test_no_habits(self):
        conn = _fresh_conn()
        _create_sprint(conn)
        result = reporting.streak_leaderboard(conn, {})
        assert result["habits"] == []

    def test_single_habit_no_entries(self):
        conn = _fresh_conn()
        _create_sprint(conn)
        _create_habit(conn, "run", "Running")
        result = reporting.streak_leaderboard(conn, {})
        assert len(result["habits"]) == 1
        h = result["habits"][0]
        assert h["habit_id"] == "run"
        assert h["current_streak"] == 0
        assert h["longest_streak"] == 0
        assert h["total_checkins"] == 0

    @patch("habit_sprint.reporting.date")
    def test_streaks_computed_correctly(self, mock_date):
        mock_date.today.return_value = date(2026, 3, 5)
        mock_date.fromisoformat = date.fromisoformat
        conn = _fresh_conn()
        _create_sprint(conn)
        _create_habit(conn, "run", "Running")
        _create_habit(conn, "read", "Reading")

        # Running: 3-day streak ending today
        for d in ["2026-03-03", "2026-03-04", "2026-03-05"]:
            _log_entry(conn, "run", d)

        # Reading: 5 entries but gap, no current streak
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-06", "2026-03-07"]:
            _log_entry(conn, "read", d)

        result = reporting.streak_leaderboard(conn, {})
        habits = result["habits"]
        assert len(habits) == 2
        # Running should be first (current_streak=3)
        assert habits[0]["habit_id"] == "run"
        assert habits[0]["current_streak"] == 3
        assert habits[0]["longest_streak"] == 3
        assert habits[0]["total_checkins"] == 3

        # Reading: no current streak (gap before today)
        assert habits[1]["habit_id"] == "read"
        assert habits[1]["current_streak"] == 0
        assert habits[1]["total_checkins"] == 5

    def test_sorted_by_current_streak(self):
        conn = _fresh_conn()
        _create_sprint(conn)
        _create_habit(conn, "a", "Habit A")
        _create_habit(conn, "b", "Habit B")
        _create_habit(conn, "c", "Habit C")

        today = date.today()
        # B: 5-day streak
        for i in range(5):
            _log_entry(conn, "b", (today - timedelta(days=i)).isoformat())
        # A: 2-day streak
        for i in range(2):
            _log_entry(conn, "a", (today - timedelta(days=i)).isoformat())
        # C: no streak

        result = reporting.streak_leaderboard(conn, {})
        assert result["habits"][0]["habit_id"] == "b"
        assert result["habits"][1]["habit_id"] == "a"
        assert result["habits"][2]["habit_id"] == "c"

    def test_via_executor(self):
        conn, db_path = _fresh_db()
        _create_sprint(conn)
        _create_habit(conn, "run", "Running")
        conn.close()

        result = execute({"action": "streak_leaderboard", "payload": {}}, db_path)
        assert result["status"] == "success"
        assert "habits" in result["data"]

    def test_no_active_sprint_error(self):
        conn = _fresh_conn()
        try:
            reporting.streak_leaderboard(conn, {})
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "No active sprint" in str(e)

    def test_specific_sprint_id(self):
        conn = _fresh_conn()
        s1 = _create_sprint(conn, start_date="2026-01-01", end_date="2026-01-14")
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})
        s2 = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        _create_habit(conn, "run", "Running")

        result = reporting.streak_leaderboard(conn, {"sprint_id": s1["id"]})
        assert result["sprint_id"] == s1["id"]


# ---------------------------------------------------------------------------
# progress_summary
# ---------------------------------------------------------------------------

class TestProgressSummary:

    def test_basic_summary(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        _create_habit(conn, "run", "Running", category="health", weight=2, target_per_week=5)
        _create_habit(conn, "read", "Reading", category="growth", weight=1, target_per_week=3)

        # Log some entries
        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            _log_entry(conn, "run", d)
        _log_entry(conn, "read", "2026-03-01")

        result = reporting.progress_summary(conn, {})
        assert "overall_score" in result
        assert "overall_trend" in result
        assert len(result["strongest_habits"]) <= 3
        assert len(result["weakest_habits"]) <= 3
        assert "category_balance" in result
        assert "active_streaks" in result
        assert "recommendations" in result

    def test_strongest_weakest_ordering(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        _create_habit(conn, "a", "Habit A", target_per_week=7)
        _create_habit(conn, "b", "Habit B", target_per_week=7)

        # A: high completion, B: low
        for i in range(10):
            _log_entry(conn, "a", f"2026-03-{i+1:02d}")
        _log_entry(conn, "b", "2026-03-01")

        result = reporting.progress_summary(conn, {})
        # A should be strongest
        assert result["strongest_habits"][0]["habit_id"] == "a"
        # B should be weakest
        assert result["weakest_habits"][0]["habit_id"] == "b"

    def test_category_balance(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        _create_habit(conn, "run", "Running", category="health", target_per_week=5)
        _create_habit(conn, "read", "Reading", category="growth", target_per_week=5)

        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]:
            _log_entry(conn, "run", d)

        result = reporting.progress_summary(conn, {})
        cats = {c["category"]: c["weighted_score"] for c in result["category_balance"]}
        assert cats["health"] > cats["growth"]

    def test_recommendations_weak_habit(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        _create_habit(conn, "run", "Running", target_per_week=7)
        # No entries → 0% completion

        result = reporting.progress_summary(conn, {})
        assert any("Running" in r for r in result["recommendations"])

    def test_via_executor(self):
        conn, db_path = _fresh_db()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        _create_habit(conn, "run", "Running")
        conn.close()

        result = execute({"action": "progress_summary", "payload": {}}, db_path)
        assert result["status"] == "success"
        assert "strongest_habits" in result["data"]

    def test_no_active_sprint_error(self):
        conn = _fresh_conn()
        try:
            reporting.progress_summary(conn, {})
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "No active sprint" in str(e)


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

class TestProgressSummaryFormatter:

    def test_format_output(self):
        data = {
            "sprint_id": "test-sprint",
            "overall_score": 72,
            "overall_trend": "improving",
            "strongest_habits": [
                {"habit_id": "run", "name": "Running", "completion_pct": 90},
            ],
            "weakest_habits": [
                {"habit_id": "read", "name": "Reading", "completion_pct": 20},
            ],
            "category_balance": [
                {"category": "health", "weighted_score": 80},
                {"category": "growth", "weighted_score": 40},
            ],
            "active_streaks": [
                {"habit_id": "run", "name": "Running", "current_streak": 5},
            ],
            "recommendations": [
                "Focus on Reading.",
            ],
        }

        output = format_progress_summary(data)
        assert "PROGRESS SUMMARY" in output
        assert "72%" in output
        assert "improving" in output
        assert "Running" in output
        assert "Reading" in output
        assert "health" in output
        assert "5 days" in output
        assert "RECOMMENDATIONS" in output
        assert "Focus on Reading." in output

    def test_format_empty_data(self):
        data = {
            "sprint_id": "test",
            "overall_score": 0,
            "overall_trend": "stable",
            "strongest_habits": [],
            "weakest_habits": [],
            "category_balance": [],
            "active_streaks": [],
            "recommendations": [],
        }
        output = format_progress_summary(data)
        assert "PROGRESS SUMMARY" in output
        assert "(none)" in output


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:

    def test_streak_leaderboard_valid_payload(self):
        conn, db_path = _fresh_db()
        _create_sprint(conn)
        conn.close()

        result = execute(
            {"action": "streak_leaderboard", "payload": {"sprint_id": "anything"}},
            db_path,
        )
        # Sprint not found is a runtime error, not a validation error
        assert result["status"] == "error"
        assert "Sprint not found" in result["error"]

    def test_streak_leaderboard_unknown_field(self):
        conn, db_path = _fresh_db()
        conn.close()

        result = execute(
            {"action": "streak_leaderboard", "payload": {"bad_field": "x"}},
            db_path,
        )
        assert result["status"] == "error"
        assert "Unknown field" in result["error"]

    def test_progress_summary_valid_payload(self):
        conn, db_path = _fresh_db()
        _create_sprint(conn)
        conn.close()

        result = execute({"action": "progress_summary", "payload": {}}, db_path)
        assert result["status"] == "success"

    def test_progress_summary_unknown_field(self):
        conn, db_path = _fresh_db()
        conn.close()

        result = execute(
            {"action": "progress_summary", "payload": {"invalid": True}},
            db_path,
        )
        assert result["status"] == "error"
        assert "Unknown field" in result["error"]


# ---------------------------------------------------------------------------
# Web API
# ---------------------------------------------------------------------------

class TestWebAPI:

    def _get_client(self):
        from habit_sprint.web import create_app
        from fastapi.testclient import TestClient
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        # Initialize DB
        get_connection(path)
        app = create_app(db_path=path)
        return TestClient(app), path

    def test_streak_leaderboard_endpoint(self):
        client, db_path = self._get_client()
        conn = get_connection(db_path)
        _create_sprint(conn)
        _create_habit(conn, "run", "Running")
        conn.close()

        resp = client.get("/api/streak-leaderboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "habits" in data["data"]

    def test_progress_summary_endpoint(self):
        client, db_path = self._get_client()
        conn = get_connection(db_path)
        _create_sprint(conn)
        _create_habit(conn, "run", "Running")
        conn.close()

        resp = client.get("/api/progress-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "strongest_habits" in data["data"]

    def test_streaks_tab_renders(self):
        client, db_path = self._get_client()
        conn = get_connection(db_path)
        _create_sprint(conn)
        conn.close()

        resp = client.get("/reports?tab=streaks")
        assert resp.status_code == 200
        assert "Streak Leaderboard" in resp.text
        assert "streak-leaderboard" in resp.text
