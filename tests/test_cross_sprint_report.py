"""Tests for the cross_sprint_report reporting function."""

import tempfile
import os
from datetime import date
from unittest.mock import patch

from habit_sprint.db import get_connection
from habit_sprint import engine, reporting
from habit_sprint.executor import execute
from habit_sprint.formatters import format_cross_sprint_report


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


class TestCrossSprintReportBasic:
    """Test basic cross_sprint_report behavior."""

    def test_empty_no_sprints(self):
        conn = _fresh_conn()
        result = reporting.cross_sprint_report(conn, {})
        assert result["sprints"] == []
        assert result["overall_trend"] == "stable"

    def test_single_sprint(self):
        conn = _fresh_conn()
        s1 = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        _create_habit(conn, "running", "Running", weight=1, target_per_week=7)

        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            _log_entry(conn, "running", d)

        result = reporting.cross_sprint_report(conn, {})
        assert len(result["sprints"]) == 1
        assert result["sprints"][0]["sprint_id"] == s1["id"]
        assert result["sprints"][0]["weighted_score"] > 0
        assert result["sprints"][0]["trend_delta"] is None
        assert result["overall_trend"] == "stable"

    def test_multiple_sprints_with_trend(self):
        conn = _fresh_conn()

        # Sprint 1: lower score
        s1 = _create_sprint(conn, start_date="2026-01-01", end_date="2026-01-14")
        _create_habit(conn, "running", "Running", weight=1, target_per_week=7)

        # Log 3/14 for sprint 1
        for d in ["2026-01-01", "2026-01-02", "2026-01-03"]:
            _log_entry(conn, "running", d)
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})

        # Sprint 2: higher score
        s2 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        # Log 10/14 for sprint 2
        for d in ["2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04",
                   "2026-02-05", "2026-02-06", "2026-02-07", "2026-02-08",
                   "2026-02-09", "2026-02-10"]:
            _log_entry(conn, "running", d)
        engine.archive_sprint(conn, {"sprint_id": s2["id"]})

        # Sprint 3: even higher
        s3 = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06", "2026-03-07", "2026-03-08",
                   "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12"]:
            _log_entry(conn, "running", d)

        result = reporting.cross_sprint_report(conn, {})

        assert len(result["sprints"]) == 3
        assert result["overall_trend"] == "improving"

        # First sprint has no trend_delta
        assert result["sprints"][0]["trend_delta"] is None
        # Subsequent sprints have deltas
        assert result["sprints"][1]["trend_delta"] is not None
        assert result["sprints"][2]["trend_delta"] is not None

        # Scores should be ascending
        scores = [s["weighted_score"] for s in result["sprints"]]
        assert scores == sorted(scores)

    def test_declining_trend(self):
        conn = _fresh_conn()

        s1 = _create_sprint(conn, start_date="2026-01-01", end_date="2026-01-14")
        _create_habit(conn, "running", "Running", weight=1, target_per_week=7)

        # Sprint 1: high score (12/14)
        for d in ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
                   "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
                   "2026-01-09", "2026-01-10", "2026-01-11", "2026-01-12"]:
            _log_entry(conn, "running", d)
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})

        # Sprint 2: low score (2/14)
        s2 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        for d in ["2026-02-01", "2026-02-02"]:
            _log_entry(conn, "running", d)

        result = reporting.cross_sprint_report(conn, {})
        assert result["overall_trend"] == "declining"
        assert result["sprints"][1]["trend_delta"] < 0


class TestCrossSprintReportPayload:
    """Test limit and habit_id payload options."""

    def test_limit_restricts_sprints(self):
        conn = _fresh_conn()

        # Create 3 sprints
        s1 = _create_sprint(conn, start_date="2026-01-01", end_date="2026-01-14")
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})
        s2 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        engine.archive_sprint(conn, {"sprint_id": s2["id"]})
        s3 = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        result = reporting.cross_sprint_report(conn, {"limit": 2})
        assert len(result["sprints"]) == 2
        # Should be the 2 most recent
        assert result["sprints"][0]["sprint_id"] == s2["id"]
        assert result["sprints"][1]["sprint_id"] == s3["id"]

    def test_habit_id_filters_to_one_habit(self):
        conn = _fresh_conn()
        s1 = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        _create_habit(conn, "running", "Running", category="health",
                      weight=2, target_per_week=5)
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      weight=1, target_per_week=5)

        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            _log_entry(conn, "running", d)
            _log_entry(conn, "reading", d)

        result = reporting.cross_sprint_report(conn, {"habit_id": "running"})

        sprint_data = result["sprints"][0]
        assert len(sprint_data["habit_completions"]) == 1
        assert sprint_data["habit_completions"][0]["habit_id"] == "running"
        # Only health category should appear
        assert len(sprint_data["category_scores"]) == 1
        assert sprint_data["category_scores"][0]["category"] == "health"

    def test_invalid_habit_id_raises(self):
        conn = _fresh_conn()
        import pytest
        with pytest.raises(ValueError, match="Habit not found"):
            reporting.cross_sprint_report(conn, {"habit_id": "nonexistent"})


class TestCrossSprintReportScores:
    """Test score calculations."""

    def test_weighted_and_unweighted_scores(self):
        conn = _fresh_conn()
        s1 = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        # running: weight=2, target=3/week -> 6 expected over 2 weeks
        _create_habit(conn, "running", "Running", category="health",
                      weight=2, target_per_week=3)
        # reading: weight=1, target=5/week -> 10 expected
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      weight=1, target_per_week=5)

        # 4 running entries
        for d in ["2026-03-02", "2026-03-04", "2026-03-06", "2026-03-08"]:
            _log_entry(conn, "running", d)
        # 7 reading entries
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06", "2026-03-07"]:
            _log_entry(conn, "reading", d)

        result = reporting.cross_sprint_report(conn, {})
        s = result["sprints"][0]

        # weighted = (4*2 + 7*1) / (6*2 + 10*1) = 15/22 = 68%
        assert s["weighted_score"] == 68
        # unweighted = (4+7) / (6+10) = 11/16 = 69%
        assert s["unweighted_score"] == 69

    def test_per_category_scores(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=7)
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      weight=1, target_per_week=7)

        # 7/14 for running, 14/14 for reading
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06", "2026-03-07"]:
            _log_entry(conn, "running", d)
            _log_entry(conn, "reading", d)
        for d in ["2026-03-08", "2026-03-09", "2026-03-10", "2026-03-11",
                   "2026-03-12", "2026-03-13", "2026-03-14"]:
            _log_entry(conn, "reading", d)

        result = reporting.cross_sprint_report(conn, {})
        cats = {c["category"]: c for c in result["sprints"][0]["category_scores"]}
        assert cats["health"]["weighted_score"] == 50
        assert cats["cognitive"]["weighted_score"] == 100

    def test_habit_completions(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        _create_habit(conn, "running", "Running", target_per_week=3)

        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            _log_entry(conn, "running", d)

        result = reporting.cross_sprint_report(conn, {})
        hc = result["sprints"][0]["habit_completions"][0]
        assert hc["habit_id"] == "running"
        assert hc["actual"] == 3
        assert hc["target"] == 3
        assert hc["completion_pct"] == 100


class TestCrossSprintReportTrendDeltas:
    """Test trend delta calculations between consecutive sprints."""

    def test_trend_delta_positive(self):
        conn = _fresh_conn()

        s1 = _create_sprint(conn, start_date="2026-01-01", end_date="2026-01-14")
        _create_habit(conn, "running", "Running", weight=1, target_per_week=7)

        # Sprint 1: 50%
        for d in ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
                   "2026-01-05", "2026-01-06", "2026-01-07"]:
            _log_entry(conn, "running", d)
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})

        # Sprint 2: ~71%
        s2 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        for d in ["2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04",
                   "2026-02-05", "2026-02-06", "2026-02-07", "2026-02-08",
                   "2026-02-09", "2026-02-10"]:
            _log_entry(conn, "running", d)

        result = reporting.cross_sprint_report(conn, {})
        assert result["sprints"][1]["trend_delta"] == 21  # 71 - 50

    def test_trend_delta_negative(self):
        conn = _fresh_conn()

        s1 = _create_sprint(conn, start_date="2026-01-01", end_date="2026-01-14")
        _create_habit(conn, "running", "Running", weight=1, target_per_week=7)

        # Sprint 1: ~71%
        for d in ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
                   "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
                   "2026-01-09", "2026-01-10"]:
            _log_entry(conn, "running", d)
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})

        # Sprint 2: 50%
        s2 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        for d in ["2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04",
                   "2026-02-05", "2026-02-06", "2026-02-07"]:
            _log_entry(conn, "running", d)

        result = reporting.cross_sprint_report(conn, {})
        assert result["sprints"][1]["trend_delta"] == -21  # 50 - 71


class TestCrossSprintReportViaExecutor:
    """Test cross_sprint_report through the executor."""

    def test_executor_routing(self):
        conn, db_path = _fresh_db()
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        conn.close()

        result = execute({"action": "cross_sprint_report", "payload": {}}, db_path)
        assert result["status"] == "success"
        assert "sprints" in result["data"]
        assert "overall_trend" in result["data"]

    def test_executor_with_limit(self):
        conn, db_path = _fresh_db()
        s1 = _create_sprint(conn, start_date="2026-01-01", end_date="2026-01-14")
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})
        s2 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        engine.archive_sprint(conn, {"sprint_id": s2["id"]})
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        conn.close()

        result = execute(
            {"action": "cross_sprint_report", "payload": {"limit": 2}}, db_path
        )
        assert result["status"] == "success"
        assert len(result["data"]["sprints"]) == 2

    def test_executor_validation_rejects_bad_limit(self):
        conn, db_path = _fresh_db()
        conn.close()

        result = execute(
            {"action": "cross_sprint_report", "payload": {"limit": 0}}, db_path
        )
        assert result["status"] == "error"
        assert "limit" in result["error"]

    def test_executor_validation_rejects_unknown_field(self):
        conn, db_path = _fresh_db()
        conn.close()

        result = execute(
            {"action": "cross_sprint_report", "payload": {"bogus": "x"}}, db_path
        )
        assert result["status"] == "error"
        assert "Unknown field" in result["error"]


class TestCrossSprintReportFormatter:
    """Test the markdown formatter."""

    def test_format_empty(self):
        data = {"sprints": [], "overall_trend": "stable"}
        output = format_cross_sprint_report(data)
        assert "CROSS-SPRINT REPORT" in output
        assert "0 sprints" in output
        assert "No sprints found" in output

    def test_format_with_sprints(self):
        data = {
            "sprints": [
                {
                    "sprint_id": "2026-S01",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-14",
                    "theme": "Focus",
                    "status": "archived",
                    "weighted_score": 50,
                    "unweighted_score": 48,
                    "category_scores": [
                        {"category": "health", "weighted_score": 55},
                    ],
                    "habit_completions": [
                        {"habit_id": "running", "name": "Running",
                         "actual": 7, "target": 14, "completion_pct": 50},
                    ],
                    "trend_delta": None,
                },
                {
                    "sprint_id": "2026-S02",
                    "start_date": "2026-02-01",
                    "end_date": "2026-02-14",
                    "theme": "Growth",
                    "status": "active",
                    "weighted_score": 75,
                    "unweighted_score": 72,
                    "category_scores": [
                        {"category": "health", "weighted_score": 80},
                    ],
                    "habit_completions": [
                        {"habit_id": "running", "name": "Running",
                         "actual": 10, "target": 14, "completion_pct": 71},
                    ],
                    "trend_delta": 25,
                },
            ],
            "overall_trend": "improving",
        }

        output = format_cross_sprint_report(data)
        assert "2 sprints" in output
        assert "improving" in output
        assert "2026-S01" in output
        assert "2026-S02" in output
        assert "50%" in output
        assert "75%" in output
        assert "+25%" in output
        assert "Running" in output
        assert "health" in output
