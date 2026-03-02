# habit-sprint

A deterministic, JSON-native sprint-based habit tracking engine designed for LLM-first workflows and agent integration.

## Overview

Habit Sprint is a lightweight behavioral state engine for managing sprint-based habit tracking. It is not a traditional habit app — it is a structured state engine where the LLM is the UI.

- **LLM-first** — Natural language in, structured JSON operations out
- **JSON-contract driven** — All inputs and outputs conform to a strict envelope schema
- **SQLite-backed** — Zero-infra, portable, inspectable persistence
- **CLI-accessible** — Thin JSON-in/JSON-out adapter for scripting and debugging
- **22 actions** — Sprints, habits, entries, reporting, retrospectives

## Requirements

- Python 3.12+

## Installation

```bash
# Quick install
make install

# With dev dependencies (pytest)
make install-dev
```

Or manually:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## CLI Usage

All interaction goes through a JSON action contract via `--json` or stdin:

```bash
# List all sprints
habit-sprint --json '{"action": "list_sprints"}'

# Create a sprint
habit-sprint --json '{"action": "create_sprint", "payload": {"name": "March 2026", "start_date": "2026-03-01"}}'

# Create a habit
habit-sprint --json '{"action": "create_habit", "payload": {"sprint_id": "...", "name": "Gym", "category": "Workout", "weight": "high", "target_per_week": 4}}'

# Log a habit entry
habit-sprint --json '{"action": "log_date", "payload": {"habit_id": "...", "date": "2026-03-03", "value": 1}}'

# Sprint dashboard (markdown output)
habit-sprint --json '{"action": "sprint_dashboard"}' --format markdown

# Use a custom database
habit-sprint --db /path/to/my.db --json '{"action": "list_sprints"}'

# Pipe JSON via stdin
echo '{"action": "list_sprints"}' | habit-sprint
```

All responses use a standard envelope:

```json
{"status": "success", "data": {...}, "error": null}
```

## Actions

| Category | Actions |
|----------|---------|
| **Sprints** | `create_sprint`, `update_sprint`, `list_sprints`, `archive_sprint`, `get_active_sprint` |
| **Habits** | `create_habit`, `update_habit`, `archive_habit`, `list_habits` |
| **Entries** | `log_date`, `log_range`, `bulk_set`, `delete_entry` |
| **Retrospectives** | `add_retro`, `get_retro` |
| **Reporting** | `weekly_completion`, `daily_score`, `get_week_view`, `sprint_report`, `habit_report`, `category_report`, `sprint_dashboard` |

See [SKILLS.md](SKILLS.md) for full action schemas and payload documentation.

## Testing

```bash
make test
```

Runs 682 tests covering the engine, CLI, reporting, validation, and error handling.

## LLM Skill Installation

habit-sprint includes an [LLM skill reference](SKILLS.md) that can be installed into Claude Code or OpenClaw so agents can use the engine directly.

```bash
# Claude Code
make claude-skill-install     # Install skill
make claude-skill-check       # Check status
make claude-skill-uninstall   # Remove skill

# OpenClaw
make openclaw-skill-install   # Install skill
make openclaw-skill-check     # Check status
make openclaw-skill-uninstall # Remove skill

# Custom OpenClaw skills directory
make openclaw-skill-install OPENCLAW_SKILLS_DIR=/path/to/skills
```

## Project Structure

```
habit-sprint/
  habit_sprint/
    cli.py          # CLI adapter (JSON-in/JSON-out)
    db.py           # SQLite connection and migration runner
    engine.py       # Core business logic (sprints, habits, entries, retros)
    executor.py     # Action router and response envelope
    formatters.py   # Markdown output formatting
    reporting.py    # Queries (dashboards, reports, scores)
    validation.py   # Payload schema validation
  migrations/
    001_initial_schema.sql
  tests/            # 682 tests
  docs/
    prd.md          # Product requirements document
  SKILLS.md         # LLM skill reference (22 action schemas)
  Makefile          # Build, test, and skill install targets
  pyproject.toml
```

## Make Targets

Run `make help` to see all available targets:

| Target | Description |
|--------|-------------|
| `make install` | Create venv and install in editable mode |
| `make install-dev` | Install with dev dependencies (pytest) |
| `make test` | Run pytest |
| `make run` | Print CLI usage examples |
| `make clean` | Remove caches and build artifacts |
| `make clean-all` | Clean + remove virtual environment |
| `make help` | Show all available targets |

## About

Created by [Eric Blue](https://about.ericblue.com)

Repository: [github.com/ericblue/habit-sprint](https://github.com/ericblue/habit-sprint)

## License

MIT
