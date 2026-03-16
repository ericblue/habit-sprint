#!/usr/bin/env python3
"""Clean reimport of historical data from import_data.txt.

Deletes all historical sprints/habits/entries, reimports from the text file,
deduplicates habits by name, and binds them to sprints via sprint_habit_goals.
Preserves the current sprint (2026-S01) and its data.
"""

import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from habit_sprint.db import get_connection

DB_PATH = Path.home() / ".habit-sprint" / "habits.db"
IMPORT_FILE = PROJECT_ROOT / "data" / "import_data.txt"
CURRENT_SPRINT = "2026-S01"


def slugify(name: str) -> str:
    """Convert habit name to a slug ID."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s


def parse_import_file(path: Path) -> list[dict]:
    """Parse import_data.txt into structured sprint data."""
    text = path.read_text()
    sprints = []
    current_sprint = None

    for line in text.splitlines():
        line = line.rstrip()

        # Sprint header
        m = re.match(r"SPRINT:\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\s+\((\d+)-week\)", line)
        if m:
            current_sprint = {
                "start_date": m.group(1),
                "end_date": m.group(2),
                "weeks": int(m.group(3)),
                "goals": [],
                "habits": [],
            }
            sprints.append(current_sprint)
            continue

        # Goals line
        if current_sprint and line.strip().startswith("GOALS:"):
            goals_text = line.strip()[6:].strip()
            current_sprint["goals"] = [g.strip() for g in goals_text.split(";") if g.strip()]
            continue

        # Habit line: [Category] Name | Xd/wk Ypts | W1:....... W2:....... | done=Nd NN%
        m = re.match(
            r"\s+\[(.+?)\]\s+(.+?)\s+\|\s+(\d+)d/wk\s+(\d+)pts\s+\|\s+(.*?)\s+\|\s+done=",
            line,
        )
        if m and current_sprint:
            category = m.group(1)
            name = m.group(2)
            target = int(m.group(3))
            weight = int(m.group(4))
            weeks_str = m.group(5)

            # Parse week patterns like "W1:X.XX..X W2:..X...."
            entries = []
            for wm in re.finditer(r"W(\d+):([X.]+)", weeks_str):
                week_num = int(wm.group(1))
                pattern = wm.group(2)
                # Week 1 starts at sprint start_date, week 2 at +7 days
                week_start = date.fromisoformat(current_sprint["start_date"]) + timedelta(
                    days=(week_num - 1) * 7
                )
                for i, ch in enumerate(pattern):
                    if ch == "X":
                        entry_date = week_start + timedelta(days=i)
                        entries.append(entry_date.isoformat())

            current_sprint["habits"].append({
                "category": category,
                "name": name,
                "target_per_week": target,
                "weight": weight,
                "entries": entries,
            })

    return sprints


def generate_sprint_id(start_date: str, existing_ids: set[str]) -> str:
    """Generate sprint ID in YYYY-S## format."""
    year = start_date[:4]
    n = 1
    while True:
        sid = f"{year}-S{n:02d}"
        if sid not in existing_ids:
            return sid
        n += 1


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)
    if not IMPORT_FILE.exists():
        print(f"Import file not found: {IMPORT_FILE}")
        sys.exit(1)

    # Backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB_PATH.parent / f"habits_pre_reimport_{timestamp}.db"
    shutil.copy2(DB_PATH, backup)
    print(f"Backup: {backup}")

    # Parse import data
    sprints_data = parse_import_file(IMPORT_FILE)
    print(f"Parsed {len(sprints_data)} sprints from import file")

    conn = get_connection(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=OFF")

    # --- Delete all historical data (keep current sprint) ---
    # Get current sprint habit IDs and entry data to preserve
    current_habit_ids = set()
    rows = conn.execute(
        "SELECT DISTINCT habit_id FROM entries e "
        "JOIN sprints s ON e.date >= s.start_date AND e.date <= s.end_date "
        "WHERE s.id = ?",
        (CURRENT_SPRINT,),
    ).fetchall()
    current_habit_ids = {r[0] for r in rows}

    # Also keep habits that are non-archived and not historical
    rows = conn.execute(
        "SELECT id FROM habits WHERE archived = 0"
    ).fetchall()
    current_habit_ids.update(r[0] for r in rows)

    print(f"Preserving {len(current_habit_ids)} current habits: {current_habit_ids}")

    # Delete historical sprints
    conn.execute("DELETE FROM sprints WHERE id != ?", (CURRENT_SPRINT,))

    # Delete historical sprint_habit_goals
    conn.execute("DELETE FROM sprint_habit_goals WHERE sprint_id != ?", (CURRENT_SPRINT,))

    # Delete historical habits (keep current ones)
    if current_habit_ids:
        placeholders = ",".join("?" * len(current_habit_ids))
        conn.execute(
            f"DELETE FROM habits WHERE id NOT IN ({placeholders})",
            tuple(current_habit_ids),
        )
        # Delete ALL entries for non-current habits
        conn.execute(
            f"DELETE FROM entries WHERE habit_id NOT IN ({placeholders})",
            tuple(current_habit_ids),
        )
        # Delete old entries for current habits that predate the current sprint
        # (these are from the old bad import; reimport will recreate correct ones)
        current_sprint_start = conn.execute(
            "SELECT start_date FROM sprints WHERE id = ?", (CURRENT_SPRINT,)
        ).fetchone()
        if current_sprint_start:
            conn.execute(
                f"DELETE FROM entries WHERE habit_id IN ({placeholders}) AND date < ?",
                (*current_habit_ids, current_sprint_start[0]),
            )
    else:
        conn.execute("DELETE FROM habits")
        conn.execute("DELETE FROM entries")

    conn.commit()

    remaining_habits = conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0]
    remaining_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    remaining_sprints = conn.execute("SELECT COUNT(*) FROM sprints").fetchone()[0]
    print(f"After cleanup: {remaining_sprints} sprints, {remaining_habits} habits, {remaining_entries} entries")

    # --- Build canonical habit map (dedup by name) ---
    # Collect all unique habit names across all sprints
    habit_info: dict[str, dict] = {}  # name -> {id, category, ...}
    for sprint in sprints_data:
        for h in sprint["habits"]:
            name = h["name"]
            if name not in habit_info:
                habit_info[name] = {
                    "id": slugify(name),
                    "name": name,
                    "category": h["category"],
                    # Use the most common target/weight as default
                    "target_per_week": h["target_per_week"],
                    "weight": h["weight"],
                }

    # Check for slug collisions
    slug_counts: dict[str, list[str]] = defaultdict(list)
    for name, info in habit_info.items():
        slug_counts[info["id"]].append(name)
    for slug, names in slug_counts.items():
        if len(names) > 1:
            # Add suffix to disambiguate
            for i, name in enumerate(names[1:], 2):
                habit_info[name]["id"] = f"{slug}-{i}"

    print(f"\nCanonical habits ({len(habit_info)}):")
    for name, info in sorted(habit_info.items()):
        print(f"  {info['id']:40s} {name} [{info['category']}]")

    # --- Check for conflicts with existing habits ---
    existing = {r[0] for r in conn.execute("SELECT id FROM habits").fetchall()}
    for name, info in habit_info.items():
        if info["id"] in existing:
            print(f"  (skipping habit creation for '{info['id']}' — already exists)")

    # --- Create historical habits (archived, global) ---
    now = datetime.now().isoformat()
    habits_created = 0
    for name, info in habit_info.items():
        if info["id"] in existing:
            continue
        conn.execute(
            """INSERT INTO habits (id, name, category, target_per_week, weight, unit, sprint_id, archived, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'count', NULL, 1, ?, ?)""",
            (info["id"], info["name"], info["category"],
             info["target_per_week"], info["weight"], now, now),
        )
        habits_created += 1

    print(f"\nCreated {habits_created} historical habits (archived)")

    # --- Create sprints, sprint_habit_goals, and entries ---
    used_sprint_ids = {r[0] for r in conn.execute("SELECT id FROM sprints").fetchall()}
    sprints_created = 0
    goals_created = 0
    entries_created = 0

    # Sort sprints by start_date so IDs are sequential within each year
    sprints_data.sort(key=lambda s: s["start_date"])

    for sprint in sprints_data:
        sprint_id = generate_sprint_id(sprint["start_date"], used_sprint_ids)
        used_sprint_ids.add(sprint_id)

        # Create sprint
        focus_goals = sprint["goals"] if sprint["goals"] else None
        import json
        conn.execute(
            """INSERT INTO sprints (id, start_date, end_date, status, theme, focus_goals, created_at, updated_at)
               VALUES (?, ?, ?, 'archived', NULL, ?, ?, ?)""",
            (sprint_id, sprint["start_date"], sprint["end_date"],
             json.dumps(focus_goals) if focus_goals else None, now, now),
        )
        sprints_created += 1

        # Create sprint_habit_goals and entries for each habit in this sprint
        for h in sprint["habits"]:
            habit_id = habit_info[h["name"]]["id"]

            # Sprint-specific goal
            conn.execute(
                """INSERT OR REPLACE INTO sprint_habit_goals (sprint_id, habit_id, target_per_week, weight)
                   VALUES (?, ?, ?, ?)""",
                (sprint_id, habit_id, h["target_per_week"], h["weight"]),
            )
            goals_created += 1

            # Entries
            for entry_date in h["entries"]:
                conn.execute(
                    """INSERT OR IGNORE INTO entries (habit_id, date, value, note, created_at, updated_at)
                       VALUES (?, ?, 1, NULL, ?, ?)""",
                    (habit_id, entry_date, now, now),
                )
                entries_created += 1

    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()

    # --- Final summary ---
    total_habits = conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0]
    total_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    total_sprints = conn.execute("SELECT COUNT(*) FROM sprints").fetchone()[0]
    total_goals = conn.execute("SELECT COUNT(*) FROM sprint_habit_goals").fetchone()[0]

    print(f"\n=== Reimport Summary ===")
    print(f"Sprints created:        {sprints_created}")
    print(f"Habits created:         {habits_created}")
    print(f"Sprint goals created:   {goals_created}")
    print(f"Entries created:        {entries_created}")
    print(f"")
    print(f"Total sprints:          {total_sprints}")
    print(f"Total habits:           {total_habits}")
    print(f"Total entries:          {total_entries}")
    print(f"Total sprint goals:     {total_goals}")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
