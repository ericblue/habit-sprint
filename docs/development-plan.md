# Development Plan: Habit Sprint

> **Generated from:** docs/prd.md
> **Created:** 2026-03-01
> **Last synced:** 2026-03-10
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
| 6. Web UI | Planning | 0% |

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

## Epic 6: Web UI

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
- [ ] `GET /api/dashboard?sprint_id=` → calls `sprint_dashboard`, returns JSON
- [ ] `POST /api/log` (body: `{habit_id, date, value}`) → calls `log_date`
- [ ] `DELETE /api/log` (body: `{habit_id, date}`) → calls `delete_entry`
- [ ] `GET /api/habits?include_archived=false` → calls `list_habits`
- [ ] `GET /api/sprints?status=active` → calls `list_sprints`
- [ ] `GET /api/sprint/active` → calls `get_active_sprint`
- [ ] All endpoints call `executor.execute()` and return the standard envelope
- [ ] Error responses use appropriate HTTP status codes

**6.3 - Dashboard page**
- [ ] `GET /` renders the dashboard for the active sprint
- [ ] Grid layout: rows = habits (grouped by category), columns = dates in sprint
- [ ] Each cell shows a checkbox (checked if entry exists with value > 0)
- [ ] Category headers separate habit groups
- [ ] Daily totals row at the bottom (points / max)
- [ ] Sprint summary sidebar or header (weighted score, days elapsed/remaining)
- [ ] Week 1 / Week 2 tab or toggle

**6.4 - Checkbox toggle interaction**
- [ ] Checkbox uses `hx-post="/api/log"` or `hx-delete="/api/log"` based on current state
- [ ] Server returns updated cell HTML fragment (htmx swap)
- [ ] Daily totals row updates after toggle
- [ ] Visual feedback on toggle (brief highlight or transition)
- [ ] Handles errors gracefully (shows toast or inline message)

**6.5 - Habit management page**
- [ ] `GET /habits` renders list of all habits with edit/archive actions
- [ ] `GET /habits/new` renders create form (name, slug, category, target, weight, unit)
- [ ] `POST /habits` creates a habit via `create_habit`
- [ ] `POST /habits/{id}/edit` updates a habit via `update_habit`
- [ ] `POST /habits/{id}/archive` archives via `archive_habit`
- [ ] Form validation mirrors engine validation rules

**6.6 - Sprint management page**
- [ ] `GET /sprints` renders list of all sprints with status badges
- [ ] `GET /sprints/new` renders create form (start_date, end_date, theme, focus_goals)
- [ ] `POST /sprints` creates a sprint via `create_sprint`
- [ ] `POST /sprints/{id}/archive` archives via `archive_sprint`
- [ ] Sprint detail view shows retro if one exists

**6.7 - Styling and layout**
- [ ] `habit_sprint/static/style.css` with clean, minimal design
- [ ] Responsive grid that works on desktop and tablet
- [ ] Navigation: Dashboard | Habits | Sprints
- [ ] Grid cells sized for easy click/tap targets
- [ ] Color-coded categories (subtle background tints)
- [ ] Dark/light mode support via `prefers-color-scheme`

**6.8 - CLI integration**
- [ ] `habit-sprint --web` starts uvicorn on `127.0.0.1:8000` (configurable via `--host` and `--port`)
- [ ] Or: separate entry point `habit-sprint-web` registered in pyproject.toml
- [ ] Uses the same `--db` flag for database path
- [ ] Prints startup message with URL to open

**6.9 - Web UI tests**
- [ ] Use FastAPI `TestClient` for endpoint testing
- [ ] Test dashboard renders with known sprint/habit data
- [ ] Test log/delete toggle cycle returns correct state
- [ ] Test habit CRUD through web endpoints
- [ ] Test error cases (invalid habit, no active sprint)
- [ ] Test concurrent access (CLI + web on same DB)

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
- **2026-03-10**: Added Epic 6 (Web UI) — 9 tasks for lightweight web interface with FastAPI + htmx. Moved Web UI and HTTP API out of "Out of Scope".
- **2026-03-10**: Synced with VibeKanban — created Epic 6 (ERI-32) and 9 tasks (ERI-33 through ERI-41). All Epics 1-5 confirmed Done. 26/35 tasks complete, 9 new tasks in To do.
