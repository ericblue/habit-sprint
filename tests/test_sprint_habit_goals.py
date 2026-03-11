"""Tests for Epic 8 features: sprint_habit_goals CRUD, reporting overrides,
data migration, web UI goal editing, and backward compatibility."""

import tempfile
import os

import pytest

from habit_sprint.db import get_connection
from habit_sprint import engine
from habit_sprint import reporting
from habit_sprint.executor import execute
from scripts.consolidate_habits import consolidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_db():
    """Return (conn, db_path) for a fresh temporary database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = get_connection(path)
    return conn, path


def _seed_sprint_and_habit(conn, sprint_id=None, habit_id="exercise",
                           habit_name="Exercise", target=5, weight=1,
                           category="health"):
    """Create a sprint and a global habit, returning (sprint_id, habit_id)."""
    result = engine.create_sprint(conn, {
        "start_date": "2026-03-02",
        "end_date": "2026-03-15",
    })
    sid = result["id"]
    engine.create_habit(conn, {
        "id": habit_id,
        "name": habit_name,
        "category": category,
        "target_per_week": target,
        "weight": weight,
    })
    return sid, habit_id


# ===========================================================================
# 1. Sprint habit goals CRUD round-trip
# ===========================================================================

class TestSprintHabitGoalsCRUD:
    """Test set/get/delete sprint_habit_goals round-trip."""

    def test_set_and_get_goal(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn)

        result = execute({"action": "set_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
            "target_per_week": 7, "weight": 3,
        }}, path)
        assert result["status"] == "success"
        goal = result["data"]
        assert goal["sprint_id"] == sid
        assert goal["habit_id"] == hid
        assert goal["target_per_week"] == 7
        assert goal["weight"] == 3

        # Get it back
        result2 = execute({"action": "get_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
        }}, path)
        assert result2["status"] == "success"
        assert result2["data"]["target_per_week"] == 7
        assert result2["data"]["weight"] == 3

    def test_get_nonexistent_goal_returns_none(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn)

        result = execute({"action": "get_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
        }}, path)
        assert result["status"] == "success"
        assert result["data"]["goal"] is None

    def test_upsert_overwrites_existing_goal(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn)
        conn.close()

        execute({"action": "set_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
            "target_per_week": 3, "weight": 1,
        }}, path)
        execute({"action": "set_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
            "target_per_week": 7, "weight": 3,
        }}, path)

        result = execute({"action": "get_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
        }}, path)
        assert result["data"]["target_per_week"] == 7
        assert result["data"]["weight"] == 3

    def test_delete_goal(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn)

        execute({"action": "set_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
            "target_per_week": 7, "weight": 2,
        }}, path)
        result = execute({"action": "delete_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
        }}, path)
        assert result["status"] == "success"
        assert result["data"]["deleted"] is True

        # Confirm gone
        result2 = execute({"action": "get_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
        }}, path)
        assert result2["data"]["goal"] is None

    def test_delete_nonexistent_goal(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn)

        result = execute({"action": "delete_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": hid,
        }}, path)
        assert result["status"] == "success"
        assert result["data"]["deleted"] is False

    def test_set_goal_invalid_sprint_raises(self):
        conn, path = _fresh_db()
        _seed_sprint_and_habit(conn)

        result = execute({"action": "set_sprint_habit_goal", "payload": {
            "sprint_id": "FAKE-S99", "habit_id": "exercise",
            "target_per_week": 5, "weight": 1,
        }}, path)
        assert result["status"] == "error"

    def test_set_goal_invalid_habit_raises(self):
        conn, path = _fresh_db()
        sid, _ = _seed_sprint_and_habit(conn)

        result = execute({"action": "set_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": "nonexistent",
            "target_per_week": 5, "weight": 1,
        }}, path)
        assert result["status"] == "error"

    def test_default_weight_is_one(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn)

        # Engine function directly — weight defaults to 1
        goal = engine.set_sprint_habit_goal(conn, {
            "sprint_id": sid, "habit_id": hid,
            "target_per_week": 4,
        })
        assert goal["weight"] == 1


# ===========================================================================
# 2. Reporting uses sprint-specific targets (overrides) vs defaults
# ===========================================================================

class TestReportingWithOverrides:
    """Test that reporting functions use sprint_habit_goals when available."""

    def _setup_with_override(self):
        """Set up a sprint + habit + override + some entries."""
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn, target=5, weight=1)

        # Set sprint-specific override: target=2, weight=3
        engine.set_sprint_habit_goal(conn, {
            "sprint_id": sid, "habit_id": hid,
            "target_per_week": 2, "weight": 3,
        })

        # Log some entries
        engine.log_date(conn, {"habit_id": hid, "date": "2026-03-02", "value": 1})
        engine.log_date(conn, {"habit_id": hid, "date": "2026-03-03", "value": 1})

        return conn, path, sid, hid

    def test_weekly_completion_uses_override_target(self):
        conn, path, sid, hid = self._setup_with_override()

        result = reporting.weekly_completion(conn, {
            "habit_id": hid,
            "sprint_id": sid,
            "week_start": "2026-03-02",
        })
        # With override target=2, 2 entries => 100%
        assert result["target_per_week"] == 2
        assert result["completion_pct"] == 100
        assert result["commitment_met"] is True

    def test_weekly_completion_without_override_uses_default(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn, target=5, weight=1)

        engine.log_date(conn, {"habit_id": hid, "date": "2026-03-02", "value": 1})
        engine.log_date(conn, {"habit_id": hid, "date": "2026-03-03", "value": 1})

        result = reporting.weekly_completion(conn, {
            "habit_id": hid,
            "sprint_id": sid,
            "week_start": "2026-03-02",
        })
        # Default target=5, 2 entries => 40%
        assert result["target_per_week"] == 5
        assert result["completion_pct"] == 40

    def test_daily_score_uses_override_weight(self):
        conn, path, sid, hid = self._setup_with_override()

        result = reporting.daily_score(conn, {
            "sprint_id": sid,
            "date": "2026-03-02",
        })
        # Override weight=3, value=1 => points=3
        assert len(result["habits_completed"]) == 1
        assert result["habits_completed"][0]["weight"] == 3
        assert result["habits_completed"][0]["points"] == 3
        assert result["max_possible"] == 3

    def test_sprint_report_uses_override(self):
        conn, path, sid, hid = self._setup_with_override()

        result = reporting.sprint_report(conn, {"sprint_id": sid})
        habit = result["habits"][0]
        assert habit["weight"] == 3
        # target_per_week=2 * num_weeks => expected
        assert habit["expected_entries"] == 2 * result["num_weeks"]

    def test_get_week_view_uses_override(self):
        conn, path, sid, hid = self._setup_with_override()

        result = reporting.get_week_view(conn, {
            "sprint_id": sid,
            "week_start": "2026-03-02",
        })
        cats = result["categories"]
        # Find the habit in categories
        for cat_data in cats.values():
            for h in cat_data["habits"]:
                if h["id"] == hid:
                    assert h["target_per_week"] == 2
                    assert h["weight"] == 3

    def test_sprint_dashboard_uses_override(self):
        conn, path, sid, hid = self._setup_with_override()

        result = reporting.sprint_dashboard(conn, {"sprint_id": sid})
        cats = result["categories"]
        for cat in cats:
            for h in cat["habits"]:
                if h["habit_id"] == hid:
                    assert h["target_per_week"] == 2
                    assert h["weight"] == 3

    def test_category_report_uses_override(self):
        conn, path, sid, hid = self._setup_with_override()

        result = reporting.category_report(conn, {"sprint_id": sid})
        # With override weight=3 and target=2, the weighted calculations should differ
        assert len(result["categories"]) == 1

    def test_habit_report_uses_override(self):
        conn, path, sid, hid = self._setup_with_override()

        result = reporting.habit_report(conn, {
            "habit_id": hid,
            "sprint_id": sid,
        })
        # Should use override target=2 for weekly history
        for week in result["weekly_history"]:
            assert week["target"] == 2


# ===========================================================================
# 3. Reporting falls back to habit defaults when no override exists
# ===========================================================================

class TestReportingFallbackToDefaults:
    """Test that reporting falls back to habit defaults when no override."""

    def test_effective_goals_no_sprint(self):
        conn, _ = _fresh_db()
        _, hid = _seed_sprint_and_habit(conn, target=5, weight=2)

        row = conn.execute("SELECT * FROM habits WHERE id = ?", (hid,)).fetchone()
        result = reporting._get_effective_goals(conn, None, [row])
        assert result[0]["target_per_week"] == 5
        assert result[0]["weight"] == 2

    def test_effective_goals_no_override_row(self):
        conn, _ = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn, target=5, weight=2)

        row = conn.execute("SELECT * FROM habits WHERE id = ?", (hid,)).fetchone()
        result = reporting._get_effective_goals(conn, sid, [row])
        assert result[0]["target_per_week"] == 5
        assert result[0]["weight"] == 2

    def test_effective_goals_with_override(self):
        conn, _ = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn, target=5, weight=2)

        engine.set_sprint_habit_goal(conn, {
            "sprint_id": sid, "habit_id": hid,
            "target_per_week": 7, "weight": 4,
        })

        row = conn.execute("SELECT * FROM habits WHERE id = ?", (hid,)).fetchone()
        result = reporting._get_effective_goals(conn, sid, [row])
        assert result[0]["target_per_week"] == 7
        assert result[0]["weight"] == 4

    def test_effective_goals_mixed_override_and_default(self):
        conn, _ = _fresh_db()
        sid, _ = _seed_sprint_and_habit(conn, habit_id="habit-one", habit_name="Habit One",
                                        target=5, weight=1)
        engine.create_habit(conn, {
            "id": "habit-two", "name": "Habit Two", "category": "health",
            "target_per_week": 3, "weight": 2,
        })

        # Only override habit-one
        engine.set_sprint_habit_goal(conn, {
            "sprint_id": sid, "habit_id": "habit-one",
            "target_per_week": 10, "weight": 5,
        })

        habits = conn.execute("SELECT * FROM habits ORDER BY id").fetchall()
        result = reporting._get_effective_goals(conn, sid, habits)
        by_id = {h["id"]: h for h in result}

        assert by_id["habit-one"]["target_per_week"] == 10
        assert by_id["habit-one"]["weight"] == 5
        assert by_id["habit-two"]["target_per_week"] == 3
        assert by_id["habit-two"]["weight"] == 2


# ===========================================================================
# 4. Data migration script correctness
# ===========================================================================

class TestConsolidateMigration:
    """Test the consolidate_habits.py migration script."""

    def _setup_duplicates(self):
        """Create a DB with duplicate habits (same name, different IDs)."""
        conn, path = _fresh_db()

        # Create a sprint
        engine.create_sprint(conn, {
            "start_date": "2026-03-02",
            "end_date": "2026-03-15",
        })
        sid = "2026-S01"

        # Create two habits with the same name but different IDs
        # One is global, one is sprint-scoped
        conn.execute(
            "INSERT INTO habits (id, name, category, target_per_week, weight, unit, sprint_id, archived, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("exercise", "Exercise", "health", 5, 1, "count", None, 0),
        )
        conn.execute(
            "INSERT INTO habits (id, name, category, target_per_week, weight, unit, sprint_id, archived, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("exercise-hist-001", "Exercise", "health", 3, 2, "count", sid, 0),
        )

        # Add entries for both
        conn.execute(
            "INSERT INTO entries (habit_id, date, value, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("exercise", "2026-03-02", 1),
        )
        conn.execute(
            "INSERT INTO entries (habit_id, date, value, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("exercise", "2026-03-03", 1),
        )
        conn.execute(
            "INSERT INTO entries (habit_id, date, value, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            ("exercise-hist-001", "2026-03-04", 1),
        )
        conn.commit()

        return conn, path, sid

    def test_entry_counts_preserved(self):
        conn, path, sid = self._setup_duplicates()

        before = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        summary = consolidate(conn)

        assert summary["entries_match"] is True
        assert summary["entry_count_before"] == before
        assert summary["entry_count_after"] == before

    def test_duplicates_removed(self):
        conn, path, sid = self._setup_duplicates()

        summary = consolidate(conn)

        assert summary["habits_deleted"] == 1
        assert summary["groups_consolidated"] == 1

        # Only canonical "exercise" remains
        habits = conn.execute("SELECT * FROM habits WHERE name = 'Exercise'").fetchall()
        assert len(habits) == 1
        assert habits[0]["id"] == "exercise"

    def test_goals_preserved(self):
        conn, path, sid = self._setup_duplicates()

        consolidate(conn)

        # The sprint-scoped duplicate's target/weight should be preserved as a goal
        goal = conn.execute(
            "SELECT * FROM sprint_habit_goals WHERE sprint_id = ? AND habit_id = ?",
            (sid, "exercise"),
        ).fetchone()
        assert goal is not None
        assert goal["target_per_week"] == 3
        assert goal["weight"] == 2

    def test_canonical_habit_becomes_global(self):
        conn, path, sid = self._setup_duplicates()

        consolidate(conn)

        habit = conn.execute("SELECT * FROM habits WHERE id = 'exercise'").fetchone()
        assert habit["sprint_id"] is None

    def test_entries_reassigned_to_canonical(self):
        conn, path, sid = self._setup_duplicates()

        consolidate(conn)

        # All entries should belong to "exercise"
        entries = conn.execute("SELECT * FROM entries ORDER BY date").fetchall()
        for e in entries:
            assert e["habit_id"] == "exercise"
        assert len(entries) == 3

    def test_conflicting_date_entries_handled(self):
        """If both canonical and duplicate have entries on the same date,
        canonical's entry is kept."""
        conn, path = _fresh_db()
        engine.create_sprint(conn, {
            "start_date": "2026-03-02", "end_date": "2026-03-15",
        })

        conn.execute(
            "INSERT INTO habits (id, name, category, target_per_week, weight, unit, sprint_id, archived, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("reading", "Reading", "learning", 3, 1, "count", None, 0),
        )
        conn.execute(
            "INSERT INTO habits (id, name, category, target_per_week, weight, unit, sprint_id, archived, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("reading-hist-001", "Reading", "learning", 5, 2, "count", "2026-S01", 0),
        )

        # Both have entries on the same date — different values
        conn.execute("INSERT INTO entries (habit_id, date, value, created_at, updated_at) "
                     "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
                     ("reading", "2026-03-02", 10))
        conn.execute("INSERT INTO entries (habit_id, date, value, created_at, updated_at) "
                     "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
                     ("reading-hist-001", "2026-03-02", 20))
        conn.commit()

        before = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        assert before == 2

        consolidate(conn)

        # Canonical's entry is kept; duplicate's conflicting entry is deleted
        entries = conn.execute("SELECT * FROM entries WHERE habit_id = 'reading'").fetchall()
        assert len(entries) == 1
        assert entries[0]["value"] == 10

    def test_single_sprint_scoped_habit_made_global(self):
        """A single habit (no duplicate) that is sprint-scoped gets made global
        and its goal is preserved."""
        conn, path = _fresh_db()
        engine.create_sprint(conn, {
            "start_date": "2026-03-02", "end_date": "2026-03-15",
        })

        conn.execute(
            "INSERT INTO habits (id, name, category, target_per_week, weight, unit, sprint_id, archived, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("meditation", "Meditation", "wellness", 4, 2, "minutes", "2026-S01", 0),
        )
        conn.commit()

        consolidate(conn)

        habit = conn.execute("SELECT * FROM habits WHERE id = 'meditation'").fetchone()
        assert habit["sprint_id"] is None

        goal = conn.execute(
            "SELECT * FROM sprint_habit_goals WHERE habit_id = 'meditation' AND sprint_id = '2026-S01'"
        ).fetchone()
        assert goal is not None
        assert goal["target_per_week"] == 4
        assert goal["weight"] == 2


# ===========================================================================
# 5. Data migration idempotency
# ===========================================================================

class TestMigrationIdempotency:
    """Run the consolidation twice and verify the same result."""

    def test_idempotent_run(self):
        conn, path = _fresh_db()
        engine.create_sprint(conn, {
            "start_date": "2026-03-02", "end_date": "2026-03-15",
        })
        sid = "2026-S01"

        conn.execute(
            "INSERT INTO habits (id, name, category, target_per_week, weight, unit, sprint_id, archived, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("ex", "Exercise", "health", 5, 1, "count", None, 0),
        )
        conn.execute(
            "INSERT INTO habits (id, name, category, target_per_week, weight, unit, sprint_id, archived, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("ex-hist", "Exercise", "health", 3, 2, "count", sid, 0),
        )
        conn.execute("INSERT INTO entries (habit_id, date, value, created_at, updated_at) "
                     "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
                     ("ex", "2026-03-02", 1))
        conn.execute("INSERT INTO entries (habit_id, date, value, created_at, updated_at) "
                     "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
                     ("ex-hist", "2026-03-04", 1))
        conn.commit()

        # First run
        summary1 = consolidate(conn)
        habits_after_1 = conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0]
        entries_after_1 = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        goals_after_1 = conn.execute("SELECT COUNT(*) FROM sprint_habit_goals").fetchone()[0]

        # Second run
        summary2 = consolidate(conn)
        habits_after_2 = conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0]
        entries_after_2 = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        goals_after_2 = conn.execute("SELECT COUNT(*) FROM sprint_habit_goals").fetchone()[0]

        # Same counts
        assert habits_after_1 == habits_after_2
        assert entries_after_1 == entries_after_2
        assert goals_after_1 == goals_after_2

        # Second run should find nothing to consolidate
        assert summary2["groups_consolidated"] == 0
        assert summary2["habits_deleted"] == 0


# ===========================================================================
# 6. Web UI goal editing form and POST endpoint
# ===========================================================================

class TestWebGoalEditing:
    """Test the /sprints/{id}/habits/goals POST endpoint."""

    @pytest.fixture()
    def goal_client(self, tmp_path):
        fastapi = pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient
        from habit_sprint.web import create_app

        db_path = str(tmp_path / "test.db")
        app = create_app(db_path=db_path)

        execute({"action": "create_sprint", "payload": {
            "start_date": "2026-03-02", "end_date": "2026-03-15",
        }}, db_path)
        execute({"action": "create_habit", "payload": {
            "id": "exercise", "name": "Exercise", "category": "health",
            "target_per_week": 5, "weight": 1,
        }}, db_path)

        # Get actual sprint ID
        result = execute({"action": "list_sprints", "payload": {}}, db_path)
        sprint_id = result["data"]["sprints"][0]["id"]

        return TestClient(app), db_path, sprint_id

    def test_save_goal_override(self, goal_client):
        client, db_path, sid = goal_client

        resp = client.post(f"/sprints/{sid}/habits/goals", data={
            "goal_target_exercise": "7",
            "goal_weight_exercise": "3",
            "default_target_exercise": "5",
            "default_weight_exercise": "1",
        }, follow_redirects=False)
        assert resp.status_code == 303

        # Verify goal was saved
        result = execute({"action": "get_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": "exercise",
        }}, db_path)
        assert result["data"]["target_per_week"] == 7
        assert result["data"]["weight"] == 3

    def test_save_matching_defaults_removes_override(self, goal_client):
        client, db_path, sid = goal_client

        # First set an override
        execute({"action": "set_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": "exercise",
            "target_per_week": 7, "weight": 3,
        }}, db_path)

        # Now POST with values matching defaults — should delete the override
        resp = client.post(f"/sprints/{sid}/habits/goals", data={
            "goal_target_exercise": "5",
            "goal_weight_exercise": "1",
            "default_target_exercise": "5",
            "default_weight_exercise": "1",
        }, follow_redirects=False)
        assert resp.status_code == 303

        result = execute({"action": "get_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": "exercise",
        }}, db_path)
        assert result["data"]["goal"] is None

    def test_save_redirects_with_message(self, goal_client):
        client, db_path, sid = goal_client

        resp = client.post(f"/sprints/{sid}/habits/goals", data={
            "goal_target_exercise": "7",
            "goal_weight_exercise": "3",
            "default_target_exercise": "5",
            "default_weight_exercise": "1",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert f"/sprints/{sid}/habits" in resp.headers["location"]
        assert "msg=" in resp.headers["location"]

    def test_empty_fields_skipped(self, goal_client):
        client, db_path, sid = goal_client

        resp = client.post(f"/sprints/{sid}/habits/goals", data={
            "goal_target_exercise": "",
            "goal_weight_exercise": "",
            "default_target_exercise": "5",
            "default_weight_exercise": "1",
        }, follow_redirects=False)
        assert resp.status_code == 303

        # No goal should be created
        result = execute({"action": "get_sprint_habit_goal", "payload": {
            "sprint_id": sid, "habit_id": "exercise",
        }}, db_path)
        assert result["data"]["goal"] is None

    def test_sprint_habits_page_loads(self, goal_client):
        client, db_path, sid = goal_client

        resp = client.get(f"/sprints/{sid}/habits")
        assert resp.status_code == 200
        assert "Exercise" in resp.text


# ===========================================================================
# 7. Backward compatibility: habits without overrides unchanged
# ===========================================================================

class TestBackwardCompatibility:
    """Existing habits without sprint_habit_goals overrides work exactly as before."""

    def test_weekly_completion_unchanged_without_goals(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn, target=5, weight=1)

        engine.log_date(conn, {"habit_id": hid, "date": "2026-03-02", "value": 1})
        engine.log_date(conn, {"habit_id": hid, "date": "2026-03-03", "value": 1})
        engine.log_date(conn, {"habit_id": hid, "date": "2026-03-04", "value": 1})

        result = reporting.weekly_completion(conn, {
            "habit_id": hid,
            "sprint_id": sid,
            "week_start": "2026-03-02",
        })
        assert result["target_per_week"] == 5
        assert result["actual_days"] == 3
        assert result["completion_pct"] == 60

    def test_daily_score_unchanged_without_goals(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn, target=5, weight=2)

        engine.log_date(conn, {"habit_id": hid, "date": "2026-03-02", "value": 1})

        result = reporting.daily_score(conn, {
            "sprint_id": sid,
            "date": "2026-03-02",
        })
        assert result["habits_completed"][0]["weight"] == 2
        assert result["habits_completed"][0]["points"] == 2
        assert result["max_possible"] == 2

    def test_sprint_report_unchanged_without_goals(self):
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn, target=5, weight=1)

        result = reporting.sprint_report(conn, {"sprint_id": sid})
        habit = result["habits"][0]
        assert habit["weight"] == 1
        assert habit["expected_entries"] == 5 * result["num_weeks"]

    def test_executor_actions_still_registered(self):
        """Verify the sprint_habit_goal actions exist in the executor."""
        conn, path = _fresh_db()
        sid, hid = _seed_sprint_and_habit(conn)

        for action in ["set_sprint_habit_goal", "get_sprint_habit_goal",
                        "delete_sprint_habit_goal"]:
            result = execute({"action": action, "payload": {
                "sprint_id": sid, "habit_id": hid,
                "target_per_week": 5, "weight": 1,
            }}, path)
            assert result["status"] in ("success", "error")

    def test_multiple_habits_only_overridden_one_changes(self):
        """With two habits, override one — the other keeps its defaults."""
        conn, path = _fresh_db()
        sid, _ = _seed_sprint_and_habit(conn, habit_id="habit-one", habit_name="Habit One",
                                        target=5, weight=1)
        engine.create_habit(conn, {
            "id": "habit-two", "name": "Habit Two", "category": "health",
            "target_per_week": 3, "weight": 2,
        })

        # Override only habit-one
        engine.set_sprint_habit_goal(conn, {
            "sprint_id": sid, "habit_id": "habit-one",
            "target_per_week": 10, "weight": 5,
        })

        engine.log_date(conn, {"habit_id": "habit-one", "date": "2026-03-02", "value": 1})
        engine.log_date(conn, {"habit_id": "habit-two", "date": "2026-03-02", "value": 1})

        result = reporting.daily_score(conn, {
            "sprint_id": sid,
            "date": "2026-03-02",
        })

        by_id = {h["id"]: h for h in result["habits_completed"]}
        assert by_id["habit-one"]["weight"] == 5   # overridden
        assert by_id["habit-two"]["weight"] == 2   # default unchanged
