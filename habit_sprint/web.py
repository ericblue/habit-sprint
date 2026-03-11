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
    async def dashboard(request: Request, week: Optional[int] = None):
        """Render the dashboard for the active sprint."""
        payload: dict = {}
        if week is not None:
            payload["week"] = week
        result = execute({"action": "sprint_dashboard", "payload": payload}, db_path)

        if result["status"] == "error":
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

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "active_nav": "dashboard",
            "data": data,
            "dates": view_dates,
            "week": week,
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
    async def habits_list(request: Request):
        result = execute(
            {"action": "list_habits", "payload": {"include_archived": True}},
            request.app.state.db_path,
        )
        habits = result["data"]["habits"] if result["status"] == "success" else []
        return templates.TemplateResponse(
            "habits_list.html",
            {
                "request": request,
                "habits": habits,
                "active_nav": "habits",
                "success_message": request.query_params.get("msg"),
            },
        )

    @app.get("/habits/new")
    async def habit_new_form(request: Request):
        return templates.TemplateResponse(
            "habit_form.html",
            {
                "request": request,
                "editing": False,
                "form_action": "/habits",
                "values": {},
                "error": None,
                "active_nav": "habits",
            },
        )

    @app.post("/habits")
    async def habit_create(
        request: Request,
        name: str = Form(...),
        id: str = Form(...),
        category: str = Form(...),
        target_per_week: int = Form(...),
        weight: int = Form(...),
        unit: str = Form(...),
    ):
        payload = {
            "id": id,
            "name": name,
            "category": category,
            "target_per_week": target_per_week,
            "weight": weight,
            "unit": unit,
        }
        result = execute({"action": "create_habit", "payload": payload}, request.app.state.db_path)
        if result["status"] == "error":
            return templates.TemplateResponse(
                "habit_form.html",
                {
                    "request": request,
                    "editing": False,
                    "form_action": "/habits",
                    "values": payload,
                    "error": result["error"],
                    "active_nav": "habits",
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
        return templates.TemplateResponse(
            "habit_form.html",
            {
                "request": request,
                "editing": True,
                "form_action": f"/habits/{habit_id}/edit",
                "values": habit,
                "error": None,
                "active_nav": "habits",
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
    ):
        payload = {
            "id": habit_id,
            "name": name,
            "category": category,
            "target_per_week": target_per_week,
            "weight": weight,
            "unit": unit,
        }
        result = execute({"action": "update_habit", "payload": payload}, request.app.state.db_path)
        if result["status"] == "error":
            return templates.TemplateResponse(
                "habit_form.html",
                {
                    "request": request,
                    "editing": True,
                    "form_action": f"/habits/{habit_id}/edit",
                    "values": payload,
                    "error": result["error"],
                    "active_nav": "habits",
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

    # --- Sprint management pages ---

    @app.get("/sprints", response_class=HTMLResponse)
    async def sprints_list(request: Request):
        result = execute({"action": "list_sprints", "payload": {}}, request.app.state.db_path)
        sprints = result["data"]["sprints"] if result["status"] == "success" else []
        error = result.get("error") if result["status"] == "error" else None
        return templates.TemplateResponse("sprints_list.html", {
            "request": request, "sprints": sprints, "error": error, "active_nav": "sprints",
        })

    @app.get("/sprints/new", response_class=HTMLResponse)
    async def sprint_form(request: Request):
        return templates.TemplateResponse("sprint_form.html", {
            "request": request, "error": None, "active_nav": "sprints", "values": {},
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

        # Compute updated daily total for this date (OOB swap)
        dashboard_result = execute(
            {"action": "sprint_dashboard", "payload": ({"week": week} if week is not None else {})},
            db,
        )
        oob_html = ""
        if dashboard_result["status"] == "success":
            tot = dashboard_result["data"]["daily_totals"].get(toggle_date, {"points": 0, "max": 0})
            total_id = f"total-{toggle_date}"
            oob_html = (
                f'<td id="{total_id}" class="pct-cell" hx-swap-oob="true">'
                f'{int(tot["points"])}/{int(tot["max"])}'
                f"</td>"
            )

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

    return app
