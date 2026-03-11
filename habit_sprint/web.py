"""FastAPI web adapter for Habit Sprint."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from habit_sprint.db import get_connection

DEFAULT_DB_DIR = os.path.join(os.path.expanduser("~"), ".habit-sprint")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, "habits.db")

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent / "static"


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

    # Jinja2 templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.templates = templates

    # Static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
