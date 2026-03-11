---
name: habit-sprint
description: Manage habit tracking via the habit-sprint engine. Use when user wants to create habits, log habit entries, manage sprints, view scores, check streaks, run retrospectives, view weekly completion, or ask about their habits.
allowed-tools: Bash(habit-sprint:*) Bash(echo:*) Read
---

# Habit Sprint — LLM Skill Reference

**Version:** 1.0
**Engine:** habit-sprint (SQLite-backed, JSON-contract-driven behavioral state engine)

## Overview

Habit Sprint is a deterministic sprint-based habit tracking engine. It manages two-week sprint cycles with weighted habits, entry logging, scoring, and retrospectives. All interaction happens through a strict JSON contract — there is no freeform input.

**Key principles for LLM consumers:**

- **Never compute metrics.** The engine computes all scores, streaks, completion percentages, and trends. The LLM only interprets results.
- **Never invent fields.** Only use fields documented in the schemas below. Unknown fields are rejected.
- **One action per request.** Do not batch multiple mutations into a single action. Each action operates atomically.
- **All operations go through the JSON contract.** No direct SQL, no bypassing the executor.

---

## Invocation

All commands go through the `habit-sprint` CLI. The CLI must be installed and on PATH (via `pip install -e .` or `make install-global`).

**Command pattern:**

```bash
habit-sprint --json '{"action": "<action_name>", "payload": {<fields>}}'
```

**Examples:**

```bash
# List all habits
habit-sprint --json '{"action": "list_habits", "payload": {}}'

# Create a habit
habit-sprint --json '{"action": "create_habit", "payload": {"id": "reading", "name": "Reading", "category": "cognitive", "target_per_week": 5, "weight": 2}}'

# Sprint dashboard with markdown rendering
habit-sprint --json '{"action": "sprint_dashboard", "payload": {}}' --format markdown
```

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--json` | JSON action string to execute | (required) |
| `--db` | Path to SQLite database | `~/.habit-sprint/habits.db` |
| `--format` | Output format: `json` or `markdown` | `json` |

The CLI also accepts JSON via stdin pipe: `echo '{"action": "list_habits"}' | habit-sprint`

---

## Global vs Sprint-Scoped Habits

Habits have two scopes controlled by the `sprint_id` field in `create_habit`:

### Global habits (`sprint_id` omitted or null)

Ongoing habits that persist across all sprints. The engine automatically includes them in every sprint's queries, reports, and dashboards. They never need to be re-created between sprints.

**Use for:** Habits that are part of your established routine or long-term commitments — things you intend to maintain indefinitely regardless of what sprint theme you're running.

**Examples:** Weightlifting 3x/week, daily reading, morning cardio, meditation, journaling.

```json
{"action": "create_habit", "payload": {"id": "weightlifting", "name": "Weightlifting", "category": "fitness", "target_per_week": 3, "weight": 2}}
```

### Sprint-scoped habits (`sprint_id` set to a specific sprint)

Temporary habits tied to a single sprint. They only appear in that sprint's queries and reports. Once the sprint ends, they stop showing up in future sprints automatically.

**Use for:** Experiments, challenges, or short-term goals you want to try for one cycle without cluttering your long-term tracking. If a sprint-scoped habit sticks, you can create a new global version of it.

**Examples:** "Cold plunge challenge", "No sugar for 2 weeks", "Write 500 words daily" (trial run), "Practice Spanish 15 min" (testing if it fits your routine).

```json
{"action": "create_habit", "payload": {"id": "cold-plunge", "name": "Cold Plunge Challenge", "category": "health", "target_per_week": 5, "weight": 1, "sprint_id": "2026-S05"}}
```

### How to choose

| Signal | Scope |
|---|---|
| "I want to track this from now on" | Global |
| "I've been doing this for a while, it's part of my routine" | Global |
| "Let me try this for a sprint and see" | Sprint-scoped |
| "Just for this two-week cycle" | Sprint-scoped |
| User doesn't specify | Default to **global** — most habits are intended to persist |

### Querying behavior

When reporting functions receive a `sprint_id`, they return **both** sprint-scoped habits for that sprint **and** all global habits. This means global habits are always visible in every sprint's dashboard, reports, and scores without any extra configuration.

---

## LLM Constraints

These rules are mandatory for any LLM consuming this skill. Violations produce incorrect, misleading, or harmful output.

### 1. Never compute metrics

Never compute streaks, scores, trends, or completion percentages. Only interpret and present values returned by the engine. The engine owns all arithmetic. If you need a streak count, call `weekly_completion` or `sprint_report` — do not count entries yourself.

### 2. Never invent fields

Never invent fields not in the schema. Only use documented field names in requests. If you send `{"action": "create_habit", "payload": {"id": "gym", "name": "Gym", "category": "fitness", "target_per_week": 4, "difficulty": "hard"}}`, the engine will reject it with `"Unknown field difficulty in payload for action create_habit"`. The field `difficulty` does not exist.

### 3. One action per request

Do not modify multiple habits in a single action unless the user explicitly requests it. Each action request should be a single, focused operation. If a user says "log reading and gym for today", emit two separate `log_date` actions — not a single fabricated batch action.

### 4. No data fabrication

Never guess or fabricate data. If the engine returns an error, report it honestly. Do not invent habit IDs, sprint IDs, dates, or values. If you are unsure whether a habit exists, call `list_habits` first.

### 5. Schema is truth

The response schemas documented here are the only valid shapes. Do not add, rename, or restructure fields when presenting engine results to the user. If the engine returns `completion_pct: 80`, do not recompute it or present a different number.

---

## JSON Contract

### Request Format

Every request is a JSON object with two keys:

```json
{
  "action": "<action_name>",
  "payload": { }
}
```

- `action` (string, required) — The action name from the table below.
- `payload` (object, optional) — Defaults to `{}` if omitted.

### Response Envelope

Every response follows this exact structure. Success and error fields are never mixed.

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

### Error Examples

| Scenario | Error message |
|---|---|
| Unknown action | `"Unknown action: foo"` |
| Unknown field in payload | `"Unknown field bar in payload for action create_habit"` |
| Missing required field | `"Missing required field: name"` |
| Invalid ISO date | `"Field date must be a valid ISO date (YYYY-MM-DD)"` |
| Integer out of range | `"Field target_per_week must be >= 1"` |
| Invalid enum value | `"Field unit must be one of: count, minutes, reps, pages"` |
| Type mismatch | `"Field weight must be an integer"` |
| Logging to archived habit | `"Habit is archived: reading"` |
| Overlapping active sprints | `"Cannot create sprint: date range ... overlaps with active sprint ..."` |
| Habit not found | `"Habit not found: reading"` |
| Sprint not found | `"Sprint not found: 2026-S01"` |
| No active sprint | `"No active sprint found"` |

---

## Action Routing Table

### Mutation Actions (15)

Mutations modify database state. Routed through `engine.py`.

| Action | Category | Description |
|---|---|---|
| `create_sprint` | Sprint | Create a new sprint |
| `update_sprint` | Sprint | Update sprint theme/goals |
| `list_sprints` | Sprint | List sprints with optional filter |
| `archive_sprint` | Sprint | Archive a sprint |
| `get_active_sprint` | Sprint | Get the currently active sprint |
| `create_habit` | Habit | Create a new habit |
| `update_habit` | Habit | Update an existing habit |
| `archive_habit` | Habit | Archive a habit |
| `list_habits` | Habit | List habits with optional filters |
| `log_date` | Entry | Log a single entry (idempotent upsert) |
| `log_range` | Entry | Log entries across a date range |
| `bulk_set` | Entry | Log entries for specific non-contiguous dates |
| `delete_entry` | Entry | Delete a single entry |
| `add_retro` | Retro | Add/update a sprint retrospective (upsert) |
| `get_retro` | Retro | Retrieve a sprint retrospective |

### Query Actions (7)

Queries are read-only analytics. Routed through `reporting.py`.

| Action | Description |
|---|---|
| `weekly_completion` | Weekly completion stats for a single habit |
| `daily_score` | Aggregate score for a single day |
| `get_week_view` | Weekly grid data (habits x days) grouped by category |
| `sprint_report` | Full sprint analytics with weighted scoring |
| `habit_report` | Detailed report for a single habit over a period |
| `category_report` | Aggregated report across categories with balance analysis |
| `sprint_dashboard` | Combined full-sprint view (richest action in the system) |

---

## Mutation Actions

### create_sprint

Creates a new sprint. Only one active sprint at a time. Sprint IDs are auto-generated in `YYYY-S##` format based on the start_date year and existing sprint count (the `id` field in the payload is validated but the engine auto-generates the actual ID).

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `id` | str | yes | Sprint identifier (validated but auto-generated by engine) | Format: `YYYY-S##` |
| `start_date` | iso_date | yes | Sprint start date | Valid ISO date (YYYY-MM-DD) |
| `end_date` | iso_date | yes | Sprint end date | Must be after start_date |
| `theme` | str | no | Sprint theme | Free text |
| `focus_goals` | list | no | List of focus goal strings | JSON array of strings |

**Behavior:**
- Validates no overlapping active sprints exist.
- `end_date` must be strictly after `start_date`.
- Default sprint duration is 14 days (2 weeks), but any range is accepted.

**Response data:**

```json
{
  "id": "2026-S05",
  "start_date": "2026-03-01",
  "end_date": "2026-03-14",
  "theme": "Foundation Building",
  "focus_goals": ["Establish morning routine", "Hit gym 4x/week"],
  "status": "active",
  "created_at": "2026-03-01T10:00:00",
  "updated_at": "2026-03-01T10:00:00"
}
```

**Example:**

```json
// Request
{"action": "create_sprint", "payload": {"id": "2026-S05", "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Foundation Building", "focus_goals": ["Establish morning routine", "Hit gym 4x/week"]}}

// Response
{"status": "success", "data": {"id": "2026-S05", "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Foundation Building", "focus_goals": ["Establish morning routine", "Hit gym 4x/week"], "status": "active", "created_at": "2026-03-01T10:00:00", "updated_at": "2026-03-01T10:00:00"}, "error": null}
```

---

### update_sprint

Updates an existing sprint's theme and/or focus goals. Only provided fields are changed; omitted fields are unchanged.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `id` | str | yes | Sprint ID to update | Must exist |
| `theme` | str | no | New theme | Free text |
| `focus_goals` | list | no | New focus goals | JSON array of strings |

**Note:** The engine reads this field as `sprint_id` internally. The validated payload field name is `id`.

**Response data:** Returns the full updated sprint object (same shape as `create_sprint` response).

**Example:**

```json
// Request
{"action": "update_sprint", "payload": {"id": "2026-S05", "theme": "Peak Performance", "focus_goals": ["Exercise daily", "Read 30 pages/day"]}}

// Response
{"status": "success", "data": {"id": "2026-S05", "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Peak Performance", "focus_goals": ["Exercise daily", "Read 30 pages/day"], "status": "active", "created_at": "2026-03-01T10:00:00", "updated_at": "2026-03-05T14:30:00"}, "error": null}
```

---

### list_sprints

Lists sprints with optional status filtering.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `status` | str | no | Filter by status | Enum: `active`, `archived`. Omit for all sprints. |

**Response data:**

```json
{
  "sprints": [
    {
      "id": "2026-S05",
      "start_date": "2026-03-01",
      "end_date": "2026-03-14",
      "theme": "Foundation Building",
      "focus_goals": ["Establish morning routine"],
      "status": "active",
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

**Example:**

```json
// Request
{"action": "list_sprints", "payload": {"status": "active"}}

// Response
{"status": "success", "data": {"sprints": [{"id": "2026-S05", "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Foundation Building", "focus_goals": ["Establish morning routine"], "status": "active", "created_at": "2026-03-01T10:00:00", "updated_at": "2026-03-01T10:00:00"}]}, "error": null}
```

---

### archive_sprint

Archives a sprint by setting its status to `"archived"`.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `id` | str | yes | Sprint ID to archive | Must exist |

**Response data:** Returns the full updated sprint object with `"status": "archived"`.

**Example:**

```json
// Request
{"action": "archive_sprint", "payload": {"id": "2026-S04"}}

// Response
{"status": "success", "data": {"id": "2026-S04", "start_date": "2026-02-15", "end_date": "2026-02-28", "theme": "Kickstart", "focus_goals": ["Build consistency"], "status": "archived", "created_at": "2026-02-15T08:00:00", "updated_at": "2026-03-01T09:00:00"}, "error": null}
```

---

### get_active_sprint

Returns the currently active sprint. No payload fields.

**Payload:** `{}` (empty)

**Response data:** Returns the full sprint object. Errors if no active sprint exists.

**Example:**

```json
// Request
{"action": "get_active_sprint", "payload": {}}

// Response
{"status": "success", "data": {"id": "2026-S05", "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Foundation Building", "focus_goals": ["Establish morning routine", "Hit gym 4x/week"], "status": "active", "created_at": "2026-03-01T10:00:00", "updated_at": "2026-03-01T10:00:00"}, "error": null}
```

---

### create_habit

Creates a new habit. Habits can be global (no sprint_id) or sprint-scoped. Global habits carry forward across all sprints.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `id` | str | yes | Habit slug identifier | Lowercase letters and hyphens only (e.g., `reading`, `daily-walk`) |
| `name` | str | yes | Display name | Free text (e.g., `"Reading"`) |
| `category` | str | yes | Category grouping | Free text (e.g., `"health"`, `"cognitive"`, `"projects"`) |
| `target_per_week` | int | yes | Minimum days per week | 1 to 7 |
| `weight` | int | no | Behavioral leverage weight | 1 to 3. Default: 1. (1=low, 2=medium, 3=high) |
| `unit` | str | no | Measurement unit | Enum: `count`, `minutes`, `reps`, `pages`. Default: `count` |
| `sprint_id` | str | no | Attach to specific sprint | Must reference existing sprint. Null = global habit. |

**Behavior:**
- `id` must be a valid slug: lowercase letters and hyphens only (regex: `^[a-z]+(-[a-z]+)*$`).
- `id` must be unique across all habits.
- For avoidance habits (e.g., "no-alcohol"), `value=1` means success (avoided the behavior).

**Response data:**

```json
{
  "id": "reading",
  "name": "Reading",
  "category": "cognitive",
  "target_per_week": 5,
  "weight": 2,
  "unit": "count",
  "sprint_id": "2026-S05",
  "archived": 0,
  "created_at": "...",
  "updated_at": "..."
}
```

**Example:**

```json
// Request
{"action": "create_habit", "payload": {"id": "workout-30min", "name": "Workout (30 min)", "category": "fitness", "target_per_week": 4, "weight": 3, "unit": "count", "sprint_id": "2026-S05"}}

// Response
{"status": "success", "data": {"id": "workout-30min", "name": "Workout (30 min)", "category": "fitness", "target_per_week": 4, "weight": 3, "unit": "count", "sprint_id": "2026-S05", "archived": 0, "created_at": "2026-03-01T10:05:00", "updated_at": "2026-03-01T10:05:00"}, "error": null}
```

---

### update_habit

Updates an existing habit. Only provided fields are changed. Cannot update archived habits.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `id` | str | yes | Habit ID to update | Must exist, must not be archived |
| `name` | str | no | New display name | Free text |
| `category` | str | no | New category | Free text |
| `target_per_week` | int | no | New weekly target | 1 to 7 |
| `weight` | int | no | New weight | 1 to 3 |
| `unit` | str | no | New unit | Enum: `count`, `minutes`, `reps`, `pages` |
| `sprint_id` | str | no | New sprint association | Sprint must exist |

**Response data:** Returns the full updated habit object (same shape as `create_habit` response).

**Example:**

```json
// Request
{"action": "update_habit", "payload": {"id": "workout-30min", "target_per_week": 5, "weight": 2}}

// Response
{"status": "success", "data": {"id": "workout-30min", "name": "Workout (30 min)", "category": "fitness", "target_per_week": 5, "weight": 2, "unit": "count", "sprint_id": "2026-S05", "archived": 0, "created_at": "2026-03-01T10:05:00", "updated_at": "2026-03-04T08:15:00"}, "error": null}
```

---

### archive_habit

Soft-deletes a habit by setting `archived=1`. Archived habits cannot receive new entries.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `id` | str | yes | Habit ID to archive | Must exist |

**Response data:** Returns the full habit object with `"archived": 1`.

**Example:**

```json
// Request
{"action": "archive_habit", "payload": {"id": "no-alcohol"}}

// Response
{"status": "success", "data": {"id": "no-alcohol", "name": "No Alcohol", "category": "health", "target_per_week": 7, "weight": 2, "unit": "count", "sprint_id": null, "archived": 1, "created_at": "2026-02-15T09:00:00", "updated_at": "2026-03-05T11:30:00"}, "error": null}
```

---

### unarchive_habit

Restores an archived habit by setting `archived=0`. The habit can then receive new entries again.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `id` | str | yes | Habit ID to restore | Must exist |

**Response data:** Returns the full habit object with `"archived": 0`.

**Example:**

```json
// Request
{"action": "unarchive_habit", "payload": {"id": "no-alcohol"}}

// Response
{"status": "success", "data": {"id": "no-alcohol", "name": "No Alcohol", "category": "health", "target_per_week": 7, "weight": 2, "unit": "count", "sprint_id": null, "archived": 0, "created_at": "2026-02-15T09:00:00", "updated_at": "2026-03-05T11:30:00"}, "error": null}
```

---

### list_habits

Lists habits with optional filters. When `sprint_id` is provided, returns both sprint-scoped habits and global habits (sprint_id IS NULL).

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `sprint_id` | str | no | Filter by sprint (includes global habits) | Sprint must exist |
| `category` | str | no | Filter by category | Exact match |
| `include_archived` | bool | no | Include archived habits | Default: false |

**Response data:**

```json
{
  "habits": [
    {
      "id": "reading",
      "name": "Reading",
      "category": "cognitive",
      "target_per_week": 5,
      "weight": 2,
      "unit": "count",
      "sprint_id": "2026-S05",
      "archived": 0,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

**Example:**

```json
// Request
{"action": "list_habits", "payload": {"sprint_id": "2026-S05", "category": "fitness"}}

// Response
{"status": "success", "data": {"habits": [{"id": "workout-30min", "name": "Workout (30 min)", "category": "fitness", "target_per_week": 4, "weight": 3, "unit": "count", "sprint_id": "2026-S05", "archived": 0, "created_at": "2026-03-01T10:05:00", "updated_at": "2026-03-01T10:05:00"}, {"id": "daily-walk", "name": "Daily Walk", "category": "fitness", "target_per_week": 5, "weight": 1, "unit": "minutes", "sprint_id": null, "archived": 0, "created_at": "2026-02-15T09:00:00", "updated_at": "2026-02-15T09:00:00"}]}, "error": null}
```

---

### log_date

Logs a single habit entry for a specific date. **Idempotent upsert** — if an entry already exists for the same habit+date, it is replaced (INSERT OR REPLACE).

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `habit_id` | str | yes | Habit to log | Must exist, must not be archived |
| `date` | iso_date | yes | Date to log | Valid ISO date (YYYY-MM-DD) |
| `value` | number | yes | Entry value | >= 0. Use `1` for binary/avoidance habits. |
| `note` | str | no | Optional context note | Free text |

**Behavior:**
- For binary habits: `value=1` means completed/success.
- For avoidance habits (e.g., "no-alcohol"): `value=1` means the avoidance was maintained (success).
- For numeric habits (e.g., minutes of reading): use the actual value.
- `value=0` effectively means "not done" but the entry record still exists.

**Response data:**

```json
{
  "habit_id": "reading",
  "date": "2026-02-28",
  "value": 1,
  "note": "Finished chapter 12",
  "created_at": "...",
  "updated_at": "...",
  "created": true
}
```

`created` is `true` for new entries, `false` for upserts (overwrites).

**Example:**

```json
// Request
{"action": "log_date", "payload": {"habit_id": "reading", "date": "2026-03-05", "value": 1, "note": "Finished chapter 12 of Atomic Habits"}}

// Response
{"status": "success", "data": {"habit_id": "reading", "date": "2026-03-05", "value": 1, "note": "Finished chapter 12 of Atomic Habits", "created_at": "2026-03-05T21:00:00", "updated_at": "2026-03-05T21:00:00", "created": true}, "error": null}
```

---

### log_range

Logs a habit across a contiguous date range with the same value.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `habit_id` | str | yes | Habit to log | Must exist, must not be archived |
| `start_date` | iso_date | yes | Range start date | Valid ISO date |
| `end_date` | iso_date | yes | Range end date | Must not be before start_date |
| `value` | number | no | Entry value for all dates | >= 0. Default: 1 |

**Response data:**

```json
{
  "habit_id": "reading",
  "dates": ["2026-02-26", "2026-02-27", "2026-02-28"],
  "count": 3
}
```

**Example:**

```json
// Request
{"action": "log_range", "payload": {"habit_id": "daily-walk", "start_date": "2026-03-03", "end_date": "2026-03-07", "value": 1}}

// Response
{"status": "success", "data": {"habit_id": "daily-walk", "dates": ["2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06", "2026-03-07"], "count": 5}, "error": null}
```

---

### bulk_set

Sets values for a habit on specific (non-contiguous) dates. Uses INSERT OR REPLACE for each date.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `habit_id` | str | yes | Habit to log | Must exist, must not be archived |
| `dates` | list_of_iso_dates | yes | List of specific dates | Each must be valid ISO date |
| `value` | number | no | Entry value for all dates | >= 0. Default: 1 |

**Response data:**

```json
{
  "habit_id": "reading",
  "dates": ["2026-02-24", "2026-02-25", "2026-02-27"],
  "count": 3
}
```

**Example:**

```json
// Request
{"action": "bulk_set", "payload": {"habit_id": "mindfulness", "dates": ["2026-03-01", "2026-03-03", "2026-03-05", "2026-03-07"], "value": 1}}

// Response
{"status": "success", "data": {"habit_id": "mindfulness", "dates": ["2026-03-01", "2026-03-03", "2026-03-05", "2026-03-07"], "count": 4}, "error": null}
```

---

### delete_entry

Removes a logged entry for a specific habit and date.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `habit_id` | str | yes | Habit ID | Must exist, must not be archived |
| `date` | iso_date | yes | Date to delete | Valid ISO date |

**Response data:**

```json
{
  "habit_id": "reading",
  "date": "2026-02-27",
  "deleted": true
}
```

`deleted` is `true` if an entry existed and was removed, `false` if no entry existed for that date.

**Example:**

```json
// Request
{"action": "delete_entry", "payload": {"habit_id": "reading", "date": "2026-03-04"}}

// Response
{"status": "success", "data": {"habit_id": "reading", "date": "2026-03-04", "deleted": true}, "error": null}
```

---

### add_retro

Stores a sprint retrospective. **Upsert behavior** — one retrospective per sprint. If a retro already exists for the sprint, it is replaced.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `sprint_id` | str | yes | Sprint to attach retro to | Must exist |
| `what_went_well` | str | no | Reflection on successes | Free text |
| `what_to_improve` | str | no | Areas for improvement | Free text |
| `ideas` | str | no | Ideas for next sprint | Free text |

**Response data:**

```json
{
  "id": 1,
  "sprint_id": "2026-S04",
  "what_went_well": "Consistent gym attendance.",
  "what_to_improve": "Journaling dropped off in week 2.",
  "ideas": "Try morning journaling instead of evening.",
  "created_at": "...",
  "updated_at": "..."
}
```

**Example:**

```json
// Request
{"action": "add_retro", "payload": {"sprint_id": "2026-S04", "what_went_well": "Consistent gym attendance. Hit 4x/week every week.", "what_to_improve": "Journaling dropped off in week 2. Only managed 3 out of 7 days.", "ideas": "Try morning journaling instead of evening. Pair it with coffee routine."}}

// Response
{"status": "success", "data": {"id": 1, "sprint_id": "2026-S04", "what_went_well": "Consistent gym attendance. Hit 4x/week every week.", "what_to_improve": "Journaling dropped off in week 2. Only managed 3 out of 7 days.", "ideas": "Try morning journaling instead of evening. Pair it with coffee routine.", "created_at": "2026-03-01T09:00:00", "updated_at": "2026-03-01T09:00:00"}, "error": null}
```

---

### get_retro

Retrieves the retrospective for a specific sprint.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `sprint_id` | str | yes | Sprint ID | Must exist, must have a retro |

**Response data:** Same shape as `add_retro` response. Errors if no retro exists for the sprint.

**Example:**

```json
// Request
{"action": "get_retro", "payload": {"sprint_id": "2026-S04"}}

// Response
{"status": "success", "data": {"id": 1, "sprint_id": "2026-S04", "what_went_well": "Consistent gym attendance. Hit 4x/week every week.", "what_to_improve": "Journaling dropped off in week 2.", "ideas": "Try morning journaling instead of evening.", "created_at": "2026-03-01T09:00:00", "updated_at": "2026-03-01T09:00:00"}, "error": null}
```

---

## Query Actions

### weekly_completion

Returns weekly completion statistics for a single habit, including streaks.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `habit_id` | str | yes | Habit to report on | Must exist |
| `week_start` | iso_date | no | Monday of the target week | Defaults to current week's Monday |

**Behavior:**
- Week boundaries are fixed Mon-Sun.
- Streaks are computed across all entries for the habit (all-time), not just the target week.

**Response data:**

```json
{
  "habit_id": "reading",
  "week_start": "2026-02-24",
  "week_end": "2026-03-02",
  "actual_days": 3,
  "target_per_week": 5,
  "completion_pct": 60,
  "commitment_met": false,
  "current_streak": 3,
  "longest_streak": 14
}
```

- `completion_pct` is capped at 100.
- `commitment_met` is `true` when `actual_days >= target_per_week`.

**Example:**

```json
// Request
{"action": "weekly_completion", "payload": {"habit_id": "reading", "week_start": "2026-03-02"}}

// Response
{"status": "success", "data": {"habit_id": "reading", "week_start": "2026-03-02", "week_end": "2026-03-08", "actual_days": 3, "target_per_week": 5, "completion_pct": 60, "commitment_met": false, "current_streak": 3, "longest_streak": 14}, "error": null}
```

---

### daily_score

Returns the aggregate weighted score for a single day.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `date` | iso_date | yes | Date to score | Valid ISO date |
| `sprint_id` | str | no | Sprint context | Defaults to active sprint |

**Formula:** `total_points = sum(value * weight)` for completed habits. `max_possible = sum(weight)` for all active habits. `completion_pct = round(total_points / max_possible * 100)`.

**Response data:**

```json
{
  "date": "2026-02-28",
  "sprint_id": "2026-S05",
  "total_points": 8,
  "max_possible": 14,
  "completion_pct": 57,
  "habits_completed": [
    { "id": "reading", "name": "Reading", "value": 1, "weight": 2, "points": 2 }
  ],
  "habits_missed": [
    { "id": "daily-walk", "name": "Daily Walk", "weight": 1, "points_possible": 1 }
  ]
}
```

**Example:**

```json
// Request
{"action": "daily_score", "payload": {"date": "2026-03-05"}}

// Response
{"status": "success", "data": {"date": "2026-03-05", "sprint_id": "2026-S05", "total_points": 8, "max_possible": 14, "completion_pct": 57, "habits_completed": [{"id": "workout-30min", "name": "Workout (30 min)", "value": 1, "weight": 3, "points": 3}, {"id": "reading", "name": "Reading", "value": 1, "weight": 2, "points": 2}, {"id": "mindfulness", "name": "Mindfulness", "value": 1, "weight": 2, "points": 2}, {"id": "daily-walk", "name": "Daily Walk", "value": 1, "weight": 1, "points": 1}], "habits_missed": [{"id": "journaling", "name": "Journaling", "weight": 2, "points_possible": 2}, {"id": "meal-prep", "name": "Meal Prep", "weight": 2, "points_possible": 2}, {"id": "no-alcohol", "name": "No Alcohol", "weight": 2, "points_possible": 2}]}, "error": null}
```

---

### get_week_view

Returns weekly grid data for all active habits, grouped by category. Primary data source for week-view rendering.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `week_start` | iso_date | no | Monday of the target week | Defaults to current week's Monday |
| `sprint_id` | str | no | Sprint context | Defaults to active sprint |

**Behavior:**
- Days outside the sprint date range show `0` values.
- Habits are grouped by category, ordered by creation date within each category.

**Response data:**

```json
{
  "sprint_id": "2026-S05",
  "week_start": "2026-02-24",
  "week_end": "2026-03-02",
  "categories": {
    "health": {
      "habits": [
        {
          "id": "daily-walk",
          "name": "Daily Walk",
          "target_per_week": 4,
          "weight": 1,
          "daily_values": {
            "Mon": 1, "Tue": 1, "Wed": 1, "Thu": 1, "Fri": 0, "Sat": 0, "Sun": 0
          },
          "week_actual": 4,
          "week_completion_pct": 100,
          "commitment_met": true
        }
      ]
    }
  }
}
```

**Example:**

```json
// Request
{"action": "get_week_view", "payload": {"week_start": "2026-03-02", "sprint_id": "2026-S05"}}

// Response
{"status": "success", "data": {"sprint_id": "2026-S05", "week_start": "2026-03-02", "week_end": "2026-03-08", "categories": {"fitness": {"habits": [{"id": "workout-30min", "name": "Workout (30 min)", "target_per_week": 4, "weight": 3, "daily_values": {"Mon": 1, "Tue": 0, "Wed": 1, "Thu": 1, "Fri": 0, "Sat": 1, "Sun": 0}, "week_actual": 4, "week_completion_pct": 100, "commitment_met": true}]}, "cognitive": {"habits": [{"id": "reading", "name": "Reading", "target_per_week": 5, "weight": 2, "daily_values": {"Mon": 1, "Tue": 1, "Wed": 0, "Thu": 1, "Fri": 1, "Sat": 0, "Sun": 0}, "week_actual": 4, "week_completion_pct": 80, "commitment_met": false}]}}}, "error": null}
```

---

### sprint_report

Full sprint analytics with weighted scoring and per-habit breakdowns.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `sprint_id` | str | no | Sprint to report on | Defaults to active sprint |

**Response data:**

```json
{
  "sprint_id": "2026-S05",
  "start_date": "2026-03-01",
  "end_date": "2026-03-14",
  "theme": "Foundation Building",
  "focus_goals": ["Increase activity levels"],
  "status": "active",
  "days_elapsed": 10,
  "days_remaining": 4,
  "total_days": 14,
  "num_weeks": 2,
  "weighted_score": 72,
  "unweighted_score": 68,
  "categories": [
    {
      "category": "health",
      "weighted_score": 85,
      "habits": [ ]
    }
  ],
  "habits": [
    {
      "habit_id": "reading",
      "name": "Reading",
      "category": "cognitive",
      "weight": 2,
      "total_entries": 8,
      "expected_entries": 10,
      "completion_pct": 80,
      "current_streak": 3,
      "longest_streak": 6,
      "weekly_breakdown": [
        { "week_start": "2026-03-01", "week_end": "2026-03-07", "actual": 4, "target": 5 }
      ]
    }
  ],
  "trend_vs_last_sprint": -5
}
```

**Notes:**
- `weighted_score` formula: `round(sum(actual_entries * weight) / sum(target_entries * weight) * 100)` where `target_entries = target_per_week * num_weeks`.
- `trend_vs_last_sprint` is an integer representing the difference in weighted_score percentage points between this sprint and the previous one. Returns `null` when no prior sprint exists.
- Scores are integer percentages (0-100).

**Example:**

```json
// Request
{"action": "sprint_report", "payload": {"sprint_id": "2026-S05"}}

// Response
{"status": "success", "data": {"sprint_id": "2026-S05", "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Foundation Building", "focus_goals": ["Establish morning routine", "Hit gym 4x/week"], "status": "active", "days_elapsed": 10, "days_remaining": 4, "total_days": 14, "num_weeks": 2, "weighted_score": 72, "unweighted_score": 68, "categories": [{"category": "fitness", "weighted_score": 85, "habits": [{"habit_id": "workout-30min", "name": "Workout (30 min)", "category": "fitness", "weight": 3, "total_entries": 7, "expected_entries": 8, "completion_pct": 88, "current_streak": 3, "longest_streak": 5, "weekly_breakdown": [{"week_start": "2026-03-01", "week_end": "2026-03-07", "actual": 4, "target": 4}, {"week_start": "2026-03-08", "week_end": "2026-03-14", "actual": 3, "target": 4}]}]}, {"category": "cognitive", "weighted_score": 60, "habits": [{"habit_id": "reading", "name": "Reading", "category": "cognitive", "weight": 2, "total_entries": 6, "expected_entries": 10, "completion_pct": 60, "current_streak": 2, "longest_streak": 8, "weekly_breakdown": [{"week_start": "2026-03-01", "week_end": "2026-03-07", "actual": 4, "target": 5}, {"week_start": "2026-03-08", "week_end": "2026-03-14", "actual": 2, "target": 5}]}]}], "habits": [{"habit_id": "workout-30min", "name": "Workout (30 min)", "category": "fitness", "weight": 3, "total_entries": 7, "expected_entries": 8, "completion_pct": 88, "current_streak": 3, "longest_streak": 5, "weekly_breakdown": [{"week_start": "2026-03-01", "week_end": "2026-03-07", "actual": 4, "target": 4}, {"week_start": "2026-03-08", "week_end": "2026-03-14", "actual": 3, "target": 4}]}, {"habit_id": "reading", "name": "Reading", "category": "cognitive", "weight": 2, "total_entries": 6, "expected_entries": 10, "completion_pct": 60, "current_streak": 2, "longest_streak": 8, "weekly_breakdown": [{"week_start": "2026-03-01", "week_end": "2026-03-07", "actual": 4, "target": 5}, {"week_start": "2026-03-08", "week_end": "2026-03-14", "actual": 2, "target": 5}]}], "trend_vs_last_sprint": -5}, "error": null}
```

---

### habit_report

Detailed report for a single habit over a configurable time period.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `habit_id` | str | yes | Habit to report on | Must exist |
| `period` | str | no | Time period | Enum: `current_sprint`, `last_4_weeks`, `last_8_weeks`. Default: `current_sprint` |
| `sprint_id` | str | no | Specific sprint to report on | Overrides `period` when provided |

**Behavior:**
- When `sprint_id` is provided, it overrides the `period` value.
- `last_4_weeks` / `last_8_weeks` are computed from the current Monday backward.
- Streaks are computed across all-time entries, not limited to the period.

**Response data:**

```json
{
  "habit_id": "reading",
  "habit_name": "Reading",
  "period": "last_4_weeks",
  "start_date": "2026-02-03",
  "end_date": "2026-03-02",
  "total_entries": 16,
  "expected_entries": 20,
  "completion_pct": 80,
  "current_streak": 3,
  "longest_streak": 14,
  "rolling_7_day_avg": 0.71,
  "trend_vs_prior_period": "+5%",
  "weekly_history": [
    { "week_start": "2026-02-03", "actual": 5, "target": 5, "completion_pct": 100 },
    { "week_start": "2026-02-10", "actual": 4, "target": 5, "completion_pct": 80 },
    { "week_start": "2026-02-17", "actual": 3, "target": 5, "completion_pct": 60 },
    { "week_start": "2026-02-24", "actual": 4, "target": 5, "completion_pct": 80 }
  ]
}
```

**Notes:**
- `rolling_7_day_avg` = entries with value > 0 in last 7 days / 7, rounded to 2 decimal places.
- `trend_vs_prior_period` is a formatted string like `"+5%"` or `"-10%"`, comparing the current period's completion_pct to an equally-long prior period.

**Example:**

```json
// Request
{"action": "habit_report", "payload": {"habit_id": "reading", "period": "last_4_weeks"}}

// Response
{"status": "success", "data": {"habit_id": "reading", "habit_name": "Reading", "period": "last_4_weeks", "start_date": "2026-02-03", "end_date": "2026-03-02", "total_entries": 16, "expected_entries": 20, "completion_pct": 80, "current_streak": 3, "longest_streak": 14, "rolling_7_day_avg": 0.71, "trend_vs_prior_period": "+5%", "weekly_history": [{"week_start": "2026-02-03", "actual": 5, "target": 5, "completion_pct": 100}, {"week_start": "2026-02-10", "actual": 4, "target": 5, "completion_pct": 80}, {"week_start": "2026-02-17", "actual": 3, "target": 5, "completion_pct": 60}, {"week_start": "2026-02-24", "actual": 4, "target": 5, "completion_pct": 80}]}, "error": null}
```

---

### category_report

Aggregated report across all categories for a sprint. Includes balance analysis to detect over/under-focus.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `sprint_id` | str | no | Sprint to report on | Defaults to active sprint |
| `category` | str | no | Filter to a single category | Exact match |

**Response data:**

```json
{
  "sprint_id": "2026-S05",
  "categories": [
    {
      "category": "health",
      "habits_count": 3,
      "weighted_score": 85,
      "unweighted_score": 80,
      "habit_ids": ["daily-walk", "gym", "no-alcohol"]
    },
    {
      "category": "cognitive",
      "habits_count": 2,
      "weighted_score": 60,
      "unweighted_score": 55,
      "habit_ids": ["reading", "journaling"]
    }
  ],
  "balance_assessment": {
    "most_adherent": "health",
    "least_adherent": "cognitive",
    "spread": 25
  }
}
```

**Notes:**
- `balance_assessment.spread` = max weighted_score minus min weighted_score across categories (integer).
- When only one category exists, `spread` is 0 and both `most_adherent` and `least_adherent` point to the same category.
- When no categories exist, both are `null` and `spread` is 0.

**Example:**

```json
// Request
{"action": "category_report", "payload": {"sprint_id": "2026-S05"}}

// Response
{"status": "success", "data": {"sprint_id": "2026-S05", "categories": [{"category": "fitness", "habits_count": 3, "weighted_score": 85, "unweighted_score": 80, "habit_ids": ["workout-30min", "daily-walk", "no-alcohol"]}, {"category": "cognitive", "habits_count": 2, "weighted_score": 60, "unweighted_score": 55, "habit_ids": ["reading", "journaling"]}, {"category": "diet", "habits_count": 1, "weighted_score": 70, "unweighted_score": 70, "habit_ids": ["meal-prep"]}], "balance_assessment": {"most_adherent": "fitness", "least_adherent": "cognitive", "spread": 25}}, "error": null}
```

---

### sprint_dashboard

The richest action in the system. Returns a combined view of the full sprint state: all habits grouped by category with daily values, daily point totals, per-habit summaries, weighted sprint score, and retrospective (if present). This is the primary action for CLI markdown rendering.

**Payload:**

| Field | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `sprint_id` | str | no | Sprint to display | Defaults to active sprint |
| `week` | int | no | View a specific week only | 1 or 2 (for 2-week sprints). Omit for full sprint. Min: 1, Max: 2. |

**Response data:**

```json
{
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
        }
      ],
      "category_weighted_score": 85
    }
  ],
  "daily_totals": {
    "2026-03-01": { "points": 12, "max": 12, "pct": 100 },
    "2026-03-02": { "points": 10, "max": 12, "pct": 83 }
  },
  "sprint_summary": {
    "weighted_score": 83,
    "unweighted_score": 79,
    "per_habit": [
      { "habit_id": "workout-30min", "actual": 3, "target": 4, "pct": 75 },
      { "habit_id": "reading", "actual": 4, "target": 5, "pct": 80 }
    ]
  },
  "retro": null
}
```

**Notes:**
- `retro` is the full retro object if one exists, or `null` if no retrospective has been recorded.
- When `week` is specified, `daily` maps and `daily_totals` only contain dates for that week.
- `daily` keys are ISO dates (YYYY-MM-DD), not day names.
- `commitment_met` in the dashboard considers the full view (if week=null, this covers both weeks).

**Example:**

```json
// Request
{"action": "sprint_dashboard", "payload": {"sprint_id": "2026-S05", "week": 1}}

// Response
{"status": "success", "data": {"sprint": {"id": "2026-S05", "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Foundation Building", "focus_goals": ["Establish morning routine", "Hit gym 4x/week"], "status": "active", "days_elapsed": 7, "days_remaining": 7}, "categories": [{"category": "fitness", "habits": [{"habit_id": "workout-30min", "name": "Workout (30 min)", "target_per_week": 4, "weight": 3, "daily": {"2026-03-01": 1, "2026-03-02": 0, "2026-03-03": 1, "2026-03-04": 1, "2026-03-05": 0, "2026-03-06": 1, "2026-03-07": 0}, "week_actual": 4, "week_completion_pct": 100, "commitment_met": true}], "category_weighted_score": 85}, {"category": "cognitive", "habits": [{"habit_id": "reading", "name": "Reading", "target_per_week": 5, "weight": 2, "daily": {"2026-03-01": 1, "2026-03-02": 1, "2026-03-03": 0, "2026-03-04": 1, "2026-03-05": 1, "2026-03-06": 0, "2026-03-07": 0}, "week_actual": 4, "week_completion_pct": 80, "commitment_met": false}], "category_weighted_score": 60}], "daily_totals": {"2026-03-01": {"points": 8, "max": 10, "pct": 80}, "2026-03-02": {"points": 4, "max": 10, "pct": 40}, "2026-03-03": {"points": 6, "max": 10, "pct": 60}, "2026-03-04": {"points": 8, "max": 10, "pct": 80}, "2026-03-05": {"points": 4, "max": 10, "pct": 40}, "2026-03-06": {"points": 6, "max": 10, "pct": 60}, "2026-03-07": {"points": 0, "max": 10, "pct": 0}}, "sprint_summary": {"weighted_score": 72, "unweighted_score": 68, "per_habit": [{"habit_id": "workout-30min", "actual": 4, "target": 4, "pct": 100}, {"habit_id": "reading", "actual": 4, "target": 5, "pct": 80}]}, "retro": null}, "error": null}
```

---

## Validation Rules

### Field Type Rules

| Type | Validation | Error on failure |
|---|---|---|
| `str` | Must be a Python string | `"Field {name} must be a string"` |
| `int` | Must be a Python integer (not bool) | `"Field {name} must be an integer"` |
| `number` | Must be int or float (not bool) | `"Field {name} must be a number"` |
| `iso_date` | Must be a string matching `YYYY-MM-DD` and represent a valid calendar date | `"Field {name} must be a valid ISO date (YYYY-MM-DD)"` |
| `bool` | Must be a Python boolean | `"Field {name} must be a boolean"` |
| `list` | Must be a Python list | `"Field {name} must be a list"` |
| `list_of_iso_dates` | Must be a list where every element is a valid ISO date | `"Field {name}[{i}] must be a valid ISO date (YYYY-MM-DD)"` |

### Range Constraints

| Field | Min | Max | Actions |
|---|---|---|---|
| `target_per_week` | 1 | 7 | `create_habit`, `update_habit` |
| `weight` | 1 | 3 | `create_habit`, `update_habit` |
| `value` | 0 | (none) | `log_date`, `log_range`, `bulk_set` |
| `week` | 1 | 2 | `sprint_dashboard` |

### Enum Constraints

| Field | Allowed values | Actions |
|---|---|---|
| `unit` | `count`, `minutes`, `reps`, `pages` | `create_habit`, `update_habit` |
| `status` (list_sprints) | `active`, `archived` | `list_sprints` |
| `period` | `current_sprint`, `last_4_weeks`, `last_8_weeks` | `habit_report` |

### Business Rules

- **No overlapping active sprints.** Creating a sprint that overlaps with an existing active sprint is rejected.
- **Archived habits are read-only.** Cannot log entries to or update archived habits.
- **Idempotent entry logging.** `log_date` uses INSERT OR REPLACE on the `(habit_id, date)` primary key.
- **Upsert retros.** `add_retro` replaces the existing retro for a sprint if one exists (one retro per sprint).
- **Habit slug format.** Habit IDs must match `^[a-z]+(-[a-z]+)*$` (lowercase letters and hyphens only).
- **Sprint ID auto-generation.** Sprint IDs are auto-generated in `YYYY-S##` format based on the year and existing sprint count.
- **Global vs sprint-scoped habits.** When `sprint_id` is null, the habit is global and included in every sprint's queries. When set, the habit is scoped to that specific sprint.
- **Week boundaries.** All weekly calculations use fixed Mon-Sun weeks.

---

## Type Reference

| Type name | JSON type | Python type | Description |
|---|---|---|---|
| `str` | string | `str` | Text string |
| `int` | number (integer) | `int` | Integer (Python booleans are rejected) |
| `number` | number | `int` or `float` | Numeric value (Python booleans are rejected) |
| `iso_date` | string | `str` | Date in `YYYY-MM-DD` format (must be a valid calendar date) |
| `bool` | boolean | `bool` | Boolean true/false |
| `list` | array | `list` | JSON array (contents not type-checked) |
| `list_of_iso_dates` | array of strings | `list[str]` | JSON array where every element is a valid `YYYY-MM-DD` date |

---

## Natural Language Translation Examples

This section shows how an LLM should translate natural language user requests into JSON action objects. The LLM must determine the correct action, infer reasonable field values from context, and ask the user for any required fields it cannot confidently infer.

| User says | LLM emits |
|---|---|
| "Start a new 2-week sprint focused on fitness starting today" | `{"action": "create_sprint", "payload": {"id": "2026-S05", "start_date": "2026-03-01", "end_date": "2026-03-14", "theme": "Fitness Focus", "focus_goals": ["Improve fitness habits"]}}` |
| "How am I doing this week?" | `{"action": "get_week_view", "payload": {}}` |
| "I did my workout today" | `{"action": "log_date", "payload": {"habit_id": "workout-30min", "date": "2026-03-05", "value": 1}}` |
| "Show me the full dashboard" | `{"action": "sprint_dashboard", "payload": {}}` |
| "Add a new habit for reading, 5 days a week, high priority" | `{"action": "create_habit", "payload": {"id": "reading", "name": "Reading", "category": "cognitive", "target_per_week": 5, "weight": 3}}` |
| "I read every day this past week Mon through Fri" | `{"action": "log_range", "payload": {"habit_id": "reading", "start_date": "2026-03-02", "end_date": "2026-03-06", "value": 1}}` |
| "How's my reading habit going over the last month?" | `{"action": "habit_report", "payload": {"habit_id": "reading", "period": "last_4_weeks"}}` |
| "What was my score yesterday?" | `{"action": "daily_score", "payload": {"date": "2026-03-04"}}` |
| "Which categories am I doing best in?" | `{"action": "category_report", "payload": {}}` |
| "I want to write a retro for this sprint. Gym was great, journaling needs work, and I want to try morning pages next time." | `{"action": "add_retro", "payload": {"sprint_id": "2026-S05", "what_went_well": "Gym was great", "what_to_improve": "Journaling needs work", "ideas": "Try morning pages next time"}}` |

**Translation guidelines for LLMs:**

1. **Resolve "today", "yesterday", "this week"** — Convert relative dates to ISO dates based on the current date before emitting the action.
2. **Infer habit IDs from display names** — If the user says "reading", map it to the habit ID `reading`. If ambiguous, call `list_habits` first to confirm.
3. **Default to the active sprint** — When the user does not specify a sprint, omit `sprint_id` from the payload. The engine defaults to the active sprint.
4. **Ask when unsure** — If a required field cannot be confidently inferred (e.g., the user says "add a habit" but does not specify a category or target), ask the user rather than guessing.
5. **Multi-habit requests require multiple actions** — If the user says "log reading and gym for today", emit two separate `log_date` actions, one per habit.
