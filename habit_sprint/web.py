"""FastAPI web adapter for Habit Sprint."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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

    # --- Web page routes ---

    @app.get("/sprints", response_class=HTMLResponse)
    async def sprints_list(request: Request):
        result = execute({"action": "list_sprints", "payload": {}}, db_path)
        sprints = result["data"]["sprints"] if result["status"] == "success" else []
        error = result.get("error") if result["status"] == "error" else None
        return templates.TemplateResponse("sprints_list.html", {
            "request": request, "sprints": sprints, "error": error,
        })

    @app.get("/sprints/new", response_class=HTMLResponse)
    async def sprint_form(request: Request):
        return templates.TemplateResponse("sprint_form.html", {
            "request": request, "error": None,
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
        payload = {
            "start_date": start_date,
            "end_date": end_date,
            "theme": theme or None,
            "focus_goals": goals,
        }
        result = execute({"action": "create_sprint", "payload": payload}, db_path)
        if result["status"] == "error":
            return templates.TemplateResponse("sprint_form.html", {
                "request": request, "error": result["error"],
            })
        return RedirectResponse(url="/sprints", status_code=303)

    @app.get("/sprints/{sprint_id}", response_class=HTMLResponse)
    async def sprint_detail(request: Request, sprint_id: str):
        # Get sprint info via list_sprints and filter
        list_result = execute({"action": "list_sprints", "payload": {}}, db_path)
        sprint = None
        if list_result["status"] == "success":
            for s in list_result["data"]["sprints"]:
                if s["id"] == sprint_id:
                    sprint = s
                    break
        if sprint is None:
            return HTMLResponse("Sprint not found", status_code=404)

        # Try to get retro
        retro = None
        retro_result = execute({"action": "get_retro", "payload": {"sprint_id": sprint_id}}, db_path)
        if retro_result["status"] == "success":
            retro = retro_result["data"]

        return templates.TemplateResponse("sprint_detail.html", {
            "request": request, "sprint": sprint, "retro": retro,
        })

    @app.post("/sprints/{sprint_id}/archive")
    async def archive_sprint(request: Request, sprint_id: str):
        execute({"action": "archive_sprint", "payload": {"sprint_id": sprint_id}}, db_path)
        return RedirectResponse(url="/sprints", status_code=303)

    return app
