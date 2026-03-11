#!/usr/bin/env python3
"""Data migration: consolidate duplicate historical habit records.

Groups habits by name, picks a canonical ID for each group, preserves
per-sprint goals in sprint_habit_goals, reassigns entries, and removes
duplicate habit rows.

Idempotent — safe to run multiple times.
"""

import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Allow running from repo root or scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from habit_sprint.db import get_connection

DEFAULT_DB_DIR = Path.home() / ".habit-sprint"
DB_PATH = DEFAULT_DB_DIR / "habits.db"


def backup_database(db_path: Path) -> Path:
    """Create a timestamped backup of the database."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"habit_sprint_backup_{timestamp}.db"
    shutil.copy2(db_path, backup_path)
    print(f"Backup created: {backup_path}")
    return backup_path


def choose_canonical_id(habit_ids: list[str]) -> str:
    """Pick the canonical ID: prefer non-hist IDs, then shortest."""
    non_hist = [h for h in habit_ids if "-hist-" not in h]
    candidates = non_hist if non_hist else habit_ids
    return min(candidates, key=len)


def consolidate(conn: sqlite3.Connection) -> dict:
    """Run the consolidation migration. Returns a summary dict."""
    # Disable FK checks during migration (we'll re-enable after)
    conn.execute("PRAGMA foreign_keys=OFF")

    # --- Snapshot entry count for verification ---
    entry_count_before = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    # --- Load all habits ---
    habits = conn.execute(
        "SELECT id, name, category, target_per_week, weight, unit, sprint_id, archived "
        "FROM habits"
    ).fetchall()

    # --- Group habits by name ---
    groups: dict[str, list[dict]] = defaultdict(list)
    for h in habits:
        groups[h["name"]].append(dict(h))

    goals_inserted = 0
    entries_reassigned = 0
    habits_deleted = 0
    groups_consolidated = 0

    for name, group in groups.items():
        if len(group) == 1:
            # Single habit — still ensure it's global and has goals if sprint-scoped
            habit = group[0]
            if habit["sprint_id"] is not None:
                # Preserve goal before making global
                conn.execute(
                    """INSERT OR IGNORE INTO sprint_habit_goals
                       (sprint_id, habit_id, target_per_week, weight)
                       VALUES (?, ?, ?, ?)""",
                    (habit["sprint_id"], habit["id"],
                     habit["target_per_week"], habit["weight"]),
                )
                goals_inserted += 1
                conn.execute(
                    "UPDATE habits SET sprint_id = NULL WHERE id = ?",
                    (habit["id"],),
                )
            continue

        groups_consolidated += 1
        ids = [h["id"] for h in group]
        canonical_id = choose_canonical_id(ids)
        duplicates = [h for h in group if h["id"] != canonical_id]

        # --- Insert sprint_habit_goals for ALL habits in the group (including canonical) ---
        for h in group:
            if h["sprint_id"] is not None:
                conn.execute(
                    """INSERT OR IGNORE INTO sprint_habit_goals
                       (sprint_id, habit_id, target_per_week, weight)
                       VALUES (?, ?, ?, ?)""",
                    (h["sprint_id"], canonical_id,
                     h["target_per_week"], h["weight"]),
                )
                goals_inserted += 1

        # --- Reassign entries from duplicates to canonical ---
        for dup in duplicates:
            dup_id = dup["id"]

            # Handle potential PK conflicts: if canonical already has an entry
            # for the same date, keep the canonical's entry and delete the dup's
            cursor = conn.execute(
                """UPDATE entries SET habit_id = ?
                   WHERE habit_id = ?
                   AND date NOT IN (
                       SELECT date FROM entries WHERE habit_id = ?
                   )""",
                (canonical_id, dup_id, canonical_id),
            )
            entries_reassigned += cursor.rowcount

            # Delete any remaining duplicate entries (conflicting dates)
            conn.execute("DELETE FROM entries WHERE habit_id = ?", (dup_id,))

            # Delete any sprint_habit_goals referencing the duplicate habit_id
            conn.execute(
                "DELETE FROM sprint_habit_goals WHERE habit_id = ?", (dup_id,)
            )

            # Delete the duplicate habit
            conn.execute("DELETE FROM habits WHERE id = ?", (dup_id,))
            habits_deleted += 1

        # --- Make canonical habit global ---
        conn.execute(
            "UPDATE habits SET sprint_id = NULL WHERE id = ?",
            (canonical_id,),
        )

    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()

    # --- Verify entry counts ---
    entry_count_after = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    habit_count_after = conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0]
    goal_count = conn.execute("SELECT COUNT(*) FROM sprint_habit_goals").fetchone()[0]

    summary = {
        "groups_consolidated": groups_consolidated,
        "habits_deleted": habits_deleted,
        "entries_reassigned": entries_reassigned,
        "goals_inserted": goals_inserted,
        "entry_count_before": entry_count_before,
        "entry_count_after": entry_count_after,
        "entries_match": entry_count_before == entry_count_after,
        "habits_remaining": habit_count_after,
        "sprint_habit_goals_total": goal_count,
    }
    return summary


def main() -> None:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    # Step 1: Backup
    backup_database(DB_PATH)

    # Step 2: Connect (applies pending schema migrations)
    conn = get_connection(str(DB_PATH))

    # Step 3: Run consolidation
    summary = consolidate(conn)
    conn.close()

    # Step 4: Print summary
    print("\n=== Consolidation Summary ===")
    print(f"Habit groups consolidated: {summary['groups_consolidated']}")
    print(f"Duplicate habits deleted:  {summary['habits_deleted']}")
    print(f"Entries reassigned:        {summary['entries_reassigned']}")
    print(f"Sprint goals preserved:    {summary['goals_inserted']}")
    print(f"Entry count before:        {summary['entry_count_before']}")
    print(f"Entry count after:         {summary['entry_count_after']}")
    print(f"Entry counts match:        {'YES' if summary['entries_match'] else 'NO — DATA LOSS!'}")
    print(f"Habits remaining:          {summary['habits_remaining']}")
    print(f"Sprint habit goals total:  {summary['sprint_habit_goals_total']}")

    if not summary["entries_match"]:
        print("\nWARNING: Entry counts do not match! Check for data issues.")
        sys.exit(1)

    if summary["groups_consolidated"] == 0:
        print("\nNo duplicates found — database is already consolidated.")
    else:
        print("\nMigration completed successfully.")


if __name__ == "__main__":
    main()
