"""Tests for payload validation."""

import tempfile
import os

from habit_sprint.validation import validate_payload, ACTION_SCHEMAS
from habit_sprint.executor import execute


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


# ---------------------------------------------------------------------------
# Unit tests for validate_payload directly
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    def test_missing_single_required_field(self):
        err = validate_payload("create_habit", {
            "id": "h1", "category": "fitness", "target_per_week": 3,
        })
        assert err == "Missing required field: name"

    def test_missing_multiple_required_fields_reports_first(self):
        err = validate_payload("create_sprint", {})
        assert err is not None
        assert "Missing required field:" in err

    def test_missing_required_id_on_archive(self):
        err = validate_payload("archive_sprint", {})
        assert err == "Missing required field: sprint_id"

    def test_missing_habit_id_on_log_date(self):
        err = validate_payload("log_date", {"date": "2024-01-01", "value": 1})
        assert err == "Missing required field: habit_id"

    def test_missing_date_on_daily_score(self):
        err = validate_payload("daily_score", {})
        assert err == "Missing required field: date"

    def test_missing_dates_on_bulk_set(self):
        err = validate_payload("bulk_set", {"habit_id": "h1"})
        assert err == "Missing required field: dates"


class TestUnknownFields:
    def test_unknown_field_in_create_habit(self):
        err = validate_payload("create_habit", {
            "id": "h1", "name": "Run", "category": "fitness",
            "target_per_week": 3, "bar": "baz",
        })
        assert err == "Unknown field bar in payload for action create_habit"

    def test_unknown_field_in_get_active_sprint(self):
        err = validate_payload("get_active_sprint", {"foo": 1})
        assert err == "Unknown field foo in payload for action get_active_sprint"

    def test_unknown_field_in_query(self):
        err = validate_payload("sprint_report", {"extra": True})
        assert err == "Unknown field extra in payload for action sprint_report"


class TestTypeValidation:
    # --- ISO date ---
    def test_bad_iso_date_format(self):
        err = validate_payload("create_sprint", {
            "id": "s1", "start_date": "not-a-date", "end_date": "2024-01-07",
        })
        assert "must be a valid ISO date" in err

    def test_iso_date_invalid_calendar(self):
        err = validate_payload("create_sprint", {
            "id": "s1", "start_date": "2024-02-30", "end_date": "2024-01-07",
        })
        assert "must be a valid ISO date" in err

    def test_iso_date_number_instead_of_string(self):
        err = validate_payload("log_date", {
            "habit_id": "h1", "date": 20240101, "value": 1,
        })
        assert "must be a valid ISO date" in err

    # --- Integer with range ---
    def test_int_out_of_range_high(self):
        err = validate_payload("create_habit", {
            "id": "h1", "name": "Run", "category": "fitness",
            "target_per_week": 8,
        })
        assert "must be <= 7" in err

    def test_int_out_of_range_low(self):
        err = validate_payload("create_habit", {
            "id": "h1", "name": "Run", "category": "fitness",
            "target_per_week": 0,
        })
        assert "must be >= 1" in err

    def test_int_wrong_type_string(self):
        err = validate_payload("create_habit", {
            "id": "h1", "name": "Run", "category": "fitness",
            "target_per_week": "three",
        })
        assert "must be an integer" in err

    def test_int_wrong_type_bool(self):
        err = validate_payload("create_habit", {
            "id": "h1", "name": "Run", "category": "fitness",
            "target_per_week": True,
        })
        assert "must be an integer" in err

    # --- Number (>= 0) ---
    def test_number_negative(self):
        err = validate_payload("log_date", {
            "habit_id": "h1", "date": "2024-01-01", "value": -1,
        })
        assert "must be >= 0" in err

    def test_number_wrong_type(self):
        err = validate_payload("log_date", {
            "habit_id": "h1", "date": "2024-01-01", "value": "five",
        })
        assert "must be a number" in err

    def test_number_float_accepted(self):
        err = validate_payload("log_date", {
            "habit_id": "h1", "date": "2024-01-01", "value": 1.5,
        })
        assert err is None

    # --- Enum ---
    def test_invalid_enum_value(self):
        err = validate_payload("list_sprints", {"status": "deleted"})
        assert "must be one of: active, archived" in err

    def test_invalid_unit_enum(self):
        err = validate_payload("create_habit", {
            "id": "h1", "name": "Run", "category": "fitness",
            "target_per_week": 3, "unit": "liters",
        })
        assert "must be one of:" in err

    def test_invalid_period_enum(self):
        err = validate_payload("habit_report", {
            "habit_id": "h1", "period": "all_time",
        })
        assert "must be one of:" in err

    # --- Boolean ---
    def test_bool_wrong_type(self):
        err = validate_payload("list_habits", {"include_archived": "yes"})
        assert "must be a boolean" in err

    # --- String ---
    def test_string_wrong_type(self):
        err = validate_payload("create_habit", {
            "id": 123, "name": "Run", "category": "fitness",
            "target_per_week": 3,
        })
        assert "must be a string" in err

    # --- List ---
    def test_list_wrong_type(self):
        err = validate_payload("create_sprint", {
            "id": "s1", "start_date": "2024-01-01",
            "end_date": "2024-01-07", "focus_goals": "not a list",
        })
        assert "must be a list" in err

    # --- List of ISO dates ---
    def test_list_of_iso_dates_bad_item(self):
        err = validate_payload("bulk_set", {
            "habit_id": "h1", "dates": ["2024-01-01", "bad-date"],
        })
        assert "dates[1]" in err
        assert "must be a valid ISO date" in err

    def test_list_of_iso_dates_not_a_list(self):
        err = validate_payload("bulk_set", {
            "habit_id": "h1", "dates": "2024-01-01",
        })
        assert "must be a list" in err


class TestValidPayloads:
    def test_create_sprint_minimal(self):
        err = validate_payload("create_sprint", {
            "id": "s1", "start_date": "2024-01-01", "end_date": "2024-01-07",
        })
        assert err is None

    def test_create_sprint_full(self):
        err = validate_payload("create_sprint", {
            "id": "s1", "start_date": "2024-01-01", "end_date": "2024-01-07",
            "theme": "Fitness Focus", "focus_goals": ["Run", "Meditate"],
        })
        assert err is None

    def test_create_habit_minimal(self):
        err = validate_payload("create_habit", {
            "id": "h1", "name": "Run", "category": "fitness",
            "target_per_week": 3,
        })
        assert err is None

    def test_create_habit_full(self):
        err = validate_payload("create_habit", {
            "id": "h1", "name": "Run", "category": "fitness",
            "target_per_week": 5, "weight": 2, "unit": "minutes",
            "sprint_id": "s1",
        })
        assert err is None

    def test_get_active_sprint_empty(self):
        err = validate_payload("get_active_sprint", {})
        assert err is None

    def test_list_sprints_with_enum(self):
        err = validate_payload("list_sprints", {"status": "active"})
        assert err is None

    def test_log_date_valid(self):
        err = validate_payload("log_date", {
            "habit_id": "h1", "date": "2024-01-15", "value": 0,
        })
        assert err is None

    def test_bulk_set_valid(self):
        err = validate_payload("bulk_set", {
            "habit_id": "h1", "dates": ["2024-01-01", "2024-01-02"],
        })
        assert err is None

    def test_sprint_dashboard_with_week(self):
        err = validate_payload("sprint_dashboard", {"week": 2})
        assert err is None

    def test_all_optional_queries(self):
        """Actions with only optional fields accept empty payloads."""
        for action in ["get_week_view", "sprint_report", "category_report", "sprint_dashboard"]:
            err = validate_payload(action, {})
            assert err is None, f"{action} rejected empty payload"

    def test_unknown_action_passes_validation(self):
        """Actions not in schema are not validated (handled by executor routing)."""
        err = validate_payload("nonexistent", {"anything": True})
        assert err is None


# ---------------------------------------------------------------------------
# Integration tests — validation errors via execute()
# ---------------------------------------------------------------------------

class TestValidationIntegration:
    def test_missing_field_returns_error_envelope(self):
        result = execute({"action": "create_sprint", "payload": {}}, _tmp_db())
        assert result["status"] == "error"
        assert "Missing required field:" in result["error"]

    def test_unknown_field_returns_error_envelope(self):
        result = execute({
            "action": "get_active_sprint",
            "payload": {"foo": "bar"},
        }, _tmp_db())
        assert result["status"] == "error"
        assert "Unknown field foo" in result["error"]

    def test_type_error_returns_error_envelope(self):
        result = execute({
            "action": "create_habit",
            "payload": {
                "id": "h1", "name": "Run", "category": "fitness",
                "target_per_week": "not_int",
            },
        }, _tmp_db())
        assert result["status"] == "error"
        assert "must be an integer" in result["error"]

    def test_valid_payload_reaches_handler(self):
        """Valid payload passes validation and reaches the handler."""
        result = execute({
            "action": "create_sprint",
            "payload": {"id": "s1", "start_date": "2024-01-01", "end_date": "2024-01-07"},
        }, _tmp_db())
        # Sprint management is implemented, so valid payloads succeed
        assert result["status"] == "success"
        assert result["data"] is not None


class TestSchemaCompleteness:
    def test_all_actions_have_schemas(self):
        """Every action in the executor routing table has a schema defined."""
        from habit_sprint.executor import _ACTION_TABLE
        for action_name in _ACTION_TABLE:
            assert action_name in ACTION_SCHEMAS, f"Missing schema for action: {action_name}"
