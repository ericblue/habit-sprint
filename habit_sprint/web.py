"""FastAPI web adapter for Habit Sprint."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
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

    return app
