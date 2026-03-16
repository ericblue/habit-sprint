"""Action executor — routes JSON actions and wraps responses in envelopes."""

from habit_sprint import engine, reporting
from habit_sprint.db import get_connection
from habit_sprint.validation import validate_payload

_MUTATION_ACTIONS = {
    "create_sprint": engine.create_sprint,
    "update_sprint": engine.update_sprint,
    "list_sprints": engine.list_sprints,
    "archive_sprint": engine.archive_sprint,
    "get_active_sprint": engine.get_active_sprint,
    "create_habit": engine.create_habit,
    "update_habit": engine.update_habit,
    "archive_habit": engine.archive_habit,
    "unarchive_habit": engine.unarchive_habit,
    "delete_habit": engine.delete_habit,
    "list_habits": engine.list_habits,
    "log_date": engine.log_date,
    "log_range": engine.log_range,
    "bulk_set": engine.bulk_set,
    "delete_entry": engine.delete_entry,
    "add_retro": engine.add_retro,
    "get_retro": engine.get_retro,
    "set_sprint_habit_goal": engine.set_sprint_habit_goal,
    "get_sprint_habit_goal": engine.get_sprint_habit_goal,
    "delete_sprint_habit_goal": engine.delete_sprint_habit_goal,
}

_QUERY_ACTIONS = {
    "weekly_completion": reporting.weekly_completion,
    "daily_score": reporting.daily_score,
    "get_week_view": reporting.get_week_view,
    "sprint_report": reporting.sprint_report,
    "habit_report": reporting.habit_report,
    "category_report": reporting.category_report,
    "sprint_dashboard": reporting.sprint_dashboard,
    "cross_sprint_report": reporting.cross_sprint_report,
    "streak_leaderboard": reporting.streak_leaderboard,
    "progress_summary": reporting.progress_summary,
}

_ACTION_TABLE = {**_MUTATION_ACTIONS, **_QUERY_ACTIONS}


def _success(data: dict) -> dict:
    return {"status": "success", "data": data, "error": None}


def _error(message: str) -> dict:
    return {"status": "error", "data": None, "error": message}


def execute(action_json: dict, db_path: str) -> dict:
    """Execute an action and return an envelope-wrapped response.

    Parameters
    ----------
    action_json : dict
        Must contain an ``action`` key with the action name.
        May contain a ``payload`` key (defaults to ``{}``).
    db_path : str
        Path to the SQLite database file.

    Returns
    -------
    dict
        ``{status, data, error}`` envelope.
    """
    try:
        if "action" not in action_json:
            return _error("Missing required field: action")

        action_name = action_json["action"]
        payload = action_json.get("payload", {})

        handler = _ACTION_TABLE.get(action_name)
        if handler is None:
            return _error(f"Unknown action: {action_name}")

        validation_error = validate_payload(action_name, payload)
        if validation_error is not None:
            return _error(validation_error)

        conn = get_connection(db_path)
        try:
            result = handler(conn, payload)
        finally:
            conn.close()

        return _success(result)

    except Exception as exc:
        return _error(str(exc))
