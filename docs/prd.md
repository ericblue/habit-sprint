# Habit Sprint — Product Requirements Document (PRD)

**Version:** 2.0
**Last Updated:** 2026-03-01
**Status:** Draft — Ready for Build

---

## 1. Project Overview

**Project Name:** habit-sprint
**Tagline:** A deterministic, JSON-native sprint and habit tracking engine designed for LLM-first workflows and agent integration.

Habit Sprint is a lightweight, deterministic state engine for managing sprint-based habit tracking. It is not a traditional habit app — it is a structured behavioral state engine. The primary mode of interaction is the LLM; the engine itself only speaks JSON.

It is designed to be:

- **LLM-first** — The model is the UI. Natural language in, structured JSON operations out.
- **JSON-contract driven** — All inputs and outputs conform to a strict envelope schema.
- **SQLite-backed** — Zero-infra, portable, inspectable persistence.
- **CLI-accessible** — Thin JSON-in/JSON-out adapter for scripting and debugging.
- **CmdShell and OpenClaw compatible** — Widget rendering and skill integration.
- **UI-optional** — No web UI, no TUI. CmdShell widgets are the visual layer.

---

## 2. Origin & Philosophy

### 2.1 Historical Context

This project evolves from a spreadsheet-based habit tracker used from 2012–2022. That system introduced several concepts that remain central:

- **Personal Development Sprints** — Two-week cycles modeled after software sprints, with planning at the start and retrospectives at the end.
- **Minimum commitment per week** — Not daily absolutism. The insight: "Don't Break The Streak is good, but not everything needs daily execution."
- **Point/weight system** — Low/medium/high effort indicators representing behavioral leverage, not just effort.
- **Daily score row** — A running total per day providing immediate feedback and momentum visibility.
- **Categories** — Habits grouped by domain (Workout, Diet, Learning, Projects) enabling balance analysis.
- **Reflection as first-class** — The most important part: "block off time for self-reflection and evaluation on a consistent basis."

The spreadsheet was visual, finite, simple, explicit, sprint-based, reflective, weighted, and category-aware. It was not gamified, infinite-scrolling, dopamine-driven, or over-automated.

### 2.2 Design Principles

1. **LLM-First Interface** — The primary mode of interaction is structured JSON via LLM tools/skills. The LLM translates natural language to JSON operations; the engine executes deterministically.
2. **Deterministic Execution** — All business logic lives in the engine, not the LLM. The LLM must never compute streaks, aggregates, or trends — it only interprets results.
3. **Sprint-Oriented Design** — Habits are grouped into 2-week (default) sprints. The sprint is the atomic unit of commitment and reflection.
4. **No Gamification** — No badges, fireworks, streak celebrations, or dopamine mechanics. Clean signal only.
5. **Reflection-Centric** — Retrospectives are first-class citizens. This is a self-awareness engine, not just a tracker.
6. **Strict JSON Contract** — All inputs/outputs conform to a defined schema. No freeform commands, no CLI parsing in the engine, no human input mode.
7. **Numeric-First Values** — All habit entries are numeric. Binary habits use `value=1`. This enables future flexibility for minutes, reps, pages, etc.
8. **Idempotent Operations** — Logging the same habit+date twice overwrites (not appends). Habit state is deterministic.
9. **Stateless Except for DB** — No in-memory habit cache, no runtime state machine. Parse action → execute SQL → return result.
10. **Single Action Contract** — Everything (LLM, CLI, CmdShell widgets) goes through the same JSON contract and engine. This prevents divergence and bugs.

---

## 3. Goals

### 3.1 Primary Goals

- Enable CRUD operations for habits via JSON.
- Support sprint cycles (default 14 days) with theme and focus goals.
- Track weighted habits with weekly minimum targets.
- Provide deterministic scoring and reporting (weekly completion, weighted sprint score, streaks, category rollups, trend deltas).
- Integrate cleanly with OpenClaw as a skill.
- Provide optional CLI interface (JSON in/out, optional markdown formatting).
- Support CmdShell widget data rendering (weekly grid, sprint summary, daily score chart).
- Store and retrieve structured sprint retrospectives.

### 3.2 Non-Goals (v1)

- No web UI
- No mobile app
- No TUI
- No notifications or push reminders
- No social features
- No SaaS deployment
- No real-time syncing system
- No in-memory caching layer

---

## 4. System Architecture

### 4.1 High-Level Architecture

There are three architectural layers with strict separation of concerns:

```
Layer 1: SQLite Core Engine    — Deterministic state (all validation, CRUD, aggregation, integrity)
Layer 2: LLM Skill Layer       — Natural language → JSON operations (via SKILLS.md constraints)
Layer 3: CmdShell Widget Layer — Visualization + light interaction (renders state, emits JSON actions)
```

All three layers communicate through the same JSON contract.

### 4.2 Data Flow Paths

**LLM Path:**
```
User (natural language)
  → LLM interprets intent
  → LLM emits JSON action (per SKILLS.md contract)
  → executor.execute(action_json)
  → Engine executes against SQLite
  → JSON response returned
  → LLM summarizes result for user
```

Example:
```
User: "Mark reading complete for the last 3 days."

LLM emits:
{
  "action": "log_range",
  "payload": {
    "habit_id": "reading",
    "start": "2026-02-26",
    "end": "2026-02-28",
    "value": 1
  }
}

Engine returns:
{
  "status": "success",
  "data": {
    "entries_created": 3,
    "habit_id": "reading",
    "dates": ["2026-02-26", "2026-02-27", "2026-02-28"]
  }
}

LLM: "Done — reading marked complete for Feb 26–28."
```

**CmdShell Widget Path:**
```
CmdShell requests data via OpenClaw
  → OpenClaw invokes habit-sprint skill
  → executor.execute({ "action": "get_week_view", ... })
  → JSON response returned
  → CmdShell renders widget (grid, chart, etc.)
  → User clicks checkbox in widget
  → Widget emits JSON action: { "action": "log_date", ... }
  → Same engine processes
  → Widget refreshes
```

**CLI Path:**
```
echo '{"action":"list_habits","payload":{}}' | habit-sprint
  → cli.py reads JSON from stdin
  → Calls executor.execute()
  → Prints JSON output to stdout
```

### 4.3 Component Structure

```
habit-sprint/
  schema.sql         # SQLite DDL
  engine.py          # Domain & mutation layer
  reporting.py       # Analytics layer (read-only)
  executor.py        # JSON contract boundary
  cli.py             # Thin CLI adapter
  SKILLS.md          # LLM skill definition
  README.md          # Project documentation
  tests/             # Test suite
```

### 4.4 Component Responsibilities

#### engine.py — Domain & Mutation Layer

Handles all state mutation:
- CRUD for habits (create, update, archive, list)
- CRUD for sprints (create, list, archive, get active)
- Entry logging (single date, date range, bulk set, delete)
- Retrospective storage (add, retrieve)
- Data validation (required fields, ISO dates, habit existence, sprint overlap prevention)
- Idempotent upsert operations
- Transaction handling

**Critical constraint:** No JSON awareness. Engine functions accept and return Python objects. The executor handles JSON serialization.

#### reporting.py — Analytics Layer

All read-only computation:
- Weekly completion metrics (actual / target per week)
- Weighted sprint scoring (Σ(actual × weight) / Σ(target × weight))
- Category rollups and balance analysis
- Streak calculation (current streak, longest streak)
- Trend comparisons (this week vs. last week delta)
- Daily scoring (total points / max possible per day)
- Full sprint reports with per-habit breakdowns
- Week view data for CmdShell grid rendering

**Critical constraint:** Read-only. No mutations. All metrics computed here, never by the LLM.

#### executor.py — JSON Contract Boundary

The single public entry point for all consumers:

```python
def execute(action_json: dict) -> dict
```

Responsibilities:
- Accepts `{ "action": "string", "payload": { } }`
- Validates action name against allowed actions list
- Validates payload fields against action schema (rejects unknown fields)
- Routes to engine.py (mutations) or reporting.py (queries)
- Wraps all responses in the standard envelope:
  ```json
  { "status": "success", "data": { }, "error": null }
  ```
  or:
  ```json
  { "status": "error", "data": null, "error": "Human-readable message" }
  ```
- Never mixes success and error fields

#### cli.py — Thin CLI Adapter

- Reads JSON from stdin or `--json` flag
- Calls `executor.execute()`
- Prints JSON output to stdout
- Optional: `--format markdown` derives markdown from structured JSON output
- **No business logic.** Pure I/O adapter.

---

## 5. Data Model

### 5.1 SQLite Schema

```sql
-- Sprints table
CREATE TABLE sprints (
    id TEXT PRIMARY KEY,                    -- slug, e.g. "2026-S01"
    start_date TEXT NOT NULL,               -- ISO 8601, e.g. "2026-01-01"
    end_date TEXT NOT NULL,                 -- ISO 8601, e.g. "2026-01-14"
    theme TEXT,                             -- optional, e.g. "Cut Phase", "Creative Phase"
    focus_goals TEXT DEFAULT '[]',          -- JSON array of strings
    status TEXT NOT NULL DEFAULT 'active',  -- "active" or "archived"
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Habits table
CREATE TABLE habits (
    id TEXT PRIMARY KEY,                    -- slug, e.g. "reading", "daily-walk"
    name TEXT NOT NULL,                     -- display name, e.g. "Reading"
    category TEXT NOT NULL,                 -- e.g. "health", "cognitive", "creative", "projects"
    target_per_week INTEGER NOT NULL,       -- minimum days per week commitment
    weight INTEGER NOT NULL DEFAULT 1,      -- behavioral leverage: 1=low, 2=medium, 3=high
    unit TEXT NOT NULL DEFAULT 'count',     -- "count", "minutes", "reps", "pages"
    sprint_id TEXT,                         -- nullable FK → sprints.id (habit can be global or sprint-scoped)
    archived INTEGER NOT NULL DEFAULT 0,    -- 0=active, 1=archived
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (sprint_id) REFERENCES sprints(id)
);

-- Entries table
CREATE TABLE entries (
    habit_id TEXT NOT NULL,
    date TEXT NOT NULL,                     -- ISO 8601, e.g. "2026-02-28"
    value REAL NOT NULL DEFAULT 1,          -- numeric-first: binary habits use 1, others use actual value
    note TEXT,                              -- optional context
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (habit_id, date),
    FOREIGN KEY (habit_id) REFERENCES habits(id)
);

-- Retrospectives table
CREATE TABLE retros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sprint_id TEXT NOT NULL UNIQUE,         -- one retro per sprint
    what_went_well TEXT,
    what_to_improve TEXT,
    ideas TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (sprint_id) REFERENCES sprints(id)
);

-- Indexes
CREATE INDEX idx_entries_date ON entries(date);
CREATE INDEX idx_entries_habit_date ON entries(habit_id, date);
CREATE INDEX idx_habits_sprint ON habits(sprint_id);
CREATE INDEX idx_habits_category ON habits(category);
CREATE INDEX idx_sprints_status ON sprints(status);
```

### 5.2 Data Model Notes

- **Habit IDs are stable slugs** — e.g. "reading", "daily-walk", "no-alcohol". This makes JSON operations human-readable and predictable.
- **Numeric-first values** — Binary completion uses `value=1`. Numeric habits (30 minutes of reading, 5 reps) store the actual value. This gives future flexibility without schema changes.
- **Idempotent entries** — `PRIMARY KEY (habit_id, date)` means logging the same date twice is an upsert, not a duplicate. Deterministic state.
- **Sprint-scoped habits** — Habits can optionally attach to a sprint via `sprint_id`. Global habits (no sprint) persist across sprints.
- **One retro per sprint** — The `UNIQUE` constraint on `sprint_id` in retros enforces one retrospective per sprint cycle.

---

## 6. JSON Contract

### 6.1 Request Envelope

All requests follow this structure:
```json
{
  "action": "action_name",
  "payload": { }
}
```

### 6.2 Response Envelope

All responses follow this structure:

**Success:**
```json
{
  "status": "success",
  "data": { },
  "error": null
}
```

**Error:**
```json
{
  "status": "error",
  "data": null,
  "error": "Human-readable error message"
}
```

Never mix success and error fields.

---

## 7. Supported Actions (v1) — Full Specifications

### 7.1 Sprint Management

#### `create_sprint`

Creates a new sprint. Only one sprint may be active at a time.

**Request:**
```json
{
  "action": "create_sprint",
  "payload": {
    "id": "2026-S05",
    "start_date": "2026-03-01",
    "end_date": "2026-03-14",
    "theme": "Foundation Building",
    "focus_goals": ["Establish morning routine", "Hit gym 4x/week"]
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "2026-S05",
    "start_date": "2026-03-01",
    "end_date": "2026-03-14",
    "theme": "Foundation Building",
    "focus_goals": ["Establish morning routine", "Hit gym 4x/week"],
    "status": "active"
  }
}
```

**Validation rules:**
- `id` is required, must be unique
- `start_date` and `end_date` are required, must be valid ISO dates
- `end_date` must be after `start_date`
- No overlapping active sprints allowed
- `theme` and `focus_goals` are optional

#### `list_sprints`

**Request:**
```json
{
  "action": "list_sprints",
  "payload": {
    "status": "active"
  }
}
```

**Payload fields:** `status` (optional, filter by "active" or "archived"; omit for all)

**Response:**
```json
{
  "status": "success",
  "data": {
    "sprints": [
      {
        "id": "2026-S05",
        "start_date": "2026-03-01",
        "end_date": "2026-03-14",
        "theme": "Foundation Building",
        "focus_goals": ["Establish morning routine", "Hit gym 4x/week"],
        "status": "active"
      }
    ]
  }
}
```

#### `archive_sprint`

**Request:**
```json
{
  "action": "archive_sprint",
  "payload": {
    "id": "2026-S04"
  }
}
```

**Validation:** Sprint must exist. Sets status to "archived".

#### `get_active_sprint`

**Request:**
```json
{
  "action": "get_active_sprint",
  "payload": {}
}
```

**Response:** Returns the currently active sprint, or error if none exists.

---

### 7.2 Habit Management

#### `create_habit`

**Request:**
```json
{
  "action": "create_habit",
  "payload": {
    "id": "reading",
    "name": "Reading",
    "category": "cognitive",
    "target_per_week": 5,
    "weight": 2,
    "unit": "count",
    "sprint_id": "2026-S05"
  }
}
```

**Validation rules:**
- `id` is required, must be a valid slug (lowercase, hyphens), must be unique
- `name` and `category` are required
- `target_per_week` is required, must be integer 1–7
- `weight` defaults to 1 if omitted, must be integer 1–3
- `unit` defaults to "count" if omitted, allowed values: "count", "minutes", "reps", "pages"
- `sprint_id` is optional (nullable)

#### `update_habit`

**Request:**
```json
{
  "action": "update_habit",
  "payload": {
    "id": "reading",
    "target_per_week": 6,
    "weight": 3
  }
}
```

**Validation:** Habit must exist and not be archived. Only provided fields are updated; omitted fields are unchanged.

#### `archive_habit`

**Request:**
```json
{
  "action": "archive_habit",
  "payload": {
    "id": "reading"
  }
}
```

**Behavior:** Sets `archived=1`. Archived habits cannot receive new entries.

#### `list_habits`

**Request:**
```json
{
  "action": "list_habits",
  "payload": {
    "sprint_id": "2026-S05",
    "include_archived": false
  }
}
```

**Payload fields:**
- `sprint_id` (optional, filter by sprint)
- `category` (optional, filter by category)
- `include_archived` (optional, boolean, default false)

**Response:**
```json
{
  "status": "success",
  "data": {
    "habits": [
      {
        "id": "reading",
        "name": "Reading",
        "category": "cognitive",
        "target_per_week": 5,
        "weight": 2,
        "unit": "count",
        "sprint_id": "2026-S05",
        "archived": false
      },
      {
        "id": "daily-walk",
        "name": "Daily Walk",
        "category": "health",
        "target_per_week": 4,
        "weight": 1,
        "unit": "minutes",
        "sprint_id": "2026-S05",
        "archived": false
      }
    ]
  }
}
```

---

### 7.3 Entry Management

#### `log_date`

Log a single habit entry for a specific date. Idempotent — overwrites if entry exists.

**Request:**
```json
{
  "action": "log_date",
  "payload": {
    "habit_id": "reading",
    "date": "2026-02-28",
    "value": 1,
    "note": "Finished chapter 12"
  }
}
```

**Validation rules:**
- `habit_id` must exist and not be archived
- `date` must be valid ISO format
- `value` is required, must be numeric (≥ 0)
- `note` is optional

**Response:**
```json
{
  "status": "success",
  "data": {
    "habit_id": "reading",
    "date": "2026-02-28",
    "value": 1,
    "note": "Finished chapter 12",
    "created": false
  }
}
```
(`created: true` for new entries, `false` for upserts)

#### `log_range`

Log a habit across a date range with the same value.

**Request:**
```json
{
  "action": "log_range",
  "payload": {
    "habit_id": "reading",
    "start": "2026-02-26",
    "end": "2026-02-28",
    "value": 1
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "habit_id": "reading",
    "entries_created": 3,
    "dates": ["2026-02-26", "2026-02-27", "2026-02-28"]
  }
}
```

#### `bulk_set`

Set values for a habit on specific (non-contiguous) dates.

**Request:**
```json
{
  "action": "bulk_set",
  "payload": {
    "habit_id": "reading",
    "dates": ["2026-02-24", "2026-02-25", "2026-02-27"],
    "value": 1
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "habit_id": "reading",
    "entries_created": 3,
    "dates": ["2026-02-24", "2026-02-25", "2026-02-27"]
  }
}
```

This is the action CmdShell emits when a user drag-selects multiple days in the weekly grid widget.

#### `delete_entry`

Remove a logged entry.

**Request:**
```json
{
  "action": "delete_entry",
  "payload": {
    "habit_id": "reading",
    "date": "2026-02-27"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "habit_id": "reading",
    "date": "2026-02-27",
    "deleted": true
  }
}
```

---

### 7.4 Reporting

#### `get_week_view`

Returns the weekly grid data used by CmdShell to render the habit tracker grid.

**Request:**
```json
{
  "action": "get_week_view",
  "payload": {
    "week_start": "2026-02-24"
  }
}
```

**Payload fields:**
- `week_start` (optional; defaults to current week's Monday)

**Response:**
```json
{
  "status": "success",
  "data": {
    "week_start": "2026-02-24",
    "week_end": "2026-03-02",
    "habits": [
      {
        "habit_id": "reading",
        "name": "Reading",
        "category": "cognitive",
        "target_per_week": 5,
        "weight": 2,
        "daily": {
          "2026-02-24": 1,
          "2026-02-25": 1,
          "2026-02-26": 0,
          "2026-02-27": 1,
          "2026-02-28": 0,
          "2026-03-01": 0,
          "2026-03-02": 0
        },
        "week_actual": 3,
        "week_completion_pct": 60,
        "commitment_met": false
      },
      {
        "habit_id": "daily-walk",
        "name": "Daily Walk",
        "category": "health",
        "target_per_week": 4,
        "weight": 1,
        "daily": {
          "2026-02-24": 1,
          "2026-02-25": 1,
          "2026-02-26": 1,
          "2026-02-27": 1,
          "2026-02-28": 0,
          "2026-03-01": 0,
          "2026-03-02": 0
        },
        "week_actual": 4,
        "week_completion_pct": 100,
        "commitment_met": true
      }
    ]
  }
}
```

When rendered in CmdShell, this produces a grid like:

```
Habit        Mon  Tue  Wed  Thu  Fri  Sat  Sun  | Done  Target
Reading       ✓    ✓         ✓                  |  3/5    60%
Daily Walk    ✓    ✓    ✓    ✓                  |  4/4   100%
```

#### `daily_score`

Returns the aggregate score for a single day.

**Request:**
```json
{
  "action": "daily_score",
  "payload": {
    "date": "2026-02-28"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "date": "2026-02-28",
    "total_points": 8,
    "max_possible": 14,
    "completion_pct": 57,
    "habits_completed": [
      { "habit_id": "reading", "value": 1, "weight": 2 },
      { "habit_id": "gym", "value": 1, "weight": 3 }
    ],
    "habits_missed": [
      { "habit_id": "daily-walk", "weight": 1 },
      { "habit_id": "meditation", "weight": 2 }
    ]
  }
}
```

Daily score formula: `Σ(value × weight)` for all habits with entries that day, divided by `Σ(weight)` for all active habits.

#### `sprint_report`

Full sprint analytics with weighted scoring.

**Request:**
```json
{
  "action": "sprint_report",
  "payload": {
    "sprint_id": "2026-S05"
  }
}
```

**Payload fields:**
- `sprint_id` (optional; defaults to active sprint)

**Response:**
```json
{
  "status": "success",
  "data": {
    "sprint_id": "2026-S05",
    "start_date": "2026-03-01",
    "end_date": "2026-03-14",
    "theme": "Foundation Building",
    "days_elapsed": 10,
    "days_remaining": 4,
    "weighted_score": 0.72,
    "unweighted_score": 0.68,
    "category_breakdown": {
      "health": { "weighted_score": 0.85, "habits_count": 3 },
      "cognitive": { "weighted_score": 0.60, "habits_count": 2 },
      "projects": { "weighted_score": 0.50, "habits_count": 1 }
    },
    "habits": [
      {
        "habit_id": "reading",
        "name": "Reading",
        "category": "cognitive",
        "target_per_week": 5,
        "weight": 2,
        "total_entries": 8,
        "expected_entries": 10,
        "completion_pct": 80,
        "current_streak": 3,
        "longest_streak": 6,
        "weekly_breakdown": [
          { "week": 1, "actual": 4, "target": 5, "completion_pct": 80 },
          { "week": 2, "actual": 4, "target": 5, "completion_pct": 80 }
        ],
        "trend_vs_last_sprint": "+15%"
      }
    ],
    "retro": null
  }
}
```

**Weighted Sprint Score formula:**
```
Σ(actual_entries × weight) / Σ(target_entries × weight)
```
Where `target_entries` = `target_per_week × number_of_weeks_in_sprint`.

#### `habit_report`

Detailed report for a single habit.

**Request:**
```json
{
  "action": "habit_report",
  "payload": {
    "habit_id": "reading",
    "period": "last_4_weeks"
  }
}
```

**Payload fields:**
- `habit_id` (required)
- `period` (optional; "current_sprint", "last_4_weeks", "last_8_weeks", or specific sprint_id; defaults to current sprint)

**Response:**
```json
{
  "status": "success",
  "data": {
    "habit_id": "reading",
    "name": "Reading",
    "category": "cognitive",
    "target_per_week": 5,
    "weight": 2,
    "period": "last_4_weeks",
    "total_entries": 16,
    "total_possible": 20,
    "overall_completion_pct": 80,
    "current_streak": 3,
    "longest_streak": 14,
    "weekly_history": [
      { "week_start": "2026-02-03", "actual": 5, "target": 5, "completion_pct": 100 },
      { "week_start": "2026-02-10", "actual": 4, "target": 5, "completion_pct": 80 },
      { "week_start": "2026-02-17", "actual": 3, "target": 5, "completion_pct": 60 },
      { "week_start": "2026-02-24", "actual": 4, "target": 5, "completion_pct": 80 }
    ],
    "trend_vs_prior_period": "-5%",
    "rolling_7_day_avg": 0.71
  }
}
```

#### `category_report`

Aggregated report across all habits in a category. Useful for balance analysis ("Am I overfocusing on health and neglecting projects?").

**Request:**
```json
{
  "action": "category_report",
  "payload": {
    "sprint_id": "2026-S05"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "sprint_id": "2026-S05",
    "categories": [
      {
        "category": "health",
        "habits_count": 3,
        "weighted_score": 0.85,
        "unweighted_score": 0.80,
        "habits": ["daily-walk", "gym", "no-alcohol"]
      },
      {
        "category": "cognitive",
        "habits_count": 2,
        "weighted_score": 0.60,
        "unweighted_score": 0.55,
        "habits": ["reading", "journaling"]
      },
      {
        "category": "projects",
        "habits_count": 1,
        "weighted_score": 0.50,
        "unweighted_score": 0.50,
        "habits": ["open-source"]
      }
    ],
    "balance_assessment": {
      "most_adherent": "health",
      "least_adherent": "projects",
      "spread": 0.35
    }
  }
}
```

---

### 7.5 Retrospective

#### `add_retro`

Store a sprint retrospective. One per sprint.

**Request:**
```json
{
  "action": "add_retro",
  "payload": {
    "sprint_id": "2026-S04",
    "what_went_well": "Consistent gym attendance. Reading streak held for 10 days.",
    "what_to_improve": "Journaling dropped off in week 2. Need to lower target or change timing.",
    "ideas": "Try morning journaling instead of evening. Add a creative category next sprint."
  }
}
```

**Validation:** Sprint must exist. Only one retro per sprint (upsert behavior).

#### `get_retro`

**Request:**
```json
{
  "action": "get_retro",
  "payload": {
    "sprint_id": "2026-S04"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "sprint_id": "2026-S04",
    "what_went_well": "Consistent gym attendance. Reading streak held for 10 days.",
    "what_to_improve": "Journaling dropped off in week 2. Need to lower target or change timing.",
    "ideas": "Try morning journaling instead of evening. Add a creative category next sprint.",
    "created_at": "2026-02-28T20:00:00Z"
  }
}
```

### 7.6 Composite Views

#### `sprint_dashboard`

Returns a combined view of the full sprint state: all habits grouped by category with daily values, daily point totals, per-habit summaries, weighted sprint score, and retrospective (if present). This is the primary action for CLI markdown rendering and the CmdShell full-sprint widget.

**Request:**
```json
{
  "action": "sprint_dashboard",
  "payload": {
    "sprint_id": "2026-S05",
    "week": 1
  }
}
```

**Payload fields:**
- `sprint_id` (optional; defaults to active sprint)
- `week` (optional; 1 or 2 for specific week view, omit for full sprint)

**Response:**
```json
{
  "status": "success",
  "data": {
    "sprint": {
      "id": "2026-S05",
      "start_date": "2026-03-01",
      "end_date": "2026-03-14",
      "theme": "Foundation Building",
      "focus_goals": ["Increase activity levels", "Prime for weight loss"],
      "status": "active",
      "days_elapsed": 7,
      "days_remaining": 7
    },
    "categories": [
      {
        "category": "workout",
        "habits": [
          {
            "habit_id": "workout-30min",
            "name": "Workout (30 min)",
            "target_per_week": 4,
            "weight": 2,
            "daily": {
              "2026-03-01": 1, "2026-03-02": 1, "2026-03-03": 0,
              "2026-03-04": 1, "2026-03-05": 0, "2026-03-06": 0, "2026-03-07": 0
            },
            "week_actual": 3,
            "week_completion_pct": 75,
            "commitment_met": false
          },
          {
            "habit_id": "stretching",
            "name": "Stretching",
            "target_per_week": 5,
            "weight": 1,
            "daily": {
              "2026-03-01": 1, "2026-03-02": 1, "2026-03-03": 1,
              "2026-03-04": 1, "2026-03-05": 1, "2026-03-06": 0, "2026-03-07": 0
            },
            "week_actual": 5,
            "week_completion_pct": 100,
            "commitment_met": true
          },
          {
            "habit_id": "daily-walk",
            "name": "Daily Walk",
            "target_per_week": 6,
            "weight": 1,
            "daily": {
              "2026-03-01": 1, "2026-03-02": 1, "2026-03-03": 1,
              "2026-03-04": 1, "2026-03-05": 1, "2026-03-06": 1, "2026-03-07": 0
            },
            "week_actual": 6,
            "week_completion_pct": 100,
            "commitment_met": true
          }
        ],
        "category_weighted_score": 0.85
      },
      {
        "category": "diet",
        "habits": [
          {
            "habit_id": "no-drinks",
            "name": "No Drinks",
            "target_per_week": 7,
            "weight": 3,
            "daily": {
              "2026-03-01": 1, "2026-03-02": 1, "2026-03-03": 1,
              "2026-03-04": 1, "2026-03-05": 1, "2026-03-06": 1, "2026-03-07": 1
            },
            "week_actual": 7,
            "week_completion_pct": 100,
            "commitment_met": true
          },
          {
            "habit_id": "no-sugar",
            "name": "No Sugar",
            "target_per_week": 5,
            "weight": 2,
            "daily": {
              "2026-03-01": 1, "2026-03-02": 1, "2026-03-03": 0,
              "2026-03-04": 1, "2026-03-05": 0, "2026-03-06": 0, "2026-03-07": 0
            },
            "week_actual": 3,
            "week_completion_pct": 60,
            "commitment_met": false
          }
        ],
        "category_weighted_score": 0.82
      },
      {
        "category": "learning",
        "habits": [
          {
            "habit_id": "reading",
            "name": "Reading",
            "target_per_week": 5,
            "weight": 2,
            "daily": {
              "2026-03-01": 1, "2026-03-02": 1, "2026-03-03": 1,
              "2026-03-04": 1, "2026-03-05": 0, "2026-03-06": 0, "2026-03-07": 0
            },
            "week_actual": 4,
            "week_completion_pct": 80,
            "commitment_met": false
          }
        ],
        "category_weighted_score": 0.80
      }
    ],
    "daily_totals": {
      "2026-03-01": { "points": 12, "max": 12, "pct": 100 },
      "2026-03-02": { "points": 12, "max": 12, "pct": 100 },
      "2026-03-03": { "points": 6, "max": 12, "pct": 50 },
      "2026-03-04": { "points": 12, "max": 12, "pct": 100 },
      "2026-03-05": { "points": 5, "max": 12, "pct": 42 },
      "2026-03-06": { "points": 5, "max": 12, "pct": 42 },
      "2026-03-07": { "points": 3, "max": 12, "pct": 25 }
    },
    "sprint_summary": {
      "weighted_score": 0.83,
      "unweighted_score": 0.79,
      "per_habit": [
        { "habit_id": "workout-30min", "actual": 3, "target": 4, "pct": 75 },
        { "habit_id": "stretching", "actual": 5, "target": 5, "pct": 100 },
        { "habit_id": "daily-walk", "actual": 6, "target": 6, "pct": 100 },
        { "habit_id": "no-drinks", "actual": 7, "target": 7, "pct": 100 },
        { "habit_id": "no-sugar", "actual": 3, "target": 5, "pct": 60 },
        { "habit_id": "reading", "actual": 4, "target": 5, "pct": 80 }
      ]
    },
    "retro": null
  }
}
```

This is the richest action in the system. It provides everything needed to render the full sprint dashboard in CmdShell or as CLI markdown output.

---

## 8. Scoring Logic

### 8.1 Weekly Completion (per habit)

```
completion_pct = (actual_days / target_per_week) × 100
commitment_met = actual_days >= target_per_week
```

This is the core metric. Not streak-obsessed — it respects the insight that not everything needs daily execution.

### 8.2 Weighted Sprint Score

```
weighted_score = Σ(actual_entries × weight) / Σ(target_entries × weight)
```

Where `target_entries = target_per_week × weeks_in_sprint`.

This gives behavioral leverage — high-weight habits (e.g., "no alcohol" at weight 3) have more impact on the sprint score than low-weight habits (e.g., "floss" at weight 1).

### 8.3 Daily Score

```
daily_score = Σ(value × weight) for completed habits / Σ(weight) for all active habits
```

Provides immediate daily feedback. CmdShell can chart this across the sprint duration.

### 8.4 Streak Calculation

- **Current streak:** Consecutive days (ending today or yesterday) where `value > 0`
- **Longest streak:** Maximum consecutive days with `value > 0` across all time

Streaks are informational, not primary. Weekly commitment is the main metric.

**All scoring is computed in the reporting layer only.** The LLM never computes these values.

---

## 9. CLI Behavior

### 9.1 JSON Mode (Default)

```bash
echo '{"action":"list_habits","payload":{}}' | habit-sprint
```

or:

```bash
habit-sprint --json '{"action":"list_habits","payload":{}}'
```

Output: JSON only, to stdout.

### 9.2 Markdown Mode (Optional)

```bash
habit-sprint --json '{"action":"sprint_dashboard","payload":{}}' --format markdown
```

Markdown is derived from the structured JSON output — it is never the primary format. The `sprint_dashboard` action is the primary candidate for markdown rendering, as it combines all sprint data into a single cohesive view.

**Reference mockup:** See `docs/ui_spreadsheet_to_ascii_mockup.md` for the canonical visual layout derived from the original 2019–2022 spreadsheet tracker.

**Rendered markdown output format (sprint_dashboard):**

```
====================================================================
SPRINT: 2026-03-01 → 2026-03-14  [Week 1 of 2]
THEME:  Foundation Building
FOCUS:  Increase activity levels | Prime for weight loss
====================================================================

CATEGORY: Workout                                      Score: 85%
--------------------------------------------------------------------
Habit                     | Min/Wk | Wt | Mon Tue Wed Thu Fri Sat Sun |
--------------------------------------------------------------------
Workout (30 min)          |   4    |  2 |  ✓   ✓   ·   ✓   ·   ·   · |  3/4   75%
Stretching                |   5    |  1 |  ✓   ✓   ✓   ✓   ✓   ·   · |  5/5  100% ★
Daily Walk                |   6    |  1 |  ✓   ✓   ✓   ✓   ✓   ✓   · |  6/6  100% ★
--------------------------------------------------------------------
Daily Points                        →  4   4   2   4   2   1   0

CATEGORY: Diet                                         Score: 82%
--------------------------------------------------------------------
Habit                     | Min/Wk | Wt | Mon Tue Wed Thu Fri Sat Sun |
--------------------------------------------------------------------
No Drinks                 |   7    |  3 |  ✓   ✓   ✓   ✓   ✓   ✓   ✓ |  7/7  100% ★
No Sugar                  |   5    |  2 |  ✓   ✓   ·   ✓   ·   ·   · |  3/5   60%
--------------------------------------------------------------------
Daily Points                        →  5   5   3   5   3   3   3

CATEGORY: Learning                                     Score: 80%
--------------------------------------------------------------------
Habit                     | Min/Wk | Wt | Mon Tue Wed Thu Fri Sat Sun |
--------------------------------------------------------------------
Reading                   |   5    |  2 |  ✓   ✓   ✓   ✓   ·   ·   · |  4/5   80%
--------------------------------------------------------------------
Daily Points                        →  2   2   2   2   0   0   0

====================================================================
DAILY TOTALS                  Mon Tue Wed Thu Fri Sat Sun
Points                    →   11  11   7  11   5   4   3
Max Possible              →   12  12  12  12  12  12  12
Completion %              →  92% 92% 58% 92% 42% 33% 25%
====================================================================

SPRINT SUMMARY                                   Weighted: 83%
--------------------------------------------------------------------
Workout (30 min)      3 / 4  →  75%
Stretching            5 / 5  → 100% ★
Daily Walk            6 / 6  → 100% ★
No Drinks             7 / 7  → 100% ★
No Sugar              3 / 5  →  60%
Reading               4 / 5  →  80%
--------------------------------------------------------------------

SPRINT REFLECTION
--------------------------------------------------------------------
(No retrospective recorded yet)
====================================================================
```

**Rendering rules:**
- `✓` for value > 0, `·` for value = 0 or no entry
- `★` appended when `commitment_met = true` (actual ≥ target)
- Daily Points per category = sum of (value × weight) for that category's habits
- Daily Totals row = sum across all categories
- Categories are rendered in the order they appear in the data
- Habits within a category are rendered in creation order
- Day column headers use abbreviated day names (Mon–Sun), derived from actual dates
- Sprint Reflection section renders retro fields if present, otherwise "(No retrospective recorded yet)"

**Other actions in markdown mode:**

The `--format markdown` flag is supported on any reporting action. Simpler actions render simpler output:

- `get_week_view` → Renders a single category-grouped week grid (subset of the dashboard above, without summary/retro)
- `sprint_report` → Renders the sprint summary block with per-habit breakdown
- `habit_report` → Renders a single habit's weekly history as a small table
- `daily_score` → Renders a single day's completed/missed habits with points

### 9.3 Database Location

```bash
habit-sprint --db /path/to/habits.db --json '{...}'
```

Default database location: `~/.habit-sprint/habits.db`. Can be overridden with `--db` flag. SQLite file should be stored in a shared mount directory for CmdShell access and backup.

---

## 10. Integration Strategy

### 10.1 OpenClaw Integration

Two options (decide during implementation):

- **Option A — Direct import:** OpenClaw skill imports `executor.execute()` directly as a Python function.
- **Option B — Subprocess:** OpenClaw skill calls CLI via `subprocess.run()` with JSON piped to stdin.

Option A is preferred for performance and simplicity.

### 10.2 CmdShell Integration

CmdShell talks to the OpenClaw endpoint. OpenClaw invokes the habit-sprint skill. The response JSON drives widget rendering.

**Widget types:**

1. **Weekly Grid Widget** — Renders habit × day grid with checkboxes. User clicks emit `log_date` or `bulk_set` actions through the same JSON contract. (See `get_week_view` response in Section 7.4.)

2. **Sprint Summary Widget** — Renders weighted score, category breakdown, and per-habit stats. (See `sprint_report` response in Section 7.4.)

3. **Daily Score Chart** — Line/bar chart of daily scores across the sprint. Data derived from running `daily_score` for each day.

**Data flow principle:** CmdShell is a rendering layer only. It never owns business logic. Widget interactions emit JSON actions that pass through the same executor as LLM and CLI operations.

### 10.3 SKILLS.md Design

The SKILLS.md file is the LLM constraint layer. It must:

- Define all allowed actions and their exact payload schemas
- Define the response envelope format
- Include concrete examples for each action
- Explicitly forbid inventing fields not in the schema
- Forbid modifying multiple habits in a single action unless the user explicitly requests it
- State that the LLM must never compute metrics — only interpret engine results
- Enforce that all operations go through the JSON contract

---

## 11. Error Handling

The engine must enforce these rules and return clear error messages:

- Reject unknown actions → `"Unknown action: 'foo'"`
- Reject unknown/extra fields in payload → `"Unknown field 'bar' in payload for action 'create_habit'"`
- Validate required fields → `"Missing required field: 'name'"`
- Validate ISO date format → `"Invalid date format: '02-28-2026'. Expected ISO 8601 (YYYY-MM-DD)."`
- Prevent logging to archived habits → `"Cannot log entry: habit 'reading' is archived"`
- Prevent overlapping active sprints → `"Cannot create sprint: active sprint '2026-S04' overlaps with requested dates"`
- Validate target_per_week range → `"target_per_week must be between 1 and 7"`
- Validate weight range → `"weight must be between 1 and 3"`
- Validate unit values → `"Invalid unit 'miles'. Allowed: count, minutes, reps, pages"`
- Enforce deterministic responses — same input always produces same output

---

## 12. Build Phases

### Phase 1 — Core Engine

1. SQLite schema (`schema.sql`)
2. Engine CRUD functions (`engine.py`) — habits, sprints, entries, retros
3. JSON action executor (`executor.py`) — routing, validation, envelope wrapping
4. Basic reporting (`reporting.py`) — weekly completion, streak calculation
5. Unit tests for all actions

### Phase 2 — Reporting & Skill Layer

1. Advanced reporting — weighted sprint scores, category rollups, daily scores, trend deltas
2. SKILLS.md — full skill definition with schemas, examples, and constraints
3. CLI adapter (`cli.py`) — JSON and markdown modes
4. Integration tests

### Phase 3 — CmdShell Integration

1. `get_week_view` optimized for widget rendering
2. CmdShell weekly grid widget
3. CmdShell sprint summary widget
4. Widget → JSON action → engine round-trip
5. Widget auto-refresh after mutations

### Phase 4 — Polish & Future

1. Cross-sprint analytics
2. Heatmap data endpoint
3. Longitudinal yearly summary
4. Export to markdown journal
5. LLM-generated sprint reflections (using retro + sprint data)
6. Correlation analysis hooks (fitness, creative output)

---

## 13. Success Criteria

v1 is successful when:

- JSON contract is stable and fully documented
- All CRUD operations work deterministically through the executor
- Sprint scoring (weighted and unweighted) is accurate
- OpenClaw skill is operational via SKILLS.md
- CLI is operational (JSON in/out)
- CmdShell can render weekly grid view from `get_week_view` data
- All reporting actions return correct, deterministic results
- Error handling covers all validation cases with clear messages
- Core implementation is < 800 LOC (excluding tests)
- Fully deterministic behavior — same input always produces same output

---

## 14. Future Enhancements (Post v1)

- Yearly heatmap data (GitHub-style visualization data)
- Cross-sprint analytics and longitudinal trends
- Correlation analysis (e.g., "weeks I hit reading 5x vs. bench press performance")
- LLM-generated sprint reflections (auto-summarize across 20+ sprints)
- Export to markdown journal
- Lightweight HTTP wrapper (optional REST API)
- Negative habits (e.g., "avoid sugar" where value=0 is success)
- Partial credit logging (e.g., 0.5 for a shortened session)
- Energy level / life balance rating per sprint
- Integration with broader personal systems (Memspan, Life Architecture Framework, Ebb & Flow cycles)

---

## 15. Summary

Habit Sprint is a deterministic sprint-based behavioral state engine built for LLM-native workflows. It is infrastructure, not an app.

Its power lies in:

- Strict JSON contracts that eliminate prompt ambiguity
- Sprint-based iteration with built-in reflection cycles
- Weighted scoring that captures behavioral leverage
- Category-aware balance analysis
- Clean architectural layering (engine → executor → skill → widget)
- A single action contract shared across LLM, CLI, and CmdShell

The system evolves a decade of personal sprint experimentation (2012–2022) into a composable, agent-ready behavioral telemetry layer.
