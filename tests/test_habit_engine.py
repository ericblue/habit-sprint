"""Tests for habit management functions in engine.py."""

import tempfile
import os

from habit_sprint.db import get_connection
from habit_sprint import engine


def _fresh_conn():
    """Return a connection to a fresh temporary database with migrations applied."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return get_connection(path)


def _create_sprint(conn):
    """Helper to create a sprint for sprint-scoped habits."""
    return engine.create_sprint(conn, {
        "start_date": "2026-03-01",
        "end_date": "2026-03-14",
    })


def _create_default_habit(conn, **overrides):
    """Helper to create a habit with sensible defaults."""
    data = {
        "id": "reading",
        "name": "Reading",
        "category": "cognitive",
        "target_per_week": 5,
    }
    data.update(overrides)
    return engine.create_habit(conn, data)


class TestCreateHabit:
    def test_creates_habit_with_valid_data(self):
        conn = _fresh_conn()
        result = _create_default_habit(conn)
        assert result["id"] == "reading"
        assert result["name"] == "Reading"
        assert result["category"] == "cognitive"
        assert result["target_per_week"] == 5
        assert result["weight"] == 1
        assert result["unit"] == "count"
        assert result["archived"] == 0
        assert result["sprint_id"] is None
        assert result["created_at"] is not None
        assert result["updated_at"] is not None

    def test_creates_habit_with_all_fields(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        result = engine.create_habit(conn, {
            "id": "daily-walk",
            "name": "Daily Walk",
            "category": "health",
            "target_per_week": 7,
            "weight": 3,
            "unit": "minutes",
            "sprint_id": sprint["id"],
        })
        assert result["id"] == "daily-walk"
        assert result["weight"] == 3
        assert result["unit"] == "minutes"
        assert result["sprint_id"] == sprint["id"]

    def test_rejects_uppercase_slug(self):
        conn = _fresh_conn()
        try:
            _create_default_habit(conn, id="Reading")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid habit id" in str(e)

    def test_rejects_slug_with_spaces(self):
        conn = _fresh_conn()
        try:
            _create_default_habit(conn, id="daily walk")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid habit id" in str(e)

    def test_rejects_slug_with_numbers(self):
        conn = _fresh_conn()
        try:
            _create_default_habit(conn, id="habit123")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid habit id" in str(e)

    def test_rejects_slug_with_underscores(self):
        conn = _fresh_conn()
        try:
            _create_default_habit(conn, id="daily_walk")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid habit id" in str(e)

    def test_accepts_hyphenated_slug(self):
        conn = _fresh_conn()
        result = _create_default_habit(conn, id="daily-morning-walk")
        assert result["id"] == "daily-morning-walk"

    def test_accepts_single_word_slug(self):
        conn = _fresh_conn()
        result = _create_default_habit(conn, id="reading")
        assert result["id"] == "reading"


class TestUpdateHabit:
    def test_updates_only_provided_fields(self):
        conn = _fresh_conn()
        _create_default_habit(conn)
        result = engine.update_habit(conn, {
            "id": "reading",
            "name": "Deep Reading",
        })
        assert result["name"] == "Deep Reading"
        # Other fields remain unchanged
        assert result["category"] == "cognitive"
        assert result["target_per_week"] == 5

    def test_updates_multiple_fields(self):
        conn = _fresh_conn()
        _create_default_habit(conn)
        result = engine.update_habit(conn, {
            "id": "reading",
            "name": "Speed Reading",
            "target_per_week": 3,
            "weight": 2,
        })
        assert result["name"] == "Speed Reading"
        assert result["target_per_week"] == 3
        assert result["weight"] == 2

    def test_updates_timestamp(self):
        conn = _fresh_conn()
        created = _create_default_habit(conn)
        updated = engine.update_habit(conn, {
            "id": "reading",
            "name": "Updated",
        })
        assert updated["updated_at"] >= created["updated_at"]

    def test_rejects_update_to_archived_habit(self):
        conn = _fresh_conn()
        _create_default_habit(conn)
        engine.archive_habit(conn, {"id": "reading"})
        try:
            engine.update_habit(conn, {
                "id": "reading",
                "name": "Should Fail",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "archived" in str(e).lower()

    def test_update_nonexistent_habit_raises(self):
        conn = _fresh_conn()
        try:
            engine.update_habit(conn, {
                "id": "nonexistent",
                "name": "Nothing",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not found" in str(e).lower()

    def test_no_changes_returns_current(self):
        conn = _fresh_conn()
        created = _create_default_habit(conn)
        result = engine.update_habit(conn, {"id": "reading"})
        assert result["name"] == created["name"]


class TestArchiveHabit:
    def test_sets_archived_flag(self):
        conn = _fresh_conn()
        _create_default_habit(conn)
        result = engine.archive_habit(conn, {"id": "reading"})
        assert result["archived"] == 1

    def test_updates_timestamp(self):
        conn = _fresh_conn()
        created = _create_default_habit(conn)
        archived = engine.archive_habit(conn, {"id": "reading"})
        assert archived["updated_at"] >= created["updated_at"]

    def test_archive_nonexistent_raises(self):
        conn = _fresh_conn()
        try:
            engine.archive_habit(conn, {"id": "nonexistent"})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not found" in str(e).lower()


class TestListHabits:
    def test_lists_all_active_habits(self):
        conn = _fresh_conn()
        _create_default_habit(conn, id="reading")
        _create_default_habit(conn, id="exercise", name="Exercise", category="health")
        result = engine.list_habits(conn, {})
        assert len(result["habits"]) == 2

    def test_sprint_filter_includes_global_habits(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        # Global habit (no sprint_id)
        _create_default_habit(conn, id="reading")
        # Sprint-scoped habit
        _create_default_habit(
            conn, id="sprint-task", name="Sprint Task",
            category="projects", sprint_id=sprint["id"],
        )
        # Habit in a different sprint (create a second sprint first)
        engine.create_sprint(conn, {
            "start_date": "2026-04-01",
            "end_date": "2026-04-14",
        })
        _create_default_habit(
            conn, id="other-sprint", name="Other Sprint",
            category="projects", sprint_id="2026-S02",
        )

        result = engine.list_habits(conn, {"sprint_id": sprint["id"]})
        habit_ids = [h["id"] for h in result["habits"]]
        assert "reading" in habit_ids       # global habit included
        assert "sprint-task" in habit_ids   # sprint-scoped habit included
        assert "other-sprint" not in habit_ids  # different sprint excluded

    def test_category_filter(self):
        conn = _fresh_conn()
        _create_default_habit(conn, id="reading", category="cognitive")
        _create_default_habit(conn, id="exercise", name="Exercise", category="health")
        _create_default_habit(conn, id="writing", name="Writing", category="cognitive")

        result = engine.list_habits(conn, {"category": "cognitive"})
        assert len(result["habits"]) == 2
        categories = {h["category"] for h in result["habits"]}
        assert categories == {"cognitive"}

    def test_excludes_archived_by_default(self):
        conn = _fresh_conn()
        _create_default_habit(conn, id="reading")
        _create_default_habit(conn, id="exercise", name="Exercise", category="health")
        engine.archive_habit(conn, {"id": "exercise"})

        result = engine.list_habits(conn, {})
        assert len(result["habits"]) == 1
        assert result["habits"][0]["id"] == "reading"

    def test_include_archived_flag(self):
        conn = _fresh_conn()
        _create_default_habit(conn, id="reading")
        _create_default_habit(conn, id="exercise", name="Exercise", category="health")
        engine.archive_habit(conn, {"id": "exercise"})

        result = engine.list_habits(conn, {"include_archived": True})
        assert len(result["habits"]) == 2

    def test_empty_list(self):
        conn = _fresh_conn()
        result = engine.list_habits(conn, {})
        assert result["habits"] == []

    def test_combined_sprint_and_category_filter(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        # Global cognitive habit
        _create_default_habit(conn, id="reading", category="cognitive")
        # Global health habit
        _create_default_habit(conn, id="exercise", name="Exercise", category="health")
        # Sprint-scoped cognitive habit
        _create_default_habit(
            conn, id="study", name="Study", category="cognitive",
            sprint_id=sprint["id"],
        )

        result = engine.list_habits(conn, {
            "sprint_id": sprint["id"],
            "category": "cognitive",
        })
        habit_ids = [h["id"] for h in result["habits"]]
        assert "reading" in habit_ids   # global + cognitive
        assert "study" in habit_ids     # sprint + cognitive
        assert "exercise" not in habit_ids  # wrong category
