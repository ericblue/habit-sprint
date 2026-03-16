"""FastAPI web adapter for Habit Sprint."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from habit_sprint.db import get_connection
from habit_sprint.executor import execute

DEFAULT_DB_DIR = os.path.join(os.path.expanduser("~"), ".habit-sprint")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, "habits.db")

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent / "static"


class LogBody(BaseModel):
    habit_id: str
    date: str
    value: float = 1


class DeleteLogBody(BaseModel):
    habit_id: str
    date: str


def _execute_action(db_path: str, action: str, payload: dict | None = None) -> JSONResponse:
    """Call executor.execute() and map the result to an appropriate HTTP response."""
    result = execute({"action": action, "payload": payload or {}}, db_path)
    if result["status"] == "error":
        error_msg = result["error"].lower()
        if "missing required" in error_msg or "must be" in error_msg or "unknown field" in error_msg:
            status_code = 400
        elif "not found" in error_msg or "no active sprint" in error_msg:
            status_code = 404
        elif "unknown action" in error_msg:
            status_code = 400
        else:
            status_code = 500
        return JSONResponse(content=result, status_code=status_code)
    return JSONResponse(content=result)


def _build_cell_html(habit_id: str, date: str, checked: bool, note: str, week: int | None, css_class: str = "") -> str:
    """Build the HTML for a single grid cell with checkbox and optional note indicator."""
    checked_attr = " checked" if checked else ""
    cell_id = f"cell-{habit_id}-{date}"
    week_param = f"?week={week}" if week is not None else ""
    note_dot = '<span class="note-dot" title="Has note"></span>' if note else ""
    extra_class = f" {css_class}" if css_class else ""
    return (
        f'<td id="{cell_id}" class="toggle-cell{extra_class}">'
        f'<input type="checkbox"{checked_attr}'
        f' hx-post="/toggle/{habit_id}/{date}{week_param}"'
        f' hx-target="#{cell_id}"'
        f' hx-swap="outerHTML"'
        f">"
        f'{note_dot}'
        f'<span class="note-icon" onclick="openNote(\'{habit_id}\', \'{date}\', this.parentElement)" title="Add/view note">&#9998;</span>'
        f"</td>"
    )


def create_app(db_path: str = DEFAULT_DB_PATH) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # Ensure database directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        # Initialize database connection and store on app state
        conn = get_connection(db_path)
        app.state.db = conn
        yield
        # Shutdown: close connection
        conn.close()

    app = FastAPI(title="Habit Sprint", lifespan=lifespan)
    app.state.db_path = db_path

    # Jinja2 templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.templates = templates

    # Static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, week: Optional[int] = None, sprint_id: Optional[str] = None):
        """Render the dashboard for a sprint (defaults to active sprint)."""
        payload: dict = {}
        if week is not None:
            payload["week"] = week
        if sprint_id is not None:
            payload["sprint_id"] = sprint_id
        result = execute({"action": "sprint_dashboard", "payload": payload}, db_path)

        if result["status"] == "error":
            error_msg = result.get("error", "")
            # If a specific sprint was requested but had an error (e.g. week out of range),
            # show the error rather than the generic "No Active Sprint" message
            if sprint_id:
                return templates.TemplateResponse("dashboard.html", {
                    "request": request,
                    "active_nav": "dashboard",
                    "data": None,
                    "dates": [],
                    "week": week,
                    "error": error_msg,
                })
            # No active sprint — render empty dashboard
            return templates.TemplateResponse("dashboard.html", {
                "request": request,
                "active_nav": "dashboard",
                "data": None,
                "dates": [],
                "week": week,
            })

        data = result["data"]

        # Build date objects for template iteration
        sprint_start = date.fromisoformat(data["sprint"]["start_date"])
        sprint_end = date.fromisoformat(data["sprint"]["end_date"])
        if week is not None:
            ws = sprint_start + timedelta(days=(week - 1) * 7)
            we = min(ws + timedelta(days=6), sprint_end)
        else:
            ws = sprint_start
            we = sprint_end
        view_dates = []
        d = ws
        while d <= we:
            view_dates.append(d)
            d += timedelta(days=1)

        # Attach notes to each habit for template rendering
        conn = get_connection(db_path)
        for cat in data["categories"]:
            for habit in cat["habits"]:
                rows = conn.execute(
                    "SELECT date, note FROM entries WHERE habit_id = ? AND note IS NOT NULL AND note != ''",
                    (habit["habit_id"],),
                ).fetchall()
                habit["notes"] = {r[0]: r[1] for r in rows}

        import math
        num_weeks = math.ceil(((sprint_end - sprint_start).days + 1) / 7)

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "active_nav": "dashboard",
            "data": data,
            "dates": view_dates,
            "week": week,
            "num_weeks": num_weeks,
        })

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # --- API endpoints ---

    @app.get("/api/dashboard")
    async def api_dashboard(request: Request, sprint_id: Optional[str] = None):
        payload: dict = {}
        if sprint_id is not None:
            payload["sprint_id"] = sprint_id
        return _execute_action(request.app.state.db_path, "sprint_dashboard", payload)

    @app.post("/api/log")
    async def api_log(request: Request, body: LogBody):
        payload = {"habit_id": body.habit_id, "date": body.date, "value": body.value}
        return _execute_action(request.app.state.db_path, "log_date", payload)

    @app.delete("/api/log")
    async def api_delete_log(request: Request, body: DeleteLogBody):
        payload = {"habit_id": body.habit_id, "date": body.date}
        return _execute_action(request.app.state.db_path, "delete_entry", payload)

    @app.get("/api/habits")
    async def api_habits(request: Request, include_archived: bool = False):
        payload: dict = {"include_archived": include_archived}
        return _execute_action(request.app.state.db_path, "list_habits", payload)

    @app.get("/api/sprints")
    async def api_sprints(request: Request, status: Optional[str] = None):
        payload: dict = {}
        if status is not None:
            payload["status"] = status
        return _execute_action(request.app.state.db_path, "list_sprints", payload)

    @app.get("/api/sprint/active")
    async def api_active_sprint(request: Request):
        return _execute_action(request.app.state.db_path, "get_active_sprint")

    @app.get("/api/entry/{habit_id}/{entry_date}")
    async def api_get_entry(request: Request, habit_id: str, entry_date: str):
        """Get a single entry's value and note."""
        conn = get_connection(request.app.state.db_path)
        row = conn.execute(
            "SELECT value, note FROM entries WHERE habit_id = ? AND date = ?",
            (habit_id, entry_date),
        ).fetchone()
        if not row:
            return JSONResponse({"value": 0, "note": ""})
        return JSONResponse({"value": row[0], "note": row[1] or ""})

    # --- Habit management pages ---

    @app.get("/habits")
    async def habits_list(request: Request, show_archived: Optional[str] = None):
        result = execute(
            {"action": "list_habits", "payload": {"include_archived": True}},
            request.app.state.db_path,
        )
        habits = result["data"]["habits"] if result["status"] == "success" else []

        # Enrich habits with entry counts and sprint goal counts
        conn = get_connection(request.app.state.db_path)
        for h in habits:
            row = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE habit_id = ?", (h["id"],)
            ).fetchone()
            h["entry_count"] = row[0]
            row = conn.execute(
                "SELECT COUNT(*) FROM sprint_habit_goals WHERE habit_id = ?", (h["id"],)
            ).fetchone()
            h["sprint_count"] = row[0]

        archived_count = sum(1 for h in habits if h.get("archived"))

        return templates.TemplateResponse(
            "habits_list.html",
            {
                "request": request,
                "habits": habits,
                "active_nav": "habits",
                "show_archived": bool(show_archived),
                "archived_count": archived_count,
                "success_message": request.query_params.get("msg"),
            },
        )

    @app.get("/habits/new")
    async def habit_new_form(request: Request):
        active_sprint = None
        sprint_result = execute({"action": "get_active_sprint", "payload": {}}, request.app.state.db_path)
        if sprint_result["status"] == "success":
            active_sprint = sprint_result["data"]
        return templates.TemplateResponse(
            "habit_form.html",
            {
                "request": request,
                "editing": False,
                "form_action": "/habits",
                "values": {},
                "error": None,
                "active_nav": "habits",
                "active_sprint": active_sprint,
            },
        )

    @app.get("/habits/{habit_id}")
    async def habit_detail(request: Request, habit_id: str):
        """Show habit detail page with sprint history and stats."""
        conn = get_connection(request.app.state.db_path)

        # Get the habit
        row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit_id,)).fetchone()
        if row is None:
            return RedirectResponse(url="/habits?msg=Habit+not+found", status_code=303)
        habit = dict(row)

        # Get all sprints this habit participated in (via sprint_habit_goals or sprint_id)
        sprint_rows = conn.execute(
            """SELECT DISTINCT s.id AS sprint_id, s.start_date, s.end_date, s.theme,
                      COALESCE(shg.target_per_week, ?) AS target_per_week
               FROM sprints s
               LEFT JOIN sprint_habit_goals shg ON shg.sprint_id = s.id AND shg.habit_id = ?
               WHERE shg.sprint_id IS NOT NULL
                  OR s.id = ?
               ORDER BY s.start_date""",
            (habit["target_per_week"], habit_id, habit.get("sprint_id")),
        ).fetchall()

        # Also include sprints where this habit has entries but no explicit binding
        entry_sprint_rows = conn.execute(
            """SELECT DISTINCT s.id AS sprint_id, s.start_date, s.end_date, s.theme
               FROM sprints s
               JOIN entries e ON e.habit_id = ? AND e.date BETWEEN s.start_date AND s.end_date
               WHERE s.id NOT IN (
                   SELECT COALESCE(shg2.sprint_id, '') FROM sprint_habit_goals shg2 WHERE shg2.habit_id = ?
               )
               AND s.id != COALESCE(?, '')
               ORDER BY s.start_date""",
            (habit_id, habit_id, habit.get("sprint_id")),
        ).fetchall()

        # Merge sprint lists (convert Row objects to dicts)
        seen_ids = {r["sprint_id"] for r in sprint_rows}
        all_sprint_data = [dict(r) for r in sprint_rows]
        for r in entry_sprint_rows:
            if r["sprint_id"] not in seen_ids:
                all_sprint_data.append(dict(r))

        # Build sprint history with completion stats
        sprint_history = []
        total_entries = 0
        total_target = 0
        from datetime import datetime
        for s in all_sprint_data:
            start = datetime.strptime(s["start_date"], "%Y-%m-%d").date()
            end = datetime.strptime(s["end_date"], "%Y-%m-%d").date()
            num_weeks = max(1, ((end - start).days + 1) // 7)

            # Get target for this sprint
            goal_row = conn.execute(
                "SELECT target_per_week FROM sprint_habit_goals WHERE sprint_id = ? AND habit_id = ?",
                (s["sprint_id"], habit_id),
            ).fetchone()
            target_per_week = goal_row[0] if goal_row else habit["target_per_week"]
            target_total = target_per_week * num_weeks

            # Count entries in this sprint's date range
            entry_count = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE habit_id = ? AND date BETWEEN ? AND ? AND value > 0",
                (habit_id, s["start_date"], s["end_date"]),
            ).fetchone()[0]

            completion_pct = min(100, round(entry_count / target_total * 100)) if target_total > 0 else 0

            sprint_history.append({
                "sprint_id": s["sprint_id"],
                "theme": s.get("theme") or s["sprint_id"],
                "start_date": s["start_date"],
                "end_date": s["end_date"],
                "target_per_week": target_per_week,
                "num_weeks": num_weeks,
                "target_total": target_total,
                "entry_count": entry_count,
                "completion_pct": completion_pct,
            })
            total_entries += entry_count
            total_target += target_total

        overall_pct = min(100, round(total_entries / total_target * 100)) if total_target > 0 else 0

        # Calculate streaks
        all_dates = conn.execute(
            "SELECT date FROM entries WHERE habit_id = ? AND value > 0 ORDER BY date DESC",
            (habit_id,),
        ).fetchall()
        date_set = {r[0] for r in all_dates}

        current_streak = 0
        d = date.today()
        while d.isoformat() in date_set:
            current_streak += 1
            d -= timedelta(days=1)

        longest_streak = 0
        streak = 0
        for r in sorted(all_dates, key=lambda x: x[0]):
            dt = datetime.strptime(r[0], "%Y-%m-%d").date()
            if streak == 0:
                streak = 1
            else:
                if (dt - prev_dt).days == 1:
                    streak += 1
                else:
                    longest_streak = max(longest_streak, streak)
                    streak = 1
            prev_dt = dt
        longest_streak = max(longest_streak, streak)

        return templates.TemplateResponse("habit_detail.html", {
            "request": request,
            "habit": habit,
            "sprint_history": sprint_history,
            "total_entries": total_entries,
            "overall_pct": overall_pct,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "active_nav": "habits",
        })

    @app.post("/habits")
    async def habit_create(
        request: Request,
        name: str = Form(...),
        id: str = Form(...),
        category: str = Form(...),
        target_per_week: int = Form(...),
        weight: int = Form(...),
        unit: str = Form(...),
        sprint_id: str = Form(""),
    ):
        payload = {
            "id": id,
            "name": name,
            "category": category,
            "target_per_week": target_per_week,
            "weight": weight,
            "unit": unit,
        }
        if sprint_id:
            payload["sprint_id"] = sprint_id
        result = execute({"action": "create_habit", "payload": payload}, request.app.state.db_path)
        if result["status"] == "error":
            active_sprint = None
            sprint_result = execute({"action": "get_active_sprint", "payload": {}}, request.app.state.db_path)
            if sprint_result["status"] == "success":
                active_sprint = sprint_result["data"]
            return templates.TemplateResponse(
                "habit_form.html",
                {
                    "request": request,
                    "editing": False,
                    "form_action": "/habits",
                    "values": payload,
                    "error": result["error"],
                    "active_nav": "habits",
                    "active_sprint": active_sprint,
                },
            )
        return RedirectResponse(url="/habits?msg=Habit+created", status_code=303)

    @app.get("/habits/{habit_id}/edit")
    async def habit_edit_form(request: Request, habit_id: str):
        result = execute(
            {"action": "list_habits", "payload": {"include_archived": True}},
            request.app.state.db_path,
        )
        habit = None
        if result["status"] == "success":
            for h in result["data"]["habits"]:
                if h["id"] == habit_id:
                    habit = h
                    break
        if habit is None:
            return RedirectResponse(url="/habits?msg=Habit+not+found", status_code=303)
        active_sprint = None
        sprint_result = execute({"action": "get_active_sprint", "payload": {}}, request.app.state.db_path)
        if sprint_result["status"] == "success":
            active_sprint = sprint_result["data"]
        return templates.TemplateResponse(
            "habit_form.html",
            {
                "request": request,
                "editing": True,
                "form_action": f"/habits/{habit_id}/edit",
                "values": habit,
                "error": None,
                "active_nav": "habits",
                "active_sprint": active_sprint,
            },
        )

    @app.post("/habits/{habit_id}/edit")
    async def habit_update(
        request: Request,
        habit_id: str,
        name: str = Form(...),
        category: str = Form(...),
        target_per_week: int = Form(...),
        weight: int = Form(...),
        unit: str = Form(...),
        sprint_id: str = Form(""),
    ):
        payload = {
            "id": habit_id,
            "name": name,
            "category": category,
            "target_per_week": target_per_week,
            "weight": weight,
            "unit": unit,
        }
        # Include sprint_id in payload to update scope (empty string = global/NULL)
        form_data = await request.form()
        if "sprint_id" in form_data:
            payload["sprint_id"] = sprint_id if sprint_id else None
        result = execute({"action": "update_habit", "payload": payload}, request.app.state.db_path)
        if result["status"] == "error":
            active_sprint = None
            sprint_result = execute({"action": "get_active_sprint", "payload": {}}, request.app.state.db_path)
            if sprint_result["status"] == "success":
                active_sprint = sprint_result["data"]
            return templates.TemplateResponse(
                "habit_form.html",
                {
                    "request": request,
                    "editing": True,
                    "form_action": f"/habits/{habit_id}/edit",
                    "values": payload,
                    "error": result["error"],
                    "active_nav": "habits",
                    "active_sprint": active_sprint,
                },
            )
        return RedirectResponse(url="/habits?msg=Habit+updated", status_code=303)

    @app.post("/habits/{habit_id}/archive")
    async def habit_archive(request: Request, habit_id: str):
        result = execute(
            {"action": "archive_habit", "payload": {"id": habit_id}},
            request.app.state.db_path,
        )
        if result["status"] == "error":
            return RedirectResponse(url=f"/habits?msg={result['error']}", status_code=303)
        return RedirectResponse(url="/habits?msg=Habit+archived", status_code=303)

    @app.post("/habits/{habit_id}/unarchive")
    async def habit_unarchive(request: Request, habit_id: str):
        result = execute(
            {"action": "unarchive_habit", "payload": {"id": habit_id}},
            request.app.state.db_path,
        )
        if result["status"] == "error":
            return RedirectResponse(url=f"/habits?msg={result['error']}", status_code=303)
        return RedirectResponse(url="/habits?msg=Habit+restored", status_code=303)

    @app.post("/habits/{habit_id}/delete")
    async def habit_delete(request: Request, habit_id: str):
        result = execute(
            {"action": "delete_habit", "payload": {"id": habit_id}},
            request.app.state.db_path,
        )
        if result["status"] == "error":
            return RedirectResponse(url=f"/habits?msg={result['error']}", status_code=303)
        return RedirectResponse(url="/habits?msg=Habit+deleted", status_code=303)

    # --- Sprint management pages ---

    @app.get("/sprints", response_class=HTMLResponse)
    async def sprints_list(request: Request, year: Optional[str] = None):
        result = execute({"action": "list_sprints", "payload": {}}, request.app.state.db_path)
        sprints = result["data"]["sprints"] if result["status"] == "success" else []
        error = result.get("error") if result["status"] == "error" else None

        # Sort: active first, then by start_date descending
        sprints.sort(key=lambda s: (0 if s["status"] == "active" else 1, s.get("start_date", "")), reverse=False)
        # Reverse archived ones so newest is first, but keep active at top
        active = [s for s in sprints if s["status"] == "active"]
        archived = [s for s in sprints if s["status"] != "active"]
        archived.sort(key=lambda s: s.get("start_date", ""), reverse=True)
        sprints = active + archived

        # Collect available years for the year filter
        years = sorted({s["start_date"][:4] for s in sprints if s.get("start_date")}, reverse=True)

        # Filter by year if specified
        if year:
            sprints = [s for s in sprints if s.get("start_date", "").startswith(year)]

        # Group sprints by year-month for display
        from collections import OrderedDict
        grouped: OrderedDict[str, list] = OrderedDict()
        for s in sprints:
            sd = s.get("start_date", "")
            ym = sd[:7] if len(sd) >= 7 else "Unknown"
            grouped.setdefault(ym, []).append(s)

        return templates.TemplateResponse("sprints_list.html", {
            "request": request, "sprints": sprints, "grouped": grouped,
            "years": years, "selected_year": year,
            "error": error, "active_nav": "sprints",
        })

    @app.get("/sprints/new", response_class=HTMLResponse)
    async def sprint_form(request: Request):
        return templates.TemplateResponse("sprint_form.html", {
            "request": request, "error": None, "active_nav": "sprints", "values": {},
            "editing": False, "form_action": "/sprints",
        })

    @app.post("/sprints", response_class=HTMLResponse)
    async def create_sprint(
        request: Request,
        start_date: str = Form(...),
        end_date: str = Form(...),
        theme: str = Form(""),
        focus_goals: str = Form(""),
    ):
        goals = [g.strip() for g in focus_goals.splitlines() if g.strip()]
        payload: dict = {
            "start_date": start_date,
            "end_date": end_date,
        }
        if theme.strip():
            payload["theme"] = theme.strip()
        if goals:
            payload["focus_goals"] = goals
        result = execute({"action": "create_sprint", "payload": payload}, request.app.state.db_path)
        if result["status"] == "error":
            return templates.TemplateResponse("sprint_form.html", {
                "request": request, "error": result["error"], "active_nav": "sprints",
                "values": {"start_date": start_date, "end_date": end_date, "theme": theme, "focus_goals": focus_goals},
                "editing": False, "form_action": "/sprints",
            })
        return RedirectResponse(url="/sprints", status_code=303)

    @app.get("/sprints/{sprint_id}", response_class=HTMLResponse)
    async def sprint_detail(request: Request, sprint_id: str):
        list_result = execute({"action": "list_sprints", "payload": {}}, request.app.state.db_path)
        sprint = None
        if list_result["status"] == "success":
            for s in list_result["data"]["sprints"]:
                if s["id"] == sprint_id:
                    sprint = s
                    break
        if sprint is None:
            return HTMLResponse("Sprint not found", status_code=404)

        retro = None
        retro_result = execute({"action": "get_retro", "payload": {"sprint_id": sprint_id}}, request.app.state.db_path)
        if retro_result["status"] == "success":
            retro = retro_result["data"]

        return templates.TemplateResponse("sprint_detail.html", {
            "request": request, "sprint": sprint, "retro": retro, "active_nav": "sprints",
            "success_message": request.query_params.get("msg"),
        })

    @app.get("/sprints/{sprint_id}/edit", response_class=HTMLResponse)
    async def sprint_edit_form(request: Request, sprint_id: str):
        list_result = execute({"action": "list_sprints", "payload": {}}, request.app.state.db_path)
        sprint = None
        if list_result["status"] == "success":
            for s in list_result["data"]["sprints"]:
                if s["id"] == sprint_id:
                    sprint = s
                    break
        if sprint is None:
            return RedirectResponse(url="/sprints?msg=Sprint+not+found", status_code=303)
        focus_goals_text = "\n".join(sprint.get("focus_goals") or [])
        return templates.TemplateResponse("sprint_form.html", {
            "request": request,
            "editing": True,
            "form_action": f"/sprints/{sprint_id}/edit",
            "values": {"theme": sprint.get("theme", ""), "focus_goals": focus_goals_text},
            "error": None,
            "active_nav": "sprints",
        })

    @app.post("/sprints/{sprint_id}/edit", response_class=HTMLResponse)
    async def sprint_update(
        request: Request,
        sprint_id: str,
        theme: str = Form(""),
        focus_goals: str = Form(""),
    ):
        goals = [g.strip() for g in focus_goals.splitlines() if g.strip()]
        payload: dict = {"sprint_id": sprint_id}
        payload["theme"] = theme.strip() if theme.strip() else None
        payload["focus_goals"] = goals if goals else None
        result = execute({"action": "update_sprint", "payload": payload}, request.app.state.db_path)
        if result["status"] == "error":
            return templates.TemplateResponse("sprint_form.html", {
                "request": request,
                "editing": True,
                "form_action": f"/sprints/{sprint_id}/edit",
                "values": {"theme": theme, "focus_goals": focus_goals},
                "error": result["error"],
                "active_nav": "sprints",
            })
        return RedirectResponse(url=f"/sprints/{sprint_id}?msg=Sprint+updated", status_code=303)

    @app.post("/sprints/{sprint_id}/retro", response_class=HTMLResponse)
    async def sprint_retro_save(
        request: Request,
        sprint_id: str,
        what_went_well: str = Form(""),
        what_to_improve: str = Form(""),
        ideas: str = Form(""),
    ):
        result = execute({"action": "add_retro", "payload": {
            "sprint_id": sprint_id,
            "what_went_well": what_went_well.strip(),
            "what_to_improve": what_to_improve.strip(),
            "ideas": ideas.strip(),
        }}, request.app.state.db_path)
        if result["status"] == "error":
            return RedirectResponse(url=f"/sprints/{sprint_id}?msg=Error:+{result['error']}", status_code=303)
        return RedirectResponse(url=f"/sprints/{sprint_id}?msg=Retrospective+saved", status_code=303)

    @app.get("/sprints/{sprint_id}/habits", response_class=HTMLResponse)
    async def sprint_habits(request: Request, sprint_id: str):
        """Show habits management page for a sprint."""
        # Get sprint info
        list_result = execute({"action": "list_sprints", "payload": {}}, request.app.state.db_path)
        sprint = None
        if list_result["status"] == "success":
            for s in list_result["data"]["sprints"]:
                if s["id"] == sprint_id:
                    sprint = s
                    break
        if sprint is None:
            return HTMLResponse("Sprint not found", status_code=404)

        # Get all non-archived habits
        habits_result = execute(
            {"action": "list_habits", "payload": {"include_archived": False}},
            request.app.state.db_path,
        )
        all_habits = habits_result["data"]["habits"] if habits_result["status"] == "success" else []

        sprint_habits_list = [h for h in all_habits if h.get("sprint_id") == sprint_id]
        global_habits_list = [h for h in all_habits if not h.get("sprint_id")]

        # Fetch sprint_habit_goals for all habits in the sprint
        conn = get_connection(request.app.state.db_path)
        all_sprint_habit_ids = [h["id"] for h in sprint_habits_list + global_habits_list]
        goals_map: dict = {}
        if all_sprint_habit_ids:
            placeholders = ",".join("?" * len(all_sprint_habit_ids))
            goal_rows = conn.execute(
                f"SELECT habit_id, target_per_week, weight FROM sprint_habit_goals "
                f"WHERE sprint_id = ? AND habit_id IN ({placeholders})",
                (sprint_id, *all_sprint_habit_ids),
            ).fetchall()
            goals_map = {r["habit_id"]: dict(r) for r in goal_rows}

        # Annotate habits with sprint goal overrides
        for h in sprint_habits_list + global_habits_list:
            goal = goals_map.get(h["id"])
            h["goal_target"] = goal["target_per_week"] if goal else None
            h["goal_weight"] = goal["weight"] if goal else None

        return templates.TemplateResponse("sprint_habits.html", {
            "request": request,
            "sprint": sprint,
            "sprint_habits": sprint_habits_list,
            "global_habits": global_habits_list,
            "active_nav": "sprints",
            "success_message": request.query_params.get("msg"),
        })

    @app.post("/sprints/{sprint_id}/habits/goals")
    async def sprint_habits_save_goals(request: Request, sprint_id: str):
        """Save per-sprint goal overrides for habits."""
        form = await request.form()
        # Form fields: goal_target_{habit_id}, goal_weight_{habit_id}
        # Only process habits that have goal fields submitted
        habit_ids = set()
        for key in form.keys():
            if key.startswith("goal_target_"):
                habit_ids.add(key[len("goal_target_"):])

        for habit_id in habit_ids:
            target_str = form.get(f"goal_target_{habit_id}", "").strip()
            weight_str = form.get(f"goal_weight_{habit_id}", "").strip()
            default_target_str = form.get(f"default_target_{habit_id}", "")
            default_weight_str = form.get(f"default_weight_{habit_id}", "")

            if not target_str or not weight_str:
                continue

            target = int(target_str)
            weight = int(weight_str)
            default_target = int(default_target_str) if default_target_str else None
            default_weight = int(default_weight_str) if default_weight_str else None

            # Only save if values differ from defaults (or goal already exists)
            if target == default_target and weight == default_weight:
                # Remove any existing override since it matches defaults
                execute(
                    {"action": "delete_sprint_habit_goal", "payload": {
                        "sprint_id": sprint_id, "habit_id": habit_id,
                    }},
                    request.app.state.db_path,
                )
            else:
                execute(
                    {"action": "set_sprint_habit_goal", "payload": {
                        "sprint_id": sprint_id, "habit_id": habit_id,
                        "target_per_week": target, "weight": weight,
                    }},
                    request.app.state.db_path,
                )

        return RedirectResponse(
            url=f"/sprints/{sprint_id}/habits?msg=Sprint+goals+saved", status_code=303,
        )

    @app.post("/sprints/{sprint_id}/habits/add")
    async def sprint_habit_add(request: Request, sprint_id: str, habit_id: str = Form(...)):
        """Add a global habit to this sprint."""
        execute(
            {"action": "update_habit", "payload": {"id": habit_id, "sprint_id": sprint_id}},
            request.app.state.db_path,
        )
        return RedirectResponse(url=f"/sprints/{sprint_id}/habits?msg=Habit+added+to+sprint", status_code=303)

    @app.post("/sprints/{sprint_id}/habits/remove")
    async def sprint_habit_remove(request: Request, sprint_id: str, habit_id: str = Form(...)):
        """Remove a habit from this sprint (make it global)."""
        execute(
            {"action": "update_habit", "payload": {"id": habit_id, "sprint_id": None}},
            request.app.state.db_path,
        )
        return RedirectResponse(url=f"/sprints/{sprint_id}/habits?msg=Habit+removed+from+sprint", status_code=303)

    # --- Reports page ---

    @app.get("/api/streak-leaderboard")
    async def api_streak_leaderboard(request: Request, sprint_id: Optional[str] = None):
        payload: dict = {}
        if sprint_id is not None:
            payload["sprint_id"] = sprint_id
        return _execute_action(request.app.state.db_path, "streak_leaderboard", payload)

    @app.get("/api/progress-summary")
    async def api_progress_summary(request: Request, sprint_id: Optional[str] = None):
        payload: dict = {}
        if sprint_id is not None:
            payload["sprint_id"] = sprint_id
        return _execute_action(request.app.state.db_path, "progress_summary", payload)

    @app.get("/reports", response_class=HTMLResponse)
    async def reports(request: Request, tab: Optional[str] = None):
        """Render the reports page with tab navigation."""
        valid_tabs = {"sprint-comparison", "heatmap", "category-balance", "trends", "streaks"}
        active_tab = tab if tab in valid_tabs else "sprint-comparison"

        # For heatmap and trends tabs, load habit list for the dropdown
        habits = []
        if active_tab in ("heatmap", "trends"):
            result = execute(
                {"action": "list_habits", "payload": {"include_archived": False}},
                request.app.state.db_path,
            )
            if result["status"] == "success":
                habits = result["data"]["habits"]

        # For category-balance and trends tabs, load sprint list for selector
        sprints = []
        if active_tab in ("category-balance", "trends"):
            result = execute(
                {"action": "list_sprints", "payload": {}},
                request.app.state.db_path,
            )
            if result["status"] == "success":
                sprints = result["data"]["sprints"]

        return templates.TemplateResponse("reports.html", {
            "request": request,
            "active_nav": "reports",
            "active_tab": active_tab,
            "habits": habits,
            "sprints": sprints,
        })

    @app.get("/api/reports/sprint-comparison")
    async def api_sprint_comparison(request: Request):
        """Return sprint comparison data as JSON."""
        return _execute_action(request.app.state.db_path, "cross_sprint_report")

    @app.get("/api/reports/heatmap")
    async def api_reports_heatmap(request: Request, habit_id: Optional[str] = None):
        """Return date-to-value mapping for the heatmap.

        If habit_id is provided, returns entries for that habit.
        If habit_id is omitted or empty, returns aggregated counts across all habits.
        """
        conn = get_connection(request.app.state.db_path)

        if habit_id:
            rows = conn.execute(
                "SELECT date, SUM(value) as total FROM entries WHERE habit_id = ? AND value > 0 GROUP BY date",
                (habit_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date, SUM(value) as total FROM entries WHERE value > 0 GROUP BY date",
            ).fetchall()

        data = {row["date"]: row["total"] for row in rows}
        return JSONResponse({"status": "success", "data": data, "error": None})

    @app.get("/api/reports/category-balance")
    async def api_category_balance(
        request: Request,
        sprint_id: Optional[str] = None,
        compare_sprint_id: Optional[str] = None,
    ):
        """Return category balance data for a sprint, optionally with comparison."""
        db = request.app.state.db_path
        payload: dict = {}
        if sprint_id is not None:
            payload["sprint_id"] = sprint_id
        primary = execute({"action": "category_report", "payload": payload}, db)

        if primary["status"] == "error":
            error_msg = primary["error"].lower()
            sc = 404 if ("not found" in error_msg or "no active sprint" in error_msg) else 500
            return JSONResponse(primary, status_code=sc)

        if compare_sprint_id:
            cmp = execute(
                {"action": "category_report", "payload": {"sprint_id": compare_sprint_id}}, db,
            )
            if cmp["status"] == "success":
                primary["data"]["comparison"] = cmp["data"]

        return JSONResponse(primary)

    @app.get("/api/reports/daily-scores")
    async def api_daily_scores(request: Request, sprint_id: Optional[str] = None):
        """Return daily completion scores for every day in a sprint."""
        from datetime import date as _date

        db = request.app.state.db_path
        conn = get_connection(db)

        # Resolve sprint
        if sprint_id:
            row = conn.execute("SELECT * FROM sprints WHERE id = ?", (sprint_id,)).fetchone()
            if row is None:
                return JSONResponse({"status": "error", "data": None, "error": "Sprint not found"}, status_code=404)
            sprint = dict(row)
        else:
            row = conn.execute(
                "SELECT * FROM sprints WHERE status = 'active' ORDER BY start_date LIMIT 1"
            ).fetchone()
            if row is None:
                return JSONResponse({"status": "error", "data": None, "error": "No active sprint"}, status_code=404)
            sprint = dict(row)
            sprint_id = sprint["id"]

        start = _date.fromisoformat(sprint["start_date"])
        end = _date.fromisoformat(sprint["end_date"])
        today = _date.today()
        if end > today:
            end = today

        scores = []
        current = start
        while current <= end:
            try:
                ds = execute(
                    {"action": "daily_score", "payload": {"date": current.isoformat(), "sprint_id": sprint_id}},
                    db,
                )
                pct = ds["data"]["completion_pct"] if ds["status"] == "success" else 0
            except Exception:
                pct = 0
            scores.append({"date": current.isoformat(), "completion_pct": pct})
            current += timedelta(days=1)

        return JSONResponse({
            "status": "success",
            "data": {
                "sprint_id": sprint_id,
                "start_date": sprint["start_date"],
                "end_date": sprint["end_date"],
                "scores": scores,
            },
            "error": None,
        })

    @app.get("/api/reports/habit-trend")
    async def api_habit_trend(request: Request, habit_id: Optional[str] = None):
        """Return weekly completion % data points for a habit across sprints.

        Query params:
            habit_id: required habit ID
        Returns JSON with weekly data points and sprint boundaries.
        """
        if not habit_id:
            return JSONResponse(
                {"status": "error", "data": None, "error": "habit_id is required"},
                status_code=400,
            )

        conn = get_connection(request.app.state.db_path)

        # Validate habit exists
        habit_row = conn.execute(
            "SELECT id, name, target_per_week FROM habits WHERE id = ?", (habit_id,)
        ).fetchone()
        if habit_row is None:
            return JSONResponse(
                {"status": "error", "data": None, "error": "Habit not found"},
                status_code=404,
            )

        target_per_week = habit_row["target_per_week"]

        # Get all sprints ordered chronologically
        sprint_rows = conn.execute(
            "SELECT id, start_date, end_date, theme FROM sprints ORDER BY start_date"
        ).fetchall()

        # Determine the overall date range from entries for this habit
        range_row = conn.execute(
            "SELECT MIN(date) as min_date, MAX(date) as max_date "
            "FROM entries WHERE habit_id = ? AND value > 0",
            (habit_id,),
        ).fetchone()

        if not range_row or not range_row["min_date"]:
            return JSONResponse({
                "status": "success",
                "data": {
                    "habit_id": habit_id,
                    "habit_name": habit_row["name"],
                    "weeks": [],
                    "sprints": [],
                    "rolling_average": [],
                },
                "error": None,
            })

        min_date = date.fromisoformat(range_row["min_date"])
        max_date = date.fromisoformat(range_row["max_date"])

        # Align to Monday boundaries
        week_start = min_date - timedelta(days=min_date.weekday())
        last_week_start = max_date - timedelta(days=max_date.weekday())

        # Build weekly data points
        weeks = []
        current = week_start
        while current <= last_week_start:
            week_end = current + timedelta(days=6)
            actual = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE habit_id = ? "
                "AND date >= ? AND date <= ? AND value > 0",
                (habit_id, current.isoformat(), week_end.isoformat()),
            ).fetchone()[0]
            pct = min(round(actual / target_per_week * 100), 100) if target_per_week > 0 else 0
            weeks.append({
                "week_start": current.isoformat(),
                "week_end": week_end.isoformat(),
                "actual_days": actual,
                "target_per_week": target_per_week,
                "completion_pct": pct,
            })
            current += timedelta(days=7)

        # Sprint boundaries
        sprints = []
        for sr in sprint_rows:
            sprints.append({
                "sprint_id": sr["id"],
                "start_date": sr["start_date"],
                "end_date": sr["end_date"],
                "label": sr["theme"] or sr["id"],
            })

        # 4-week rolling average
        rolling_average = []
        pcts = [w["completion_pct"] for w in weeks]
        window = 4
        for i in range(len(pcts)):
            start_idx = max(0, i - window + 1)
            avg = round(sum(pcts[start_idx:i + 1]) / (i - start_idx + 1), 1)
            rolling_average.append(avg)

        return JSONResponse({
            "status": "success",
            "data": {
                "habit_id": habit_id,
                "habit_name": habit_row["name"],
                "weeks": weeks,
                "sprints": sprints,
                "rolling_average": rolling_average,
            },
            "error": None,
        })

    @app.post("/sprints/{sprint_id}/archive")
    async def archive_sprint(request: Request, sprint_id: str):
        execute({"action": "archive_sprint", "payload": {"sprint_id": sprint_id}}, request.app.state.db_path)
        return RedirectResponse(url="/sprints", status_code=303)

    # --- Checkbox toggle endpoint (htmx) ---

    @app.post("/toggle/{habit_id}/{toggle_date}")
    async def toggle_habit(request: Request, habit_id: str, toggle_date: str, week: Optional[int] = None):
        """Toggle a habit entry and return updated HTML fragments."""
        db = request.app.state.db_path

        # Check current state via entries table
        conn = get_connection(db)
        row = conn.execute(
            "SELECT value, note FROM entries WHERE habit_id = ? AND date = ?",
            (habit_id, toggle_date),
        ).fetchone()

        if row and row[0] > 0:
            # Currently checked → delete
            result = execute({"action": "delete_entry", "payload": {"habit_id": habit_id, "date": toggle_date}}, db)
        else:
            # Currently unchecked → log
            result = execute({"action": "log_date", "payload": {"habit_id": habit_id, "date": toggle_date, "value": 1}}, db)

        if result["status"] == "error":
            return Response(
                content="",
                status_code=422,
                headers={"HX-Trigger": '{"showToast": "' + result["error"].replace('"', '\\"') + '"}'},
            )

        # Re-check new state
        new_row = conn.execute(
            "SELECT value, note FROM entries WHERE habit_id = ? AND date = ?",
            (habit_id, toggle_date),
        ).fetchone()
        checked = bool(new_row and new_row[0] > 0)
        note = (new_row[1] or "") if new_row else ""

        cell_html = _build_cell_html(habit_id, toggle_date, checked, note, week, css_class="just-toggled")

        # Compute updated daily total and habit done count (OOB swaps)
        dashboard_result = execute(
            {"action": "sprint_dashboard", "payload": ({"week": week} if week is not None else {})},
            db,
        )
        oob_html = ""
        if dashboard_result["status"] == "success":
            data = dashboard_result["data"]
            tot = data["daily_totals"].get(toggle_date, {"points": 0, "max": 0})
            total_id = f"total-{toggle_date}"
            oob_html = (
                f'<td id="{total_id}" class="pct-cell" hx-swap-oob="true">'
                f'{int(tot["points"])}/{int(tot["max"])}'
                f"</td>"
            )

            # Update the habit's Done cell
            import math
            sprint_start = date.fromisoformat(data["sprint"]["start_date"])
            sprint_end = date.fromisoformat(data["sprint"]["end_date"])
            if week is not None:
                num_wks = 1
            else:
                num_wks = math.ceil(((sprint_end - sprint_start).days + 1) / 7)
            for cat in data["categories"]:
                for h in cat["habits"]:
                    if h["habit_id"] == habit_id:
                        actual = h["week_actual"]
                        target_total = h["target_per_week"] * num_wks
                        pct = int(actual / target_total * 100) if target_total > 0 else 0
                        pct = min(pct, 100)
                        if pct >= 80:
                            bar_class = "progress-bar-success"
                        elif pct >= 50:
                            bar_class = "progress-bar-warning"
                        else:
                            bar_class = "progress-bar-danger"
                        tip = f'{actual} done / {h["target_per_week"]}/wk'
                        if num_wks > 1:
                            tip += f" &times; {num_wks} wks"
                        oob_html += (
                            f'<td id="done-{habit_id}" class="pct-cell" hx-swap-oob="true">'
                            f'<span class="has-tooltip">{actual}/{target_total}'
                            f'<span class="tooltip">{tip}</span></span>'
                            f'<div class="progress progress-sm progress-inline">'
                            f'<div class="progress-bar {bar_class}" style="width: {pct}%"></div>'
                            f'</div></td>'
                        )
                        break

        return HTMLResponse(content=cell_html + oob_html)

    # --- Note endpoint ---

    class NoteBody(BaseModel):
        note: str = ""

    @app.post("/note/{habit_id}/{note_date}")
    async def save_note(request: Request, habit_id: str, note_date: str, body: NoteBody, week: Optional[int] = None):
        """Save a note on an existing entry."""
        db = request.app.state.db_path
        conn = get_connection(db)
        row = conn.execute(
            "SELECT value, note FROM entries WHERE habit_id = ? AND date = ?",
            (habit_id, note_date),
        ).fetchone()

        if not row:
            return Response(content="", status_code=404)

        # Update note via log_date (upsert preserves value)
        note_text = body.note.strip() if body.note else None
        result = execute({"action": "log_date", "payload": {
            "habit_id": habit_id, "date": note_date, "value": row[0], "note": note_text,
        }}, db)

        if result["status"] == "error":
            return Response(content="", status_code=422)

        checked = row[0] > 0
        cell_html = _build_cell_html(habit_id, note_date, checked, note_text or "", week)
        return HTMLResponse(content=cell_html)

    # --- Settings / Database page ---

    @app.get("/settings", response_class=HTMLResponse)
    async def settings(request: Request):
        """Render the settings page with database info and stats."""
        import csv as _csv
        import io as _io

        db = request.app.state.db_path
        conn = get_connection(db)

        # File size
        try:
            size_bytes = os.path.getsize(db)
            if size_bytes < 1024:
                db_size = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                db_size = f"{size_bytes / 1024:.1f} KB"
            else:
                db_size = f"{size_bytes / (1024 * 1024):.1f} MB"
        except OSError:
            db_size = "unknown"

        # Schema version
        try:
            schema_version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        except Exception:
            schema_version = "unknown"

        # Stats
        habits = conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0]
        archived_habits = conn.execute("SELECT COUNT(*) FROM habits WHERE archived = 1").fetchone()[0]
        sprints = conn.execute("SELECT COUNT(*) FROM sprints").fetchone()[0]
        active_sprints = conn.execute("SELECT COUNT(*) FROM sprints WHERE status = 'active'").fetchone()[0]
        archived_sprints = conn.execute("SELECT COUNT(*) FROM sprints WHERE status = 'archived'").fetchone()[0]
        entries = conn.execute("SELECT COUNT(*) FROM entries WHERE value > 0").fetchone()[0]
        date_range = conn.execute("SELECT MIN(date), MAX(date) FROM entries WHERE value > 0").fetchone()
        retros = conn.execute("SELECT COUNT(*) FROM retros").fetchone()[0]

        has_shg = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sprint_habit_goals'").fetchone()[0]
        shg_count = 0
        if has_shg:
            shg_count = conn.execute("SELECT COUNT(*) FROM sprint_habit_goals").fetchone()[0]

        stats = {
            "habits": habits,
            "archived_habits": archived_habits,
            "sprints": sprints,
            "active_sprints": active_sprints,
            "archived_sprints": archived_sprints,
            "entries": entries,
            "min_date": date_range[0] if date_range else None,
            "max_date": date_range[1] if date_range else None,
            "retros": retros,
            "has_sprint_habit_goals": bool(has_shg),
            "sprint_habit_goals": shg_count,
        }

        from habit_sprint import __version__

        return templates.TemplateResponse("settings.html", {
            "request": request,
            "active_nav": "settings",
            "db_path": os.path.abspath(db),
            "db_size": db_size,
            "schema_version": schema_version,
            "stats": stats,
            "version": __version__,
        })

    @app.get("/export/{table_name}.csv")
    async def export_csv(request: Request, table_name: str):
        """Export a database table as CSV."""
        import csv as _csv
        import io as _io

        allowed = {"habits", "sprints", "entries", "retros", "sprint_habit_goals"}
        if table_name not in allowed:
            return JSONResponse({"error": f"Unknown table: {table_name}"}, status_code=404)

        conn = get_connection(request.app.state.db_path)

        # Check table exists
        exists = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        ).fetchone()[0]
        if not exists:
            return JSONResponse({"error": f"Table {table_name} does not exist"}, status_code=404)

        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()  # noqa: S608 — table_name is validated above

        output = _io.StringIO()
        if rows:
            writer = _csv.writer(output)
            writer.writerow(rows[0].keys())
            for row in rows:
                writer.writerow(tuple(row))
        else:
            output.write("(empty table)\n")

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{table_name}.csv"'},
        )

    return app


# Module-level app instance for uvicorn reload mode (uses HABIT_SPRINT_DB env var)
app = create_app(db_path=os.environ.get("HABIT_SPRINT_DB", DEFAULT_DB_PATH))
