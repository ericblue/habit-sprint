"""Tests for sprint management functions in engine.py."""

import tempfile
import os

from habit_sprint.db import get_connection
from habit_sprint import engine


def _fresh_conn():
    """Return a connection to a fresh temporary database with migrations applied."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return get_connection(path)


class TestCreateSprint:
    def test_generates_correct_id_format(self):
        conn = _fresh_conn()
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        assert result["id"] == "2026-S01"
        assert result["status"] == "active"

    def test_sequential_id_generation(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-01-01",
            "end_date": "2026-01-14",
        })
        engine.create_sprint(conn, {
            "start_date": "2026-01-15",
            "end_date": "2026-01-28",
        })
        result = engine.create_sprint(conn, {
            "start_date": "2026-02-01",
            "end_date": "2026-02-14",
        })
        assert result["id"] == "2026-S03"

    def test_id_resets_per_year(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2025-12-01",
            "end_date": "2025-12-14",
        })
        result = engine.create_sprint(conn, {
            "start_date": "2026-01-01",
            "end_date": "2026-01-14",
        })
        assert result["id"] == "2026-S01"

    def test_prevents_overlapping_active_sprints(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        try:
            engine.create_sprint(conn, {
                "start_date": "2026-03-10",
                "end_date": "2026-03-20",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "overlaps" in str(e).lower()

    def test_allows_non_overlapping_sprints(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-15",
            "end_date": "2026-03-28",
        })
        assert result["id"] == "2026-S02"

    def test_archived_sprints_dont_block_overlap(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        # Overlapping dates should be allowed since the first sprint is archived
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-05",
            "end_date": "2026-03-20",
        })
        assert result["id"] == "2026-S02"
        assert result["status"] == "active"

    def test_validates_end_date_after_start_date(self):
        conn = _fresh_conn()
        try:
            engine.create_sprint(conn, {
                "start_date": "2026-03-14",
                "end_date": "2026-03-01",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "end_date must be after start_date" in str(e)

    def test_validates_equal_dates(self):
        conn = _fresh_conn()
        try:
            engine.create_sprint(conn, {
                "start_date": "2026-03-01",
                "end_date": "2026-03-01",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "end_date must be after start_date" in str(e)

    def test_validates_invalid_date_format(self):
        conn = _fresh_conn()
        try:
            engine.create_sprint(conn, {
                "start_date": "not-a-date",
                "end_date": "2026-03-14",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid start_date" in str(e)

    def test_validates_invalid_end_date_format(self):
        conn = _fresh_conn()
        try:
            engine.create_sprint(conn, {
                "start_date": "2026-03-01",
                "end_date": "bad",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid end_date" in str(e)

    def test_stores_theme_and_focus_goals(self):
        conn = _fresh_conn()
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
            "theme": "Focus Phase",
            "focus_goals": ["Read daily", "Exercise"],
        })
        assert result["theme"] == "Focus Phase"
        assert result["focus_goals"] == ["Read daily", "Exercise"]

    def test_defaults_focus_goals_to_empty_list(self):
        conn = _fresh_conn()
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        assert result["focus_goals"] == []

    def test_sets_timestamps(self):
        conn = _fresh_conn()
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        assert result["created_at"] is not None
        assert result["updated_at"] is not None


class TestUpdateSprint:
    def test_updates_theme(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
            "theme": "Original",
        })
        result = engine.update_sprint(conn, {
            "sprint_id": "2026-S01",
            "theme": "Updated Theme",
        })
        assert result["theme"] == "Updated Theme"

    def test_updates_focus_goals(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        result = engine.update_sprint(conn, {
            "sprint_id": "2026-S01",
            "focus_goals": ["Goal A", "Goal B"],
        })
        assert result["focus_goals"] == ["Goal A", "Goal B"]

    def test_updates_both_theme_and_goals(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        result = engine.update_sprint(conn, {
            "sprint_id": "2026-S01",
            "theme": "New Theme",
            "focus_goals": ["X"],
        })
        assert result["theme"] == "New Theme"
        assert result["focus_goals"] == ["X"]

    def test_update_changes_updated_at(self):
        conn = _fresh_conn()
        created = engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        updated = engine.update_sprint(conn, {
            "sprint_id": "2026-S01",
            "theme": "New",
        })
        assert updated["updated_at"] >= created["updated_at"]

    def test_update_nonexistent_sprint_raises(self):
        conn = _fresh_conn()
        try:
            engine.update_sprint(conn, {
                "sprint_id": "2026-S99",
                "theme": "Nothing",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Sprint not found" in str(e)

    def test_update_with_no_changes_returns_current(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
            "theme": "Same",
        })
        result = engine.update_sprint(conn, {"sprint_id": "2026-S01"})
        assert result["theme"] == "Same"


class TestListSprints:
    def test_list_all_sprints(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-01-01",
            "end_date": "2026-01-14",
        })
        engine.create_sprint(conn, {
            "start_date": "2026-02-01",
            "end_date": "2026-02-14",
        })
        result = engine.list_sprints(conn, {})
        assert len(result["sprints"]) == 2

    def test_list_with_status_filter_active(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-01-01",
            "end_date": "2026-01-14",
        })
        engine.create_sprint(conn, {
            "start_date": "2026-02-01",
            "end_date": "2026-02-14",
        })
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        result = engine.list_sprints(conn, {"status": "active"})
        assert len(result["sprints"]) == 1
        assert result["sprints"][0]["id"] == "2026-S02"

    def test_list_with_status_filter_archived(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-01-01",
            "end_date": "2026-01-14",
        })
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        engine.create_sprint(conn, {
            "start_date": "2026-02-01",
            "end_date": "2026-02-14",
        })
        result = engine.list_sprints(conn, {"status": "archived"})
        assert len(result["sprints"]) == 1
        assert result["sprints"][0]["id"] == "2026-S01"

    def test_list_with_all_filter_returns_everything(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-01-01",
            "end_date": "2026-01-14",
        })
        engine.create_sprint(conn, {
            "start_date": "2026-02-01",
            "end_date": "2026-02-14",
        })
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        result = engine.list_sprints(conn, {"status": "all"})
        assert len(result["sprints"]) == 2

    def test_list_empty_db(self):
        conn = _fresh_conn()
        result = engine.list_sprints(conn, {})
        assert result["sprints"] == []

    def test_list_ordered_by_start_date(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        engine.create_sprint(conn, {
            "start_date": "2026-01-01",
            "end_date": "2026-01-14",
        })
        result = engine.list_sprints(conn, {})
        assert result["sprints"][0]["start_date"] == "2026-01-01"
        assert result["sprints"][1]["start_date"] == "2026-03-01"


class TestArchiveSprint:
    def test_archive_sets_status(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        result = engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        assert result["status"] == "archived"

    def test_archive_updates_timestamp(self):
        conn = _fresh_conn()
        created = engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        archived = engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        assert archived["updated_at"] >= created["updated_at"]

    def test_archive_nonexistent_sprint_raises(self):
        conn = _fresh_conn()
        try:
            engine.archive_sprint(conn, {"sprint_id": "2026-S99"})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Sprint not found" in str(e)


class TestGetActiveSprint:
    def test_returns_active_sprint(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
            "theme": "Active One",
        })
        result = engine.get_active_sprint(conn, {})
        assert result["id"] == "2026-S01"
        assert result["theme"] == "Active One"
        assert result["status"] == "active"

    def test_errors_when_no_active_sprint(self):
        conn = _fresh_conn()
        try:
            engine.get_active_sprint(conn, {})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No active sprint found" in str(e)

    def test_errors_when_all_archived(self):
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        try:
            engine.get_active_sprint(conn, {})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No active sprint found" in str(e)

    def test_returns_earliest_active_when_multiple(self):
        """If somehow multiple active sprints exist (non-overlapping), return earliest."""
        conn = _fresh_conn()
        engine.create_sprint(conn, {
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
        })
        engine.create_sprint(conn, {
            "start_date": "2026-04-01",
            "end_date": "2026-04-14",
        })
        result = engine.get_active_sprint(conn, {})
        assert result["id"] == "2026-S01"
