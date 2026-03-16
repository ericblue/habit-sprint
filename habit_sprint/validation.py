"""Schema-based payload validation for habit-sprint actions."""

import re
from datetime import datetime

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_iso_date(value):
    """Return True if value is a valid YYYY-MM-DD date string."""
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _check_type(field_name, value, spec, action):
    """Validate a single field value against its spec. Returns error message or None."""
    ftype = spec["type"]

    if ftype == "str":
        if not isinstance(value, str):
            return f"Field {field_name} must be a string"
        if "enum" in spec and value not in spec["enum"]:
            allowed = ", ".join(spec["enum"])
            return f"Field {field_name} must be one of: {allowed}"

    elif ftype == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"Field {field_name} must be an integer"
        if "min" in spec and value < spec["min"]:
            return f"Field {field_name} must be >= {spec['min']}"
        if "max" in spec and value > spec["max"]:
            return f"Field {field_name} must be <= {spec['max']}"

    elif ftype == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"Field {field_name} must be a number"
        if "min" in spec and value < spec["min"]:
            return f"Field {field_name} must be >= {spec['min']}"

    elif ftype == "iso_date":
        if not _is_iso_date(value):
            return f"Field {field_name} must be a valid ISO date (YYYY-MM-DD)"

    elif ftype == "bool":
        if not isinstance(value, bool):
            return f"Field {field_name} must be a boolean"

    elif ftype == "list":
        if not isinstance(value, list):
            return f"Field {field_name} must be a list"

    elif ftype == "list_of_iso_dates":
        if not isinstance(value, list):
            return f"Field {field_name} must be a list"
        for i, item in enumerate(value):
            if not _is_iso_date(item):
                return f"Field {field_name}[{i}] must be a valid ISO date (YYYY-MM-DD)"

    return None


# ---------------------------------------------------------------------------
# Action schemas — each key maps to a dict of field_name -> spec
# ---------------------------------------------------------------------------

ACTION_SCHEMAS = {
    # --- Sprint mutations ---
    "create_sprint": {
        "id": {"type": "str", "required": False},
        "start_date": {"type": "iso_date", "required": True},
        "end_date": {"type": "iso_date", "required": True},
        "theme": {"type": "str", "required": False},
        "focus_goals": {"type": "list", "required": False},
    },
    "update_sprint": {
        "sprint_id": {"type": "str", "required": True},
        "theme": {"type": "str", "required": False},
        "focus_goals": {"type": "list", "required": False},
    },
    "list_sprints": {
        "status": {"type": "str", "required": False, "enum": ["active", "archived"]},
    },
    "archive_sprint": {
        "sprint_id": {"type": "str", "required": True},
    },
    "get_active_sprint": {},

    # --- Habit mutations ---
    "create_habit": {
        "id": {"type": "str", "required": True},
        "name": {"type": "str", "required": True},
        "category": {"type": "str", "required": True},
        "target_per_week": {"type": "int", "required": True, "min": 1, "max": 7},
        "weight": {"type": "int", "required": False, "min": 1, "max": 3},
        "unit": {"type": "str", "required": False, "enum": ["count", "minutes", "reps", "pages"]},
        "sprint_id": {"type": "str", "required": False},
    },
    "update_habit": {
        "id": {"type": "str", "required": True},
        "name": {"type": "str", "required": False},
        "category": {"type": "str", "required": False},
        "target_per_week": {"type": "int", "required": False, "min": 1, "max": 7},
        "weight": {"type": "int", "required": False, "min": 1, "max": 3},
        "unit": {"type": "str", "required": False, "enum": ["count", "minutes", "reps", "pages"]},
        "sprint_id": {"type": "str", "required": False},
    },
    "archive_habit": {
        "id": {"type": "str", "required": True},
    },
    "unarchive_habit": {
        "id": {"type": "str", "required": True},
    },
    "delete_habit": {
        "id": {"type": "str", "required": True},
    },
    "list_habits": {
        "sprint_id": {"type": "str", "required": False},
        "category": {"type": "str", "required": False},
        "include_archived": {"type": "bool", "required": False},
    },

    # --- Log mutations ---
    "log_date": {
        "habit_id": {"type": "str", "required": True},
        "date": {"type": "iso_date", "required": True},
        "value": {"type": "number", "required": True, "min": 0},
        "note": {"type": "str", "required": False},
    },
    "log_range": {
        "habit_id": {"type": "str", "required": True},
        "start_date": {"type": "iso_date", "required": True},
        "end_date": {"type": "iso_date", "required": True},
        "value": {"type": "number", "required": False, "min": 0},
    },
    "bulk_set": {
        "habit_id": {"type": "str", "required": True},
        "dates": {"type": "list_of_iso_dates", "required": True},
        "value": {"type": "number", "required": False, "min": 0},
    },
    "delete_entry": {
        "habit_id": {"type": "str", "required": True},
        "date": {"type": "iso_date", "required": True},
    },

    # --- Retro mutations ---
    "add_retro": {
        "sprint_id": {"type": "str", "required": True},
        "what_went_well": {"type": "str", "required": False},
        "what_to_improve": {"type": "str", "required": False},
        "ideas": {"type": "str", "required": False},
    },
    "get_retro": {
        "sprint_id": {"type": "str", "required": True},
    },

    # --- Sprint habit goals ---
    "set_sprint_habit_goal": {
        "sprint_id": {"type": "str", "required": True},
        "habit_id": {"type": "str", "required": True},
        "target_per_week": {"type": "int", "required": True, "min": 1, "max": 7},
        "weight": {"type": "int", "required": False, "min": 1, "max": 3},
    },
    "get_sprint_habit_goal": {
        "sprint_id": {"type": "str", "required": True},
        "habit_id": {"type": "str", "required": True},
    },
    "delete_sprint_habit_goal": {
        "sprint_id": {"type": "str", "required": True},
        "habit_id": {"type": "str", "required": True},
    },

    # --- Query actions ---
    "weekly_completion": {
        "habit_id": {"type": "str", "required": True},
        "week_start": {"type": "iso_date", "required": False},
    },
    "daily_score": {
        "date": {"type": "iso_date", "required": True},
        "sprint_id": {"type": "str", "required": False},
    },
    "get_week_view": {
        "week_start": {"type": "iso_date", "required": False},
        "sprint_id": {"type": "str", "required": False},
    },
    "sprint_report": {
        "sprint_id": {"type": "str", "required": False},
    },
    "habit_report": {
        "habit_id": {"type": "str", "required": True},
        "period": {"type": "str", "required": False, "enum": ["current_sprint", "last_4_weeks", "last_8_weeks"]},
        "sprint_id": {"type": "str", "required": False},
    },
    "category_report": {
        "sprint_id": {"type": "str", "required": False},
        "category": {"type": "str", "required": False},
    },
    "sprint_dashboard": {
        "sprint_id": {"type": "str", "required": False},
        "week": {"type": "int", "required": False, "min": 1, "max": 2},
    },
    "cross_sprint_report": {
        "limit": {"type": "int", "required": False, "min": 1},
        "habit_id": {"type": "str", "required": False},
    },
}


def validate_payload(action, payload):
    """Validate payload against the schema for the given action.

    Returns None if valid, or an error message string if invalid.
    """
    schema = ACTION_SCHEMAS.get(action)
    if schema is None:
        return None  # unknown actions handled elsewhere

    # Check for unknown fields
    for key in payload:
        if key not in schema:
            return f"Unknown field {key} in payload for action {action}"

    # Check required fields
    for field_name, spec in schema.items():
        if spec.get("required") and field_name not in payload:
            return f"Missing required field: {field_name}"

    # Type-check provided fields
    for field_name, value in payload.items():
        spec = schema[field_name]
        # Allow None for optional fields (sets DB column to NULL)
        if value is None and not spec.get("required"):
            continue
        err = _check_type(field_name, value, spec, action)
        if err is not None:
            return err

    return None
