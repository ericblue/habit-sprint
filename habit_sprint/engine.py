"""Mutation handlers for the habit-sprint engine."""

import json
import re
import sqlite3
from datetime import date, datetime, timedelta

_SLUG_RE = re.compile(r"^[a-z]+(-[a-z]+)*$")
_VALID_UNITS = {"count", "minutes", "reps", "pages"}


def _generate_sprint_id(conn: sqlite3.Connection, start_date: str) -> str:
    """Generate auto-ID in YYYY-S## format based on existing sprints for that year."""
    year = start_date[:4]
    row = conn.execute(
        "SELECT COUNT(*) FROM sprints WHERE id LIKE ?", (f"{year}-S%",)
    ).fetchone()
    count = row[0]
    return f"{year}-S{count + 1:02d}"


def _check_overlap(conn: sqlite3.Connection, start_date: str, end_date: str) -> None:
    """Raise ValueError if the date range overlaps any active sprint."""
    overlapping = conn.execute(
        """SELECT id, start_date, end_date FROM sprints
           WHERE status = 'active'
             AND NOT (start_date > ? OR end_date < ?)""",
        (end_date, start_date),
    ).fetchone()
    if overlapping:
        raise ValueError(
            f"Cannot create sprint: date range {start_date} to {end_date} "
            f"overlaps with active sprint '{overlapping['id']}' "
            f"({overlapping['start_date']} to {overlapping['end_date']})"
        )


def _validate_dates(start_date: str, end_date: str) -> None:
    """Validate ISO date format and that end_date > start_date."""
    try:
        sd = date.fromisoformat(start_date)
    except ValueError:
        raise ValueError(f"Invalid start_date: {start_date}")
    try:
        ed = date.fromisoformat(end_date)
    except ValueError:
        raise ValueError(f"Invalid end_date: {end_date}")
    if ed <= sd:
        raise ValueError(
            f"end_date must be after start_date "
            f"(got start_date={start_date}, end_date={end_date})"
        )


def _sprint_row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row for a sprint to a plain dict."""
    d = dict(row)
    if isinstance(d.get("focus_goals"), str):
        d["focus_goals"] = json.loads(d["focus_goals"])
    return d


def create_sprint(conn: sqlite3.Connection, payload: dict) -> dict:
    start_date = payload["start_date"]
    end_date = payload["end_date"]
    theme = payload.get("theme")
    focus_goals = payload.get("focus_goals", [])

    _validate_dates(start_date, end_date)
    _check_overlap(conn, start_date, end_date)

    sprint_id = _generate_sprint_id(conn, start_date)
    now = datetime.now().isoformat()
    focus_goals_json = json.dumps(focus_goals)

    conn.execute(
        """INSERT INTO sprints (id, start_date, end_date, theme, focus_goals,
                                status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
        (sprint_id, start_date, end_date, theme, focus_goals_json, now, now),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    return _sprint_row_to_dict(row)


def update_sprint(conn: sqlite3.Connection, payload: dict) -> dict:
    sprint_id = payload["sprint_id"]
    row = conn.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    if row is None:
        raise ValueError(f"Sprint not found: {sprint_id}")

    now = datetime.now().isoformat()
    updates = []
    params = []

    if "theme" in payload:
        updates.append("theme = ?")
        params.append(payload["theme"])
    if "focus_goals" in payload:
        updates.append("focus_goals = ?")
        params.append(json.dumps(payload["focus_goals"]))

    if not updates:
        return _sprint_row_to_dict(row)

    updates.append("updated_at = ?")
    params.append(now)
    params.append(sprint_id)

    conn.execute(
        f"UPDATE sprints SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()

    row = conn.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    return _sprint_row_to_dict(row)


def list_sprints(conn: sqlite3.Connection, payload: dict) -> dict:
    status_filter = payload.get("status")
    if status_filter and status_filter != "all":
        rows = conn.execute(
            "SELECT * FROM sprints WHERE status = ? ORDER BY start_date",
            (status_filter,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sprints ORDER BY start_date"
        ).fetchall()
    return {"sprints": [_sprint_row_to_dict(r) for r in rows]}


def archive_sprint(conn: sqlite3.Connection, payload: dict) -> dict:
    sprint_id = payload["sprint_id"]
    row = conn.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    if row is None:
        raise ValueError(f"Sprint not found: {sprint_id}")

    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE sprints SET status = 'archived', updated_at = ? WHERE id = ?",
        (now, sprint_id),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    return _sprint_row_to_dict(row)


def get_active_sprint(conn: sqlite3.Connection, payload: dict) -> dict:
    row = conn.execute(
        "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("No active sprint found")
    return _sprint_row_to_dict(row)


def create_habit(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["id"]
    name = payload["name"]
    category = payload["category"]
    target_per_week = payload["target_per_week"]
    weight = payload.get("weight", 1)
    unit = payload.get("unit", "count")
    sprint_id = payload.get("sprint_id")

    if not _SLUG_RE.match(habit_id):
        raise ValueError(
            f"Invalid habit id: {habit_id}. Must be lowercase letters and hyphens only."
        )

    if unit not in _VALID_UNITS:
        raise ValueError(f"Invalid unit: {unit}. Must be one of: {', '.join(sorted(_VALID_UNITS))}")

    if not 1 <= target_per_week <= 7:
        raise ValueError(f"target_per_week must be between 1 and 7, got {target_per_week}")

    if not 1 <= weight <= 3:
        raise ValueError(f"weight must be between 1 and 3, got {weight}")

    now = datetime.now().isoformat()

    conn.execute(
        """INSERT INTO habits (id, name, category, target_per_week, weight, unit,
                               sprint_id, archived, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (habit_id, name, category, target_per_week, weight, unit, sprint_id, now, now),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    return dict(row)


def update_habit(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["id"]
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    if row is None:
        raise ValueError(f"Habit not found: {habit_id}")

    if row["archived"]:
        raise ValueError(f"Cannot update archived habit: {habit_id}")

    now = datetime.now().isoformat()
    updates = []
    params = []

    for field in ("name", "category", "target_per_week", "weight", "unit", "sprint_id"):
        if field in payload:
            updates.append(f"{field} = ?")
            params.append(payload[field])

    if not updates:
        return dict(row)

    updates.append("updated_at = ?")
    params.append(now)
    params.append(habit_id)

    conn.execute(
        f"UPDATE habits SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()

    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    return dict(row)


def archive_habit(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["id"]
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    if row is None:
        raise ValueError(f"Habit not found: {habit_id}")

    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE habits SET archived = 1, updated_at = ? WHERE id = ?",
        (now, habit_id),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    return dict(row)


def list_habits(conn: sqlite3.Connection, payload: dict) -> dict:
    sprint_id = payload.get("sprint_id")
    category = payload.get("category")
    include_archived = payload.get("include_archived", False)

    conditions = []
    params = []

    if not include_archived:
        conditions.append("archived = 0")

    if sprint_id:
        conditions.append("(sprint_id = ? OR sprint_id IS NULL)")
        params.append(sprint_id)

    if category:
        conditions.append("category = ?")
        params.append(category)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    rows = conn.execute(
        f"SELECT * FROM habits WHERE {where_clause} ORDER BY created_at",
        params,
    ).fetchall()

    return {"habits": [dict(r) for r in rows]}


def _validate_habit_active(conn: sqlite3.Connection, habit_id: str) -> None:
    """Validate that a habit exists and is not archived."""
    row = conn.execute("SELECT archived FROM habits WHERE id = ?", (habit_id,)).fetchone()
    if row is None:
        raise ValueError(f"Habit not found: {habit_id}")
    if row["archived"]:
        raise ValueError(f"Habit is archived: {habit_id}")


def _validate_date(d: str) -> None:
    """Validate that a string is a valid ISO 8601 date."""
    try:
        date.fromisoformat(d)
    except ValueError:
        raise ValueError(f"Invalid date: {d}")


def log_date(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["habit_id"]
    entry_date = payload["date"]
    value = payload.get("value", 1)
    note = payload.get("note")

    _validate_habit_active(conn, habit_id)
    _validate_date(entry_date)

    existing = conn.execute(
        "SELECT 1 FROM entries WHERE habit_id = ? AND date = ?",
        (habit_id, entry_date),
    ).fetchone()
    created = existing is None

    now = datetime.now().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO entries (habit_id, date, value, note, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (habit_id, entry_date, value, note, now, now),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM entries WHERE habit_id = ? AND date = ?",
        (habit_id, entry_date),
    ).fetchone()
    result = dict(row)
    result["created"] = created
    return result


def log_range(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["habit_id"]
    start_date = payload["start_date"]
    end_date = payload["end_date"]
    value = payload.get("value", 1)
    note = payload.get("note")

    _validate_habit_active(conn, habit_id)
    _validate_date(start_date)
    _validate_date(end_date)

    sd = date.fromisoformat(start_date)
    ed = date.fromisoformat(end_date)
    if ed < sd:
        raise ValueError(
            f"end_date must not be before start_date "
            f"(got start_date={start_date}, end_date={end_date})"
        )

    now = datetime.now().isoformat()
    entries = []
    current = sd
    while current <= ed:
        d_str = current.isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO entries (habit_id, date, value, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (habit_id, d_str, value, note, now, now),
        )
        entries.append(d_str)
        current += timedelta(days=1)

    conn.commit()
    return {"habit_id": habit_id, "dates": entries, "count": len(entries)}


def bulk_set(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["habit_id"]
    dates = payload["dates"]
    value = payload.get("value", 1)
    note = payload.get("note")

    _validate_habit_active(conn, habit_id)
    for d in dates:
        _validate_date(d)

    now = datetime.now().isoformat()
    for d in dates:
        conn.execute(
            """INSERT OR REPLACE INTO entries (habit_id, date, value, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (habit_id, d, value, note, now, now),
        )

    conn.commit()
    return {"habit_id": habit_id, "dates": dates, "count": len(dates)}


def delete_entry(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["habit_id"]
    entry_date = payload["date"]

    _validate_habit_active(conn, habit_id)
    _validate_date(entry_date)

    cursor = conn.execute(
        "DELETE FROM entries WHERE habit_id = ? AND date = ?",
        (habit_id, entry_date),
    )
    conn.commit()

    return {"habit_id": habit_id, "date": entry_date, "deleted": cursor.rowcount > 0}


def add_retro(conn: sqlite3.Connection, payload: dict) -> dict:
    sprint_id = payload["sprint_id"]

    # Validate sprint exists
    row = conn.execute("SELECT id FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
    if row is None:
        raise ValueError(f"Sprint not found: {sprint_id}")

    what_went_well = payload.get("what_went_well")
    what_to_improve = payload.get("what_to_improve")
    ideas = payload.get("ideas")
    now = datetime.now().isoformat()

    conn.execute(
        """INSERT INTO retros (sprint_id, what_went_well, what_to_improve, ideas,
                               created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(sprint_id) DO UPDATE SET
               what_went_well = excluded.what_went_well,
               what_to_improve = excluded.what_to_improve,
               ideas = excluded.ideas,
               updated_at = excluded.updated_at""",
        (sprint_id, what_went_well, what_to_improve, ideas, now, now),
    )
    conn.commit()

    retro = conn.execute(
        "SELECT * FROM retros WHERE sprint_id = ?", (sprint_id,)
    ).fetchone()
    return dict(retro)


def get_retro(conn: sqlite3.Connection, payload: dict) -> dict:
    sprint_id = payload["sprint_id"]
    retro = conn.execute(
        "SELECT * FROM retros WHERE sprint_id = ?", (sprint_id,)
    ).fetchone()
    if retro is None:
        raise ValueError(f"No retrospective found for sprint {sprint_id}")
    return dict(retro)
