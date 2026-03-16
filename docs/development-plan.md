# Development Plan: Habit Sprint

> **Generated from:** docs/prd.md
> **Created:** 2026-03-01
> **Last synced:** 2026-03-15T01:25Z
> **Status:** Active Planning Document
> **VibeKanban Project ID:** 9c59dcf5-0dc3-4305-855b-9b9432dd88c2

## Overview

Habit Sprint is a deterministic, JSON-native sprint-based habit tracking engine designed for LLM-first workflows. It provides CRUD operations for habits and sprints via a strict JSON contract, weighted scoring and analytics via a read-only reporting layer, and a thin CLI adapter — all backed by SQLite with zero external infrastructure.

## Tech Stack

- **Backend:** Python 3.12+
- **Frontend:** Lightweight web UI (htmx + Jinja2 templates)
- **Database:** SQLite (stdlib sqlite3 module)
- **Testing:** pytest
- **Packaging:** pyproject.toml with venv
- **Infrastructure:** Local-only, single-user

## PRD Clarifications (from review)

| Decision | Detail |
|----------|--------|
| `update_sprint` action | Added to spec |
| Habit lifecycle | Habits carry forward across sprints; global habits always carry forward |
| Sprint ID format | Auto-generated `"YYYY-S##"` from start date |
| Week boundaries | Fixed Mon–Sun for all views |
| `trend_vs_last_sprint` no prior data | Returns `null` |
| Avoidance habits | `value=1` means success, no type field for v1 |
| `balance_assessment.spread` | Max minus min of category scores |
| Database migrations | Simple migration system with schema version table |
| Dependencies | Pure stdlib + sqlite3; external only if truly needed |

---

## Completion Status Summary

| Epic | Status | Progress |
|------|--------|----------|
| 1. Project Foundation & Schema | Done | 100% |
| 2. Core Engine & Executor | Done | 100% |
| 3. Reporting Engine | Done | 100% |
| 4. CLI Adapter | Done | 100% |
| 5. LLM Skill Layer | Done | 100% |
| 6. Web UI | Done | 100% |
| 7. Web UI Polish & Sprint Habit Management | Done | 100% |
| 8. Habit Consolidation & Per-Sprint Goals | Done | 100% |
| 9. Reports & Analytics | Not Started | 0% |

---

## Epic 1: Project Foundation & Schema (DONE)

Set up the project structure, SQLite schema, migration system, and database connection management. This epic is the foundation everything else builds on.

### Acceptance Criteria

- [ ] Project installs cleanly with `pip install -e .` in a fresh venv
- [ ] SQLite database is created with all tables and indexes on first run
- [ ] Migration system tracks schema version and can apply incremental migrations
- [ ] pytest runs and discovers tests

### Tasks

| ID | Title | Description | Priority | Complexity | Depends On | Status |
|----|-------|-------------|----------|------------|------------|--------|
| 1.1 | Project scaffolding | Create pyproject.toml, directory structure (habit_sprint/, tests/), venv setup, pytest config | High | S | — | <!-- vk:ERI-6 --> |
| 1.2 | SQLite schema | Create schema.sql with sprints, habits, entries, retros tables and all indexes per PRD Section 5 | High | S | 1.1 | <!-- vk:ERI-7 --> |
| 1.3 | Migration system | Create db.py with connection management, schema version table, migration runner that applies .sql files in order | High | M | 1.1 | <!-- vk:ERI-8 --> |
| 1.4 | Database initialization | Wire schema.sql as migration v1, ensure DB is auto-created with WAL mode and foreign keys enabled on first use | High | S | 1.2, 1.3 | <!-- vk:ERI-9 --> |

### Task Details

**1.1 - Project scaffolding**
- [ ] `pyproject.toml` defines project metadata, Python 3.12+ requirement, pytest config, and `habit-sprint` CLI entry point
- [ ] Directory structure: `habit_sprint/` (package), `tests/`, `docs/`, `migrations/`
- [ ] `habit_sprint/__init__.py` exists with version string
- [ ] `pytest` discovers and runs an empty test file successfully

**1.2 - SQLite schema**
- [ ] `migrations/001_initial_schema.sql` contains CREATE TABLE statements for sprints, habits, entries, retros
- [ ] All indexes from PRD Section 5.1 are included
- [ ] Schema matches PRD exactly (column names, types, constraints, foreign keys)

**1.3 - Migration system**
- [ ] `habit_sprint/db.py` provides `get_connection(db_path)` that returns a configured sqlite3 connection
- [ ] Connection has WAL mode, foreign keys enabled, and row_factory set to sqlite3.Row
- [ ] `schema_version` table tracks applied migration versions
- [ ] `migrate(conn)` applies all pending `.sql` files from `migrations/` directory in sorted order
- [ ] Already-applied migrations are skipped (idempotent)

**1.4 - Database initialization**
- [ ] Calling `get_connection()` on a non-existent DB file creates it and runs all migrations
- [ ] After initialization, all 4 tables exist with correct schemas
- [ ] `schema_version` table shows version 1 applied
- [ ] Tests verify table creation and migration idempotency

---

## Epic 2: Core Engine & Executor (DONE)

Implement the domain logic (engine.py) for all CRUD operations and the JSON contract boundary (executor.py) that routes, validates, and wraps all actions. This is the heart of the system.

### Acceptance Criteria

- [ ] All 16 mutation/query actions route through executor.execute() and return correct envelope responses
- [ ] Sprint IDs are auto-generated in "YYYY-S##" format
- [ ] Habits carry forward across sprints (no re-creation needed)
- [ ] All validation rules from PRD Section 11 are enforced with clear error messages
- [ ] All operations are idempotent where specified (entries, retros)
- [ ] 100% of engine functions have passing unit tests

### Tasks

| ID | Title | Description | Priority | Complexity | Depends On | Status |
|----|-------|-------------|----------|------------|------------|--------|
| 2.1 | Executor framework | Create executor.py with execute() entry point, action routing, envelope wrapping, and unknown action rejection | High | M | 1.4 | <!-- vk:ERI-10 --> |
| 2.2 | Payload validation | Add schema-based payload validation to executor: required fields, type checking, unknown field rejection | High | M | 2.1 | <!-- vk:ERI-11 --> |
| 2.3 | Sprint management | Implement create_sprint (with auto-ID), update_sprint, list_sprints, archive_sprint, get_active_sprint in engine.py | High | L | 2.1 | <!-- vk:ERI-12 --> |
| 2.4 | Habit management | Implement create_habit, update_habit, archive_habit, list_habits in engine.py with sprint carry-forward logic | High | L | 2.3 | <!-- vk:ERI-13 --> |
| 2.5 | Entry management | Implement log_date, log_range, bulk_set, delete_entry in engine.py with idempotent upsert behavior | High | M | 2.4 | <!-- vk:ERI-14 --> |
| 2.6 | Retrospectives | Implement add_retro (upsert) and get_retro in engine.py | Medium | S | 2.3 | <!-- vk:ERI-15 --> |
| 2.7 | Error handling | Ensure all validation rules from PRD Section 11 produce clear error messages (overlap prevention, archived habits, date format, ranges) | High | M | 2.3, 2.4, 2.5 | <!-- vk:ERI-16 --> |
| 2.8 | Core engine tests | Comprehensive pytest suite for all engine + executor operations, happy paths and error cases | High | L | 2.3, 2.4, 2.5, 2.6, 2.7 | <!-- vk:ERI-17 --> |

### Task Details

**2.1 - Executor framework**
- [ ] `executor.py` exposes `execute(action_json: dict, db_path: str) -> dict`
- [ ] Routes actions to engine.py (mutations) or reporting.py (queries) based on action name
- [ ] Returns `{"status": "success", "data": {...}, "error": null}` for success
- [ ] Returns `{"status": "error", "data": null, "error": "message"}` for errors
- [ ] Rejects unknown actions with `"Unknown action: 'foo'"`

**2.2 - Payload validation**
- [ ] Each action has a defined schema of allowed fields with types
- [ ] Missing required fields return `"Missing required field: 'name'"`
- [ ] Unknown/extra fields return `"Unknown field 'bar' in payload for action 'create_habit'"`
- [ ] Type validation (ISO dates, integers, allowed enum values) with clear messages

**2.3 - Sprint management**
- [ ] `create_sprint` auto-generates ID in "YYYY-S##" format (sequential per year based on existing sprints)
- [ ] `create_sprint` prevents overlapping active sprints with clear error message
- [ ] `create_sprint` validates end_date > start_date, valid ISO dates
- [ ] `update_sprint` allows updating theme and focus_goals on existing sprints
- [ ] `list_sprints` supports optional status filter ("active", "archived", or all)
- [ ] `archive_sprint` sets status to "archived"
- [ ] `get_active_sprint` returns the active sprint or error if none

**2.4 - Habit management**
- [ ] `create_habit` validates slug format, target_per_week (1-7), weight (1-3), unit enum
- [ ] `update_habit` only updates provided fields, rejects updates to archived habits
- [ ] `archive_habit` sets archived=1; archived habits reject new entries
- [ ] `list_habits` supports filters: sprint_id, category, include_archived
- [ ] Global habits (no sprint_id) are always returned regardless of sprint filter
- [ ] Habits carry forward — no re-creation needed between sprints

**2.5 - Entry management**
- [ ] `log_date` performs idempotent upsert (INSERT OR REPLACE), returns created=true/false
- [ ] `log_range` creates entries for each date in [start, end] inclusive
- [ ] `bulk_set` creates entries for specific non-contiguous dates
- [ ] `delete_entry` removes a single entry, returns deleted=true/false
- [ ] All entry operations validate habit exists and is not archived
- [ ] All dates validated as ISO 8601 format

**2.6 - Retrospectives**
- [ ] `add_retro` performs upsert (one retro per sprint)
- [ ] `add_retro` validates sprint exists
- [ ] `get_retro` returns retro data or clear message if none exists
- [ ] All three text fields (what_went_well, what_to_improve, ideas) are optional

**2.7 - Error handling**
- [ ] Every validation rule from PRD Section 11 has a corresponding test
- [ ] Error messages are human-readable and specific (include the invalid value)
- [ ] Overlapping sprint detection works correctly with date range comparison
- [ ] Invalid ISO dates, out-of-range integers, and invalid enums all caught

**2.8 - Core engine tests**
- [ ] Each action has at least one happy-path test and one error-path test
- [ ] Idempotent operations tested (log_date twice, add_retro twice)
- [ ] Sprint overlap detection tested with various edge cases
- [ ] Habit carry-forward behavior verified across sprint boundaries
- [ ] Tests use in-memory SQLite (`:memory:`) for speed

---

## Epic 3: Reporting Engine (DONE)

Implement all read-only analytics in reporting.py: weekly completion, streaks, daily scores, weighted sprint scoring, category rollups, trend analysis, and the composite sprint dashboard view.

### Acceptance Criteria

- [ ] All 7 reporting actions return correct, deterministic results
- [ ] Weighted sprint score formula matches PRD: Σ(actual × weight) / Σ(target × weight)
- [ ] Sprint dashboard combines all data into a single response matching PRD Section 7.6
- [ ] All metrics computed in reporting layer only — never in engine or executor
- [ ] Reporting functions are strictly read-only (no mutations)

### Tasks

| ID | Title | Description | Priority | Complexity | Depends On | Status |
|----|-------|-------------|----------|------------|------------|--------|
| 3.1 | Weekly completion & streaks | Implement weekly completion % (actual/target) and streak calculation (current + longest) | High | M | 2.5 | <!-- vk:ERI-18 --> |
| 3.2 | Daily score | Implement daily_score action: Σ(value × weight) / Σ(weight) with completed/missed habit lists | High | M | 2.5 | <!-- vk:ERI-19 --> |
| 3.3 | Week view | Implement get_week_view with fixed Mon–Sun grid, per-habit daily values, week_actual, completion_pct, commitment_met | High | M | 3.1 | <!-- vk:ERI-20 --> |
| 3.4 | Sprint report | Implement sprint_report with weighted/unweighted scores, category breakdown, per-habit stats, weekly breakdown, trend_vs_last_sprint | High | L | 3.1, 3.2 | <!-- vk:ERI-21 --> |
| 3.5 | Habit report | Implement habit_report with period support (current_sprint, last_4_weeks, last_8_weeks), weekly history, rolling 7-day avg, trend | Medium | M | 3.1 | <!-- vk:ERI-22 --> |
| 3.6 | Category report | Implement category_report with per-category weighted/unweighted scores, balance_assessment (most/least adherent, spread=max-min) | Medium | M | 3.4 | <!-- vk:ERI-23 --> |
| 3.7 | Sprint dashboard | Implement sprint_dashboard composite view: categories with habits, daily totals, sprint summary, retro — per PRD Section 7.6 | High | L | 3.3, 3.4 | <!-- vk:ERI-24 --> |
| 3.8 | Reporting tests | Comprehensive pytest suite for all reporting actions with known test data and verified expected outputs | High | L | 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7 | <!-- vk:ERI-25 --> |

### Task Details

**3.1 - Weekly completion & streaks**
- [ ] `completion_pct = (actual_days / target_per_week) × 100`, capped display at whole integers
- [ ] `commitment_met = actual_days >= target_per_week`
- [ ] Current streak: consecutive days ending today or yesterday with value > 0
- [ ] Longest streak: maximum consecutive days with value > 0 across all time
- [ ] Handles edge case of no entries (streak = 0, completion = 0%)

**3.2 - Daily score**
- [ ] Formula: `Σ(value × weight)` for completed habits / `Σ(weight)` for all active habits
- [ ] Returns total_points, max_possible, completion_pct, habits_completed list, habits_missed list
- [ ] Handles days with no entries (score = 0)
- [ ] Only counts non-archived habits active during that date's sprint

**3.3 - Week view**
- [ ] Returns fixed Mon–Sun grid regardless of sprint start day
- [ ] `week_start` defaults to current week's Monday when omitted
- [ ] Per-habit: daily values map, week_actual, week_completion_pct, commitment_met
- [ ] Groups habits by category in response
- [ ] Days outside sprint range return 0 values

**3.4 - Sprint report**
- [ ] Weighted score: `Σ(actual_entries × weight) / Σ(target_entries × weight)`
- [ ] Unweighted score: `Σ(actual_entries) / Σ(target_entries)`
- [ ] Category breakdown with per-category weighted scores
- [ ] Per-habit: total_entries, expected_entries, completion_pct, current_streak, longest_streak, weekly_breakdown
- [ ] `trend_vs_last_sprint` returns `null` when no prior sprint data exists
- [ ] days_elapsed and days_remaining computed from current date vs sprint dates

**3.5 - Habit report**
- [ ] Supports periods: "current_sprint", "last_4_weeks", "last_8_weeks", or specific sprint_id
- [ ] weekly_history array with per-week actual/target/completion_pct
- [ ] rolling_7_day_avg computed correctly
- [ ] trend_vs_prior_period shows delta as percentage string

**3.6 - Category report**
- [ ] Per-category: habits_count, weighted_score, unweighted_score, habit ID list
- [ ] balance_assessment.most_adherent and least_adherent by weighted_score
- [ ] balance_assessment.spread = max(weighted_scores) - min(weighted_scores)
- [ ] Handles categories with a single habit correctly

**3.7 - Sprint dashboard**
- [ ] Combines: sprint metadata, categories with habits (daily values), daily_totals, sprint_summary, retro
- [ ] Supports optional `week` parameter (1 or 2) for single-week view
- [ ] Defaults to active sprint when sprint_id omitted
- [ ] Daily totals compute points/max/pct per day across all habits
- [ ] Response structure exactly matches PRD Section 7.6

**3.8 - Reporting tests**
- [ ] Test fixtures with known sprint/habit/entry data for deterministic verification
- [ ] Weighted score calculation verified against hand-computed expected values
- [ ] Streak edge cases: gaps, start of data, today vs yesterday
- [ ] Sprint dashboard tested against full expected response structure
- [ ] Empty data edge cases (no entries, no habits, no sprints)

---

## Epic 4: CLI Adapter (DONE)

Implement the thin CLI adapter that reads JSON, calls the executor, and outputs JSON or formatted markdown. The CLI is a pure I/O adapter with zero business logic.

### Acceptance Criteria

- [ ] `echo '{"action":"list_habits","payload":{}}' | habit-sprint` returns valid JSON
- [ ] `habit-sprint --json '{...}'` works as alternative input method
- [ ] `--format markdown` renders sprint_dashboard in the canonical ASCII format from PRD Section 9.2
- [ ] `--db /path/to/file.db` overrides default database location
- [ ] CLI exits with code 0 on success, non-zero on error

### Tasks

| ID | Title | Description | Priority | Complexity | Depends On | Status |
|----|-------|-------------|----------|------------|------------|--------|
| 4.1 | CLI JSON mode | Implement cli.py with stdin pipe and --json flag input, JSON output to stdout, --db flag | High | M | 2.1 | <!-- vk:ERI-26 --> |
| 4.2 | Sprint dashboard markdown | Implement --format markdown rendering for sprint_dashboard matching PRD Section 9.2 ASCII format exactly | High | L | 3.7 | <!-- vk:ERI-27 --> |
| 4.3 | Other markdown renderers | Implement markdown rendering for get_week_view, sprint_report, habit_report, daily_score, category_report | Medium | M | 3.3, 3.4, 3.5, 3.6 | <!-- vk:ERI-28 --> |
| 4.4 | CLI tests | Integration tests for CLI: JSON mode, markdown mode, error handling, --db flag | Medium | M | 4.1, 4.2, 4.3 | <!-- vk:ERI-29 --> |

### Task Details

**4.1 - CLI JSON mode**
- [ ] Reads JSON from stdin when piped, or from --json flag argument
- [ ] Calls `executor.execute()` and prints JSON result to stdout
- [ ] `--db` flag overrides default database path (default: `~/.habit-sprint/habits.db`)
- [ ] Entry point registered in pyproject.toml as `habit-sprint` console script
- [ ] Exit code 0 for success, 1 for errors

**4.2 - Sprint dashboard markdown**
- [ ] Output matches PRD Section 9.2 format exactly (header, categories, daily points, totals, summary, reflection)
- [ ] `✓` for value > 0, `·` for 0/no entry
- [ ] `★` appended when commitment_met = true
- [ ] Daily Points per category = sum of (value × weight) per habit
- [ ] Column alignment is correct for variable-length habit names

**4.3 - Other markdown renderers**
- [ ] `get_week_view` renders category-grouped week grid (subset of dashboard, no summary/retro)
- [ ] `sprint_report` renders sprint summary with per-habit breakdown
- [ ] `habit_report` renders weekly history as a small table
- [ ] `daily_score` renders completed/missed habits with points
- [ ] `category_report` renders category scores with balance info

**4.4 - CLI tests**
- [ ] Test JSON stdin pipe with valid and invalid input
- [ ] Test --json flag with valid and invalid input
- [ ] Test --format markdown produces expected output for sprint_dashboard
- [ ] Test --db flag creates database at specified path
- [ ] Test error output format (JSON envelope with error)

---

## Epic 5: LLM Skill Layer (DONE)

Create the SKILLS.md file that constrains LLM behavior when interacting with the habit-sprint engine. This is the bridge between natural language and the JSON contract.

### Acceptance Criteria

- [ ] SKILLS.md defines all allowed actions with exact payload schemas
- [ ] Every action has at least one concrete request/response example
- [ ] Constraints explicitly forbid LLM metric computation
- [ ] Document is self-contained — an LLM can use it without reading source code

### Tasks

| ID | Title | Description | Priority | Complexity | Depends On | Status |
|----|-------|-------------|----------|------------|------------|--------|
| 5.1 | SKILLS.md action schemas | Document all action schemas with required/optional fields, types, and validation rules | Medium | M | 2.7 | <!-- vk:ERI-30 --> |
| 5.2 | SKILLS.md examples & constraints | Add concrete examples for each action and explicit LLM constraint rules (no metric computation, no field invention, single-action enforcement) | Medium | M | 5.1 | <!-- vk:ERI-31 --> |

### Task Details

**5.1 - SKILLS.md action schemas**
- [ ] Every action listed with full payload schema (field names, types, required/optional, allowed values)
- [ ] Response envelope format documented
- [ ] Error response format documented with example error messages
- [ ] Action routing table (which actions are mutations vs queries)

**5.2 - SKILLS.md examples & constraints**
- [ ] At least one request/response example per action
- [ ] Natural language → JSON translation examples (user says X, LLM emits Y)
- [ ] Explicit constraint: "Never compute streaks, scores, or trends — only interpret engine results"
- [ ] Explicit constraint: "Never invent fields not in the schema"
- [ ] Explicit constraint: "Do not modify multiple habits in a single action unless the user explicitly requests it"

---

## Epic 6: Web UI (DONE)

Add a lightweight web interface for quick visual check-ins and dashboard viewing. The web UI is a thin adapter (peer to cli.py) that calls the same executor — no business logic in the web layer.

**Motivation:** The LLM interface works well for complex queries and natural language, but a visual grid with checkboxes is faster for daily habit logging and at-a-glance sprint progress.

**Architecture:**

```
cli.py  ─┐
          ├──► executor.py ──► engine.py / reporting.py ──► SQLite
web.py  ─┘
```

### Acceptance Criteria

- [ ] `habit-sprint --web` or `habit-sprint-web` starts a local server on a configurable port
- [ ] Dashboard page renders the current sprint grid with clickable checkboxes
- [ ] Clicking a checkbox toggles a habit entry for that date via `log_date` / `delete_entry`
- [ ] All data flows through `executor.execute()` — no direct SQL or bypassing the engine
- [ ] Works alongside CLI and LLM usage on the same database (SQLite WAL)
- [ ] No JavaScript build toolchain required (htmx + vanilla CSS)

### Tasks

| ID | Title | Description | Priority | Complexity | Depends On | Status |
|----|-------|-------------|----------|------------|------------|--------|
| 6.1 | FastAPI app scaffold | Create `habit_sprint/web.py` with FastAPI app, database lifecycle, and static file / template setup | High | M | 4.1 | <!-- vk:ERI-33 --> |
| 6.2 | API endpoints | Expose core actions as REST endpoints: GET /api/dashboard, POST /api/log, DELETE /api/log, GET /api/habits, GET /api/sprints | High | M | 6.1 | <!-- vk:ERI-34 --> |
| 6.3 | Dashboard page | Jinja2 template rendering the sprint grid (habits × dates) with checkboxes, category grouping, and daily totals | High | L | 6.2 | <!-- vk:ERI-35 --> |
| 6.4 | Checkbox toggle interaction | htmx-powered checkbox click that POSTs/DELETEs entries and updates the grid without full page reload | High | M | 6.3 | <!-- vk:ERI-36 --> |
| 6.5 | Habit management page | Simple CRUD page for creating, editing, and archiving habits | Medium | M | 6.2 | <!-- vk:ERI-37 --> |
| 6.6 | Sprint management page | View/create/archive sprints, view retros | Medium | M | 6.2 | <!-- vk:ERI-38 --> |
| 6.7 | Styling and layout | Responsive CSS for the dashboard grid, navigation, and forms — clean and minimal, no framework required | Medium | M | 6.3 | <!-- vk:ERI-39 --> |
| 6.8 | CLI integration | Add `--web` flag to CLI or separate `habit-sprint-web` entry point to start the server with configurable host/port | Medium | S | 6.1 | <!-- vk:ERI-40 --> |
| 6.9 | Web UI tests | pytest suite for API endpoints and template rendering, using TestClient | Medium | M | 6.2, 6.3, 6.4 | <!-- vk:ERI-41 --> |

### Task Details

**6.1 - FastAPI app scaffold**
- [x] `habit_sprint/web.py` creates a FastAPI application
- [x] Database connection managed via app lifespan (same `db.get_connection()`)
- [x] Jinja2 template directory at `habit_sprint/templates/`
- [x] Static files served from `habit_sprint/static/`
- [x] Add `fastapi` and `uvicorn` as optional dependencies in pyproject.toml (`[project.optional-dependencies] web = [...]`)

**6.2 - API endpoints**
- [x] `GET /api/dashboard?sprint_id=` → calls `sprint_dashboard`, returns JSON
- [x] `POST /api/log` (body: `{habit_id, date, value}`) → calls `log_date`
- [x] `DELETE /api/log` (body: `{habit_id, date}`) → calls `delete_entry`
- [x] `GET /api/habits?include_archived=false` → calls `list_habits`
- [x] `GET /api/sprints?status=active` → calls `list_sprints`
- [x] `GET /api/sprint/active` → calls `get_active_sprint`
- [x] All endpoints call `executor.execute()` and return the standard envelope
- [x] Error responses use appropriate HTTP status codes

**6.3 - Dashboard page**
- [x] `GET /` renders the dashboard for the active sprint
- [x] Grid layout: rows = habits (grouped by category), columns = dates in sprint
- [x] Each cell shows a checkbox (checked if entry exists with value > 0)
- [x] Category headers separate habit groups
- [x] Daily totals row at the bottom (points / max)
- [x] Sprint summary sidebar or header (weighted score, days elapsed/remaining)
- [x] Week 1 / Week 2 tab or toggle

**6.4 - Checkbox toggle interaction**
- [x] Checkbox uses `hx-post="/toggle/{habit_id}/{date}"` to toggle state (checks current and POSTs or DELETEs)
- [x] Server returns updated cell HTML fragment (htmx swap)
- [x] Daily totals row updates after toggle (via hx-swap-oob)
- [x] Visual feedback on toggle (brief highlight/transition on cell background)
- [x] Handles errors gracefully (shows toast via HX-Trigger header)

**6.5 - Habit management page**
- [x] `GET /habits` renders list of all habits with edit/archive actions
- [x] `GET /habits/new` renders create form (name, slug, category, target, weight, unit)
- [x] `POST /habits` creates a habit via `create_habit`
- [x] `POST /habits/{id}/edit` updates a habit via `update_habit`
- [x] `POST /habits/{id}/archive` archives via `archive_habit`
- [x] Form validation mirrors engine validation rules

**6.6 - Sprint management page**
- [x] `GET /sprints` renders list of all sprints with status badges
- [x] `GET /sprints/new` renders create form (start_date, end_date, theme, focus_goals)
- [x] `POST /sprints` creates a sprint via `create_sprint`
- [x] `POST /sprints/{id}/archive` archives via `archive_sprint`
- [x] Sprint detail view shows retro if one exists

**6.7 - Styling and layout**
- [x] `habit_sprint/static/style.css` with clean, minimal design
- [x] Responsive grid that works on desktop and tablet
- [x] Navigation: Dashboard | Habits | Sprints
- [x] Grid cells sized for easy click/tap targets
- [x] Color-coded categories (subtle background tints)
- [x] Dark/light mode support via `prefers-color-scheme`

**6.8 - CLI integration**
- [x] `habit-sprint --web` starts uvicorn on `127.0.0.1:8000` (configurable via `--host` and `--port`)
- [x] Or: separate entry point `habit-sprint-web` registered in pyproject.toml
- [x] Uses the same `--db` flag for database path
- [x] Prints startup message with URL to open

**6.9 - Web UI tests**
- [x] Use FastAPI `TestClient` for endpoint testing
- [x] Test dashboard renders with known sprint/habit data
- [x] Test log/delete toggle cycle returns correct state
- [x] Test habit CRUD through web endpoints
- [x] Test error cases (invalid habit, no active sprint)
- [x] Test concurrent access (CLI + web on same DB)

---

## Epic 7: Web UI Polish & Sprint Habit Management (DONE)

Polish the web UI with improved visual design and add missing sprint-habit management features: habit weight/sprint scope in forms, sprint editing, retrospective editing, and a sprint habits management page for adding/removing habits from sprints.

**Motivation:** The web UI is functional but visually basic. Key engine features (sprint-scoped habits, habit weights, sprint editing, retro editing) are not yet exposed in the UI.

### Acceptance Criteria

- [ ] UI has polished visual design with better typography, card layouts, progress indicators, and smooth transitions
- [ ] Habit form includes weight (1-3) selector and sprint scope (global vs current sprint) field
- [x] Sprint detail page allows editing theme and focus goals
- [ ] Sprint detail page allows creating/editing retrospectives
- [x] Dedicated sprint habits page shows which habits are in a sprint and allows adding/removing them
- [ ] Dashboard shows visual progress indicators (completion bars)
- [x] All new features have passing tests

### Tasks

| ID | Title | Description | Priority | Complexity | Depends On | Status |
|----|-------|-------------|----------|------------|------------|--------|
| 7.1 | UI visual polish | Improve CSS: better typography, card-based list layouts, progress bars in dashboard, subtle hover/transition effects, improved form styling | High | M | 6.7 | <!-- vk:ERI-43 --> |
| 7.2 | Habit sprint scope field | Add sprint_id field to habit create/edit form (global vs current sprint dropdown), update web.py handlers to pass sprint_id to executor | High | M | 6.5 | <!-- vk:ERI-44 --> |
| 7.3 | Sprint edit page | Add GET/POST /sprints/{id}/edit endpoints and template for editing sprint theme and focus_goals via update_sprint | Medium | S | 6.6 | <!-- vk:ERI-45 --> |
| 7.4 | Sprint retro editing | Add retro form to sprint detail page, POST /sprints/{id}/retro endpoint that calls add_retro executor action | Medium | M | 6.6 | <!-- vk:ERI-46 --> |
| 7.5 | Sprint habits management page | Dedicated page at /sprints/{id}/habits showing habits in sprint + global habits, with add/remove actions (update_habit sprint_id) | High | L | 7.2 | <!-- vk:ERI-47 --> |
| 7.6 | Dashboard progress indicators | Add visual completion bars per habit and per category in the dashboard grid, streak indicators, and overall sprint progress bar in header | Medium | M | 7.1 | <!-- vk:ERI-48 --> |
| 7.7 | Epic 7 tests | Tests for all new endpoints: sprint edit, retro edit, habit sprint scope, sprint habits management, progress bar rendering | Medium | M | 7.2, 7.3, 7.4, 7.5, 7.6 | <!-- vk:ERI-49 --> |

### Task Details

**7.1 - UI visual polish**
- [x] Improve base typography: better font sizing hierarchy, line heights, letter spacing
- [x] Card-based layouts for habits list and sprints list (replace plain tables with styled cards or enhanced table rows)
- [x] Improved form styling: better input focus states, field grouping, helper text
- [x] Add subtle hover effects on table rows and cards
- [x] Smooth transitions on checkbox toggle, note popover open/close
- [x] Better mobile responsive layout with collapsible navigation
- [x] Progress bar CSS component (reusable for dashboard and sprint detail)

**7.2 - Habit sprint scope field**
- [x] Add "Sprint Scope" dropdown to habit form: "Global (all sprints)" or current active sprint name
- [x] When creating habit, pass `sprint_id` to executor if sprint-scoped is selected
- [x] When editing habit, show current sprint scope and allow changing it
- [x] Habits list page shows sprint scope column (Global or sprint ID)
- [x] Form pre-fills sprint scope correctly when editing

**7.3 - Sprint edit page**
- [x] `GET /sprints/{id}/edit` renders edit form pre-filled with current theme and focus_goals
- [x] `POST /sprints/{id}/edit` calls `update_sprint` executor action
- [x] Sprint detail page has "Edit" button linking to edit form
- [x] Sprints list page has "Edit" action for active sprints
- [x] Handles validation errors (preserves form values on error)

**7.4 - Sprint retro editing**
- [x] Sprint detail page shows retro form (inline or separate page) with what_went_well, what_to_improve, ideas textareas
- [x] `POST /sprints/{id}/retro` calls `add_retro` executor action (upsert behavior)
- [x] Pre-fills form with existing retro data when editing
- [x] Success message shown after saving retro
- [x] Only allows retro editing for active sprints (or make configurable)

**7.5 - Sprint habits management page**
- [x] `GET /sprints/{id}/habits` shows two sections: "Sprint Habits" and "Available Global Habits"
- [x] Sprint habits section lists habits with sprint_id matching this sprint, with "Remove from Sprint" action
- [x] Available habits section lists global habits (sprint_id IS NULL) with "Add to Sprint" action
- [x] "Add to Sprint" calls update_habit to set sprint_id; "Remove" sets sprint_id to null
- [x] Shows habit weight, target_per_week, and category for each habit
- [x] Sprint detail page links to this management page

**7.6 - Dashboard progress indicators**
- [x] Per-habit row shows a thin completion bar (actual/target) in the "Done" column
- [x] Category row shows category weighted score as a progress bar
- [x] Sprint header shows overall weighted score as a prominent progress bar
- [x] Color coding: green for on-track (>=80%), yellow for warning (50-79%), red for behind (<50%)
- [x] Progress bars are CSS-only (no JS), using inline width styles

**7.7 - Epic 7 tests**
- [x] Test sprint edit form renders with pre-filled values
- [x] Test sprint edit POST updates theme and focus_goals
- [x] Test retro form renders (empty and pre-filled)
- [x] Test retro POST creates/updates retro data
- [x] Test habit form includes sprint scope field
- [x] Test habit create with sprint_id sets sprint scope correctly
- [x] Test sprint habits page lists correct habits per section
- [x] Test add/remove habit from sprint via management page
- [x] Test dashboard progress bars render with correct percentages

---

## Epic 8: Habit Consolidation & Per-Sprint Goals (DONE)

Consolidate duplicate historical habit records (159 rows to ~33 unique habits) and add a `sprint_habit_goals` junction table to preserve per-sprint `target_per_week` and `weight` values. This ensures historical reporting remains accurate even when a habit's current defaults change.

**Motivation:** Historical habits were imported as separate records per sprint (e.g., 14 "Cardio" habits with different IDs). This creates clutter and fragile reporting. A junction table decouples habit identity from sprint-specific goals.

**Schema change:**

```sql
CREATE TABLE sprint_habit_goals (
    sprint_id TEXT NOT NULL REFERENCES sprints(id),
    habit_id  TEXT NOT NULL REFERENCES habits(id),
    target_per_week INTEGER NOT NULL,
    weight    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (sprint_id, habit_id)
);
```

### Acceptance Criteria

- [x] `sprint_habit_goals` table exists with correct schema and foreign keys
- [ ] Engine supports CRUD for per-sprint habit goals (set/get/delete)
- [ ] All 7 reporting functions use sprint-specific targets when available, falling back to habit defaults
- [ ] Historical habits are consolidated: ~33 unique habits instead of 159, all entries reassigned
- [ ] Per-sprint targets preserved in `sprint_habit_goals` for every historical sprint
- [ ] Web UI allows editing per-sprint targets on the sprint habits management page
- [ ] All new and existing tests pass

### Tasks

| ID | Title | Description | Priority | Complexity | Depends On | Status |
|----|-------|-------------|----------|------------|------------|--------|
| 8.1 | Schema migration: sprint_habit_goals table | Create migration 002 adding sprint_habit_goals junction table with (sprint_id, habit_id, target_per_week, weight) PK | High | S | 1.3 | <!-- vk:ERI-52 --> |
| 8.2 | Engine: sprint_habit_goals CRUD | Add set_sprint_habit_goal (upsert), get_sprint_habit_goal, delete_sprint_habit_goal to engine + executor + validation | High | M | 8.1 | <!-- vk:ERI-53 --> |
| 8.3 | Reporting: use sprint_habit_goals for targets | Update all 7 reporting functions to check sprint_habit_goals first, fall back to habit defaults | High | L | 8.1 | <!-- vk:ERI-54 --> |
| 8.4 | Data migration: consolidate historical habits | Script to deduplicate habits, reassign entries, populate sprint_habit_goals, remove duplicates. Must be idempotent with backup. | High | L | 8.1, 8.2 | <!-- vk:ERI-55 --> |
| 8.5 | Web UI: per-sprint goal editing | Update sprint habits management page to show/edit per-sprint target_per_week and weight | Medium | M | 8.2, 8.3 | <!-- vk:ERI-56 --> |
| 8.6 | Epic 8 tests | Tests for sprint_habit_goals CRUD, reporting with overrides vs defaults, data migration correctness, web UI goal editing, backward compatibility | Medium | L | 8.2, 8.3, 8.4, 8.5 | <!-- vk:ERI-57 --> |

### Task Details

**8.1 - Schema migration: sprint_habit_goals table**
- [x] Create `migrations/002_sprint_habit_goals.sql` with CREATE TABLE statement
- [x] Table has composite PK (sprint_id, habit_id), FKs to sprints and habits
- [x] Columns: sprint_id, habit_id, target_per_week (INT NOT NULL), weight (INT NOT NULL DEFAULT 1)
- [x] Migration system applies it automatically on next `get_connection()`
- [x] Existing data and schema untouched (additive migration only)

**8.2 - Engine: sprint_habit_goals CRUD**
- [x] `set_sprint_habit_goal(conn, payload)` — upsert: INSERT OR REPLACE into sprint_habit_goals
- [x] `get_sprint_habit_goal(conn, payload)` — returns goal for (sprint_id, habit_id) or null
- [x] `delete_sprint_habit_goal(conn, payload)` — removes override, habit reverts to its defaults
- [x] Wire all three through executor.py and validation.py
- [x] When adding a habit to a sprint (update_habit with sprint_id), auto-create a sprint_habit_goals row

**8.3 - Reporting: use sprint_habit_goals for targets**
- [x] Create helper `_get_effective_target(conn, sprint_id, habit)` that checks sprint_habit_goals first
- [x] Update `weekly_completion` to use effective target
- [x] Update `daily_score` to use effective weight
- [x] Update `get_week_view` to use effective target and weight
- [x] Update `sprint_report` to use effective target and weight
- [x] Update `habit_report` to use effective target
- [x] Update `category_report` to use effective weight
- [x] Update `sprint_dashboard` to use effective target and weight
- [x] Habits without sprint_habit_goals rows fall back to habit.target_per_week and habit.weight

**8.4 - Data migration: consolidate historical habits**
- [x] Create backup of database before migration
- [x] Group habits by canonical name (strip `-hist-*` suffix patterns)
- [x] For each group, choose canonical ID (prefer shortest ID or non-hist ID if exists)
- [x] Insert sprint_habit_goals rows for each duplicate's (sprint_id, target_per_week, weight)
- [x] UPDATE entries SET habit_id = canonical_id WHERE habit_id = duplicate_id
- [x] DELETE duplicate habit records
- [x] SET sprint_id = NULL on canonical habits (make them global)
- [x] Verify entry counts match before and after migration
- [x] Script is idempotent (safe to run multiple times)

**8.5 - Web UI: per-sprint goal editing**
- [x] Sprint habits management page shows target_per_week and weight columns with editable inputs
- [x] "Save Goals" action calls set_sprint_habit_goal for each modified habit
- [x] Dashboard displays sprint-specific targets in the Done column (e.g., "3/5" using sprint goal, not habit default)
- [x] Habit cards on sprint habits page show effective vs default values when they differ

**8.6 - Epic 8 tests**
- [x] Test set/get/delete sprint_habit_goals round-trip
- [x] Test reporting uses sprint-specific targets when available
- [x] Test reporting falls back to habit defaults when no override exists
- [x] Test data migration: entry counts preserved, duplicates removed, goals preserved
- [x] Test data migration idempotency (run twice, same result)
- [x] Test web UI goal editing form and POST endpoint
- [x] Test backward compatibility: existing habits without overrides unchanged

---

## Epic 9: Reports & Analytics (NOT STARTED)

Add a dedicated reports feature with static and dynamic reports for the web UI, plus more sophisticated cross-sprint reporting for the CLI/LLM interface. Includes lightweight charts using Chart.js and cal-heatmap.

### Acceptance Criteria

- [ ] `/reports` page with tab navigation between report types
- [ ] Sprint comparison table with bar chart showing weighted scores across all sprints
- [ ] GitHub-style habit consistency heatmap for any habit or all habits combined
- [ ] `cross_sprint_report` CLI action comparing metrics across sprints
- [ ] Category balance chart and weekly score trend line chart
- [ ] Per-habit trend line chart across sprints
- [ ] Streak leaderboard and `progress_summary` CLI action for LLM
- [ ] All new reports have passing tests

### Tasks

| ID | Title | Description | Priority | Complexity | Depends On | Status |
|----|-------|-------------|----------|------------|------------|--------|
| 9.1 | Reports page layout + Chart.js/cal-heatmap integration | Create `/reports` route, base template with tab nav, load Chart.js + cal-heatmap via CDN | High | M | 6.7 | <!-- vk:ERI-59 --> |
| 9.2 | Sprint comparison report (table + bar chart) | Sprint comparison view with table and Chart.js bar chart of weighted scores | High | L | 9.1 | <!-- vk:ERI-60 --> |
| 9.3 | Habit consistency heatmap (GitHub-style calendar) | GitHub-style contribution heatmap for daily check-ins using cal-heatmap | High | L | 9.1 | Done <!-- vk:ERI-61 --> |
| 9.4 | cross_sprint_report CLI action + formatter | New engine action comparing metrics across sprints, with markdown formatter | High | L | — | Done <!-- vk:ERI-62 --> |
| 9.5 | Category balance chart + weekly score trend | Category balance radar/bar chart and daily completion % line chart | Medium | M | 9.1 | <!-- vk:ERI-63 --> |
| 9.6 | Habit trend line chart (per-habit across sprints) | Per-habit weekly completion % line chart across sprints | Medium | M | 9.1 | <!-- vk:ERI-64 --> |
| 9.7 | Streak leaderboard + progress_summary CLI action | Streak ranking table and holistic `progress_summary` CLI action for LLM | Medium | M | 9.4 | Done <!-- vk:ERI-65 --> |
| 9.8 | README refresh + screenshots | Update README to reflect web UI, reports, per-sprint goals, and current feature set; add screenshots of dashboard, reports, and habit detail pages | Medium | S | 9.7 | |

### Task Details

**9.1 - Reports page layout + Chart.js/cal-heatmap integration**
- [x] GET `/reports` route returns reports page
- [x] Base reports template with tab navigation (Sprint Comparison, Habit Heatmap, Category Balance, Trends, Streaks)
- [x] Chart.js loaded via CDN (only on reports page)
- [x] cal-heatmap loaded via CDN for heatmap view
- [x] Navigation bar highlights "Reports" as active
- [x] Tests for route returning 200

**9.2 - Sprint comparison report (table + bar chart)**
- [x] GET `/reports/sprints` (or tab within `/reports`) renders sprint comparison
- [x] Table: sprint name/theme, dates, weighted score %, unweighted score %, habit count, trend arrow
- [x] Chart.js bar chart showing weighted score % per sprint (chronological)
- [x] Color coding: green >= 80%, yellow >= 50%, red < 50%
- [x] API endpoint `GET /api/reports/sprint-comparison` returning JSON
- [x] Tests for route and API endpoint

**9.3 - Habit consistency heatmap (GitHub-style calendar)**
- [x] GET `/reports/heatmap` (or tab within `/reports`) renders heatmap view
- [x] Dropdown to select specific habit or "All Habits"
- [x] cal-heatmap renders full-year calendar grid colored by check-in intensity
- [x] API endpoint `GET /api/reports/heatmap?habit_id=X` returning date→value mapping
- [x] Tests for API endpoint

**9.4 - cross_sprint_report CLI action + formatter**
- [x] New `cross_sprint_report` action in executor (query action)
- [x] Payload: optional `limit`, optional `habit_id`
- [x] Returns: array of sprint summaries with weighted/unweighted scores, per-category scores, trend deltas
- [x] Includes overall trend assessment (improving/declining/stable)
- [x] Validation schema in validation.py
- [x] Markdown formatter in formatters.py
- [x] Unit tests with multiple sprints

**9.5 - Category balance chart + weekly score trend**
- [ ] Category balance chart (radar or horizontal bar) for current sprint
- [ ] Option to overlay previous sprint for comparison
- [ ] Weekly score trend: line chart of daily completion % within a sprint
- [ ] Sprint selector dropdown
- [ ] API endpoints for category balance and daily scores
- [ ] Tests for API endpoints

**9.6 - Habit trend line chart (per-habit across sprints)**
- [ ] Habit trend view with habit dropdown
- [ ] Chart.js line chart of weekly completion % over time
- [ ] Sprint boundaries marked with vertical lines or shading
- [ ] Rolling average overlay
- [ ] API endpoint `GET /api/reports/habit-trend?habit_id=X`
- [ ] Tests for API endpoint

**9.7 - Streak leaderboard + progress_summary CLI action**
- [x] Streak leaderboard table: habit name, current streak, longest streak, total check-ins
- [x] Visual streak indicators
- [x] New `progress_summary` CLI action: overall trend, top/bottom habits, category balance, active streaks
- [x] Validation schema and markdown formatter for `progress_summary`
- [x] Tests for leaderboard and progress_summary

**9.8 - README refresh + screenshots**
- [ ] Update README intro to highlight both LLM-first and web UI approaches as dual interfaces
- [ ] Add "Web Interface" section with description of the dashboard, habit management, sprint management, and reports pages
- [ ] Capture and add screenshots: sprint dashboard, reports page (charts/heatmap), habits list, habit detail, sprint detail
- [ ] Add screenshots to a `docs/screenshots/` directory
- [ ] Update architecture diagram to show web UI alongside CLI/LLM flow
- [ ] Document new features: per-sprint goal overrides, habit detail with streaks, delete habit, year/month sprint grouping
- [ ] Update "Quick Start" section to include `habit-sprint serve` for launching the web UI
- [ ] Review and update any outdated sections (dependencies, feature list, etc.)

---

## Dependencies

- Python 3.12+
- sqlite3 (stdlib)
- pytest (dev dependency)
- fastapi, uvicorn, jinja2 (optional web dependencies)

## Out of Scope (v1)

- CmdShell widget implementation (Phase 3 per PRD)
- Mobile app
- Notifications / push reminders
- Multi-user / authentication
- Real-time sync
- Negative habit type field
- Cross-sprint longitudinal analytics
- Heatmap data endpoint

## Open Questions

- [ ] OpenClaw integration method — Option A (direct import) vs Option B (subprocess) — deferred to CmdShell phase
- [ ] Exact sprint ID auto-generation: sequential within year (S01, S02...) or derived from week number?
- [ ] Should `list_habits` without a sprint_id filter return sprint-scoped habits from all sprints, or only global + active sprint habits?

## Related Documents

| Document | Purpose | Status |
|----------|---------|--------|
| docs/prd.md | Product Requirements | Current (v2.0) |
| docs/ui_spreadsheet_to_ascii_mockup.md | ASCII mockup reference | Current |
| docs/chat_history.md | Design conversation history | Reference |

---

## Changelog

- **2026-03-01**: Initial development plan created from PRD v2.0
- **2026-03-01**: Generated 31 VibeKanban issues (5 epics + 26 tasks) — all linked with `<!-- vk:ERI-X -->` markers
- **2026-03-01**: Work loop iteration 1 — completed tasks 1.2, 1.3 (3/4 of Epic 1)
- **2026-03-01**: Work loop iteration 2 — completed task 1.4, Epic 1 done (100%)
- **2026-03-01**: Work loop iteration 3 — completed task 2.1 (executor framework)
- **2026-03-01**: Work loop iteration 4 — completed tasks 2.2, 2.3, 4.1 (3 parallel, 1 merge conflict auto-resolved, 1 test fix)
- **2026-03-01**: Work loop iteration 5 — completed tasks 2.4, 2.6 (2 parallel)
- **2026-03-01**: Work loop iteration 6 — completed task 2.5 (entry management)
- **2026-03-01**: Work loop iteration 7 — completed tasks 2.7, 3.1, 3.2 (3 parallel, 1 merge conflict auto-resolved)
- **2026-03-01**: Work loop iteration 8 — completed tasks 3.3, 3.4, 3.5 (3 parallel)
- **2026-03-01**: Work loop iteration 9 — completed tasks 2.8, 3.6, 3.7 (3 parallel, Epic 2 done)
- **2026-03-01**: Work loop iteration 10 — completed tasks 3.8, 4.2, 4.3 (3 parallel, 1 merge conflict auto-resolved in formatters.py/cli.py/test_formatters.py, Epics 3 done)
- **2026-03-01**: Autonomous work loop reached iteration cap (10). 23/26 tasks done. Remaining: 4.4 (CLI tests), 5.1, 5.2. All 663 tests passing.
- **2026-03-01**: Completed remaining tasks 4.4, 5.1, 5.2 (4.4 + 5.1 parallel, then 5.2). All 26/26 tasks done. All 5 epics complete. 682 tests passing.
- **2026-03-15**: Synced with VibeKanban — fixed Epic 7 (ERI-42) and Epic 8 (ERI-51) parent issues from "To do" → "Done" in VK. All Epics 1-8 confirmed complete. Epic 9 remains not started (0/7 tasks). Task 9.8 unlinked (no VK ID). ERI-50 orphaned (in VK, not in plan).
- **2026-03-10**: Added Epic 6 (Web UI) — 9 tasks for lightweight web interface with FastAPI + htmx. Moved Web UI and HTTP API out of "Out of Scope".
- **2026-03-10**: Synced with VibeKanban — created Epic 6 (ERI-32) and 9 tasks (ERI-33 through ERI-41). All Epics 1-5 confirmed Done. 26/35 tasks complete, 9 new tasks in To do.
- **2026-03-11**: Autonomous work loop completed Epic 6 (Web UI) in 5 iterations. All 9/9 tasks done, 4 merge conflicts auto-resolved, 1 test fix. All 6 epics complete. 682 tests passing + 1 skipped (optional web dep).
- **2026-03-10**: Added Epic 7 (Web UI Polish & Sprint Habit Management) — 7 tasks for UI polish, habit sprint scope, sprint editing, retro editing, sprint habits management, dashboard progress indicators. Created VK epic ERI-42 and tasks ERI-43 through ERI-49.
- **2026-03-10**: Autonomous work loop completed Epic 7 in 3 iterations. All 7/7 tasks done, 3 merge conflicts auto-resolved, 1 validation bug fix. All 7 epics complete. 757 tests passing.
- **2026-03-11**: Added Epic 8 (Habit Consolidation & Per-Sprint Goals) — 6 tasks for sprint_habit_goals junction table, reporting updates, historical data migration, and web UI goal editing. Created VK epic ERI-51 and tasks ERI-52 through ERI-57.
- **2026-03-11**: Autonomous work loop completed Epic 8 in 4 iterations. All 6/6 tasks done, 0 merge conflicts, 0 test fixes. All 8 epics complete. 798 tests passing.
- **2026-03-11**: Added Epic 9 (Reports & Analytics) — 7 tasks for reports page with Chart.js/cal-heatmap, sprint comparison, habit heatmap, cross-sprint CLI report, category balance, habit trends, streak leaderboard. Created VK epic ERI-58 and tasks ERI-59 through ERI-65.
- **2026-03-11**: Synced with VibeKanban — Epics 1-8 confirmed Done. Epic 9 added (0/7 tasks). 45/52 total tasks complete.
