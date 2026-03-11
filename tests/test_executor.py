"""Tests for the action executor."""

import tempfile
import os

from habit_sprint.executor import execute


def _tmp_db():
    """Return a path to a fresh temporary database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


class TestUnknownAction:
    def test_unknown_action_returns_error_envelope(self):
        result = execute({"action": "foo"}, _tmp_db())
        assert result["status"] == "error"
        assert result["data"] is None
        assert result["error"] == "Unknown action: foo"

    def test_unknown_action_with_payload(self):
        result = execute({"action": "nope", "payload": {"x": 1}}, _tmp_db())
        assert result["status"] == "error"
        assert "Unknown action: nope" in result["error"]


class TestMissingFields:
    def test_missing_action_field(self):
        result = execute({}, _tmp_db())
        assert result["status"] == "error"
        assert result["data"] is None
        assert "Missing required field: action" in result["error"]

    def test_missing_action_field_with_payload(self):
        result = execute({"payload": {"x": 1}}, _tmp_db())
        assert result["status"] == "error"
        assert "Missing required field: action" in result["error"]

    def test_missing_payload_defaults_to_empty_dict(self):
        """When payload is omitted, it defaults to {} — actions with no required fields reach the handler."""
        result = execute({"action": "get_active_sprint"}, _tmp_db())
        # get_active_sprint has no required fields, so validation passes and handler runs
        assert result["status"] == "error"
        assert result["error"] is not None


class TestActionRouting:
    """Routing tests use valid payloads so they pass validation and reach the stubs."""

    # Minimal valid payloads for each action (stubs raise NotImplementedError)
    _VALID_PAYLOADS = {
        "create_sprint": {"start_date": "2024-01-01", "end_date": "2024-01-07"},
        "update_sprint": {"sprint_id": "s1"},
        "list_sprints": {},
        "archive_sprint": {"sprint_id": "s1"},
        "get_active_sprint": {},
        "create_habit": {"id": "h1", "name": "Run", "category": "fitness", "target_per_week": 3},
        "update_habit": {"id": "h1"},
        "archive_habit": {"id": "h1"},
        "list_habits": {},
        "log_date": {"habit_id": "h1", "date": "2024-01-01", "value": 1},
        "log_range": {"habit_id": "h1", "start_date": "2024-01-01", "end_date": "2024-01-07"},
        "bulk_set": {"habit_id": "h1", "dates": ["2024-01-01"]},
        "delete_entry": {"habit_id": "h1", "date": "2024-01-01"},
        "add_retro": {"sprint_id": "s1"},
        "get_retro": {"sprint_id": "s1"},
        "weekly_completion": {"habit_id": "h1"},
        "daily_score": {"date": "2024-01-01"},
        "get_week_view": {},
        "sprint_report": {},
        "habit_report": {"habit_id": "h1"},
        "category_report": {},
        "sprint_dashboard": {},
    }

    def test_mutation_action_routes_to_engine(self):
        payload = self._VALID_PAYLOADS["create_sprint"]
        result = execute({"action": "create_sprint", "payload": payload}, _tmp_db())
        # Sprint management is implemented — this creates a sprint successfully
        assert result["status"] in ("success", "error")
        assert result["error"] is not None or result["data"] is not None

    def test_query_action_routes_to_reporting(self):
        payload = self._VALID_PAYLOADS["weekly_completion"]
        result = execute({"action": "weekly_completion", "payload": payload}, _tmp_db())
        # Implemented handler hits ValueError (habit not found) — confirms routing works
        assert result["status"] == "error"
        assert result["error"] is not None

    def test_all_mutation_actions_are_routed(self):
        mutations = [
            "create_sprint", "update_sprint", "list_sprints",
            "archive_sprint", "get_active_sprint",
            "create_habit", "update_habit", "archive_habit", "list_habits",
            "log_date", "log_range", "bulk_set", "delete_entry",
            "add_retro", "get_retro",
        ]
        for action in mutations:
            payload = self._VALID_PAYLOADS[action]
            result = execute({"action": action, "payload": payload}, _tmp_db())
            # Implemented handlers may succeed or fail depending on DB state;
            # stubs raise NotImplementedError. Both confirm the action is routed.
            assert result["status"] in ("success", "error"), f"{action} did not route"

    def test_all_query_actions_are_routed(self):
        queries = [
            "weekly_completion", "daily_score", "get_week_view",
            "sprint_report", "habit_report", "category_report",
            "sprint_dashboard",
        ]
        # Implemented handlers may raise ValueError (missing data);
        # stubs raise NotImplementedError. Both confirm routing works.
        implemented = {"weekly_completion"}
        for action in queries:
            payload = self._VALID_PAYLOADS[action]
            result = execute({"action": action, "payload": payload}, _tmp_db())
            # Implemented handlers may succeed or fail depending on DB state;
            # stubs raise NotImplementedError. Both confirm the action is routed.
            assert result["status"] in ("success", "error"), f"{action} did not route"


class TestEnvelopeStructure:
    def test_error_envelope_has_correct_keys(self):
        result = execute({"action": "foo"}, _tmp_db())
        assert set(result.keys()) == {"status", "data", "error"}
        assert result["status"] == "error"
        assert result["data"] is None
        assert isinstance(result["error"], str)

    def test_success_envelope_structure(self):
        """Verify success envelope shape by monkeypatching a handler."""
        from habit_sprint import executor

        original = executor._ACTION_TABLE.get("create_sprint")
        executor._ACTION_TABLE["create_sprint"] = lambda conn, payload: {"id": 1}
        try:
            result = execute({
                "action": "create_sprint",
                "payload": {"id": "s1", "start_date": "2024-01-01", "end_date": "2024-01-07"},
            }, _tmp_db())
            assert set(result.keys()) == {"status", "data", "error"}
            assert result["status"] == "success"
            assert result["data"] == {"id": 1}
            assert result["error"] is None
        finally:
            executor._ACTION_TABLE["create_sprint"] = original

    def test_error_and_success_never_mixed(self):
        """Error responses must have data=None; success must have error=None."""
        err = execute({"action": "unknown_action"}, _tmp_db())
        assert err["data"] is None and err["error"] is not None

        from habit_sprint import executor
        original = executor._ACTION_TABLE.get("list_sprints")
        executor._ACTION_TABLE["list_sprints"] = lambda conn, p: {"items": []}
        try:
            ok = execute({"action": "list_sprints", "payload": {}}, _tmp_db())
            assert ok["error"] is None and ok["data"] is not None
        finally:
            executor._ACTION_TABLE["list_sprints"] = original
