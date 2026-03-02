"""Comprehensive error handling tests for PRD Section 11 compliance.

Every validation rule from the PRD should produce a clear, human-readable
error message that includes the specific invalid value.
"""

import tempfile
import os

import pytest

from habit_sprint.db import get_connection
from habit_sprint import engine


def _fresh_conn():
    """Return a connection to a fresh temporary database with migrations applied."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return get_connection(path)


def _setup_sprint(conn, start="2026-03-01", end="2026-03-14"):
    """Helper to create a sprint."""
    return engine.create_sprint(conn, {
        "start_date": start,
        "end_date": end,
    })


def _setup_habit(conn, habit_id="reading"):
    """Create a sprint and habit for tests."""
    _setup_sprint(conn)
    return engine.create_habit(conn, {
        "id": habit_id,
        "name": "Reading",
        "category": "cognitive",
        "target_per_week": 5,
    })


# ===========================================================================
# Sprint overlap detection — various edge cases
# ===========================================================================

class TestSprintOverlapDetection:
    """PRD: Prevent overlapping active sprints with clear error messages."""

    def test_partial_overlap_new_starts_before_existing_ends(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-14")
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-10",
                "end_date": "2026-03-24",
            })

    def test_partial_overlap_new_ends_after_existing_starts(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-15", "2026-03-28")
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-01",
                "end_date": "2026-03-20",
            })

    def test_exact_same_dates(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-14")
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-01",
                "end_date": "2026-03-14",
            })

    def test_one_day_overlap_at_end(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-14")
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-14",
                "end_date": "2026-03-28",
            })

    def test_one_day_overlap_at_start(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-15", "2026-03-28")
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-01",
                "end_date": "2026-03-15",
            })

    def test_new_sprint_completely_inside_existing(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-28")
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-10",
                "end_date": "2026-03-20",
            })

    def test_existing_sprint_completely_inside_new(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-10", "2026-03-20")
        with pytest.raises(ValueError, match="overlaps"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-01",
                "end_date": "2026-03-28",
            })

    def test_adjacent_sprints_no_overlap(self):
        """Sprints that are adjacent (end+1 = start) should not overlap."""
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-14")
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-15",
            "end_date": "2026-03-28",
        })
        assert result["id"] == "2026-S02"

    def test_overlap_error_includes_conflicting_sprint_id(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-14")
        with pytest.raises(ValueError, match="2026-S01"):
            engine.create_sprint(conn, {
                "start_date": "2026-03-10",
                "end_date": "2026-03-24",
            })

    def test_overlap_error_includes_conflicting_dates(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-14")
        with pytest.raises(ValueError) as exc_info:
            engine.create_sprint(conn, {
                "start_date": "2026-03-10",
                "end_date": "2026-03-24",
            })
        msg = str(exc_info.value)
        assert "2026-03-01" in msg
        assert "2026-03-14" in msg
        assert "2026-S01" in msg

    def test_overlap_error_includes_requested_dates(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-14")
        with pytest.raises(ValueError) as exc_info:
            engine.create_sprint(conn, {
                "start_date": "2026-03-10",
                "end_date": "2026-03-24",
            })
        msg = str(exc_info.value)
        assert "2026-03-10" in msg
        assert "2026-03-24" in msg

    def test_archived_sprint_does_not_cause_overlap(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-14")
        engine.archive_sprint(conn, {"sprint_id": "2026-S01"})
        result = engine.create_sprint(conn, {
            "start_date": "2026-03-05",
            "end_date": "2026-03-20",
        })
        assert result["status"] == "active"


# ===========================================================================
# Archived habit rejection
# ===========================================================================

class TestArchivedHabitRejection:
    """PRD: Prevent logging to archived habits with clear error messages."""

    def test_log_date_to_archived_habit(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.archive_habit(conn, {"id": "reading"})
        with pytest.raises(ValueError, match="archived.*reading"):
            engine.log_date(conn, {
                "habit_id": "reading",
                "date": "2026-03-01",
            })

    def test_log_range_to_archived_habit(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.archive_habit(conn, {"id": "reading"})
        with pytest.raises(ValueError, match="archived.*reading"):
            engine.log_range(conn, {
                "habit_id": "reading",
                "start_date": "2026-03-01",
                "end_date": "2026-03-05",
            })

    def test_bulk_set_to_archived_habit(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.archive_habit(conn, {"id": "reading"})
        with pytest.raises(ValueError, match="archived.*reading"):
            engine.bulk_set(conn, {
                "habit_id": "reading",
                "dates": ["2026-03-01"],
            })

    def test_delete_entry_for_archived_habit(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.log_date(conn, {"habit_id": "reading", "date": "2026-03-01"})
        engine.archive_habit(conn, {"id": "reading"})
        with pytest.raises(ValueError, match="archived.*reading"):
            engine.delete_entry(conn, {
                "habit_id": "reading",
                "date": "2026-03-01",
            })

    def test_update_archived_habit(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        engine.archive_habit(conn, {"id": "reading"})
        with pytest.raises(ValueError, match="archived.*reading"):
            engine.update_habit(conn, {
                "id": "reading",
                "name": "Should Fail",
            })

    def test_archived_error_includes_habit_id(self):
        """Every archived-habit error must include the habit ID."""
        conn = _fresh_conn()
        _setup_habit(conn, "daily-walk")
        engine.archive_habit(conn, {"id": "daily-walk"})
        with pytest.raises(ValueError) as exc_info:
            engine.log_date(conn, {
                "habit_id": "daily-walk",
                "date": "2026-03-01",
            })
        assert "daily-walk" in str(exc_info.value)


# ===========================================================================
# Non-existent resource errors
# ===========================================================================

class TestNonExistentResourceErrors:
    """Error messages for non-existent resources must include the ID."""

    def test_update_sprint_not_found_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.update_sprint(conn, {
                "sprint_id": "2026-S99",
                "theme": "Nothing",
            })
        assert "2026-S99" in str(exc_info.value)

    def test_archive_sprint_not_found_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.archive_sprint(conn, {"sprint_id": "2099-S01"})
        assert "2099-S01" in str(exc_info.value)

    def test_update_habit_not_found_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.update_habit(conn, {
                "id": "no-such-habit",
                "name": "Nothing",
            })
        assert "no-such-habit" in str(exc_info.value)

    def test_archive_habit_not_found_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.archive_habit(conn, {"id": "ghost-habit"})
        assert "ghost-habit" in str(exc_info.value)

    def test_log_date_nonexistent_habit_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.log_date(conn, {
                "habit_id": "nonexistent",
                "date": "2026-03-01",
            })
        assert "nonexistent" in str(exc_info.value)

    def test_log_range_nonexistent_habit_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.log_range(conn, {
                "habit_id": "missing-habit",
                "start_date": "2026-03-01",
                "end_date": "2026-03-05",
            })
        assert "missing-habit" in str(exc_info.value)

    def test_bulk_set_nonexistent_habit_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.bulk_set(conn, {
                "habit_id": "no-habit",
                "dates": ["2026-03-01"],
            })
        assert "no-habit" in str(exc_info.value)

    def test_delete_entry_nonexistent_habit_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.delete_entry(conn, {
                "habit_id": "vanished",
                "date": "2026-03-01",
            })
        assert "vanished" in str(exc_info.value)

    def test_add_retro_nonexistent_sprint_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.add_retro(conn, {
                "sprint_id": "2099-S42",
                "what_went_well": "Nothing",
            })
        assert "2099-S42" in str(exc_info.value)

    def test_get_retro_nonexistent_sprint_includes_id(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.get_retro(conn, {"sprint_id": "2099-S77"})
        assert "2099-S77" in str(exc_info.value)

    def test_no_active_sprint_message(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError, match="No active sprint found"):
            engine.get_active_sprint(conn, {})


# ===========================================================================
# Invalid date format errors
# ===========================================================================

class TestInvalidDateErrors:
    """PRD: Validate ISO date format with clear error messages."""

    def test_invalid_start_date_in_create_sprint(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_sprint(conn, {
                "start_date": "02-28-2026",
                "end_date": "2026-03-14",
            })
        msg = str(exc_info.value)
        assert "02-28-2026" in msg

    def test_invalid_end_date_in_create_sprint(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_sprint(conn, {
                "start_date": "2026-03-01",
                "end_date": "not-a-date",
            })
        msg = str(exc_info.value)
        assert "not-a-date" in msg

    def test_invalid_date_in_log_date(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        with pytest.raises(ValueError) as exc_info:
            engine.log_date(conn, {
                "habit_id": "reading",
                "date": "2026/03/01",
            })
        msg = str(exc_info.value)
        assert "2026/03/01" in msg

    def test_invalid_start_date_in_log_range(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        with pytest.raises(ValueError) as exc_info:
            engine.log_range(conn, {
                "habit_id": "reading",
                "start_date": "bad-date",
                "end_date": "2026-03-05",
            })
        assert "bad-date" in str(exc_info.value)

    def test_invalid_end_date_in_log_range(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        with pytest.raises(ValueError) as exc_info:
            engine.log_range(conn, {
                "habit_id": "reading",
                "start_date": "2026-03-01",
                "end_date": "garbage",
            })
        assert "garbage" in str(exc_info.value)

    def test_invalid_date_in_bulk_set(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        with pytest.raises(ValueError) as exc_info:
            engine.bulk_set(conn, {
                "habit_id": "reading",
                "dates": ["2026-03-01", "nope"],
            })
        assert "nope" in str(exc_info.value)

    def test_invalid_date_in_delete_entry(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        with pytest.raises(ValueError) as exc_info:
            engine.delete_entry(conn, {
                "habit_id": "reading",
                "date": "13-2026-01",
            })
        assert "13-2026-01" in str(exc_info.value)

    def test_end_date_before_start_date_includes_values(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_sprint(conn, {
                "start_date": "2026-03-14",
                "end_date": "2026-03-01",
            })
        msg = str(exc_info.value)
        assert "end_date must be after start_date" in msg
        assert "2026-03-14" in msg
        assert "2026-03-01" in msg

    def test_equal_dates_includes_values(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_sprint(conn, {
                "start_date": "2026-03-01",
                "end_date": "2026-03-01",
            })
        msg = str(exc_info.value)
        assert "end_date must be after start_date" in msg
        assert "2026-03-01" in msg

    def test_log_range_end_before_start_includes_values(self):
        conn = _fresh_conn()
        _setup_habit(conn)
        with pytest.raises(ValueError) as exc_info:
            engine.log_range(conn, {
                "habit_id": "reading",
                "start_date": "2026-03-10",
                "end_date": "2026-03-01",
            })
        msg = str(exc_info.value)
        assert "2026-03-10" in msg
        assert "2026-03-01" in msg


# ===========================================================================
# Invalid enum, slug, and range errors
# ===========================================================================

class TestInvalidValueErrors:
    """PRD: Invalid enums, slugs, and out-of-range values must be caught."""

    def test_invalid_habit_slug_includes_value(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_habit(conn, {
                "id": "Bad_Slug!",
                "name": "Test",
                "category": "test",
                "target_per_week": 3,
            })
        assert "Bad_Slug!" in str(exc_info.value)

    def test_invalid_unit_includes_value(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_habit(conn, {
                "id": "test",
                "name": "Test",
                "category": "test",
                "target_per_week": 3,
                "unit": "miles",
            })
        msg = str(exc_info.value)
        assert "miles" in msg
        assert "count" in msg  # shows allowed values

    def test_target_per_week_too_high_includes_value(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_habit(conn, {
                "id": "test",
                "name": "Test",
                "category": "test",
                "target_per_week": 10,
            })
        assert "10" in str(exc_info.value)

    def test_target_per_week_too_low_includes_value(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_habit(conn, {
                "id": "test",
                "name": "Test",
                "category": "test",
                "target_per_week": 0,
            })
        assert "0" in str(exc_info.value)

    def test_weight_too_high_includes_value(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_habit(conn, {
                "id": "test",
                "name": "Test",
                "category": "test",
                "target_per_week": 3,
                "weight": 5,
            })
        assert "5" in str(exc_info.value)

    def test_weight_too_low_includes_value(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_habit(conn, {
                "id": "test",
                "name": "Test",
                "category": "test",
                "target_per_week": 3,
                "weight": 0,
            })
        assert "0" in str(exc_info.value)


# ===========================================================================
# Error message quality — human-readable and specific
# ===========================================================================

class TestErrorMessageQuality:
    """Verify that all error messages are human-readable and actionable."""

    def test_sprint_not_found_is_human_readable(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.update_sprint(conn, {
                "sprint_id": "2026-S42",
                "theme": "X",
            })
        msg = str(exc_info.value)
        assert "Sprint not found" in msg
        assert "2026-S42" in msg

    def test_habit_not_found_is_human_readable(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.update_habit(conn, {
                "id": "mystery-habit",
                "name": "X",
            })
        msg = str(exc_info.value)
        assert "Habit not found" in msg
        assert "mystery-habit" in msg

    def test_archived_habit_error_is_human_readable(self):
        conn = _fresh_conn()
        _setup_habit(conn, "my-habit")
        engine.archive_habit(conn, {"id": "my-habit"})
        with pytest.raises(ValueError) as exc_info:
            engine.log_date(conn, {
                "habit_id": "my-habit",
                "date": "2026-03-01",
            })
        msg = str(exc_info.value)
        assert "archived" in msg.lower()
        assert "my-habit" in msg

    def test_overlap_error_is_human_readable(self):
        conn = _fresh_conn()
        _setup_sprint(conn, "2026-03-01", "2026-03-14")
        with pytest.raises(ValueError) as exc_info:
            engine.create_sprint(conn, {
                "start_date": "2026-03-10",
                "end_date": "2026-03-24",
            })
        msg = str(exc_info.value)
        assert "Cannot create sprint" in msg
        assert "overlaps" in msg
        assert "2026-S01" in msg

    def test_invalid_date_error_is_human_readable(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_sprint(conn, {
                "start_date": "March 1st",
                "end_date": "2026-03-14",
            })
        msg = str(exc_info.value)
        assert "Invalid" in msg
        assert "March 1st" in msg

    def test_retro_not_found_is_human_readable(self):
        conn = _fresh_conn()
        _setup_sprint(conn)
        with pytest.raises(ValueError) as exc_info:
            engine.get_retro(conn, {"sprint_id": "2026-S01"})
        msg = str(exc_info.value)
        assert "No retrospective found" in msg
        assert "2026-S01" in msg

    def test_invalid_slug_error_is_human_readable(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_habit(conn, {
                "id": "UPPER_case",
                "name": "Test",
                "category": "test",
                "target_per_week": 3,
            })
        msg = str(exc_info.value)
        assert "UPPER_case" in msg
        assert "lowercase" in msg.lower()

    def test_invalid_unit_error_is_human_readable(self):
        conn = _fresh_conn()
        with pytest.raises(ValueError) as exc_info:
            engine.create_habit(conn, {
                "id": "test",
                "name": "Test",
                "category": "test",
                "target_per_week": 3,
                "unit": "kilometers",
            })
        msg = str(exc_info.value)
        assert "kilometers" in msg
        assert "count" in msg
        assert "minutes" in msg
