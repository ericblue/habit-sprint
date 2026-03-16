"""Query handlers for habit-sprint reporting."""

import json
import math
import sqlite3
from datetime import date, timedelta


def _compute_streaks(entry_rows: list) -> tuple[int, int]:
    """Compute (current_streak, longest_streak) from a list of entry rows.

    Each row must expose a ``"date"`` key with an ISO-format date string.
    Returns ``(0, 0)`` when *entry_rows* is empty.
    """
    if not entry_rows:
        return 0, 0

    entry_dates = {date.fromisoformat(r["date"]) for r in entry_rows}
    sorted_dates = sorted(entry_dates)

    # Longest streak
    longest_streak = 1
    run = 1
    for i in range(1, len(sorted_dates)):
        if sorted_dates[i] - sorted_dates[i - 1] == timedelta(days=1):
            run += 1
            if run > longest_streak:
                longest_streak = run
        else:
            run = 1

    # Current streak: consecutive days ending today or yesterday
    today = date.today()
    if today in entry_dates:
        check = today
    elif (today - timedelta(days=1)) in entry_dates:
        check = today - timedelta(days=1)
    else:
        check = None

    if check is None:
        current_streak = 0
    else:
        current_streak = 0
        while check in entry_dates:
            current_streak += 1
            check -= timedelta(days=1)

    return current_streak, longest_streak


def _get_effective_goals(
    conn: sqlite3.Connection, sprint_id: str | None, habits: list
) -> list[dict]:
    """Enrich habits with effective target_per_week and weight from sprint_habit_goals.

    For each habit, if a ``sprint_habit_goals`` row exists for the given sprint,
    its ``target_per_week`` and ``weight`` override the habit defaults.  Otherwise
    the habit's own values are kept.  Returns a list of plain dicts.
    """
    # Convert rows to dicts
    result = [dict(h) for h in habits]

    if not sprint_id or not result:
        return result

    habit_ids = [h["id"] for h in result]
    placeholders = ",".join("?" * len(habit_ids))
    rows = conn.execute(
        f"SELECT habit_id, target_per_week, weight FROM sprint_habit_goals "
        f"WHERE sprint_id = ? AND habit_id IN ({placeholders})",
        (sprint_id, *habit_ids),
    ).fetchall()

    overrides = {r["habit_id"]: r for r in rows}

    for h in result:
        if h["id"] in overrides:
            goal = overrides[h["id"]]
            h["target_per_week"] = goal["target_per_week"]
            h["weight"] = goal["weight"]

    return result


def _get_sprint_habits(conn: sqlite3.Connection, sprint_id: str) -> list:
    """Get habits for a sprint.

    For active sprints: sprint_habit_goals rows + sprint-scoped + global unarchived habits.
    For archived sprints with sprint_habit_goals: only those bound habits + sprint-scoped.
    For archived sprints without sprint_habit_goals: fall back to globals (legacy behavior).
    """
    # Check sprint status and whether it has any sprint_habit_goals
    row = conn.execute(
        "SELECT status FROM sprints WHERE id = ?", (sprint_id,)
    ).fetchone()
    is_active = row and row["status"] == "active"

    has_goals = conn.execute(
        "SELECT 1 FROM sprint_habit_goals WHERE sprint_id = ? LIMIT 1", (sprint_id,)
    ).fetchone() is not None

    if is_active:
        # Active sprint: include sprint_habit_goals + sprint-scoped + globals, but never archived
        return conn.execute(
            """SELECT DISTINCT h.* FROM habits h
               LEFT JOIN sprint_habit_goals shg
                 ON shg.habit_id = h.id AND shg.sprint_id = ?
               WHERE h.archived = 0
                 AND (shg.sprint_id IS NOT NULL
                      OR h.sprint_id = ?
                      OR h.sprint_id IS NULL)
               ORDER BY h.category, h.created_at""",
            (sprint_id, sprint_id),
        ).fetchall()
    elif not has_goals:
        # Archived without explicit goals: fall back to globals (legacy)
        return conn.execute(
            """SELECT DISTINCT h.* FROM habits h
               LEFT JOIN sprint_habit_goals shg
                 ON shg.habit_id = h.id AND shg.sprint_id = ?
               WHERE shg.sprint_id IS NOT NULL
                  OR (h.archived = 0 AND h.sprint_id = ?)
                  OR (h.archived = 0 AND h.sprint_id IS NULL)
               ORDER BY h.category, h.created_at""",
            (sprint_id, sprint_id),
        ).fetchall()
    else:
        # Archived with explicit sprint_habit_goals: only bound habits
        return conn.execute(
            """SELECT DISTINCT h.* FROM habits h
               LEFT JOIN sprint_habit_goals shg
                 ON shg.habit_id = h.id AND shg.sprint_id = ?
               WHERE shg.sprint_id IS NOT NULL
                  OR (h.archived = 0 AND h.sprint_id = ?)
               ORDER BY h.category, h.created_at""",
            (sprint_id, sprint_id),
        ).fetchall()


def weekly_completion(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["habit_id"]
    sprint_id = payload.get("sprint_id")

    # Look up habit
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    if row is None:
        raise ValueError(f"Habit not found: {habit_id}")
    enriched = _get_effective_goals(conn, sprint_id, [row])
    target_per_week = enriched[0]["target_per_week"]

    # Determine week boundaries (Mon–Sun)
    if "week_start" in payload and payload["week_start"] is not None:
        week_start = date.fromisoformat(payload["week_start"])
    else:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday

    # Count entries in the week with value > 0
    actual_days = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE habit_id = ? AND date >= ? AND date <= ? AND value > 0",
        (habit_id, week_start.isoformat(), week_end.isoformat()),
    ).fetchone()[0]

    # Completion and commitment
    completion_pct = int((actual_days / target_per_week) * 100)
    if completion_pct > 100:
        completion_pct = 100
    commitment_met = actual_days >= target_per_week

    # Streaks: fetch all entries sorted by date
    entry_rows = conn.execute(
        "SELECT date FROM entries WHERE habit_id = ? AND value > 0 ORDER BY date",
        (habit_id,),
    ).fetchall()

    current_streak, longest_streak = _compute_streaks(entry_rows)

    return {
        "habit_id": habit_id,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "actual_days": actual_days,
        "target_per_week": target_per_week,
        "completion_pct": completion_pct,
        "commitment_met": commitment_met,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
    }


def daily_score(conn: sqlite3.Connection, payload: dict) -> dict:
    target_date = payload["date"]
    sprint_id = payload.get("sprint_id")

    # Resolve sprint
    if sprint_id:
        row = conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Sprint not found: {sprint_id}")
        sprint = dict(row)
    else:
        row = conn.execute(
            "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("No active sprint found")
        sprint = dict(row)
        sprint_id = sprint["id"]

    # Get habits for this sprint (sprint_habit_goals rows + non-archived globals)
    habits = _get_sprint_habits(conn, sprint_id)
    habits = _get_effective_goals(conn, sprint_id, habits)

    habits_completed = []
    habits_missed = []
    total_points = 0
    max_possible = 0

    for h in habits:
        weight = h["weight"]
        max_possible += weight

        entry = conn.execute(
            "SELECT * FROM entries WHERE habit_id = ? AND date = ?",
            (h["id"], target_date),
        ).fetchone()

        if entry and entry["value"] > 0:
            value = entry["value"]
            points = value * weight
            total_points += points
            habits_completed.append({
                "id": h["id"],
                "name": h["name"],
                "value": value,
                "weight": weight,
                "points": points,
            })
        else:
            habits_missed.append({
                "id": h["id"],
                "name": h["name"],
                "weight": weight,
                "points_possible": weight,
            })

    completion_pct = round(total_points / max_possible * 100) if max_possible > 0 else 0

    return {
        "date": target_date,
        "sprint_id": sprint_id,
        "total_points": total_points,
        "max_possible": max_possible,
        "completion_pct": completion_pct,
        "habits_completed": habits_completed,
        "habits_missed": habits_missed,
    }


def get_week_view(conn: sqlite3.Connection, payload: dict) -> dict:
    sprint_id = payload.get("sprint_id")

    # Resolve sprint
    if sprint_id:
        row = conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Sprint not found: {sprint_id}")
        sprint = dict(row)
    else:
        row = conn.execute(
            "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("No active sprint found")
        sprint = dict(row)
        sprint_id = sprint["id"]

    sprint_start = date.fromisoformat(sprint["start_date"])
    sprint_end = date.fromisoformat(sprint["end_date"])

    # Determine week boundaries (Mon-Sun)
    if "week_start" in payload and payload["week_start"] is not None:
        week_start = date.fromisoformat(payload["week_start"])
    else:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday

    # Build list of days in the week
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    # Determine which days are inside the sprint range
    in_sprint = [sprint_start <= d <= sprint_end for d in week_dates]

    # Get habits for this sprint (sprint_habit_goals rows + non-archived globals)
    habits = _get_sprint_habits(conn, sprint_id)
    habits = _get_effective_goals(conn, sprint_id, habits)

    # Fetch all entries for these habits in the week range
    habit_ids = [h["id"] for h in habits]
    entries_by_habit = {}
    if habit_ids:
        placeholders = ",".join("?" * len(habit_ids))
        entry_rows = conn.execute(
            f"""SELECT habit_id, date, value FROM entries
                WHERE habit_id IN ({placeholders})
                  AND date >= ? AND date <= ?""",
            (*habit_ids, week_start.isoformat(), week_end.isoformat()),
        ).fetchall()
        for e in entry_rows:
            entries_by_habit.setdefault(e["habit_id"], {})[e["date"]] = e["value"]

    # Group habits by category
    categories = {}
    for h in habits:
        cat = h["category"]
        habit_entries = entries_by_habit.get(h["id"], {})

        # Build daily_values map — 0 for days outside sprint range
        daily_values = {}
        week_actual = 0
        for i, label in enumerate(day_labels):
            if not in_sprint[i]:
                daily_values[label] = 0
            else:
                val = habit_entries.get(week_dates[i].isoformat(), 0)
                daily_values[label] = val
                if val > 0:
                    week_actual += 1

        target = h["target_per_week"]
        completion_pct = int((week_actual / target) * 100) if target > 0 else 0
        if completion_pct > 100:
            completion_pct = 100

        habit_data = {
            "id": h["id"],
            "name": h["name"],
            "target_per_week": target,
            "weight": h["weight"],
            "daily_values": daily_values,
            "week_actual": week_actual,
            "week_completion_pct": completion_pct,
            "commitment_met": week_actual >= target,
        }

        if cat not in categories:
            categories[cat] = {"habits": []}
        categories[cat]["habits"].append(habit_data)

    return {
        "sprint_id": sprint_id,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "categories": categories,
    }


def sprint_report(conn: sqlite3.Connection, payload: dict) -> dict:
    sprint_id = payload.get("sprint_id")

    # Resolve sprint
    if sprint_id:
        row = conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Sprint not found: {sprint_id}")
        sprint = dict(row)
    else:
        row = conn.execute(
            "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("No active sprint found")
        sprint = dict(row)
        sprint_id = sprint["id"]

    start = date.fromisoformat(sprint["start_date"])
    end = date.fromisoformat(sprint["end_date"])
    today = date.today()

    total_days = (end - start).days + 1
    num_weeks = math.ceil(total_days / 7)

    # days_elapsed / days_remaining
    if today < start:
        days_elapsed = 0
        days_remaining = total_days
    elif today > end:
        days_elapsed = total_days
        days_remaining = 0
    else:
        days_elapsed = (today - start).days + 1
        days_remaining = (end - today).days

    # Get habits for this sprint (sprint_habit_goals rows + non-archived globals)
    habits = _get_sprint_habits(conn, sprint_id)
    habits = _get_effective_goals(conn, sprint_id, habits)

    # Compute week boundaries within the sprint
    week_ranges = []
    ws = start
    while ws <= end:
        we = min(ws + timedelta(days=6), end)
        week_ranges.append((ws, we))
        ws = ws + timedelta(days=7)

    total_weighted_actual = 0
    total_weighted_target = 0
    total_actual = 0
    total_target = 0
    categories: dict[str, dict] = {}
    habit_stats = []

    for h in habits:
        target_entries = h["target_per_week"] * num_weeks

        actual_entries = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE habit_id = ? AND date >= ? AND date <= ? AND value > 0",
            (h["id"], sprint["start_date"], sprint["end_date"]),
        ).fetchone()[0]

        completion_pct = round(actual_entries / target_entries * 100) if target_entries > 0 else 0

        total_weighted_actual += actual_entries * h["weight"]
        total_weighted_target += target_entries * h["weight"]
        total_actual += actual_entries
        total_target += target_entries

        # Streaks (across all entries for the habit, not just this sprint)
        entry_rows = conn.execute(
            "SELECT date FROM entries WHERE habit_id = ? AND value > 0 ORDER BY date",
            (h["id"],),
        ).fetchall()
        current_streak, longest_streak = _compute_streaks(entry_rows)

        # Weekly breakdown
        weekly_breakdown = []
        for w_start, w_end in week_ranges:
            w_actual = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE habit_id = ? AND date >= ? AND date <= ? AND value > 0",
                (h["id"], w_start.isoformat(), w_end.isoformat()),
            ).fetchone()[0]
            weekly_breakdown.append({
                "week_start": w_start.isoformat(),
                "week_end": w_end.isoformat(),
                "actual": w_actual,
                "target": h["target_per_week"],
            })

        stat = {
            "habit_id": h["id"],
            "name": h["name"],
            "category": h["category"],
            "weight": h["weight"],
            "total_entries": actual_entries,
            "expected_entries": target_entries,
            "completion_pct": completion_pct,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "weekly_breakdown": weekly_breakdown,
        }
        habit_stats.append(stat)

        # Group by category
        cat = h["category"]
        if cat not in categories:
            categories[cat] = {"weighted_actual": 0, "weighted_target": 0, "habits": []}
        categories[cat]["weighted_actual"] += actual_entries * h["weight"]
        categories[cat]["weighted_target"] += target_entries * h["weight"]
        categories[cat]["habits"].append(stat)

    # Build category list with weighted scores
    category_list = []
    for cat_name, cat_data in categories.items():
        wa = cat_data["weighted_actual"]
        wt = cat_data["weighted_target"]
        category_list.append({
            "category": cat_name,
            "weighted_score": round(wa / wt * 100) if wt > 0 else 0,
            "habits": cat_data["habits"],
        })

    weighted_score = round(total_weighted_actual / total_weighted_target * 100) if total_weighted_target > 0 else 0
    unweighted_score = round(total_actual / total_target * 100) if total_target > 0 else 0

    # Trend vs last sprint
    prev_row = conn.execute(
        "SELECT * FROM sprints WHERE start_date < ? ORDER BY start_date DESC LIMIT 1",
        (sprint["start_date"],),
    ).fetchone()

    trend_vs_last_sprint = None
    if prev_row is not None:
        prev = dict(prev_row)
        prev_start = date.fromisoformat(prev["start_date"])
        prev_end = date.fromisoformat(prev["end_date"])
        prev_num_weeks = math.ceil(((prev_end - prev_start).days + 1) / 7)

        prev_habits = _get_sprint_habits(conn, prev["id"])
        prev_habits = _get_effective_goals(conn, prev["id"], prev_habits)

        prev_wa = 0
        prev_wt = 0
        for ph_d in prev_habits:
            prev_target = ph_d["target_per_week"] * prev_num_weeks
            prev_actual = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE habit_id = ? AND date >= ? AND date <= ? AND value > 0",
                (ph_d["id"], prev["start_date"], prev["end_date"]),
            ).fetchone()[0]
            prev_wa += prev_actual * ph_d["weight"]
            prev_wt += prev_target * ph_d["weight"]

        if prev_wt > 0:
            prev_weighted_score = round(prev_wa / prev_wt * 100)
            trend_vs_last_sprint = weighted_score - prev_weighted_score

    # Parse focus_goals
    focus_goals = sprint.get("focus_goals", "[]")
    if isinstance(focus_goals, str):
        focus_goals = json.loads(focus_goals)

    return {
        "sprint_id": sprint_id,
        "start_date": sprint["start_date"],
        "end_date": sprint["end_date"],
        "theme": sprint["theme"],
        "focus_goals": focus_goals,
        "status": sprint["status"],
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "total_days": total_days,
        "num_weeks": num_weeks,
        "weighted_score": weighted_score,
        "unweighted_score": unweighted_score,
        "categories": category_list,
        "habits": habit_stats,
        "trend_vs_last_sprint": trend_vs_last_sprint,
    }


def habit_report(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["habit_id"]
    period = payload.get("period", "current_sprint")
    sprint_id = payload.get("sprint_id")

    # Look up habit
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    if row is None:
        raise ValueError(f"Habit not found: {habit_id}")
    habit = dict(row)

    today = date.today()

    # Determine period dates and resolve sprint for effective goals
    resolved_sprint_id = None
    if sprint_id:
        sprint_row = conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if sprint_row is None:
            raise ValueError(f"Sprint not found: {sprint_id}")
        start_date = date.fromisoformat(sprint_row["start_date"])
        end_date = date.fromisoformat(sprint_row["end_date"])
        resolved_sprint_id = sprint_id
        period = sprint_id
    elif period == "current_sprint":
        sprint_row = conn.execute(
            "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
        ).fetchone()
        if sprint_row is None:
            raise ValueError("No active sprint found")
        start_date = date.fromisoformat(sprint_row["start_date"])
        end_date = date.fromisoformat(sprint_row["end_date"])
        resolved_sprint_id = sprint_row["id"]
    elif period == "last_4_weeks":
        current_monday = today - timedelta(days=today.weekday())
        start_date = current_monday - timedelta(weeks=3)
        end_date = current_monday + timedelta(days=6)
    elif period == "last_8_weeks":
        current_monday = today - timedelta(days=today.weekday())
        start_date = current_monday - timedelta(weeks=7)
        end_date = current_monday + timedelta(days=6)
    else:
        raise ValueError(f"Invalid period: {period}")

    # Apply effective goals from sprint_habit_goals if sprint context available
    enriched = _get_effective_goals(conn, resolved_sprint_id, [habit])
    habit = enriched[0]
    target_per_week = habit["target_per_week"]

    # Count total entries in period
    total_entries = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE habit_id = ? "
        "AND date >= ? AND date <= ? AND value > 0",
        (habit_id, start_date.isoformat(), end_date.isoformat()),
    ).fetchone()[0]

    # Build weekly history (Monday-aligned weeks)
    weekly_history = []
    week_start = start_date - timedelta(days=start_date.weekday())
    while week_start <= end_date:
        week_end = week_start + timedelta(days=6)
        effective_start = max(week_start, start_date)
        effective_end = min(week_end, end_date)

        actual = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE habit_id = ? "
            "AND date >= ? AND date <= ? AND value > 0",
            (habit_id, effective_start.isoformat(), effective_end.isoformat()),
        ).fetchone()[0]

        pct = int((actual / target_per_week) * 100) if target_per_week > 0 else 0
        if pct > 100:
            pct = 100

        weekly_history.append({
            "week_start": week_start.isoformat(),
            "actual": actual,
            "target": target_per_week,
            "completion_pct": pct,
        })
        week_start += timedelta(weeks=1)

    # Expected entries and completion
    expected_entries = len(weekly_history) * target_per_week
    completion_pct = (
        int((total_entries / expected_entries) * 100) if expected_entries > 0 else 0
    )
    if completion_pct > 100:
        completion_pct = 100

    # Streaks (all-time for this habit)
    entry_rows = conn.execute(
        "SELECT date FROM entries WHERE habit_id = ? AND value > 0 ORDER BY date",
        (habit_id,),
    ).fetchall()

    if not entry_rows:
        current_streak = 0
        longest_streak = 0
    else:
        entry_dates = {date.fromisoformat(r["date"]) for r in entry_rows}
        sorted_dates = sorted(entry_dates)
        longest_streak = 1
        run = 1
        for i in range(1, len(sorted_dates)):
            if sorted_dates[i] - sorted_dates[i - 1] == timedelta(days=1):
                run += 1
                if run > longest_streak:
                    longest_streak = run
            else:
                run = 1

        if today in entry_dates:
            check = today
        elif (today - timedelta(days=1)) in entry_dates:
            check = today - timedelta(days=1)
        else:
            check = None

        if check is None:
            current_streak = 0
        else:
            current_streak = 0
            while check in entry_dates:
                current_streak += 1
                check -= timedelta(days=1)

    # Rolling 7-day average: entries with value > 0 in last 7 days / 7
    seven_days_ago = today - timedelta(days=6)
    rolling_count = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE habit_id = ? "
        "AND date >= ? AND date <= ? AND value > 0",
        (habit_id, seven_days_ago.isoformat(), today.isoformat()),
    ).fetchone()[0]
    rolling_7_day_avg = round(rolling_count / 7, 2)

    # Trend vs prior period
    period_days = (end_date - start_date).days + 1
    prior_end = start_date - timedelta(days=1)
    prior_start = prior_end - timedelta(days=period_days - 1)

    prior_entries = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE habit_id = ? "
        "AND date >= ? AND date <= ? AND value > 0",
        (habit_id, prior_start.isoformat(), prior_end.isoformat()),
    ).fetchone()[0]
    prior_completion_pct = (
        int((prior_entries / expected_entries) * 100) if expected_entries > 0 else 0
    )
    if prior_completion_pct > 100:
        prior_completion_pct = 100

    delta = completion_pct - prior_completion_pct
    trend_vs_prior_period = f"+{delta}%" if delta >= 0 else f"{delta}%"

    return {
        "habit_id": habit_id,
        "habit_name": habit["name"],
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_entries": total_entries,
        "expected_entries": expected_entries,
        "completion_pct": completion_pct,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "rolling_7_day_avg": rolling_7_day_avg,
        "trend_vs_prior_period": trend_vs_prior_period,
        "weekly_history": weekly_history,
    }


def category_report(conn: sqlite3.Connection, payload: dict) -> dict:
    sprint_id = payload.get("sprint_id")
    category_filter = payload.get("category")

    # Resolve sprint
    if sprint_id:
        row = conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Sprint not found: {sprint_id}")
        sprint = dict(row)
    else:
        row = conn.execute(
            "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("No active sprint found")
        sprint = dict(row)
        sprint_id = sprint["id"]

    start = date.fromisoformat(sprint["start_date"])
    end = date.fromisoformat(sprint["end_date"])
    total_days = (end - start).days + 1
    num_weeks = math.ceil(total_days / 7)

    # Get habits for this sprint (sprint_habit_goals rows + non-archived globals)
    habits = _get_sprint_habits(conn, sprint_id)
    habits = _get_effective_goals(conn, sprint_id, habits)

    # Group habits by category
    cat_data: dict[str, list[dict]] = {}
    for h in habits:
        cat = h["category"]
        if category_filter and cat != category_filter:
            continue
        cat_data.setdefault(cat, []).append(h)

    # Compute per-category scores
    categories = []
    for cat_name, cat_habits in cat_data.items():
        weighted_actual = 0
        weighted_target = 0
        total_actual = 0
        total_target = 0
        habit_ids = []

        for h in cat_habits:
            target_entries = h["target_per_week"] * num_weeks
            actual_entries = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE habit_id = ? "
                "AND date >= ? AND date <= ? AND value > 0",
                (h["id"], sprint["start_date"], sprint["end_date"]),
            ).fetchone()[0]

            weighted_actual += actual_entries * h["weight"]
            weighted_target += target_entries * h["weight"]
            total_actual += actual_entries
            total_target += target_entries
            habit_ids.append(h["id"])

        weighted_score = round(weighted_actual / weighted_target * 100) if weighted_target > 0 else 0
        unweighted_score = round(total_actual / total_target * 100) if total_target > 0 else 0

        categories.append({
            "category": cat_name,
            "habits_count": len(cat_habits),
            "weighted_score": weighted_score,
            "unweighted_score": unweighted_score,
            "habit_ids": habit_ids,
        })

    # Balance assessment
    if len(categories) >= 2:
        sorted_by_weighted = sorted(categories, key=lambda c: c["weighted_score"])
        least = sorted_by_weighted[0]
        most = sorted_by_weighted[-1]
        balance_assessment = {
            "most_adherent": most["category"],
            "least_adherent": least["category"],
            "spread": most["weighted_score"] - least["weighted_score"],
        }
    elif len(categories) == 1:
        cat = categories[0]
        balance_assessment = {
            "most_adherent": cat["category"],
            "least_adherent": cat["category"],
            "spread": 0,
        }
    else:
        balance_assessment = {
            "most_adherent": None,
            "least_adherent": None,
            "spread": 0,
        }

    return {
        "sprint_id": sprint_id,
        "categories": categories,
        "balance_assessment": balance_assessment,
    }


def cross_sprint_report(conn: sqlite3.Connection, payload: dict) -> dict:
    """Compare metrics across multiple sprints.

    Payload
    -------
    limit : int, optional
        Maximum number of sprints to include (most recent first).
        Default: all sprints.
    habit_id : str, optional
        Filter results to a single habit.

    Returns
    -------
    dict with ``sprints`` (array of sprint summaries) and ``overall_trend``.
    """
    limit = payload.get("limit")
    habit_id_filter = payload.get("habit_id")

    # Validate habit_id if provided
    if habit_id_filter:
        row = conn.execute(
            "SELECT * FROM habits WHERE id = ?", (habit_id_filter,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Habit not found: {habit_id_filter}")

    # Fetch sprints ordered by start_date ascending
    if limit:
        sprint_rows = conn.execute(
            "SELECT * FROM sprints ORDER BY start_date DESC LIMIT ?", (limit,)
        ).fetchall()
        sprint_rows = list(reversed(sprint_rows))  # back to chronological
    else:
        sprint_rows = conn.execute(
            "SELECT * FROM sprints ORDER BY start_date"
        ).fetchall()

    if not sprint_rows:
        return {"sprints": [], "overall_trend": "stable"}

    sprint_summaries = []
    prev_weighted_score = None

    for sprint_row in sprint_rows:
        sprint = dict(sprint_row)
        sprint_id = sprint["id"]
        start = date.fromisoformat(sprint["start_date"])
        end = date.fromisoformat(sprint["end_date"])
        total_days = (end - start).days + 1
        num_weeks = math.ceil(total_days / 7)

        # Get habits for this sprint
        habits = _get_sprint_habits(conn, sprint_id)
        habits = _get_effective_goals(conn, sprint_id, habits)

        # Filter to single habit if requested
        if habit_id_filter:
            habits = [h for h in habits if h["id"] == habit_id_filter]

        total_weighted_actual = 0
        total_weighted_target = 0
        total_actual = 0
        total_target = 0
        categories: dict[str, dict] = {}
        habit_completions = []

        for h in habits:
            target_entries = h["target_per_week"] * num_weeks
            actual_entries = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE habit_id = ? "
                "AND date >= ? AND date <= ? AND value > 0",
                (h["id"], sprint["start_date"], sprint["end_date"]),
            ).fetchone()[0]

            completion_pct = (
                round(actual_entries / target_entries * 100)
                if target_entries > 0 else 0
            )

            total_weighted_actual += actual_entries * h["weight"]
            total_weighted_target += target_entries * h["weight"]
            total_actual += actual_entries
            total_target += target_entries

            habit_completions.append({
                "habit_id": h["id"],
                "name": h["name"],
                "actual": actual_entries,
                "target": target_entries,
                "completion_pct": completion_pct,
            })

            # Accumulate per-category
            cat = h["category"]
            if cat not in categories:
                categories[cat] = {"weighted_actual": 0, "weighted_target": 0}
            categories[cat]["weighted_actual"] += actual_entries * h["weight"]
            categories[cat]["weighted_target"] += target_entries * h["weight"]

        weighted_score = (
            round(total_weighted_actual / total_weighted_target * 100)
            if total_weighted_target > 0 else 0
        )
        unweighted_score = (
            round(total_actual / total_target * 100)
            if total_target > 0 else 0
        )

        # Per-category scores
        category_scores = []
        for cat_name, cat_data in categories.items():
            wa = cat_data["weighted_actual"]
            wt = cat_data["weighted_target"]
            category_scores.append({
                "category": cat_name,
                "weighted_score": round(wa / wt * 100) if wt > 0 else 0,
            })

        # Trend delta vs previous sprint
        trend_delta = None
        if prev_weighted_score is not None:
            trend_delta = weighted_score - prev_weighted_score

        # Parse focus_goals
        focus_goals = sprint.get("focus_goals", "[]")
        if isinstance(focus_goals, str):
            import json as _json
            focus_goals = _json.loads(focus_goals)

        sprint_summaries.append({
            "sprint_id": sprint_id,
            "start_date": sprint["start_date"],
            "end_date": sprint["end_date"],
            "theme": sprint["theme"],
            "status": sprint["status"],
            "weighted_score": weighted_score,
            "unweighted_score": unweighted_score,
            "category_scores": category_scores,
            "habit_completions": habit_completions,
            "trend_delta": trend_delta,
        })

        prev_weighted_score = weighted_score

    # Overall trend assessment
    if len(sprint_summaries) < 2:
        overall_trend = "stable"
    else:
        scores = [s["weighted_score"] for s in sprint_summaries]
        # Compare last score to first score
        diff = scores[-1] - scores[0]
        if diff > 5:
            overall_trend = "improving"
        elif diff < -5:
            overall_trend = "declining"
        else:
            overall_trend = "stable"

    return {
        "sprints": sprint_summaries,
        "overall_trend": overall_trend,
    }


def streak_leaderboard(conn: sqlite3.Connection, payload: dict) -> dict:
    """Return a streak leaderboard for all active habits.

    Payload
    -------
    sprint_id : str, optional
        Scope to habits in a specific sprint.  Defaults to the active sprint.

    Returns
    -------
    dict with ``habits`` list sorted by current_streak descending.
    """
    sprint_id = payload.get("sprint_id")

    # Resolve sprint
    if sprint_id:
        row = conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Sprint not found: {sprint_id}")
        sprint = dict(row)
    else:
        row = conn.execute(
            "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("No active sprint found")
        sprint = dict(row)
        sprint_id = sprint["id"]

    habits = _get_sprint_habits(conn, sprint_id)
    habits = _get_effective_goals(conn, sprint_id, habits)

    leaderboard = []
    for h in habits:
        entry_rows = conn.execute(
            "SELECT date FROM entries WHERE habit_id = ? AND value > 0 ORDER BY date",
            (h["id"],),
        ).fetchall()
        current_streak, longest_streak = _compute_streaks(entry_rows)
        total_checkins = len(entry_rows)

        leaderboard.append({
            "habit_id": h["id"],
            "name": h["name"],
            "category": h["category"],
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "total_checkins": total_checkins,
        })

    # Sort by current_streak desc, then longest_streak desc, then total_checkins desc
    leaderboard.sort(
        key=lambda x: (x["current_streak"], x["longest_streak"], x["total_checkins"]),
        reverse=True,
    )

    return {"sprint_id": sprint_id, "habits": leaderboard}


def progress_summary(conn: sqlite3.Connection, payload: dict) -> dict:
    """Return a holistic progress summary for LLM consumption.

    Payload
    -------
    sprint_id : str, optional
        Scope to a specific sprint.  Defaults to the active sprint.

    Returns
    -------
    dict with overall_trend, strongest/weakest habits, category balance,
    active streaks, and recommendations.
    """
    sprint_id = payload.get("sprint_id")

    # Resolve sprint
    if sprint_id:
        row = conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Sprint not found: {sprint_id}")
        sprint = dict(row)
    else:
        row = conn.execute(
            "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("No active sprint found")
        sprint = dict(row)
        sprint_id = sprint["id"]

    start = date.fromisoformat(sprint["start_date"])
    end = date.fromisoformat(sprint["end_date"])
    total_days = (end - start).days + 1
    num_weeks = math.ceil(total_days / 7)

    # Get habits
    habits = _get_sprint_habits(conn, sprint_id)
    habits = _get_effective_goals(conn, sprint_id, habits)

    # Compute per-habit stats
    habit_stats = []
    cat_data: dict[str, dict] = {}

    for h in habits:
        target_entries = h["target_per_week"] * num_weeks
        actual_entries = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE habit_id = ? "
            "AND date >= ? AND date <= ? AND value > 0",
            (h["id"], sprint["start_date"], sprint["end_date"]),
        ).fetchone()[0]
        completion_pct = round(actual_entries / target_entries * 100) if target_entries > 0 else 0

        entry_rows = conn.execute(
            "SELECT date FROM entries WHERE habit_id = ? AND value > 0 ORDER BY date",
            (h["id"],),
        ).fetchall()
        current_streak, longest_streak = _compute_streaks(entry_rows)

        stat = {
            "habit_id": h["id"],
            "name": h["name"],
            "category": h["category"],
            "weight": h["weight"],
            "completion_pct": completion_pct,
            "actual": actual_entries,
            "target": target_entries,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
        }
        habit_stats.append(stat)

        # Category accumulation
        cat = h["category"]
        if cat not in cat_data:
            cat_data[cat] = {"weighted_actual": 0, "weighted_target": 0}
        cat_data[cat]["weighted_actual"] += actual_entries * h["weight"]
        cat_data[cat]["weighted_target"] += target_entries * h["weight"]

    # Sort habits by completion_pct
    sorted_by_completion = sorted(habit_stats, key=lambda x: x["completion_pct"], reverse=True)
    strongest = sorted_by_completion[:3]
    weakest = sorted(habit_stats, key=lambda x: x["completion_pct"])[:3]

    # Category balance
    category_balance = []
    for cat_name, cd in cat_data.items():
        wa = cd["weighted_actual"]
        wt = cd["weighted_target"]
        category_balance.append({
            "category": cat_name,
            "weighted_score": round(wa / wt * 100) if wt > 0 else 0,
        })
    category_balance.sort(key=lambda x: x["weighted_score"], reverse=True)

    # Active streaks (habits with current_streak > 0)
    active_streaks = [
        {"habit_id": s["habit_id"], "name": s["name"], "current_streak": s["current_streak"]}
        for s in sorted(habit_stats, key=lambda x: x["current_streak"], reverse=True)
        if s["current_streak"] > 0
    ]

    # Overall trend from cross_sprint_report
    cross_data = cross_sprint_report(conn, {})
    overall_trend = cross_data.get("overall_trend", "stable")

    # Overall weighted score for this sprint
    total_wa = sum(cd["weighted_actual"] for cd in cat_data.values())
    total_wt = sum(cd["weighted_target"] for cd in cat_data.values())
    overall_score = round(total_wa / total_wt * 100) if total_wt > 0 else 0

    # Recommendations
    recommendations = []
    if weakest and weakest[0]["completion_pct"] < 50:
        recommendations.append(
            f"Focus on \"{weakest[0]['name']}\" — only {weakest[0]['completion_pct']}% completion."
        )
    if len(category_balance) >= 2:
        spread = category_balance[0]["weighted_score"] - category_balance[-1]["weighted_score"]
        if spread > 30:
            recommendations.append(
                f"Category imbalance detected: {category_balance[-1]['category']} "
                f"({category_balance[-1]['weighted_score']}%) lags behind "
                f"{category_balance[0]['category']} ({category_balance[0]['weighted_score']}%)."
            )
    no_streak = [s for s in habit_stats if s["current_streak"] == 0]
    if no_streak:
        recommendations.append(
            f"{len(no_streak)} habit(s) have no active streak — consider re-engaging."
        )
    if overall_trend == "declining":
        recommendations.append("Overall trend is declining — review workload and priorities.")

    return {
        "sprint_id": sprint_id,
        "overall_score": overall_score,
        "overall_trend": overall_trend,
        "strongest_habits": [
            {"habit_id": s["habit_id"], "name": s["name"], "completion_pct": s["completion_pct"]}
            for s in strongest
        ],
        "weakest_habits": [
            {"habit_id": s["habit_id"], "name": s["name"], "completion_pct": s["completion_pct"]}
            for s in weakest
        ],
        "category_balance": category_balance,
        "active_streaks": active_streaks,
        "recommendations": recommendations,
    }


def sprint_dashboard(conn: sqlite3.Connection, payload: dict) -> dict:
    sprint_id = payload.get("sprint_id")
    week = payload.get("week")  # 1 or 2, optional

    # Resolve sprint
    if sprint_id:
        row = conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Sprint not found: {sprint_id}")
        sprint = dict(row)
    else:
        row = conn.execute(
            "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
        ).fetchone()
        if row is None:
            raise ValueError("No active sprint found")
        sprint = dict(row)
        sprint_id = sprint["id"]

    # Parse focus_goals
    focus_goals = sprint.get("focus_goals", "[]")
    if isinstance(focus_goals, str):
        focus_goals = json.loads(focus_goals)

    start = date.fromisoformat(sprint["start_date"])
    end = date.fromisoformat(sprint["end_date"])
    today = date.today()

    total_days = (end - start).days + 1

    # days_elapsed / days_remaining
    if today < start:
        days_elapsed = 0
        days_remaining = total_days
    elif today > end:
        days_elapsed = total_days
        days_remaining = 0
    else:
        days_elapsed = (today - start).days + 1
        days_remaining = (end - today).days

    # Determine date range based on week parameter
    if week is not None:
        week_start = start + timedelta(days=(week - 1) * 7)
        week_end = min(week_start + timedelta(days=6), end)
        if week_start > end:
            raise ValueError(f"Week {week} is outside sprint range")
        view_dates = []
        d = week_start
        while d <= week_end:
            view_dates.append(d)
            d += timedelta(days=1)
    else:
        view_dates = []
        d = start
        while d <= end:
            view_dates.append(d)
            d += timedelta(days=1)

    # Get habits for this sprint (sprint_habit_goals rows + non-archived globals)
    habits = _get_sprint_habits(conn, sprint_id)
    habits = _get_effective_goals(conn, sprint_id, habits)

    # Fetch all entries for these habits in the view date range
    habit_ids = [h["id"] for h in habits]
    entries_by_habit: dict[str, dict[str, float]] = {}
    if habit_ids and view_dates:
        placeholders = ",".join("?" * len(habit_ids))
        entry_rows = conn.execute(
            f"""SELECT habit_id, date, value FROM entries
                WHERE habit_id IN ({placeholders})
                  AND date >= ? AND date <= ?""",
            (*habit_ids, view_dates[0].isoformat(), view_dates[-1].isoformat()),
        ).fetchall()
        for e in entry_rows:
            entries_by_habit.setdefault(e["habit_id"], {})[e["date"]] = e["value"]

    # Build categories with habits and daily values
    num_weeks_in_view = math.ceil(len(view_dates) / 7) if view_dates else 0
    categories: dict[str, dict] = {}

    for h in habits:
        cat = h["category"]
        habit_entries = entries_by_habit.get(h["id"], {})

        # Build daily values for the view dates
        daily = {}
        actual_count = 0
        for vd in view_dates:
            ds = vd.isoformat()
            val = habit_entries.get(ds, 0)
            daily[ds] = val
            if val > 0:
                actual_count += 1

        target = h["target_per_week"]
        total_target = target * num_weeks_in_view
        completion_pct = round(actual_count / total_target * 100) if total_target > 0 else 0
        if completion_pct > 100:
            completion_pct = 100

        habit_data = {
            "habit_id": h["id"],
            "name": h["name"],
            "target_per_week": target,
            "weight": h["weight"],
            "daily": daily,
            "week_actual": actual_count,
            "week_completion_pct": completion_pct,
            "commitment_met": actual_count >= total_target,
        }

        if cat not in categories:
            categories[cat] = {
                "habits": [],
                "weighted_actual": 0,
                "weighted_target": 0,
            }
        categories[cat]["habits"].append(habit_data)
        categories[cat]["weighted_actual"] += actual_count * h["weight"]
        categories[cat]["weighted_target"] += total_target * h["weight"]

    # Build category list with weighted scores
    category_list = []
    for cat_name, cat_data in categories.items():
        wa = cat_data["weighted_actual"]
        wt = cat_data["weighted_target"]
        category_list.append({
            "category": cat_name,
            "habits": cat_data["habits"],
            "category_weighted_score": round(wa / wt * 100) if wt > 0 else 0,
        })

    # Build daily_totals: for each day, sum(value*weight) / sum(weight)
    daily_totals = {}
    for vd in view_dates:
        ds = vd.isoformat()
        points = 0
        max_points = 0
        for h in habits:
            weight = h["weight"]
            max_points += weight
            habit_entries = entries_by_habit.get(h["id"], {})
            val = habit_entries.get(ds, 0)
            points += val * weight
        pct = round(points / max_points * 100) if max_points > 0 else 0
        daily_totals[ds] = {
            "points": points,
            "max": max_points,
            "pct": pct,
        }

    # Build sprint_summary
    total_weighted_actual = 0
    total_weighted_target = 0
    total_actual = 0
    total_target = 0
    per_habit = []

    for h in habits:
        target_entries = h["target_per_week"] * num_weeks_in_view
        habit_entries = entries_by_habit.get(h["id"], {})
        actual_entries = sum(
            1 for vd in view_dates if habit_entries.get(vd.isoformat(), 0) > 0
        )

        total_weighted_actual += actual_entries * h["weight"]
        total_weighted_target += target_entries * h["weight"]
        total_actual += actual_entries
        total_target += target_entries

        pct = round(actual_entries / target_entries * 100) if target_entries > 0 else 0
        per_habit.append({
            "habit_id": h["id"],
            "actual": actual_entries,
            "target": target_entries,
            "pct": pct,
        })

    weighted_score = (
        round(total_weighted_actual / total_weighted_target * 100)
        if total_weighted_target > 0 else 0
    )
    unweighted_score = (
        round(total_actual / total_target * 100)
        if total_target > 0 else 0
    )

    sprint_summary = {
        "weighted_score": weighted_score,
        "unweighted_score": unweighted_score,
        "per_habit": per_habit,
    }

    # Fetch retro
    retro_row = conn.execute(
        "SELECT * FROM retros WHERE sprint_id = ?", (sprint_id,)
    ).fetchone()
    retro = dict(retro_row) if retro_row else None

    return {
        "sprint": {
            "id": sprint_id,
            "start_date": sprint["start_date"],
            "end_date": sprint["end_date"],
            "theme": sprint["theme"],
            "focus_goals": focus_goals,
            "status": sprint["status"],
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
        },
        "categories": category_list,
        "daily_totals": daily_totals,
        "sprint_summary": sprint_summary,
        "retro": retro,
    }
