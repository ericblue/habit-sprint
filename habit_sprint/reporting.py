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


def weekly_completion(conn: sqlite3.Connection, payload: dict) -> dict:
    habit_id = payload["habit_id"]

    # Look up habit
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
    if row is None:
        raise ValueError(f"Habit not found: {habit_id}")
    target_per_week = row["target_per_week"]

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

    # Get all non-archived habits for this sprint (sprint-scoped + global)
    habits = conn.execute(
        """SELECT * FROM habits
           WHERE archived = 0
             AND (sprint_id = ? OR sprint_id IS NULL)
           ORDER BY created_at""",
        (sprint_id,),
    ).fetchall()

    habits_completed = []
    habits_missed = []
    total_points = 0
    max_possible = 0

    for habit in habits:
        h = dict(habit)
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

    # Get all non-archived habits for this sprint
    habits = conn.execute(
        """SELECT * FROM habits
           WHERE archived = 0
             AND (sprint_id = ? OR sprint_id IS NULL)
           ORDER BY category, created_at""",
        (sprint_id,),
    ).fetchall()

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
    for habit in habits:
        h = dict(habit)
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

    # All non-archived habits for this sprint (sprint-scoped + global)
    habits = conn.execute(
        """SELECT * FROM habits
           WHERE archived = 0
             AND (sprint_id = ? OR sprint_id IS NULL)
           ORDER BY created_at""",
        (sprint_id,),
    ).fetchall()

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

    for habit in habits:
        h = dict(habit)
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

        prev_habits = conn.execute(
            """SELECT * FROM habits
               WHERE sprint_id = ? OR sprint_id IS NULL
               ORDER BY created_at""",
            (prev["id"],),
        ).fetchall()

        prev_wa = 0
        prev_wt = 0
        for ph in prev_habits:
            ph_d = dict(ph)
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
    target_per_week = habit["target_per_week"]

    today = date.today()

    # Determine period dates
    if sprint_id:
        sprint_row = conn.execute(
            "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
        ).fetchone()
        if sprint_row is None:
            raise ValueError(f"Sprint not found: {sprint_id}")
        start_date = date.fromisoformat(sprint_row["start_date"])
        end_date = date.fromisoformat(sprint_row["end_date"])
        period = sprint_id
    elif period == "current_sprint":
        sprint_row = conn.execute(
            "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
        ).fetchone()
        if sprint_row is None:
            raise ValueError("No active sprint found")
        start_date = date.fromisoformat(sprint_row["start_date"])
        end_date = date.fromisoformat(sprint_row["end_date"])
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

    # All non-archived habits for this sprint (sprint-scoped + global)
    habits = conn.execute(
        """SELECT * FROM habits
           WHERE archived = 0
             AND (sprint_id = ? OR sprint_id IS NULL)
           ORDER BY created_at""",
        (sprint_id,),
    ).fetchall()

    # Group habits by category
    cat_data: dict[str, list[dict]] = {}
    for habit in habits:
        h = dict(habit)
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

    # Get all non-archived habits for this sprint
    habits = conn.execute(
        """SELECT * FROM habits
           WHERE archived = 0
             AND (sprint_id = ? OR sprint_id IS NULL)
           ORDER BY category, created_at""",
        (sprint_id,),
    ).fetchall()

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

    for habit in habits:
        h = dict(habit)
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
        for habit in habits:
            h = dict(habit)
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

    for habit in habits:
        h = dict(habit)
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
