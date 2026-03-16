"""ASCII/markdown formatters for habit-sprint reporting data."""

import json
import math
from datetime import date

DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LINE_WIDTH = 68
HABIT_COL = 26
MINWK_COL = 8
WT_COL = 4
DAY_W = 4  # width of each day column


def _check(val: int | float) -> str:
    """Return ✓ for value > 0, · otherwise."""
    return "✓" if val > 0 else "·"


def _star(commitment_met: bool) -> str:
    """Return ★ suffix when commitment is met."""
    return " ★" if commitment_met else ""


def _pct(value: int) -> str:
    """Right-align a percentage string to 4 chars (e.g. ' 75%')."""
    return f"{value}%".rjust(4)


# ---------------------------------------------------------------------------
# sprint_dashboard — full ASCII grid with ✓/·/★ symbols
# ---------------------------------------------------------------------------

def format_sprint_dashboard(data: dict) -> str:
    """Format sprint_dashboard data as aligned ASCII text.

    Implements the PRD Section 9.2 rendering rules:
    - checkmark for value > 0, dot for 0/no entry
    - star appended when commitment_met = true
    - daily points per category = sum of (value * weight)
    - daily totals across all categories
    """
    sprint = data["sprint"]
    categories = data["categories"]
    daily_totals = data["daily_totals"]
    summary = data["sprint_summary"]
    retro = data["retro"]

    view_dates = sorted(daily_totals.keys())
    num_days = len(view_dates)

    # Week detection
    start = date.fromisoformat(sprint["start_date"])
    end = date.fromisoformat(sprint["end_date"])
    total_days = (end - start).days + 1
    total_weeks = math.ceil(total_days / 7)

    is_filtered = num_days < total_days
    if is_filtered and view_dates:
        first_view = date.fromisoformat(view_dates[0])
        current_week = (first_view - start).days // 7 + 1
    else:
        current_week = None

    # Day column headers from actual dates
    day_names = [DAY_ABBR[date.fromisoformat(d).weekday()] for d in view_dates]

    # Build habit_id -> habit info map for summary section
    habit_map = {}
    for cat in categories:
        for h in cat["habits"]:
            habit_map[h["habit_id"]] = h

    lines: list[str] = []

    # === HEADER ===
    lines.append(_sep("="))
    week_suffix = f"  [Week {current_week} of {total_weeks}]" if current_week else ""
    lines.append(
        f"SPRINT: {sprint['start_date']} \u2192 {sprint['end_date']}{week_suffix}"
    )
    if sprint.get("theme"):
        lines.append(f"THEME:  {sprint['theme']}")
    goals = sprint.get("focus_goals", [])
    if goals:
        lines.append(f"FOCUS:  {' | '.join(goals)}")
    lines.append(_sep("="))

    # === CATEGORIES ===
    for cat in categories:
        lines.append("")
        _render_category(lines, cat, view_dates, day_names)

    # === DAILY TOTALS ===
    lines.append("")
    lines.append(_sep("="))
    _render_daily_totals(lines, daily_totals, view_dates, day_names)
    lines.append(_sep("="))

    # === SPRINT SUMMARY ===
    lines.append("")
    _render_summary(lines, summary, habit_map)

    # === SPRINT REFLECTION ===
    lines.append("")
    _render_reflection(lines, retro)
    lines.append(_sep("="))

    return "\n".join(lines) + "\n"


def _sep(char: str) -> str:
    return char * LINE_WIDTH


def _render_category(
    lines: list[str],
    cat: dict,
    view_dates: list[str],
    day_names: list[str],
) -> None:
    cat_name = cat["category"]
    score = cat["category_weighted_score"]
    num_days = len(view_dates)

    # Category header with score right-aligned
    left = f"CATEGORY: {cat_name}"
    right = f"Score: {score}%"
    gap = LINE_WIDTH - len(left) - len(right)
    lines.append(f"{left}{' ' * max(gap, 2)}{right}")
    lines.append(_sep("-"))

    # Table header
    day_hdr = "".join(f"{n:>{DAY_W}}" for n in day_names)
    lines.append(
        f"{'Habit':<{HABIT_COL}}|{'Min/Wk':^{MINWK_COL}}|{'Wt':^{WT_COL}}|{day_hdr} |"
    )
    lines.append(_sep("-"))

    # Habit rows
    for h in cat["habits"]:
        name = h["name"]
        if len(name) > HABIT_COL - 1:
            name = name[: HABIT_COL - 1]
        target = h["target_per_week"]
        weight = h["weight"]
        daily = h["daily"]
        actual = h["week_actual"]

        num_view_weeks = math.ceil(num_days / 7) if num_days > 0 else 0
        total_target = target * num_view_weeks
        pct = h["week_completion_pct"]
        met = h["commitment_met"]

        # Day marks aligned with header columns
        marks = ""
        for ds in view_dates:
            val = daily.get(ds, 0)
            m = "\u2713" if val > 0 else "\u00b7"
            marks += f"{m:>{DAY_W}}"

        star = " \u2605" if met else ""
        tally = f"{actual:>2}/{total_target:<2} {pct:>3}%{star}"

        lines.append(
            f"{name:<{HABIT_COL}}"
            f"|{target:^{MINWK_COL}}"
            f"|{weight:^{WT_COL}}"
            f"|{marks} | {tally}"
        )

    lines.append(_sep("-"))

    # Daily points for this category
    cat_daily_points: list[int] = []
    for ds in view_dates:
        pts = 0
        for h in cat["habits"]:
            val = h["daily"].get(ds, 0)
            pts += int(val * h["weight"])
        cat_daily_points.append(pts)

    pts_str = "".join(f"{p:>{DAY_W}}" for p in cat_daily_points)
    # Prefix length: habit_col + pipe + minwk_col + pipe + wt_col + pipe
    prefix_len = HABIT_COL + 1 + MINWK_COL + 1 + WT_COL + 1
    prefix = "Daily Points" + " " * (prefix_len - len("Daily Points") - 2) + "\u2192 "
    lines.append(f"{prefix}{pts_str}")


def _render_daily_totals(
    lines: list[str],
    daily_totals: dict,
    view_dates: list[str],
    day_names: list[str],
) -> None:
    # Use wider columns (DAY_W+1) for daily totals to accommodate "100%"
    col_w = DAY_W + 1
    day_hdr = "".join(f"{n:>{col_w}}" for n in day_names)
    label_w = 30
    lines.append(f"{'DAILY TOTALS':<{label_w}}{day_hdr}")

    pts_str = "".join(
        f"{int(daily_totals[ds]['points']):>{col_w}}" for ds in view_dates
    )
    lines.append(f"{'Points':<{label_w - 4}}\u2192  {pts_str}")

    max_str = "".join(
        f"{daily_totals[ds]['max']:>{col_w}}" for ds in view_dates
    )
    lines.append(f"{'Max Possible':<{label_w - 4}}\u2192  {max_str}")

    pct_parts = "".join(
        f"{str(daily_totals[ds]['pct']) + '%':>{col_w}}" for ds in view_dates
    )
    lines.append(f"{'Completion %':<{label_w - 4}}\u2192  {pct_parts}")


def _render_summary(
    lines: list[str], summary: dict, habit_map: dict
) -> None:
    left = "SPRINT SUMMARY"
    right = f"Weighted: {summary['weighted_score']}%"
    gap = LINE_WIDTH - len(left) - len(right)
    lines.append(f"{left}{' ' * max(gap, 2)}{right}")
    lines.append(_sep("-"))

    for ph in summary["per_habit"]:
        hid = ph["habit_id"]
        h = habit_map.get(hid, {})
        name = h.get("name", hid)
        actual = ph["actual"]
        target = ph["target"]
        pct = ph["pct"]
        met = h.get("commitment_met", actual >= target)
        star = " \u2605" if met else ""
        lines.append(f"{name:<22}{actual:>2} / {target:<2} \u2192 {pct:>3}%{star}")

    lines.append(_sep("-"))


def _render_reflection(lines: list[str], retro: dict | None) -> None:
    lines.append("SPRINT REFLECTION")
    lines.append(_sep("-"))

    if retro is None:
        lines.append("(No retrospective recorded yet)")
        return

    sections = [
        ("what_went_well", "What went well:"),
        ("what_to_improve", "What needs improvement:"),
        ("ideas", "Ideas for next sprint:"),
    ]
    has_content = False
    for field, heading in sections:
        val = retro.get(field)
        if not val:
            continue
        items = _parse_retro_field(val)
        if not items:
            continue
        has_content = True
        lines.append(heading)
        for item in items:
            lines.append(f"- {item}")
        lines.append("")

    if not has_content:
        lines.append("(No retrospective recorded yet)")


def _parse_retro_field(field: str | list | None) -> list[str]:
    """Parse a retro field that could be a JSON array string or plain text."""
    if field is None:
        return []
    if isinstance(field, list):
        return [str(x) for x in field]
    if isinstance(field, str):
        try:
            parsed = json.loads(field)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        # Treat as single string entry
        return [field] if field.strip() else []
    return [str(field)]


# ---------------------------------------------------------------------------
# get_week_view — category-grouped week grid
# ---------------------------------------------------------------------------

def format_week_view(data: dict) -> str:
    """Render get_week_view data as a category-grouped week grid.

    This is a subset of the sprint_dashboard: category grids with daily
    points, but without the daily-totals summary, sprint summary, or
    reflection sections.
    """
    lines: list[str] = []
    sep = "=" * 68
    dash = "-" * 68
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    lines.append(sep)
    lines.append(
        f"WEEK VIEW: {data['week_start']} \u2192 {data['week_end']}"
    )
    lines.append(sep)

    categories = data.get("categories", {})
    for cat_name, cat_data in categories.items():
        habits = cat_data.get("habits", [])

        # Compute category weighted score
        weighted_actual = 0
        weighted_target = 0
        for h in habits:
            actual = h["week_actual"]
            target = h["target_per_week"]
            weight = h["weight"]
            weighted_actual += actual * weight
            weighted_target += target * weight
        cat_score = round(weighted_actual / weighted_target * 100) if weighted_target > 0 else 0

        lines.append("")
        cat_header = f"CATEGORY: {cat_name}"
        score_str = f"Score: {cat_score}%"
        pad = 68 - len(cat_header) - len(score_str)
        lines.append(f"{cat_header}{' ' * max(pad, 1)}{score_str}")
        lines.append(dash)

        # Table header
        lines.append(
            f"{'Habit':<26}| Min/Wk | Wt | {' '.join(f'{d:>3}' for d in day_labels)} |"
        )
        lines.append(dash)

        # Habit rows
        daily_points = [0] * 7
        for h in habits:
            name = h["name"][:25]
            target = h["target_per_week"]
            weight = h["weight"]
            dv = h["daily_values"]
            vals = [dv.get(d, 0) for d in day_labels]
            checks = " ".join(f"{_check(v):>3}" for v in vals)
            actual = h["week_actual"]
            pct = h["week_completion_pct"]
            met = h.get("commitment_met", actual >= target)
            star = _star(met)

            lines.append(
                f"{name:<26}|   {target:<5}|  {weight} | {checks} | {actual:>2}/{target:<2} {_pct(pct)}{star}"
            )

            # Accumulate daily points for this category
            for i, v in enumerate(vals):
                daily_points[i] += v * weight

        lines.append(dash)
        pts_str = " ".join(f"{p:>3}" for p in daily_points)
        lines.append(f"{'Daily Points':<26}{'':>12}\u2192 {pts_str}")

    lines.append("")
    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sprint_report — sprint summary with per-habit breakdown
# ---------------------------------------------------------------------------

def format_sprint_report(data: dict) -> str:
    """Render sprint_report data as a text summary."""
    lines: list[str] = []
    sep = "=" * 68
    dash = "-" * 68

    lines.append(sep)
    lines.append(
        f"SPRINT REPORT: {data['start_date']} \u2192 {data['end_date']}"
    )
    if data.get("theme"):
        lines.append(f"THEME:  {data['theme']}")
    status = data.get("status", "")
    lines.append(
        f"STATUS: {status}  "
        f"({data['days_elapsed']}/{data['total_days']} days elapsed, "
        f"{data['days_remaining']} remaining)"
    )
    lines.append(sep)

    # Focus goals
    focus_goals = data.get("focus_goals", [])
    if focus_goals:
        lines.append(f"FOCUS:  {' | '.join(focus_goals)}")
        lines.append("")

    # Overall scores
    lines.append(
        f"OVERALL SCORE                                    "
        f"Weighted: {data['weighted_score']}%"
    )
    if data.get("trend_vs_last_sprint") is not None:
        trend = data["trend_vs_last_sprint"]
        sign = "+" if trend >= 0 else ""
        lines.append(f"Trend vs last sprint: {sign}{trend}%")
    lines.append(dash)

    # Per-habit breakdown
    for h in data.get("habits", []):
        actual = h["total_entries"]
        expected = h["expected_entries"]
        pct = h["completion_pct"]
        met = actual >= expected
        star = _star(met)
        lines.append(
            f"{h['name']:<22}{actual:>2} / {expected:<2} \u2192 {_pct(pct)}{star}"
        )

    lines.append(dash)

    # Category scores
    cats = data.get("categories", [])
    if cats:
        lines.append("")
        lines.append("CATEGORY SCORES")
        lines.append(dash)
        for cat in cats:
            lines.append(
                f"  {cat['category']:<20} {cat['weighted_score']:>3}%"
            )
        lines.append(dash)

    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# habit_report — single habit weekly history table
# ---------------------------------------------------------------------------

def format_habit_report(data: dict) -> str:
    """Render habit_report data as a weekly history table."""
    lines: list[str] = []
    sep = "=" * 68
    dash = "-" * 68

    lines.append(sep)
    lines.append(f"HABIT REPORT: {data['habit_name']}")
    lines.append(
        f"Period: {data['start_date']} \u2192 {data['end_date']}"
    )
    lines.append(sep)

    # Summary stats
    lines.append(
        f"Completion: {data['total_entries']}/{data['expected_entries']} "
        f"({data['completion_pct']}%)"
    )
    lines.append(
        f"Streaks: current {data['current_streak']}, "
        f"longest {data['longest_streak']}"
    )
    lines.append(f"Rolling 7-day avg: {data['rolling_7_day_avg']}")
    lines.append(f"Trend vs prior period: {data['trend_vs_prior_period']}")
    lines.append("")

    # Weekly history table
    lines.append("WEEKLY HISTORY")
    lines.append(dash)
    lines.append(f"{'Week Start':<14} {'Actual':>6} / {'Target':<6} {'Pct':>5}")
    lines.append(dash)
    for week in data.get("weekly_history", []):
        met = week["actual"] >= week["target"]
        star = _star(met)
        lines.append(
            f"{week['week_start']:<14} {week['actual']:>6} / {week['target']:<6} "
            f"{_pct(week['completion_pct'])}{star}"
        )
    lines.append(dash)
    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# daily_score — single day's completed/missed habits with points
# ---------------------------------------------------------------------------

def format_daily_score(data: dict) -> str:
    """Render daily_score data showing completed and missed habits."""
    lines: list[str] = []
    sep = "=" * 68
    dash = "-" * 68

    lines.append(sep)
    lines.append(f"DAILY SCORE: {data['date']}")
    lines.append(
        f"Total: {data['total_points']}/{data['max_possible']} points "
        f"({data['completion_pct']}%)"
    )
    lines.append(sep)

    # Completed habits
    completed = data.get("habits_completed", [])
    if completed:
        lines.append("")
        lines.append("COMPLETED")
        lines.append(dash)
        for h in completed:
            lines.append(
                f"  \u2713 {h['name']:<22} "
                f"value={h['value']}  weight={h['weight']}  "
                f"points={h['points']}"
            )

    # Missed habits
    missed = data.get("habits_missed", [])
    if missed:
        lines.append("")
        lines.append("MISSED")
        lines.append(dash)
        for h in missed:
            lines.append(
                f"  \u00b7 {h['name']:<22} "
                f"weight={h['weight']}  "
                f"points_possible={h['points_possible']}"
            )

    lines.append("")
    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# category_report — category scores with balance assessment
# ---------------------------------------------------------------------------

def format_category_report(data: dict) -> str:
    """Render category_report data with scores and balance info."""
    lines: list[str] = []
    sep = "=" * 68
    dash = "-" * 68

    lines.append(sep)
    lines.append("CATEGORY REPORT")
    lines.append(sep)

    cats = data.get("categories", [])
    if cats:
        lines.append("")
        lines.append(
            f"{'Category':<20} {'Habits':>6}  {'Weighted':>8}  {'Unweighted':>10}"
        )
        lines.append(dash)
        for cat in cats:
            lines.append(
                f"{cat['category']:<20} {cat['habits_count']:>6}  "
                f"{cat['weighted_score']:>7}%  "
                f"{cat['unweighted_score']:>9}%"
            )
        lines.append(dash)

    # Balance assessment
    ba = data.get("balance_assessment", {})
    if ba.get("most_adherent") is not None:
        lines.append("")
        lines.append("BALANCE ASSESSMENT")
        lines.append(dash)
        lines.append(f"  Most adherent:  {ba['most_adherent']}")
        lines.append(f"  Least adherent: {ba['least_adherent']}")
        lines.append(f"  Spread:         {ba['spread']}%")
        lines.append(dash)

    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatcher — maps action names to formatter functions
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# cross_sprint_report — comparison table across sprints
# ---------------------------------------------------------------------------

def format_cross_sprint_report(data: dict) -> str:
    """Render cross_sprint_report data as a comparison table."""
    lines: list[str] = []
    sep = "=" * 68
    dash = "-" * 68

    sprints = data.get("sprints", [])
    overall_trend = data.get("overall_trend", "stable")

    lines.append(sep)
    lines.append(f"CROSS-SPRINT REPORT ({len(sprints)} sprints)")
    lines.append(f"Overall trend: {overall_trend}")
    lines.append(sep)

    if not sprints:
        lines.append("(No sprints found)")
        lines.append(sep)
        return "\n".join(lines)

    # Sprint comparison table
    lines.append("")
    lines.append(
        f"{'Sprint':<14} {'Dates':<25} {'Weighted':>8} {'Unwgtd':>7} {'Delta':>6}"
    )
    lines.append(dash)

    for s in sprints:
        dates = f"{s['start_date']} -> {s['end_date']}"
        delta_str = ""
        if s["trend_delta"] is not None:
            d = s["trend_delta"]
            delta_str = f"+{d}%" if d >= 0 else f"{d}%"
        lines.append(
            f"{s['sprint_id']:<14} {dates:<25} {s['weighted_score']:>7}% "
            f"{s['unweighted_score']:>6}% {delta_str:>6}"
        )

    lines.append(dash)

    # Per-sprint category breakdown
    for s in sprints:
        cat_scores = s.get("category_scores", [])
        if cat_scores:
            lines.append("")
            lines.append(f"  {s['sprint_id']} categories:")
            for cat in cat_scores:
                lines.append(
                    f"    {cat['category']:<20} {cat['weighted_score']:>3}%"
                )

    # Per-sprint habit completions
    lines.append("")
    lines.append("HABIT COMPLETIONS")
    lines.append(dash)

    # Collect all habit IDs across sprints
    all_habit_ids = []
    habit_names = {}
    for s in sprints:
        for h in s.get("habit_completions", []):
            if h["habit_id"] not in habit_names:
                all_habit_ids.append(h["habit_id"])
                habit_names[h["habit_id"]] = h["name"]

    # Build per-habit row: habit name then pct per sprint
    if all_habit_ids:
        # Header
        sprint_labels = [s["sprint_id"][:10] for s in sprints]
        hdr = f"{'Habit':<22}" + "".join(f"{lbl:>12}" for lbl in sprint_labels)
        lines.append(hdr)
        lines.append(dash)

        for hid in all_habit_ids:
            name = habit_names[hid]
            if len(name) > 21:
                name = name[:21]
            row = f"{name:<22}"
            for s in sprints:
                found = None
                for h in s.get("habit_completions", []):
                    if h["habit_id"] == hid:
                        found = h
                        break
                if found:
                    row += f"{found['completion_pct']:>11}%"
                else:
                    row += f"{'—':>12}"
            lines.append(row)

        lines.append(dash)

    lines.append(sep)
    return "\n".join(lines)


FORMATTERS: dict[str, callable] = {
    "sprint_dashboard": format_sprint_dashboard,
    "get_week_view": format_week_view,
    "sprint_report": format_sprint_report,
    "habit_report": format_habit_report,
    "daily_score": format_daily_score,
    "category_report": format_category_report,
    "cross_sprint_report": format_cross_sprint_report,
}
