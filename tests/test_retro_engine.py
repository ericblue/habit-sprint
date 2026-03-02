"""Tests for retrospective functions in engine.py."""

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
    """Helper to create a sprint and return it."""
    return engine.create_sprint(conn, {
        "start_date": "2026-03-01",
        "end_date": "2026-03-14",
    })


class TestAddRetro:
    def test_creates_new_retro(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        result = engine.add_retro(conn, {
            "sprint_id": sprint["id"],
            "what_went_well": "Stayed consistent",
            "what_to_improve": "Morning routine",
            "ideas": "Try time-blocking",
        })
        assert result["sprint_id"] == sprint["id"]
        assert result["what_went_well"] == "Stayed consistent"
        assert result["what_to_improve"] == "Morning routine"
        assert result["ideas"] == "Try time-blocking"
        assert result["created_at"] is not None
        assert result["updated_at"] is not None

    def test_upsert_updates_existing_retro(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        engine.add_retro(conn, {
            "sprint_id": sprint["id"],
            "what_went_well": "Original",
        })
        result = engine.add_retro(conn, {
            "sprint_id": sprint["id"],
            "what_went_well": "Updated",
            "what_to_improve": "Added later",
        })
        assert result["what_went_well"] == "Updated"
        assert result["what_to_improve"] == "Added later"
        # Only one retro should exist for this sprint
        count = conn.execute(
            "SELECT COUNT(*) FROM retros WHERE sprint_id = ?", (sprint["id"],)
        ).fetchone()[0]
        assert count == 1

    def test_optional_fields_can_be_omitted(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        result = engine.add_retro(conn, {
            "sprint_id": sprint["id"],
            "what_went_well": "Just this one",
        })
        assert result["what_went_well"] == "Just this one"
        assert result["what_to_improve"] is None
        assert result["ideas"] is None

    def test_all_fields_optional(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        result = engine.add_retro(conn, {
            "sprint_id": sprint["id"],
        })
        assert result["what_went_well"] is None
        assert result["what_to_improve"] is None
        assert result["ideas"] is None

    def test_fails_if_sprint_does_not_exist(self):
        conn = _fresh_conn()
        try:
            engine.add_retro(conn, {
                "sprint_id": "2026-S99",
                "what_went_well": "Nothing",
            })
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Sprint not found" in str(e)


class TestGetRetro:
    def test_returns_retro_data(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        engine.add_retro(conn, {
            "sprint_id": sprint["id"],
            "what_went_well": "Great progress",
            "what_to_improve": "Sleep schedule",
            "ideas": "Use alarms",
        })
        result = engine.get_retro(conn, {"sprint_id": sprint["id"]})
        assert result["sprint_id"] == sprint["id"]
        assert result["what_went_well"] == "Great progress"
        assert result["what_to_improve"] == "Sleep schedule"
        assert result["ideas"] == "Use alarms"

    def test_returns_error_when_no_retro_exists(self):
        conn = _fresh_conn()
        sprint = _create_sprint(conn)
        try:
            engine.get_retro(conn, {"sprint_id": sprint["id"]})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No retrospective found" in str(e)

    def test_returns_error_for_nonexistent_sprint(self):
        conn = _fresh_conn()
        try:
            engine.get_retro(conn, {"sprint_id": "2026-S99"})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "No retrospective found" in str(e)
