"""Habit Sprint CLI adapter."""

import argparse
import json
import os
import sys

DEFAULT_DB_DIR = os.path.join(os.path.expanduser("~"), ".habit-sprint")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, "habits.db")


def main() -> int:
    """Entry point for the habit-sprint CLI."""
    parser = argparse.ArgumentParser(
        description="habit-sprint: JSON-native habit tracking engine",
    )
    parser.add_argument(
        "--json",
        dest="json_str",
        help="JSON action string to execute",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["json", "markdown"],
        default="json",
        help="Output format (default: json)",
    )
    args = parser.parse_args()

    # Determine JSON input source (--json flag takes priority over stdin)
    raw_json: str | None = None

    if args.json_str is not None:
        raw_json = args.json_str
    elif not sys.stdin.isatty():
        raw_json = sys.stdin.read()

    if raw_json is None:
        print("Error: provide JSON via stdin pipe or --json flag", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return 1

    # Parse JSON input
    try:
        action_json = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        envelope = {"status": "error", "data": None, "error": f"Invalid JSON: {exc}"}
        print(json.dumps(envelope, indent=2))
        return 1

    # Ensure database directory exists
    db_dir = os.path.dirname(args.db)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # Execute action
    from habit_sprint.executor import execute

    result = execute(action_json, args.db)

    if (
        args.output_format == "markdown"
        and result["status"] == "success"
        and result["data"] is not None
    ):
        from habit_sprint.formatters import FORMATTERS

        action_name = action_json.get("action", "")
        formatter = FORMATTERS.get(action_name)
        if formatter is not None:
            print(formatter(result["data"]))
            return 0

    print(json.dumps(result, indent=2))

    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
