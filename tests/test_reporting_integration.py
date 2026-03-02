"""Comprehensive integration tests for all 7 reporting actions.

Uses a shared dataset of:
- 2 sprints (1 archived, 1 active): Feb 2-15 and Mar 2-15 (both Mon-Sun aligned)
- 5 habits across 4 categories with varying weights
- 2 weeks of entries with known completion patterns

All expected values are hand-computed from the test data.

Habit summary (Sprint 2: Mar 2-15, 2 weeks):
  running     | health      | w=3  | t=3/wk | entries: Mar 2,4,6,9,11         = 5 of 6
  yoga        | health      | w=1  | t=5/wk | entries: Mar 2,3,4,5,9,10,11    = 7 of 10
  reading     | cognitive   | w=1  | t=5/wk | entries: Mar 2,3,4,5,6,9,10     = 7 of 10  (global)
  meditation  | mindfulness | w=2  | t=7/wk | entries: Mar 2-12 consecutive   = 11 of 14
  journaling  | creative    | w=1  | t=3/wk | entries: Mar 2,4,6,10,12        = 5 of 6   (global)

Weighted score: (5*3 + 7*1 + 7*1 + 11*2 + 5*1) / (6*3 + 10*1 + 10*1 + 14*2 + 6*1)
             = 56/72 = round(77.78) = 78
Unweighted:    (5 + 7 + 7 + 11 + 5) / (6 + 10 + 10 + 14 + 6) = 35/46 = round(76.09) = 76
"""

import os
import tempfile
from datetime import date
from unittest.mock import patch

import pytest

from habit_sprint import engine, reporting
from habit_sprint.db import get_connection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_TODAY = date(2026, 3, 12)  # Thursday


def _fresh_conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return get_connection(path)


def _fake_today(d):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return d

        @classmethod
        def fromisoformat(cls, s):
            return date.fromisoformat(s)

    return patch("habit_sprint.reporting.date", FakeDate)


def _log(conn, habit_id, dates):
    for d in dates:
        engine.log_date(conn, {"habit_id": habit_id, "date": d})


# ---------------------------------------------------------------------------
# Shared dataset (module-scope — reporting functions are read-only)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ds():
    """Build a complete dataset: 2 sprints, 5 habits, 2 weeks of entries."""
    conn = _fresh_conn()

    # Sprint 1 (archived) — Feb 2 (Mon) to Feb 15 (Sun)
    s1 = engine.create_sprint(conn, {
        "start_date": "2026-02-02",
        "end_date": "2026-02-15",
        "theme": "Foundation",
    })

    # Global habits (included in both sprints via sprint_id IS NULL)
    engine.create_habit(conn, {
        "id": "reading", "name": "Reading",
        "category": "cognitive", "target_per_week": 5, "weight": 1,
    })
    engine.create_habit(conn, {
        "id": "journaling", "name": "Journaling",
        "category": "creative", "target_per_week": 3, "weight": 1,
    })

    # Sprint 1 entries for global habits
    _log(conn, "reading", [
        "2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05",
        "2026-02-06", "2026-02-09", "2026-02-10",
    ])
    _log(conn, "journaling", [
        "2026-02-03", "2026-02-05", "2026-02-07", "2026-02-10", "2026-02-12",
    ])

    engine.archive_sprint(conn, {"sprint_id": s1["id"]})

    # Sprint 2 (active) — Mar 2 (Mon) to Mar 15 (Sun)
    s2 = engine.create_sprint(conn, {
        "start_date": "2026-03-02",
        "end_date": "2026-03-15",
        "theme": "Growth Phase",
        "focus_goals": ["Build consistency", "Increase mindfulness"],
    })

    # Sprint-scoped habits
    engine.create_habit(conn, {
        "id": "running", "name": "Running",
        "category": "health", "target_per_week": 3, "weight": 3,
        "sprint_id": s2["id"],
    })
    engine.create_habit(conn, {
        "id": "yoga", "name": "Yoga",
        "category": "health", "target_per_week": 5, "weight": 1,
        "sprint_id": s2["id"],
    })
    engine.create_habit(conn, {
        "id": "meditation", "name": "Meditation",
        "category": "mindfulness", "target_per_week": 7, "weight": 2,
        "sprint_id": s2["id"],
    })

    # Sprint 2 entries — Week 1 (Mar 2-8) and Week 2 (Mar 9-15)
    _log(conn, "running", [
        "2026-03-02", "2026-03-04", "2026-03-06",         # week 1: 3
        "2026-03-09", "2026-03-11",                        # week 2: 2
    ])
    _log(conn, "yoga", [
        "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05",  # week 1: 4
        "2026-03-09", "2026-03-10", "2026-03-11",                # week 2: 3
    ])
    _log(conn, "reading", [
        "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06",  # week 1: 5
        "2026-03-09", "2026-03-10",                                             # week 2: 2
    ])
    _log(conn, "meditation", [
        "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06",
        "2026-03-07", "2026-03-08",                                # week 1: 7
        "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12",   # week 2: 4
    ])
    _log(conn, "journaling", [
        "2026-03-02", "2026-03-04", "2026-03-06",     # week 1: 3
        "2026-03-10", "2026-03-12",                    # week 2: 2
    ])

    return {"conn": conn, "sprint1": s1, "sprint2": s2}


# ===========================================================================
# 1. Hand-computed weighted score verification
# ===========================================================================

class TestHandComputedScores:
    """Verify weighted/unweighted scores match hand-computed values."""

    def test_sprint_report_weighted_score(self, ds):
        # wa: 5*3 + 7*1 + 7*1 + 11*2 + 5*1 = 15+7+7+22+5 = 56
        # wt: 6*3 + 10*1 + 10*1 + 14*2 + 6*1 = 18+10+10+28+6 = 72
        # weighted = round(56/72*100) = 78
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(ds["conn"], {})
        assert result["weighted_score"] == 78

    def test_sprint_report_unweighted_score(self, ds):
        # actual: 5+7+7+11+5=35  target: 6+10+10+14+6=46
        # unweighted = round(35/46*100) = 76
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(ds["conn"], {})
        assert result["unweighted_score"] == 76

    def test_dashboard_scores_match_sprint_report(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        assert result["sprint_summary"]["weighted_score"] == 78
        assert result["sprint_summary"]["unweighted_score"] == 76

    def test_category_health_weighted_score(self, ds):
        # health: running wa=15, wt=18; yoga wa=7, wt=10
        # total wa=22, wt=28 -> round(22/28*100) = 79
        with _fake_today(FAKE_TODAY):
            result = reporting.category_report(ds["conn"], {})
        cats = {c["category"]: c for c in result["categories"]}
        assert cats["health"]["weighted_score"] == 79
        assert cats["health"]["unweighted_score"] == 75  # round(12/16*100)

    def test_category_cognitive_weighted_score(self, ds):
        # reading: wa=7, wt=10 -> 70
        with _fake_today(FAKE_TODAY):
            result = reporting.category_report(ds["conn"], {})
        cats = {c["category"]: c for c in result["categories"]}
        assert cats["cognitive"]["weighted_score"] == 70

    def test_category_mindfulness_weighted_score(self, ds):
        # meditation: wa=22, wt=28 -> round(22/28*100) = 79
        with _fake_today(FAKE_TODAY):
            result = reporting.category_report(ds["conn"], {})
        cats = {c["category"]: c for c in result["categories"]}
        assert cats["mindfulness"]["weighted_score"] == 79

    def test_category_creative_weighted_score(self, ds):
        # journaling: wa=5, wt=6 -> round(5/6*100) = 83
        with _fake_today(FAKE_TODAY):
            result = reporting.category_report(ds["conn"], {})
        cats = {c["category"]: c for c in result["categories"]}
        assert cats["creative"]["weighted_score"] == 83

    def test_daily_score_known_date(self, ds):
        # Mar 5: reading(1*1=1), yoga(1*1=1), meditation(1*2=2) completed
        #         running(w=3), journaling(w=1) missed
        # total=4, max=3+1+1+1+2=8, pct=50
        with _fake_today(FAKE_TODAY):
            result = reporting.daily_score(ds["conn"], {"date": "2026-03-05"})
        assert result["total_points"] == 4
        assert result["max_possible"] == 8
        assert result["completion_pct"] == 50
        assert len(result["habits_completed"]) == 3
        assert len(result["habits_missed"]) == 2

    def test_trend_vs_last_sprint(self, ds):
        # Sprint 1 global habits: reading (wa=7, wt=10), journaling (wa=5, wt=6)
        # prev_weighted = round(12/16*100) = 75
        # current_weighted = 78 -> trend = 78 - 75 = 3
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(ds["conn"], {})
        assert result["trend_vs_last_sprint"] == 3

    def test_habit_report_reading_known_values(self, ds):
        # reading in current_sprint: total=7, expected=10, pct=70
        # streaks: longest=5 (Feb 2-6 or Mar 2-6), current=0 (last entry Mar 10, gap)
        # rolling_7: Mar 6-12 -> Mar 6, 9, 10 = 3 -> 3/7 = 0.43
        # trend: prior period Feb 16-Mar 1, entries=0 -> +70%
        with _fake_today(FAKE_TODAY):
            result = reporting.habit_report(ds["conn"], {"habit_id": "reading"})
        assert result["total_entries"] == 7
        assert result["expected_entries"] == 10
        assert result["completion_pct"] == 70
        assert result["current_streak"] == 0
        assert result["longest_streak"] == 5
        assert result["rolling_7_day_avg"] == 0.43
        assert result["trend_vs_prior_period"] == "+70%"
        assert len(result["weekly_history"]) == 2
        assert result["weekly_history"][0]["actual"] == 5
        assert result["weekly_history"][0]["completion_pct"] == 100
        assert result["weekly_history"][1]["actual"] == 2
        assert result["weekly_history"][1]["completion_pct"] == 40

    def test_weekly_completion_running_week1(self, ds):
        # running week 1 (Mar 2-8): actual=3, target=3 -> 100%, commitment met
        with _fake_today(FAKE_TODAY):
            result = reporting.weekly_completion(ds["conn"], {
                "habit_id": "running", "week_start": "2026-03-02",
            })
        assert result["actual_days"] == 3
        assert result["target_per_week"] == 3
        assert result["completion_pct"] == 100
        assert result["commitment_met"] is True

    def test_weekly_completion_running_week2(self, ds):
        # running week 2 (Mar 9-15): actual=2, target=3 -> int(2/3*100)=66
        with _fake_today(FAKE_TODAY):
            result = reporting.weekly_completion(ds["conn"], {
                "habit_id": "running", "week_start": "2026-03-09",
            })
        assert result["actual_days"] == 2
        assert result["completion_pct"] == 66
        assert result["commitment_met"] is False


# ===========================================================================
# 2. Streak edge cases
# ===========================================================================

class TestStreakEdgeCases:
    """Test streak computation through reporting functions."""

    # --- Via shared dataset ---

    def test_long_consecutive_streak(self, ds):
        # meditation: Mar 2-12 = 11 consecutive; today=Mar 12 -> current=11, longest=11
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(ds["conn"], {})
        h = next(h for h in result["habits"] if h["habit_id"] == "meditation")
        assert h["current_streak"] == 11
        assert h["longest_streak"] == 11

    def test_all_isolated_entries(self, ds):
        # running: Mar 2,4,6,9,11 (all gaps); yesterday=Mar 11 in entries -> current=1
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(ds["conn"], {})
        h = next(h for h in result["habits"] if h["habit_id"] == "running")
        assert h["current_streak"] == 1
        assert h["longest_streak"] == 1

    def test_current_streak_zero_when_gap_exceeds_one_day(self, ds):
        # reading: last entry Mar 10, today=Mar 12, yesterday=Mar 11 -> not in entries
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(ds["conn"], {})
        h = next(h for h in result["habits"] if h["habit_id"] == "reading")
        assert h["current_streak"] == 0

    def test_longest_streak_from_past_data(self, ds):
        # reading: Feb 2-6 and Mar 2-6 are both 5-day streaks -> longest=5
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(ds["conn"], {})
        h = next(h for h in result["habits"] if h["habit_id"] == "reading")
        assert h["longest_streak"] == 5

    def test_current_streak_shorter_than_longest(self, ds):
        # yoga: Mar 9-11 -> current=3 (yesterday=11); Mar 2-5 -> longest=4
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(ds["conn"], {})
        h = next(h for h in result["habits"] if h["habit_id"] == "yoga")
        assert h["current_streak"] == 3
        assert h["longest_streak"] == 4

    # --- Targeted edge cases with isolated setup ---

    def test_single_entry_today(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-01-01", "end_date": "2026-12-31"})
        engine.create_habit(conn, {
            "id": "test-h", "name": "Test", "category": "health", "target_per_week": 7,
        })
        engine.log_date(conn, {"habit_id": "test-h", "date": "2026-03-12"})

        with _fake_today(date(2026, 3, 12)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "test-h", "week_start": "2026-03-09",
            })
        assert result["current_streak"] == 1
        assert result["longest_streak"] == 1

    def test_streak_gap_then_resume(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-01-01", "end_date": "2026-12-31"})
        engine.create_habit(conn, {
            "id": "test-h", "name": "Test", "category": "health", "target_per_week": 7,
        })
        # 3-day streak, gap, 2-day streak ending today
        _log(conn, "test-h", [
            "2026-03-05", "2026-03-06", "2026-03-07",
            "2026-03-11", "2026-03-12",
        ])

        with _fake_today(date(2026, 3, 12)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "test-h", "week_start": "2026-03-09",
            })
        assert result["current_streak"] == 2
        assert result["longest_streak"] == 3

    def test_streak_ending_yesterday(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-01-01", "end_date": "2026-12-31"})
        engine.create_habit(conn, {
            "id": "test-h", "name": "Test", "category": "health", "target_per_week": 7,
        })
        _log(conn, "test-h", ["2026-03-09", "2026-03-10", "2026-03-11"])

        with _fake_today(date(2026, 3, 12)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "test-h", "week_start": "2026-03-09",
            })
        # yesterday=Mar 11 in entries -> current=3 (11, 10, 9)
        assert result["current_streak"] == 3
        assert result["longest_streak"] == 3

    def test_streak_broken_two_days_ago(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-01-01", "end_date": "2026-12-31"})
        engine.create_habit(conn, {
            "id": "test-h", "name": "Test", "category": "health", "target_per_week": 7,
        })
        _log(conn, "test-h", ["2026-03-08", "2026-03-09", "2026-03-10"])

        with _fake_today(date(2026, 3, 12)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "test-h", "week_start": "2026-03-09",
            })
        # today=12 not in, yesterday=11 not in -> current=0
        assert result["current_streak"] == 0
        assert result["longest_streak"] == 3

    def test_no_entries_zero_streaks(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-01-01", "end_date": "2026-12-31"})
        engine.create_habit(conn, {
            "id": "test-h", "name": "Test", "category": "health", "target_per_week": 7,
        })

        with _fake_today(date(2026, 3, 12)):
            result = reporting.weekly_completion(conn, {
                "habit_id": "test-h", "week_start": "2026-03-09",
            })
        assert result["current_streak"] == 0
        assert result["longest_streak"] == 0


# ===========================================================================
# 3. Sprint dashboard response structure
# ===========================================================================

class TestSprintDashboardResponseStructure:
    """Verify the dashboard response has correct structure at every level."""

    def test_top_level_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        assert set(result.keys()) == {
            "sprint", "categories", "daily_totals", "sprint_summary", "retro",
        }

    def test_sprint_metadata_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        expected = {
            "id", "start_date", "end_date", "theme",
            "focus_goals", "status", "days_elapsed", "days_remaining",
        }
        assert expected.issubset(set(result["sprint"].keys()))

    def test_sprint_metadata_values(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        s = result["sprint"]
        assert s["id"] == ds["sprint2"]["id"]
        assert s["start_date"] == "2026-03-02"
        assert s["end_date"] == "2026-03-15"
        assert s["theme"] == "Growth Phase"
        assert s["focus_goals"] == ["Build consistency", "Increase mindfulness"]
        assert s["status"] == "active"
        # today=Mar 12: days_elapsed = (12-2)+1 = 11, days_remaining = (15-12) = 3
        assert s["days_elapsed"] == 11
        assert s["days_remaining"] == 3

    def test_summary_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        assert set(result["sprint_summary"].keys()) == {
            "weighted_score", "unweighted_score", "per_habit",
        }

    def test_per_habit_entry_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        for ph in result["sprint_summary"]["per_habit"]:
            assert set(ph.keys()) == {"habit_id", "actual", "target", "pct"}

    def test_category_entry_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        for cat in result["categories"]:
            assert "category" in cat
            assert "habits" in cat
            assert "category_weighted_score" in cat

    def test_habit_in_category_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        required = {
            "habit_id", "name", "target_per_week", "weight",
            "daily", "week_actual", "week_completion_pct", "commitment_met",
        }
        for cat in result["categories"]:
            for h in cat["habits"]:
                assert required.issubset(set(h.keys()))

    def test_daily_totals_structure(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        # Full sprint = 14 days
        assert len(result["daily_totals"]) == 14
        for day_data in result["daily_totals"].values():
            assert set(day_data.keys()) == {"points", "max", "pct"}

    def test_retro_is_none_when_absent(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        assert result["retro"] is None

    def test_five_habits_across_four_categories(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        cat_names = {c["category"] for c in result["categories"]}
        assert cat_names == {"health", "cognitive", "mindfulness", "creative"}
        all_habits = []
        for c in result["categories"]:
            all_habits.extend(c["habits"])
        assert len(all_habits) == 5


# ===========================================================================
# 4. Empty data cases
# ===========================================================================

class TestEmptyDataCases:
    """Verify correct behaviour when there are no habits or no entries."""

    def test_sprint_report_no_habits(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-03-02", "end_date": "2026-03-15"})
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(conn, {})
        assert result["weighted_score"] == 0
        assert result["unweighted_score"] == 0
        assert result["habits"] == []
        assert result["categories"] == []

    def test_sprint_report_no_entries(self):
        conn = _fresh_conn()
        sprint = engine.create_sprint(conn, {
            "start_date": "2026-03-02", "end_date": "2026-03-15",
        })
        engine.create_habit(conn, {
            "id": "running", "name": "Running", "category": "health",
            "target_per_week": 5, "sprint_id": sprint["id"],
        })
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(conn, {})
        assert result["weighted_score"] == 0
        assert result["unweighted_score"] == 0
        assert len(result["habits"]) == 1
        assert result["habits"][0]["total_entries"] == 0

    def test_daily_score_no_habits(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-03-02", "end_date": "2026-03-15"})
        result = reporting.daily_score(conn, {"date": "2026-03-05"})
        assert result["total_points"] == 0
        assert result["max_possible"] == 0
        assert result["completion_pct"] == 0
        assert result["habits_completed"] == []
        assert result["habits_missed"] == []

    def test_daily_score_no_entries(self):
        conn = _fresh_conn()
        sprint = engine.create_sprint(conn, {
            "start_date": "2026-03-02", "end_date": "2026-03-15",
        })
        engine.create_habit(conn, {
            "id": "running", "name": "Running", "category": "health",
            "target_per_week": 5, "sprint_id": sprint["id"],
        })
        result = reporting.daily_score(conn, {"date": "2026-03-05"})
        assert result["total_points"] == 0
        assert result["max_possible"] == 1  # default weight=1
        assert result["completion_pct"] == 0
        assert len(result["habits_missed"]) == 1

    def test_week_view_no_habits(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-03-02", "end_date": "2026-03-15"})
        with _fake_today(FAKE_TODAY):
            result = reporting.get_week_view(conn, {"week_start": "2026-03-02"})
        assert result["categories"] == {}

    def test_category_report_no_habits(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-03-02", "end_date": "2026-03-15"})
        with _fake_today(FAKE_TODAY):
            result = reporting.category_report(conn, {})
        assert result["categories"] == []
        assert result["balance_assessment"]["most_adherent"] is None
        assert result["balance_assessment"]["least_adherent"] is None
        assert result["balance_assessment"]["spread"] == 0

    def test_sprint_dashboard_no_habits(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-03-02", "end_date": "2026-03-15"})
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(conn, {})
        assert result["categories"] == []
        assert result["sprint_summary"]["weighted_score"] == 0
        assert result["sprint_summary"]["unweighted_score"] == 0
        assert result["sprint_summary"]["per_habit"] == []

    def test_habit_report_no_entries(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-03-02", "end_date": "2026-03-15"})
        engine.create_habit(conn, {
            "id": "running", "name": "Running", "category": "health",
            "target_per_week": 5,
        })
        with _fake_today(FAKE_TODAY):
            result = reporting.habit_report(conn, {"habit_id": "running"})
        assert result["total_entries"] == 0
        assert result["completion_pct"] == 0
        assert result["current_streak"] == 0
        assert result["longest_streak"] == 0
        assert result["rolling_7_day_avg"] == 0.0

    def test_weekly_completion_no_entries(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {"start_date": "2026-03-02", "end_date": "2026-03-15"})
        engine.create_habit(conn, {
            "id": "running", "name": "Running", "category": "health",
            "target_per_week": 5,
        })
        with _fake_today(FAKE_TODAY):
            result = reporting.weekly_completion(conn, {
                "habit_id": "running", "week_start": "2026-03-02",
            })
        assert result["actual_days"] == 0
        assert result["completion_pct"] == 0
        assert result["commitment_met"] is False
        assert result["current_streak"] == 0
        assert result["longest_streak"] == 0


# ===========================================================================
# 5. Data shape for each reporting action
# ===========================================================================

class TestActionDataShapes:
    """Each reporting action returns the expected set of top-level keys."""

    def test_weekly_completion_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.weekly_completion(ds["conn"], {
                "habit_id": "running", "week_start": "2026-03-02",
            })
        expected = {
            "habit_id", "week_start", "week_end", "actual_days",
            "target_per_week", "completion_pct", "commitment_met",
            "current_streak", "longest_streak",
        }
        assert expected == set(result.keys())

    def test_daily_score_keys(self, ds):
        result = reporting.daily_score(ds["conn"], {"date": "2026-03-05"})
        expected = {
            "date", "sprint_id", "total_points", "max_possible",
            "completion_pct", "habits_completed", "habits_missed",
        }
        assert expected == set(result.keys())

    def test_week_view_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.get_week_view(ds["conn"], {"week_start": "2026-03-02"})
        assert set(result.keys()) == {"sprint_id", "week_start", "week_end", "categories"}

    def test_sprint_report_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_report(ds["conn"], {})
        expected = {
            "sprint_id", "start_date", "end_date", "theme", "focus_goals",
            "status", "days_elapsed", "days_remaining", "total_days",
            "num_weeks", "weighted_score", "unweighted_score",
            "categories", "habits", "trend_vs_last_sprint",
        }
        assert expected == set(result.keys())

    def test_habit_report_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.habit_report(ds["conn"], {"habit_id": "reading"})
        expected = {
            "habit_id", "habit_name", "period", "start_date", "end_date",
            "total_entries", "expected_entries", "completion_pct",
            "current_streak", "longest_streak", "rolling_7_day_avg",
            "trend_vs_prior_period", "weekly_history",
        }
        assert expected == set(result.keys())

    def test_category_report_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.category_report(ds["conn"], {})
        assert set(result.keys()) == {"sprint_id", "categories", "balance_assessment"}

    def test_sprint_dashboard_keys(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.sprint_dashboard(ds["conn"], {})
        assert set(result.keys()) == {
            "sprint", "categories", "daily_totals", "sprint_summary", "retro",
        }


# ===========================================================================
# 6. Cross-action consistency
# ===========================================================================

class TestCrossActionConsistency:
    """Scores computed by different actions on the same data should agree."""

    def test_sprint_report_and_dashboard_weighted_scores(self, ds):
        with _fake_today(FAKE_TODAY):
            report = reporting.sprint_report(ds["conn"], {})
            dashboard = reporting.sprint_dashboard(ds["conn"], {})
        assert report["weighted_score"] == dashboard["sprint_summary"]["weighted_score"]
        assert report["unweighted_score"] == dashboard["sprint_summary"]["unweighted_score"]

    def test_category_weighted_scores_match_sprint_report(self, ds):
        with _fake_today(FAKE_TODAY):
            report = reporting.sprint_report(ds["conn"], {})
            cat_report = reporting.category_report(ds["conn"], {})
        report_cats = {c["category"]: c["weighted_score"] for c in report["categories"]}
        cat_cats = {c["category"]: c["weighted_score"] for c in cat_report["categories"]}
        assert report_cats == cat_cats

    def test_balance_assessment_correct(self, ds):
        # sorted by weighted: cognitive(70), health(79), mindfulness(79), creative(83)
        with _fake_today(FAKE_TODAY):
            result = reporting.category_report(ds["conn"], {})
        ba = result["balance_assessment"]
        assert ba["least_adherent"] == "cognitive"
        assert ba["most_adherent"] == "creative"
        assert ba["spread"] == 13  # 83 - 70


# ===========================================================================
# 7. Week view known values
# ===========================================================================

class TestWeekViewKnownValues:
    """Verify week view with hand-computed daily values."""

    def test_health_habits_week1(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.get_week_view(ds["conn"], {"week_start": "2026-03-02"})
        health = result["categories"]["health"]["habits"]
        running = next(h for h in health if h["id"] == "running")
        assert running["daily_values"]["Mon"] == 1
        assert running["daily_values"]["Tue"] == 0
        assert running["daily_values"]["Wed"] == 1
        assert running["daily_values"]["Fri"] == 1
        assert running["week_actual"] == 3
        assert running["week_completion_pct"] == 100
        assert running["commitment_met"] is True

        yoga = next(h for h in health if h["id"] == "yoga")
        assert yoga["daily_values"]["Mon"] == 1
        assert yoga["daily_values"]["Tue"] == 1
        assert yoga["daily_values"]["Wed"] == 1
        assert yoga["daily_values"]["Thu"] == 1
        assert yoga["daily_values"]["Fri"] == 0
        assert yoga["week_actual"] == 4
        assert yoga["week_completion_pct"] == 80
        assert yoga["commitment_met"] is False

    def test_meditation_perfect_week1(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.get_week_view(ds["conn"], {"week_start": "2026-03-02"})
        mindfulness = result["categories"]["mindfulness"]["habits"]
        meditation = mindfulness[0]
        for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            assert meditation["daily_values"][day] == 1
        assert meditation["week_actual"] == 7
        assert meditation["week_completion_pct"] == 100
        assert meditation["commitment_met"] is True

    def test_four_categories_present(self, ds):
        with _fake_today(FAKE_TODAY):
            result = reporting.get_week_view(ds["conn"], {"week_start": "2026-03-02"})
        assert set(result["categories"].keys()) == {
            "health", "cognitive", "mindfulness", "creative",
        }
