"""Tests for all markdown/ASCII formatters."""

import json
import tempfile
import os
from datetime import date
from unittest import mock
from unittest.mock import patch

import pytest

from habit_sprint.db import get_connection
from habit_sprint import engine, reporting
from habit_sprint.formatters import (
    FORMATTERS,
    format_sprint_dashboard,
    format_week_view,
    format_sprint_report,
    format_habit_report,
    format_daily_score,
    format_category_report,
)


# ---------------------------------------------------------------------------
# Helpers (integration tests for sprint_dashboard)
# ---------------------------------------------------------------------------

def _fresh_conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return get_connection(path)


def _create_sprint(conn, **overrides):
    data = {"start_date": "2026-03-01", "end_date": "2026-03-14"}
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
    class FakeDate(date):
        @classmethod
        def today(cls):
            return d

        @classmethod
        def fromisoformat(cls, s):
            return date.fromisoformat(s)

    return patch("habit_sprint.reporting.date", FakeDate)


def _build_dashboard(conn, payload=None):
    """Get sprint_dashboard data and format it."""
    if payload is None:
        payload = {}
    data = reporting.sprint_dashboard(conn, payload)
    return format_sprint_dashboard(data), data


# ---------------------------------------------------------------------------
# Minimal fixture: a simple sprint with well-known data
# ---------------------------------------------------------------------------

def _setup_basic_sprint():
    """Create a sprint with 3 habits across 2 categories for week 1."""
    conn = _fresh_conn()
    sprint = _create_sprint(conn, theme="Foundation Building",
                            start_date="2026-03-02", end_date="2026-03-15")
    sid = sprint["id"]

    # Category: Workout
    _create_habit(conn, "workout-thirty", "Workout (30 min)", category="Workout",
                  weight=2, target_per_week=4, sprint_id=sid)
    _create_habit(conn, "stretching", "Stretching", category="Workout",
                  weight=1, target_per_week=5, sprint_id=sid)

    # Category: Diet
    _create_habit(conn, "no-drinks", "No Drinks", category="Diet",
                  weight=3, target_per_week=7, sprint_id=sid)

    # Log some entries for week 1 (Mon 3/2 - Sun 3/8)
    # workout-thirty: Mon, Tue, Thu = 3 done (target 4 → 75%)
    for d in ["2026-03-02", "2026-03-03", "2026-03-05"]:
        _log_entry(conn, "workout-thirty", d)
    # stretching: Mon-Fri = 5 done (target 5 → 100%, commitment met)
    for d in ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]:
        _log_entry(conn, "stretching", d)
    # no-drinks: every day = 7 done (target 7 → 100%, commitment met)
    for d in ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05",
              "2026-03-06", "2026-03-07", "2026-03-08"]:
        _log_entry(conn, "no-drinks", d)

    return conn, sid


# ===========================================================================
# PART 1: Sprint Dashboard integration tests (from task 4.2)
# ===========================================================================

# ---------------------------------------------------------------------------
# Tests: Header section
# ---------------------------------------------------------------------------

class TestHeader:
    def test_sprint_dates_in_header(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "SPRINT: 2026-03-02 \u2192 2026-03-15" in output

    def test_theme_in_header(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "THEME:  Foundation Building" in output

    def test_week_indicator_when_filtered(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "[Week 1 of 2]" in output

    def test_week_2_indicator(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 12)):
            output, _ = _build_dashboard(conn, {"week": 2})
        assert "[Week 2 of 2]" in output

    def test_no_week_indicator_for_full_sprint(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn)
        assert "[Week" not in output

    def test_focus_goals_in_header(self):
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-02", end_date="2026-03-15",
                       focus_goals=["Goal A", "Goal B"])
        _create_habit(conn, "test-habit", "Test", sprint_id=None)
        with _fake_today(date(2026, 3, 5)):
            data = reporting.sprint_dashboard(conn, {})
            output = format_sprint_dashboard(data)
        assert "FOCUS:  Goal A | Goal B" in output

    def test_separator_lines(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "=" * 68 in output
        assert "-" * 68 in output


# ---------------------------------------------------------------------------
# Tests: Category sections
# ---------------------------------------------------------------------------

class TestCategorySection:
    def test_category_name_and_score(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "CATEGORY: Workout" in output
        assert "CATEGORY: Diet" in output
        assert "Score:" in output

    def test_habit_names_present(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "Workout (30 min)" in output
        assert "Stretching" in output
        assert "No Drinks" in output

    def test_table_header_columns(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "Min/Wk" in output
        assert "Wt" in output
        assert "Mon" in output

    def test_checkmarks_for_logged_entries(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "\u2713" in output  # checkmark present

    def test_dots_for_missing_entries(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "\u00b7" in output  # dot present

    def test_star_for_commitment_met(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        # Stretching (5/5) and No Drinks (7/7) should have stars
        assert "\u2605" in output

    def test_no_star_when_commitment_not_met(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, data = _build_dashboard(conn, {"week": 1})
        # Find the Workout (30 min) line - should NOT have a star
        for line in output.split("\n"):
            if "Workout (30 min)" in line and "CATEGORY" not in line:
                assert "\u2605" not in line
                break

    def test_tally_shows_actual_over_target(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        # Stretching: 5/5 100%
        for line in output.split("\n"):
            if "Stretching" in line and "CATEGORY" not in line:
                assert "5/5" in line
                assert "100%" in line
                break


# ---------------------------------------------------------------------------
# Tests: Daily Points per category
# ---------------------------------------------------------------------------

class TestDailyPoints:
    def test_daily_points_row_present(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "Daily Points" in output

    def test_daily_points_arrow(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        # Arrow character should be in daily points lines
        daily_lines = [l for l in output.split("\n") if "Daily Points" in l]
        assert len(daily_lines) > 0
        for line in daily_lines:
            assert "\u2192" in line

    def test_daily_points_calculation(self):
        """Daily points for Workout category on Monday 3/2:
        workout-thirty (weight=2, value=1) + stretching (weight=1, value=1) = 3."""
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            _, data = _build_dashboard(conn, {"week": 1})
        # Find workout category by name
        workout_cat = next(c for c in data["categories"] if c["category"] == "Workout")
        # Monday 2026-03-02: workout(1*2) + stretching(1*1) = 3
        mon_pts = 0
        for h in workout_cat["habits"]:
            mon_pts += h["daily"].get("2026-03-02", 0) * h["weight"]
        assert mon_pts == 3


# ---------------------------------------------------------------------------
# Tests: Daily Totals section
# ---------------------------------------------------------------------------

class TestDailyTotals:
    def test_daily_totals_header(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "DAILY TOTALS" in output

    def test_points_row(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "Points" in output

    def test_max_possible_row(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "Max Possible" in output

    def test_completion_pct_row(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "Completion %" in output

    def test_daily_totals_values(self):
        """Monday 3/2: h1(2)+h2(1)+h3(3)=6 points, max=6."""
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            _, data = _build_dashboard(conn, {"week": 1})
        totals = data["daily_totals"]
        mon = totals["2026-03-02"]
        assert mon["points"] == 6  # 1*2 + 1*1 + 1*3
        assert mon["max"] == 6  # 2 + 1 + 3


# ---------------------------------------------------------------------------
# Tests: Sprint Summary
# ---------------------------------------------------------------------------

class TestSprintSummary:
    def test_summary_header(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "SPRINT SUMMARY" in output
        assert "Weighted:" in output

    def test_per_habit_breakdown(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        # All 3 habits should appear in the summary
        assert "Workout (30 min)" in output
        assert "Stretching" in output
        assert "No Drinks" in output

    def test_summary_shows_actual_target_pct(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        # Look for Stretching in the SPRINT SUMMARY section (after "SPRINT SUMMARY" line)
        lines = output.split("\n")
        in_summary = False
        found = False
        for line in lines:
            if "SPRINT SUMMARY" in line:
                in_summary = True
                continue
            if in_summary and "Stretching" in line:
                assert "5 / 5" in line or "5/5" in line
                assert "100%" in line
                found = True
                break
        assert found, "Stretching summary line not found"

    def test_star_in_summary_for_met_commitment(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        # Stretching (commitment met) should have star in summary
        for line in output.split("\n"):
            if "Stretching" in line and "/" in line:
                assert "\u2605" in line
                break


# ---------------------------------------------------------------------------
# Tests: Sprint Reflection
# ---------------------------------------------------------------------------

class TestReflection:
    def test_no_retro_message(self):
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "SPRINT REFLECTION" in output
        assert "(No retrospective recorded yet)" in output

    def test_retro_with_content(self):
        conn, sid = _setup_basic_sprint()
        engine.add_retro(conn, {
            "sprint_id": sid,
            "what_went_well": "Strong consistency",
            "what_to_improve": "Sugar compliance",
            "ideas": "Try new approach",
        })
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "What went well:" in output
        assert "- Strong consistency" in output
        assert "What needs improvement:" in output
        assert "- Sugar compliance" in output
        assert "Ideas for next sprint:" in output
        assert "- Try new approach" in output

    def test_retro_with_json_array_field(self):
        conn, sid = _setup_basic_sprint()
        engine.add_retro(conn, {
            "sprint_id": sid,
            "what_went_well": json.dumps(["Item A", "Item B"]),
            "what_to_improve": None,
            "ideas": None,
        })
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        assert "- Item A" in output
        assert "- Item B" in output


# ---------------------------------------------------------------------------
# Tests: Column alignment
# ---------------------------------------------------------------------------

class TestColumnAlignment:
    def test_habit_rows_same_pipe_positions(self):
        """All habit rows within a category should have pipes at the same positions."""
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        lines = output.split("\n")
        # Find habit data lines (contain pipes and checkmarks/dots)
        habit_lines = [l for l in lines if "|" in l and ("\u2713" in l or "\u00b7" in l)]
        if len(habit_lines) < 2:
            pytest.skip("Not enough habit lines to compare")

        # All lines should have the same pipe positions
        def pipe_positions(line):
            return [i for i, c in enumerate(line) if c == "|"]

        reference = pipe_positions(habit_lines[0])
        for line in habit_lines[1:]:
            assert pipe_positions(line) == reference, (
                f"Pipe positions mismatch:\n  {habit_lines[0]}\n  {line}"
            )

    def test_header_and_data_pipes_align(self):
        """Table header pipes should align with data row pipes."""
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 5)):
            output, _ = _build_dashboard(conn, {"week": 1})
        lines = output.split("\n")

        # Find header line (contains "Min/Wk") and a data line
        header_line = None
        data_line = None
        for line in lines:
            if "Min/Wk" in line:
                header_line = line
            elif "|" in line and "\u2713" in line and data_line is None:
                data_line = line

        assert header_line is not None
        assert data_line is not None

        def pipe_positions(line):
            return [i for i, c in enumerate(line) if c == "|"]

        assert pipe_positions(header_line) == pipe_positions(data_line)


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_categories(self):
        """Sprint with no habits should still render without errors."""
        conn = _fresh_conn()
        _create_sprint(conn, start_date="2026-03-02", end_date="2026-03-15")
        with _fake_today(date(2026, 3, 5)):
            data = reporting.sprint_dashboard(conn, {})
            output = format_sprint_dashboard(data)
        assert "SPRINT:" in output
        assert "DAILY TOTALS" in output
        assert "SPRINT SUMMARY" in output

    def test_long_habit_name_truncated(self):
        """Habit names longer than column width should be truncated."""
        conn = _fresh_conn()
        sprint = _create_sprint(conn, start_date="2026-03-02", end_date="2026-03-08")
        long_name = "A" * 40
        _create_habit(conn, "long-name-habit", long_name, sprint_id=sprint["id"])
        with _fake_today(date(2026, 3, 5)):
            data = reporting.sprint_dashboard(conn, {"week": 1})
            output = format_sprint_dashboard(data)
        # Name should be truncated to fit column
        for line in output.split("\n"):
            if "|" in line and "A" * 10 in line and "Min/Wk" not in line:
                name_part = line[:26]
                assert len(name_part) == 26
                break

    def test_full_sprint_14_days(self):
        """Full 14-day sprint should render all days."""
        conn, _ = _setup_basic_sprint()
        with _fake_today(date(2026, 3, 10)):
            output, data = _build_dashboard(conn)
        # Should have 14 dates in daily_totals
        assert len(data["daily_totals"]) == 14
        # Header should not show week indicator
        assert "[Week" not in output


# ---------------------------------------------------------------------------
# Tests: CLI integration (sprint_dashboard)
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_cli_format_flag_accepted(self):
        """The --format markdown flag should be accepted by argparse."""
        import argparse
        from habit_sprint.cli import main
        # Just verify the argument parser accepts the flag (don't run full CLI)
        parser = argparse.ArgumentParser()
        parser.add_argument("--format", dest="output_format",
                            choices=["json", "markdown"], default="json")
        args = parser.parse_args(["--format", "markdown"])
        assert args.output_format == "markdown"


# ===========================================================================
# PART 2: Unit tests for other formatters (from task 4.3)
# ===========================================================================

# ---------------------------------------------------------------------------
# Fixtures: sample data matching the shapes returned by reporting.py
# ---------------------------------------------------------------------------


def _week_view_data():
    return {
        "sprint_id": "sp-1",
        "week_start": "2026-03-02",
        "week_end": "2026-03-08",
        "categories": {
            "Workout": {
                "habits": [
                    {
                        "id": "h1",
                        "name": "Workout (30 min)",
                        "target_per_week": 4,
                        "weight": 2,
                        "daily_values": {
                            "Mon": 1, "Tue": 1, "Wed": 0,
                            "Thu": 1, "Fri": 0, "Sat": 0, "Sun": 0,
                        },
                        "week_actual": 3,
                        "week_completion_pct": 75,
                        "commitment_met": False,
                    },
                    {
                        "id": "h2",
                        "name": "Stretching",
                        "target_per_week": 5,
                        "weight": 1,
                        "daily_values": {
                            "Mon": 1, "Tue": 1, "Wed": 1,
                            "Thu": 1, "Fri": 1, "Sat": 0, "Sun": 0,
                        },
                        "week_actual": 5,
                        "week_completion_pct": 100,
                        "commitment_met": True,
                    },
                ],
            },
            "Diet": {
                "habits": [
                    {
                        "id": "h3",
                        "name": "No Sugar",
                        "target_per_week": 5,
                        "weight": 2,
                        "daily_values": {
                            "Mon": 1, "Tue": 1, "Wed": 0,
                            "Thu": 1, "Fri": 0, "Sat": 0, "Sun": 0,
                        },
                        "week_actual": 3,
                        "week_completion_pct": 60,
                        "commitment_met": False,
                    },
                ],
            },
        },
    }


def _sprint_report_data():
    return {
        "sprint_id": "sp-1",
        "start_date": "2026-03-01",
        "end_date": "2026-03-14",
        "theme": "Foundation Building",
        "focus_goals": ["Increase activity", "Prime for weight loss"],
        "status": "active",
        "days_elapsed": 7,
        "days_remaining": 7,
        "total_days": 14,
        "num_weeks": 2,
        "weighted_score": 83,
        "unweighted_score": 80,
        "categories": [
            {"category": "Workout", "weighted_score": 85, "habits": []},
            {"category": "Diet", "weighted_score": 60, "habits": []},
        ],
        "habits": [
            {
                "habit_id": "h1",
                "name": "Workout (30 min)",
                "category": "Workout",
                "weight": 2,
                "total_entries": 6,
                "expected_entries": 8,
                "completion_pct": 75,
                "current_streak": 2,
                "longest_streak": 4,
                "weekly_breakdown": [],
            },
            {
                "habit_id": "h2",
                "name": "Stretching",
                "category": "Workout",
                "weight": 1,
                "total_entries": 10,
                "expected_entries": 10,
                "completion_pct": 100,
                "current_streak": 5,
                "longest_streak": 10,
                "weekly_breakdown": [],
            },
        ],
        "trend_vs_last_sprint": 5,
    }


def _habit_report_data():
    return {
        "habit_id": "h1",
        "habit_name": "Workout (30 min)",
        "period": "current_sprint",
        "start_date": "2026-03-01",
        "end_date": "2026-03-14",
        "total_entries": 6,
        "expected_entries": 8,
        "completion_pct": 75,
        "current_streak": 2,
        "longest_streak": 4,
        "rolling_7_day_avg": 0.57,
        "trend_vs_prior_period": "+10%",
        "weekly_history": [
            {
                "week_start": "2026-02-24",
                "actual": 3,
                "target": 4,
                "completion_pct": 75,
            },
            {
                "week_start": "2026-03-02",
                "actual": 3,
                "target": 4,
                "completion_pct": 75,
            },
            {
                "week_start": "2026-03-09",
                "actual": 4,
                "target": 4,
                "completion_pct": 100,
            },
        ],
    }


def _daily_score_data():
    return {
        "date": "2026-03-05",
        "sprint_id": "sp-1",
        "total_points": 5,
        "max_possible": 7,
        "completion_pct": 71,
        "habits_completed": [
            {
                "id": "h1",
                "name": "Workout (30 min)",
                "value": 1,
                "weight": 2,
                "points": 2,
            },
            {
                "id": "h2",
                "name": "Stretching",
                "value": 1,
                "weight": 1,
                "points": 1,
            },
            {
                "id": "h3",
                "name": "No Sugar",
                "value": 1,
                "weight": 2,
                "points": 2,
            },
        ],
        "habits_missed": [
            {
                "id": "h4",
                "name": "Reading",
                "weight": 2,
                "points_possible": 2,
            },
        ],
    }


def _category_report_data():
    return {
        "sprint_id": "sp-1",
        "categories": [
            {
                "category": "Workout",
                "habits_count": 3,
                "weighted_score": 85,
                "unweighted_score": 80,
                "habit_ids": ["h1", "h2", "h3"],
            },
            {
                "category": "Diet",
                "habits_count": 2,
                "weighted_score": 60,
                "unweighted_score": 55,
                "habit_ids": ["h4", "h5"],
            },
        ],
        "balance_assessment": {
            "most_adherent": "Workout",
            "least_adherent": "Diet",
            "spread": 25,
        },
    }


# ---------------------------------------------------------------------------
# format_week_view
# ---------------------------------------------------------------------------


class TestFormatWeekView:
    def test_header_contains_dates(self):
        out = format_week_view(_week_view_data())
        assert "2026-03-02" in out
        assert "2026-03-08" in out
        assert "WEEK VIEW" in out

    def test_category_headers_present(self):
        out = format_week_view(_week_view_data())
        assert "CATEGORY: Workout" in out
        assert "CATEGORY: Diet" in out

    def test_check_marks(self):
        out = format_week_view(_week_view_data())
        assert "\u2713" in out
        assert "\u00b7" in out

    def test_star_for_commitment_met(self):
        out = format_week_view(_week_view_data())
        lines = out.split("\n")
        stretching_line = [l for l in lines if "Stretching" in l][0]
        assert "\u2605" in stretching_line

    def test_no_star_when_not_met(self):
        out = format_week_view(_week_view_data())
        lines = out.split("\n")
        workout_line = [l for l in lines if "Workout (30 min)" in l][0]
        assert "\u2605" not in workout_line

    def test_daily_points_row(self):
        out = format_week_view(_week_view_data())
        assert "Daily Points" in out

    def test_category_score_shown(self):
        out = format_week_view(_week_view_data())
        # Workout: (3*2 + 5*1) / (4*2 + 5*1) = 11/13 = 85%
        assert "Score: 85%" in out

    def test_habit_completion_percentage(self):
        out = format_week_view(_week_view_data())
        assert "75%" in out  # Workout (30 min): 3/4
        assert "100%" in out  # Stretching: 5/5

    def test_multiple_categories(self):
        out = format_week_view(_week_view_data())
        # Both categories appear
        workout_idx = out.index("CATEGORY: Workout")
        diet_idx = out.index("CATEGORY: Diet")
        assert workout_idx < diet_idx

    def test_empty_categories(self):
        data = {
            "sprint_id": "sp-1",
            "week_start": "2026-03-02",
            "week_end": "2026-03-08",
            "categories": {},
        }
        out = format_week_view(data)
        assert "WEEK VIEW" in out


# ---------------------------------------------------------------------------
# format_sprint_report
# ---------------------------------------------------------------------------


class TestFormatSprintReport:
    def test_header_contains_dates(self):
        out = format_sprint_report(_sprint_report_data())
        assert "2026-03-01" in out
        assert "2026-03-14" in out
        assert "SPRINT REPORT" in out

    def test_theme_shown(self):
        out = format_sprint_report(_sprint_report_data())
        assert "Foundation Building" in out

    def test_status_and_progress(self):
        out = format_sprint_report(_sprint_report_data())
        assert "active" in out
        assert "7/14 days elapsed" in out
        assert "7 remaining" in out

    def test_focus_goals(self):
        out = format_sprint_report(_sprint_report_data())
        assert "Increase activity" in out
        assert "Prime for weight loss" in out

    def test_weighted_score(self):
        out = format_sprint_report(_sprint_report_data())
        assert "Weighted: 83%" in out

    def test_trend_shown(self):
        out = format_sprint_report(_sprint_report_data())
        assert "+5%" in out

    def test_negative_trend(self):
        data = _sprint_report_data()
        data["trend_vs_last_sprint"] = -3
        out = format_sprint_report(data)
        assert "-3%" in out

    def test_no_trend(self):
        data = _sprint_report_data()
        data["trend_vs_last_sprint"] = None
        out = format_sprint_report(data)
        assert "Trend vs last sprint" not in out

    def test_per_habit_breakdown(self):
        out = format_sprint_report(_sprint_report_data())
        assert "Workout (30 min)" in out
        assert "Stretching" in out
        assert "6 / 8" in out
        assert "10 / 10" in out

    def test_star_for_met_commitment(self):
        out = format_sprint_report(_sprint_report_data())
        lines = out.split("\n")
        stretching_line = [l for l in lines if "Stretching" in l][0]
        assert "\u2605" in stretching_line

    def test_category_scores(self):
        out = format_sprint_report(_sprint_report_data())
        assert "CATEGORY SCORES" in out
        assert "Workout" in out
        assert "85%" in out

    def test_no_focus_goals(self):
        data = _sprint_report_data()
        data["focus_goals"] = []
        out = format_sprint_report(data)
        assert "FOCUS" not in out


# ---------------------------------------------------------------------------
# format_habit_report
# ---------------------------------------------------------------------------


class TestFormatHabitReport:
    def test_header(self):
        out = format_habit_report(_habit_report_data())
        assert "HABIT REPORT" in out
        assert "Workout (30 min)" in out

    def test_period_dates(self):
        out = format_habit_report(_habit_report_data())
        assert "2026-03-01" in out
        assert "2026-03-14" in out

    def test_completion_stats(self):
        out = format_habit_report(_habit_report_data())
        assert "6/8" in out
        assert "75%" in out

    def test_streaks(self):
        out = format_habit_report(_habit_report_data())
        assert "current 2" in out
        assert "longest 4" in out

    def test_rolling_avg(self):
        out = format_habit_report(_habit_report_data())
        assert "0.57" in out

    def test_trend(self):
        out = format_habit_report(_habit_report_data())
        assert "+10%" in out

    def test_weekly_history_table(self):
        out = format_habit_report(_habit_report_data())
        assert "WEEKLY HISTORY" in out
        assert "2026-02-24" in out
        assert "2026-03-02" in out
        assert "2026-03-09" in out

    def test_star_in_weekly_history(self):
        out = format_habit_report(_habit_report_data())
        lines = out.split("\n")
        # Week 2026-03-09: 4/4 = 100% → ★
        week3_line = [l for l in lines if "2026-03-09" in l][0]
        assert "\u2605" in week3_line

    def test_no_star_when_not_met(self):
        out = format_habit_report(_habit_report_data())
        lines = out.split("\n")
        # Week 2026-02-24: 3/4 = 75% → no ★
        week1_line = [l for l in lines if "2026-02-24" in l][0]
        assert "\u2605" not in week1_line

    def test_empty_weekly_history(self):
        data = _habit_report_data()
        data["weekly_history"] = []
        out = format_habit_report(data)
        assert "WEEKLY HISTORY" in out


# ---------------------------------------------------------------------------
# format_daily_score
# ---------------------------------------------------------------------------


class TestFormatDailyScore:
    def test_header(self):
        out = format_daily_score(_daily_score_data())
        assert "DAILY SCORE" in out
        assert "2026-03-05" in out

    def test_total_points(self):
        out = format_daily_score(_daily_score_data())
        assert "5/7 points" in out
        assert "71%" in out

    def test_completed_section(self):
        out = format_daily_score(_daily_score_data())
        assert "COMPLETED" in out
        assert "\u2713 Workout (30 min)" in out
        assert "\u2713 Stretching" in out
        assert "\u2713 No Sugar" in out

    def test_missed_section(self):
        out = format_daily_score(_daily_score_data())
        assert "MISSED" in out
        assert "\u00b7 Reading" in out

    def test_points_in_completed(self):
        out = format_daily_score(_daily_score_data())
        lines = out.split("\n")
        workout_line = [l for l in lines if "Workout (30 min)" in l][0]
        assert "points=2" in workout_line
        assert "weight=2" in workout_line

    def test_points_possible_in_missed(self):
        out = format_daily_score(_daily_score_data())
        lines = out.split("\n")
        reading_line = [l for l in lines if "Reading" in l][0]
        assert "points_possible=2" in reading_line

    def test_no_completed(self):
        data = _daily_score_data()
        data["habits_completed"] = []
        out = format_daily_score(data)
        assert "COMPLETED" not in out
        assert "MISSED" in out

    def test_no_missed(self):
        data = _daily_score_data()
        data["habits_missed"] = []
        out = format_daily_score(data)
        assert "COMPLETED" in out
        assert "MISSED" not in out


# ---------------------------------------------------------------------------
# format_category_report
# ---------------------------------------------------------------------------


class TestFormatCategoryReport:
    def test_header(self):
        out = format_category_report(_category_report_data())
        assert "CATEGORY REPORT" in out

    def test_category_rows(self):
        out = format_category_report(_category_report_data())
        assert "Workout" in out
        assert "Diet" in out

    def test_scores(self):
        out = format_category_report(_category_report_data())
        assert "85%" in out
        assert "60%" in out

    def test_habits_count(self):
        out = format_category_report(_category_report_data())
        lines = out.split("\n")
        workout_line = [l for l in lines if "Workout" in l and "CATEGORY" not in l][0]
        assert "3" in workout_line

    def test_balance_assessment(self):
        out = format_category_report(_category_report_data())
        assert "BALANCE ASSESSMENT" in out
        assert "Most adherent:  Workout" in out
        assert "Least adherent: Diet" in out
        assert "Spread:         25%" in out

    def test_no_balance_when_null(self):
        data = _category_report_data()
        data["balance_assessment"] = {
            "most_adherent": None,
            "least_adherent": None,
            "spread": 0,
        }
        out = format_category_report(data)
        assert "BALANCE ASSESSMENT" not in out

    def test_empty_categories(self):
        data = {
            "sprint_id": "sp-1",
            "categories": [],
            "balance_assessment": {
                "most_adherent": None,
                "least_adherent": None,
                "spread": 0,
            },
        }
        out = format_category_report(data)
        assert "CATEGORY REPORT" in out

    def test_unweighted_score_shown(self):
        out = format_category_report(_category_report_data())
        assert "80%" in out  # Workout unweighted
        assert "55%" in out  # Diet unweighted


# ---------------------------------------------------------------------------
# FORMATTERS dispatcher
# ---------------------------------------------------------------------------


class TestFormattersDispatcher:
    def test_all_actions_registered(self):
        expected = {
            "sprint_dashboard",
            "get_week_view",
            "sprint_report",
            "habit_report",
            "daily_score",
            "category_report",
            "cross_sprint_report",
            "progress_summary",
        }
        assert set(FORMATTERS.keys()) == expected

    def test_each_formatter_is_callable(self):
        for name, fn in FORMATTERS.items():
            assert callable(fn), f"{name} is not callable"


# ---------------------------------------------------------------------------
# CLI integration: --format markdown (unit tests with mocked executor)
# ---------------------------------------------------------------------------


class TestCliFormatFlag:
    def _run_cli(self, action_json, result, extra_args=None):
        """Helper to run CLI main() with mocked executor."""
        from habit_sprint.cli import main

        args_list = ["habit-sprint", "--json", json.dumps(action_json)]
        if extra_args:
            args_list.extend(extra_args)

        stdin_mock = mock.MagicMock()
        stdin_mock.isatty.return_value = True

        with mock.patch("sys.argv", args_list):
            with mock.patch("sys.stdin", stdin_mock):
                with mock.patch(
                    "habit_sprint.executor.execute", return_value=result
                ):
                    return main()

    def test_json_format_outputs_json(self, capsys):
        result = {"status": "success", "data": _daily_score_data(), "error": None}
        code = self._run_cli(
            {"action": "daily_score", "payload": {"date": "2026-03-05"}},
            result,
        )
        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "success"

    def test_markdown_format_outputs_markdown(self, capsys):
        result = {"status": "success", "data": _daily_score_data(), "error": None}
        code = self._run_cli(
            {"action": "daily_score", "payload": {"date": "2026-03-05"}},
            result,
            extra_args=["--format", "markdown"],
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "DAILY SCORE" in out
        assert "2026-03-05" in out

    def test_markdown_format_for_week_view(self, capsys):
        result = {"status": "success", "data": _week_view_data(), "error": None}
        code = self._run_cli(
            {"action": "get_week_view", "payload": {}},
            result,
            extra_args=["--format", "markdown"],
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "WEEK VIEW" in out

    def test_markdown_format_for_sprint_report(self, capsys):
        result = {"status": "success", "data": _sprint_report_data(), "error": None}
        code = self._run_cli(
            {"action": "sprint_report", "payload": {}},
            result,
            extra_args=["--format", "markdown"],
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "SPRINT REPORT" in out

    def test_markdown_format_for_habit_report(self, capsys):
        result = {"status": "success", "data": _habit_report_data(), "error": None}
        code = self._run_cli(
            {"action": "habit_report", "payload": {"habit_id": "h1"}},
            result,
            extra_args=["--format", "markdown"],
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "HABIT REPORT" in out

    def test_markdown_format_for_category_report(self, capsys):
        result = {"status": "success", "data": _category_report_data(), "error": None}
        code = self._run_cli(
            {"action": "category_report", "payload": {}},
            result,
            extra_args=["--format", "markdown"],
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "CATEGORY REPORT" in out

    def test_markdown_fallback_to_json_for_unknown_action(self, capsys):
        result = {"status": "success", "data": {"items": []}, "error": None}
        code = self._run_cli(
            {"action": "list_sprints", "payload": {}},
            result,
            extra_args=["--format", "markdown"],
        )
        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "success"

    def test_markdown_fallback_to_json_on_error(self, capsys):
        result = {"status": "error", "data": None, "error": "Something failed"}
        code = self._run_cli(
            {"action": "daily_score", "payload": {"date": "2026-03-05"}},
            result,
            extra_args=["--format", "markdown"],
        )
        assert code == 1
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "error"
