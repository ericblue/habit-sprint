# Habit Sprint Cookbook

A practical guide with commands and example prompts for using the habit-sprint engine.

## Table of Contents

- [Getting Started](#getting-started)
- [Database Initialization](#database-initialization)
- [Sprint Management](#sprint-management)
- [Habit Management](#habit-management)
- [Habit Logging](#habit-logging)
- [Reporting & Dashboards](#reporting--dashboards)
- [Retrospectives](#retrospectives)
- [Tips & Patterns](#tips--patterns)

---

## Getting Started

### Install

```bash
make install          # Create venv + install
make install-dev      # With pytest for running tests
```

### Install the LLM Skill

If you're using Claude Code or OpenClaw, install the skill so the agent can drive the engine with natural language:

```bash
make claude-skill-install     # Claude Code
make openclaw-skill-install   # OpenClaw
```

### Verify

```bash
habit-sprint --json '{"action": "list_sprints"}'
# → {"status": "success", "data": {"sprints": []}, "error": null}
```

---

## Database Initialization

The database is created automatically on first use at `~/.habit-sprint/habits.db`. No explicit init step is needed.

### Use a custom database path

```bash
habit-sprint --db /path/to/my.db --json '{"action": "list_sprints"}'
```

### Example LLM Prompts

> Initialize the habit tracker and show me the current state.

> List all sprints — I want to make sure the database is set up.

---

## Sprint Management

### Create a Sprint

```bash
habit-sprint --json '{
  "action": "create_sprint",
  "payload": {
    "start_date": "2026-03-02",
    "end_date": "2026-03-15",
    "theme": "Build Morning Routine",
    "focus_goals": ["Wake by 6am", "No phone first hour", "Exercise before work"]
  }
}'
```

Sprint IDs are auto-generated in `YYYY-S##` format (e.g. `2026-S01`).

### List Sprints

```bash
habit-sprint --json '{"action": "list_sprints"}'
habit-sprint --json '{"action": "list_sprints", "payload": {"status": "active"}}'
```

### Get the Active Sprint

```bash
habit-sprint --json '{"action": "get_active_sprint"}'
```

### Update a Sprint

```bash
habit-sprint --json '{
  "action": "update_sprint",
  "payload": {
    "id": "2026-S01",
    "theme": "Morning Routine + Deep Work",
    "focus_goals": ["Wake by 6am", "2 hours deep work daily"]
  }
}'
```

### Archive a Sprint

```bash
habit-sprint --json '{"action": "archive_sprint", "payload": {"id": "2026-S01"}}'
```

### Example LLM Prompts

> Create a new 2-week sprint starting today with the theme "Deep Focus" and goals of reading daily, meditating, and limiting social media.

> Start a sprint from March 2 to March 15 focused on building a morning routine.

> Show me all my sprints.

> What's the current active sprint?

> Archive sprint 2026-S01 — it's done.

> Update the current sprint's theme to "Consistency Over Intensity".

---

## Habit Management

### Create Habits

```bash
# Binary habit (did it or didn't)
habit-sprint --json '{
  "action": "create_habit",
  "payload": {
    "id": "meditation",
    "name": "Meditation",
    "category": "Mindfulness",
    "target_per_week": 5,
    "weight": 2
  }
}'

# Numeric habit (tracking minutes)
habit-sprint --json '{
  "action": "create_habit",
  "payload": {
    "id": "deep-work",
    "name": "Deep Work",
    "category": "Productivity",
    "target_per_week": 5,
    "weight": 3,
    "unit": "minutes"
  }
}'

# Sprint-scoped habit
habit-sprint --json '{
  "action": "create_habit",
  "payload": {
    "id": "cold-shower",
    "name": "Cold Shower",
    "category": "Health",
    "target_per_week": 7,
    "weight": 1,
    "sprint_id": "2026-S01"
  }
}'
```

**Key fields:**
- `id` — lowercase slug (`reading`, `daily-walk`, `deep-work`)
- `target_per_week` — 1 to 7 days
- `weight` — 1 (low), 2 (medium), 3 (high behavioral leverage)
- `unit` — `count` (default), `minutes`, `reps`, `pages`
- `sprint_id` — omit for global habits, set for sprint-scoped

### List Habits

```bash
habit-sprint --json '{"action": "list_habits"}'
habit-sprint --json '{"action": "list_habits", "payload": {"category": "Health"}}'
habit-sprint --json '{"action": "list_habits", "payload": {"include_archived": true}}'
```

### Update a Habit

```bash
habit-sprint --json '{
  "action": "update_habit",
  "payload": {"id": "meditation", "target_per_week": 7}
}'
```

### Archive a Habit

```bash
habit-sprint --json '{"action": "archive_habit", "payload": {"id": "cold-shower"}}'
```

### Example LLM Prompts

> Create these habits for my sprint:
> - Reading (30 min/day, 5x/week, high priority, Learning category)
> - Exercise (4x/week, high priority, Health category)
> - Journaling (daily, medium priority, Mindfulness category)
> - No junk food (daily, low priority, Health category)

> Add a habit called "deep-work" — track it in minutes, 5 days a week, high weight, Productivity category.

> Show me all my habits grouped by category.

> I want to stop tracking cold showers — archive that habit.

> Bump my meditation target to 7 days a week.

> List only Health category habits.

---

## Habit Logging

### Log a Single Day

```bash
habit-sprint --json '{
  "action": "log_date",
  "payload": {"habit_id": "meditation", "date": "2026-03-03", "value": 1}
}'

# With a note
habit-sprint --json '{
  "action": "log_date",
  "payload": {"habit_id": "deep-work", "date": "2026-03-03", "value": 90, "note": "Focused session on API design"}
}'
```

### Log a Date Range

```bash
habit-sprint --json '{
  "action": "log_range",
  "payload": {"habit_id": "meditation", "start_date": "2026-03-02", "end_date": "2026-03-06"}
}'
```

### Log Specific (Non-Contiguous) Dates

```bash
habit-sprint --json '{
  "action": "bulk_set",
  "payload": {"habit_id": "exercise", "dates": ["2026-03-02", "2026-03-04", "2026-03-06"]}
}'
```

### Delete an Entry

```bash
habit-sprint --json '{
  "action": "delete_entry",
  "payload": {"habit_id": "meditation", "date": "2026-03-03"}
}'
```

### Example LLM Prompts

> I meditated today.

> Log 90 minutes of deep work for today with the note "finished API refactor".

> I exercised Monday, Wednesday, and Friday this week.

> I read every day this week — log reading for March 2 through March 8.

> Actually I didn't meditate on Thursday — delete that entry for March 5.

> Log that I did journaling on March 3, 5, and 7.

> I did 50 pushups today — log it under exercise.

---

## Reporting & Dashboards

### Sprint Dashboard (the big one)

```bash
# Full dashboard
habit-sprint --json '{"action": "sprint_dashboard"}' --format markdown

# Week 1 only
habit-sprint --json '{"action": "sprint_dashboard", "payload": {"week": 1}}' --format markdown
```

### Weekly View (habit × day grid)

```bash
habit-sprint --json '{"action": "get_week_view"}' --format markdown

# Specific week
habit-sprint --json '{"action": "get_week_view", "payload": {"week_start": "2026-03-02"}}' --format markdown
```

### Sprint Report (analytics)

```bash
habit-sprint --json '{"action": "sprint_report"}' --format markdown
```

### Individual Habit Report

```bash
habit-sprint --json '{"action": "habit_report", "payload": {"habit_id": "meditation"}}' --format markdown

# Different time periods
habit-sprint --json '{"action": "habit_report", "payload": {"habit_id": "meditation", "period": "last_4_weeks"}}' --format markdown
```

### Daily Score

```bash
habit-sprint --json '{"action": "daily_score", "payload": {"date": "2026-03-03"}}' --format markdown
```

### Weekly Completion (single habit)

```bash
habit-sprint --json '{"action": "weekly_completion", "payload": {"habit_id": "meditation"}}' --format markdown
```

### Category Report

```bash
habit-sprint --json '{"action": "category_report"}' --format markdown

# Single category
habit-sprint --json '{"action": "category_report", "payload": {"category": "Health"}}' --format markdown
```

### Example LLM Prompts

> Show me the sprint dashboard.

> How did I do this week?

> Show me the dashboard for week 1 only.

> Give me the full sprint report with analytics.

> How's my meditation habit going? Show me the report.

> What's my daily score for today?

> How's my meditation streak looking?

> Show me a category breakdown — which areas am I strongest and weakest in?

> Compare my Health habits vs Productivity habits.

> How did I do on reading over the last 4 weeks?

---

## Retrospectives

### Add a Retrospective

```bash
habit-sprint --json '{
  "action": "add_retro",
  "payload": {
    "sprint_id": "2026-S01",
    "what_went_well": "Hit meditation target every week. Deep work sessions were productive.",
    "what_to_improve": "Exercise dropped off in week 2. Too many late nights.",
    "ideas": "Try morning exercise before it gets crowded. Set a hard 10pm cutoff."
  }
}'
```

### Get a Retrospective

```bash
habit-sprint --json '{"action": "get_retro", "payload": {"sprint_id": "2026-S01"}}'
```

### Example LLM Prompts

> Let's do a retro for the current sprint. What went well: I stuck to meditation and reading every day. What to improve: exercise fell off in week 2, and I kept staying up too late. Ideas: try working out in the morning and setting a hard 10pm screen cutoff.

> Show me the retrospective for sprint 2026-S01.

> Update the retro — add "try time-blocking" to the ideas.

---

## Tips & Patterns

### Full Setup in One Conversation

Here's an example of a natural conversation to set up everything from scratch:

> 1. "Create a 2-week sprint starting today called 'Foundation Sprint' with goals: build morning routine, read daily, exercise 4x/week."
> 2. "Add these habits: meditation (daily, high weight, Mindfulness), reading (5x/week, high weight, Learning), exercise (4x/week, high weight, Health), journaling (daily, medium weight, Mindfulness), no-sugar (daily, low weight, Health)."
> 3. "I did meditation, reading, and journaling today. I also exercised for 45 minutes."
> 4. "Show me the dashboard."

### End-of-Day Logging

> "Today I meditated, read for 30 minutes, did 50 pushups, and journaled. I didn't exercise or avoid sugar."

### Weekly Check-In

> "Show me the week view and tell me how I'm doing against my targets."

### Sprint Wrap-Up

> "The sprint is ending. Show me the sprint report. Then let's do a retro — here's what went well: ..., what to improve: ..., ideas: ..."

> "Archive the current sprint and create a new one starting Monday."

### Using a Custom Database

Useful for separate tracking contexts (e.g., work vs personal):

```bash
habit-sprint --db ~/work-habits.db --json '{"action": "list_sprints"}'
habit-sprint --db ~/personal-habits.db --json '{"action": "list_sprints"}'
```

### Output Formats

- `--format json` (default) — raw JSON for programmatic use
- `--format markdown` — rendered ASCII tables and formatted output for reading

### Piping from Stdin

```bash
echo '{"action": "sprint_dashboard"}' | habit-sprint --format markdown
cat request.json | habit-sprint
```
