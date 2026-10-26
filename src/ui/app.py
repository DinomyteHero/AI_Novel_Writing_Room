"""FastAPI application factory for the read-only writers' room console.

This server is intentionally a viewer: manuscript pages and ledger events.
All mutating operations (planning, compiling, drafting, exporting) run through
the CLI. Keeping writes out of the web app removes the pipeline-control state
machine, the worldbuilding CRUD surface, and the unauthenticated run trigger.
"""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from src.project_paths import ProjectPaths
from src.run_ledger import RunLedger

logger = logging.getLogger(__name__)


class AppState:
    """Application-wide read-only state."""

    def __init__(self) -> None:
        self.config: dict = {}
        self.concept_seed: dict = {}
        self.concept_seed_path: str = ""
        self.manuscripts_dir: str = "output/_fallback/manuscripts"
        self.export_dir: str = "output/_fallback/export"
        self.phase: int = 1
        self.ledger: Optional[RunLedger] = None


def get_app_state(request: Request) -> AppState:
    """Retrieve the AppState from the request."""
    return request.app.state._app_state


def create_app(
    config_path: str = "config/settings.yaml",
    concept_seed_path: Optional[str] = None,
    phase: int = 1,
) -> FastAPI:
    """Create and configure the read-only FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state: AppState = app.state._app_state

        with open(config_path, encoding="utf-8") as f:
            state.config = yaml.safe_load(f) or {}
        state.phase = phase

        if concept_seed_path:
            state.concept_seed_path = concept_seed_path
            with open(concept_seed_path, encoding="utf-8") as f:
                state.concept_seed = json.load(f)

        paths = (
            ProjectPaths.from_concept_seed(state.concept_seed)
            if state.concept_seed
            else ProjectPaths("untitled")
        )
        state.manuscripts_dir = state.config.get("pipeline", {}).get(
            "chapter_output_dir", str(paths.manuscripts_dir)
        )
        state.export_dir = str(paths.export_dir)
        state.ledger = RunLedger(db_path=str(paths.run_ledger_db))

        logger.info("Read-only console started (phase=%d)", phase)
        yield

        if state.ledger is not None:
            try:
                state.ledger.close()
            except Exception:
                logger.exception("Error closing ledger")

        logger.info("Application shut down")

    app = FastAPI(
        title="AI Writers' Room",
        description="Read-only manuscript and ledger viewer",
        version="0.6.0",
        lifespan=lifespan,
    )
    app.state._app_state = AppState()

    @app.get("/api/health")
    async def health(request: Request):
        state = get_app_state(request)
        return {
            "status": "ok",
            "deployment_mode": state.config.get("deployment_mode", "unknown"),
            "phase": state.phase,
            "pipeline_state": "read_only",
        }

    from src.ui.routes.chapters import router as chapters_router
    from src.ui.routes.ledger import router as ledger_router

    app.include_router(chapters_router, prefix="/api")
    app.include_router(ledger_router, prefix="/api")

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists() and any(static_dir.iterdir()):
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
