"""Tests for the category_report reporting function."""

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


class TestCategoryReportBasic:
    """Test basic category_report structure and sprint resolution."""

    def test_defaults_to_active_sprint(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sprint["id"])

        with _fake_today(date(2026, 3, 8)):
            result = reporting.category_report(conn, {})

        assert result["sprint_id"] == sprint["id"]

    def test_explicit_sprint_id(self):
        conn = _fresh_conn()
        s1 = _create_sprint(conn, start_date="2026-02-01", end_date="2026-02-14")
        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=s1["id"])
        engine.archive_sprint(conn, {"sprint_id": s1["id"]})
        _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")

        with _fake_today(date(2026, 3, 8)):
            result = reporting.category_report(conn, {"sprint_id": s1["id"]})

        assert result["sprint_id"] == s1["id"]

    def test_invalid_sprint_id_raises(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError, match="Sprint not found"):
            reporting.category_report(conn, {"sprint_id": "bogus"})

    def test_no_active_sprint_raises(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError, match="No active sprint found"):
            reporting.category_report(conn, {})

    def test_no_habits_returns_empty(self):
        conn = _fresh_conn()
        _create_sprint(conn)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.category_report(conn, {})

        assert result["categories"] == []
        assert result["balance_assessment"]["most_adherent"] is None
        assert result["balance_assessment"]["least_adherent"] is None
        assert result["balance_assessment"]["spread"] == 0


class TestCategoryReportPerCategory:
    """Test per-category fields: habits_count, weighted_score, unweighted_score, habit_ids."""

    def test_per_category_fields(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        # health: 2 habits
        _create_habit(conn, "running", "Running", category="health",
                      weight=2, target_per_week=3, sprint_id=sid)
        _create_habit(conn, "yoga", "Yoga", category="health",
                      weight=1, target_per_week=3, sprint_id=sid)
        # cognitive: 1 habit
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
            result = reporting.category_report(conn, {})

        cats = {c["category"]: c for c in result["categories"]}

        # health
        assert cats["health"]["habits_count"] == 2
        assert set(cats["health"]["habit_ids"]) == {"running", "yoga"}
        # weighted: (3*2 + 2*1) / (6*2 + 6*1) = 8/18 = 44%
        assert cats["health"]["weighted_score"] == 44
        # unweighted: (3 + 2) / (6 + 6) = 5/12 = 42%
        assert cats["health"]["unweighted_score"] == 42

        # cognitive
        assert cats["cognitive"]["habits_count"] == 1
        assert cats["cognitive"]["habit_ids"] == ["reading"]
        # weighted: (3*1) / (10*1) = 30%
        assert cats["cognitive"]["weighted_score"] == 30
        # unweighted: 3/10 = 30%
        assert cats["cognitive"]["unweighted_score"] == 30

    def test_no_entries_gives_zero_scores(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", category="health",
                      weight=2, target_per_week=5, sprint_id=sprint["id"])

        with _fake_today(date(2026, 3, 8)):
            result = reporting.category_report(conn, {})

        assert len(result["categories"]) == 1
        cat = result["categories"][0]
        assert cat["weighted_score"] == 0
        assert cat["unweighted_score"] == 0
        assert cat["habits_count"] == 1
        assert cat["habit_ids"] == ["running"]

    def test_perfect_score(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=3, sprint_id=sid)

        for d in ["2026-03-01", "2026-03-03", "2026-03-05"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 7)):
            result = reporting.category_report(conn, {})

        assert result["categories"][0]["weighted_score"] == 100
        assert result["categories"][0]["unweighted_score"] == 100


class TestCategoryReportCategoryFilter:
    """Test optional category filter."""

    def test_filter_by_category(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sid)
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      sprint_id=sid)

        with _fake_today(date(2026, 3, 8)):
            result = reporting.category_report(conn, {"category": "health"})

        assert len(result["categories"]) == 1
        assert result["categories"][0]["category"] == "health"

    def test_filter_nonexistent_category_returns_empty(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sprint["id"])

        with _fake_today(date(2026, 3, 8)):
            result = reporting.category_report(conn, {"category": "nonexistent"})

        assert result["categories"] == []


class TestCategoryReportBalanceAssessment:
    """Test balance_assessment: most_adherent, least_adherent, spread."""

    def test_balance_with_multiple_categories(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-14")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=5, sprint_id=sid)
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      weight=1, target_per_week=5, sprint_id=sid)
        _create_habit(conn, "painting", "Painting", category="creative",
                      weight=1, target_per_week=5, sprint_id=sid)

        # health: 8 of 10 = 80%
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06", "2026-03-07", "2026-03-08"]:
            _log_entry(conn, "running", d)
        # cognitive: 5 of 10 = 50%
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05"]:
            _log_entry(conn, "reading", d)
        # creative: 2 of 10 = 20%
        for d in ["2026-03-01", "2026-03-02"]:
            _log_entry(conn, "painting", d)

        with _fake_today(date(2026, 3, 10)):
            result = reporting.category_report(conn, {})

        ba = result["balance_assessment"]
        assert ba["most_adherent"] == "health"
        assert ba["least_adherent"] == "creative"
        assert ba["spread"] == 60  # 80 - 20

    def test_balance_single_category(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sprint["id"])

        with _fake_today(date(2026, 3, 8)):
            result = reporting.category_report(conn, {})

        ba = result["balance_assessment"]
        assert ba["most_adherent"] == "health"
        assert ba["least_adherent"] == "health"
        assert ba["spread"] == 0

    def test_balance_equal_categories(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=1, target_per_week=5, sprint_id=sid)
        _create_habit(conn, "reading", "Reading", category="cognitive",
                      weight=1, target_per_week=5, sprint_id=sid)

        # Both: 3 of 5 = 60%
        for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
            _log_entry(conn, "running", d)
            _log_entry(conn, "reading", d)

        with _fake_today(date(2026, 3, 7)):
            result = reporting.category_report(conn, {})

        ba = result["balance_assessment"]
        assert ba["spread"] == 0


class TestCategoryReportSingleHabitCategory:
    """Test categories with a single habit."""

    def test_single_habit_category_scores(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      weight=3, target_per_week=5, sprint_id=sid)

        for d in ["2026-03-01", "2026-03-03", "2026-03-05"]:
            _log_entry(conn, "running", d)

        with _fake_today(date(2026, 3, 7)):
            result = reporting.category_report(conn, {})

        cat = result["categories"][0]
        assert cat["habits_count"] == 1
        assert cat["habit_ids"] == ["running"]
        # weighted = (3*3)/(5*3) = 9/15 = 60%
        assert cat["weighted_score"] == 60
        # unweighted = 3/5 = 60%
        assert cat["unweighted_score"] == 60


class TestCategoryReportGlobalHabits:
    """Test that global habits (sprint_id IS NULL) are included."""

    def test_includes_global_habits(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)

        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sprint["id"])
        _create_habit(conn, "water", "Drink Water", category="health")

        with _fake_today(date(2026, 3, 8)):
            result = reporting.category_report(conn, {})

        cat = result["categories"][0]
        assert cat["habits_count"] == 2
        assert set(cat["habit_ids"]) == {"running", "water"}


class TestCategoryReportArchivedHabits:
    """Test that archived habits are excluded."""

    def test_excludes_archived_habits(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        sid = sprint["id"]

        _create_habit(conn, "running", "Running", category="health",
                      sprint_id=sid)
        _create_habit(conn, "yoga", "Yoga", category="health",
                      sprint_id=sid)
        engine.archive_habit(conn, {"id": "yoga"})

        with _fake_today(date(2026, 3, 8)):
            result = reporting.category_report(conn, {})

        cat = result["categories"][0]
        assert cat["habits_count"] == 1
        assert cat["habit_ids"] == ["running"]


class TestCategoryReportWeightedVsUnweighted:
    """Test that weighted and unweighted scores differ when weights vary."""

    def test_scores_differ_with_mixed_weights(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-01", end_date="2026-03-07")
        sid = sprint["id"]

        # High-weight habit with low completion
        _create_habit(conn, "running", "Running", category="health",
                      weight=3, target_per_week=5, sprint_id=sid)
        # Low-weight habit with high completion
        _create_habit(conn, "stretch", "Stretch", category="health",
                      weight=1, target_per_week=5, sprint_id=sid)

        # running: 1 of 5
        _log_entry(conn, "running", "2026-03-01")
        # stretch: 4 of 5
        for d in ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"]:
            _log_entry(conn, "stretch", d)

        with _fake_today(date(2026, 3, 7)):
            result = reporting.category_report(conn, {})

        cat = result["categories"][0]
        # weighted = (1*3 + 4*1) / (5*3 + 5*1) = 7/20 = 35%
        assert cat["weighted_score"] == 35
        # unweighted = (1 + 4) / (5 + 5) = 5/10 = 50%
        assert cat["unweighted_score"] == 50
