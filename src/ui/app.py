"""FastAPI application factory for the AI Writers' Room web interface.

Creates and configures the FastAPI app with CORS, static file serving,
lifespan management, and all API routes.
"""

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.model_router import ModelRouter
from src.project_paths import ProjectPaths
from src.ui.connection_manager import ConnectionManager
from src.ui.pipeline_manager import PipelineManager
from src.ui.websocket_ledger import WebSocketLedger

logger = logging.getLogger(__name__)


class AppState:
    """Application-wide shared state."""

    def __init__(self):
        self.router: Optional[ModelRouter] = None
        self.ledger: Optional[WebSocketLedger] = None
        self.story_state = None
        self.knowledge_layers = None
        self.chapter_memory = None
        self.config: dict = {}
        self.concept_seed: dict = {}
        self.concept_seed_path: str = ""
        self.scene_cards_dir: str = ""
        self.manuscripts_dir: str = "data/manuscripts"
        self.export_dir: str = "data/export"
        self.phase: int = 4
        self.pipeline_manager: PipelineManager = PipelineManager()
        self.connection_manager: Optional[ConnectionManager] = None
        self.event_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self.pipeline_session = None
        self.export_manager = None
        self.scene_card_generator = None
        self.embedding_function = None
        self.lore_service = None


def get_app_state(request: Request) -> AppState:
    """Retrieve the AppState from the request."""
    return request.app.state._app_state


def create_app(
    config_path: str = "config/settings.yaml",
    concept_seed_path: Optional[str] = None,
    phase: int = 4,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Initialize and tear down application resources."""
        state: AppState = app.state._app_state

        # Load config
        with open(config_path, encoding="utf-8") as f:
            state.config = yaml.safe_load(f)

        state.phase = phase
        pipeline_cfg = state.config.get("pipeline", {})

        # Load concept seed if provided
        if concept_seed_path:
            state.concept_seed_path = concept_seed_path
            with open(concept_seed_path, encoding="utf-8") as f:
                state.concept_seed = json.load(f)

            # Infer scene cards dir from concept seed path
            seed_dir = Path(concept_seed_path).parent
            scene_cards_dir = seed_dir / "scene_cards"
            if scene_cards_dir.exists():
                state.scene_cards_dir = str(scene_cards_dir)

        # Resolve project-scoped paths
        paths = ProjectPaths.from_concept_seed(state.concept_seed)
        paths.ensure_dirs()
        state.manuscripts_dir = pipeline_cfg.get(
            "chapter_output_dir", str(paths.manuscripts_dir)
        )
        state.export_dir = str(paths.export_dir)

        # Initialize ModelRouter
        state.router = ModelRouter(config_path)

        # Initialize WebSocketLedger (project-scoped)
        ledger_path = str(paths.run_ledger_db)
        state.ledger = WebSocketLedger(db_path=ledger_path, queue=state.event_queue)

        # Initialize Phase 2+ components if available
        if phase >= 2 and concept_seed_path:
            _init_story_state(state, concept_seed_path, pipeline_cfg, paths=paths)

        # Initialize Phase 4 components if available
        if phase >= 4:
            _init_phase4_components(state)

        # Initialize worldbuilding service
        _init_worldbuilding(state, state.config, paths=paths)

        # Start connection manager and broadcaster
        state.connection_manager = ConnectionManager(state.event_queue)
        await state.connection_manager.start_broadcaster()

        logger.info("Application started (phase=%d, mode=%s)", phase, state.router.mode)

        yield

        # Shutdown — each component wrapped individually so one failure
        # doesn't prevent the rest from cleaning up.
        state.pipeline_manager.reset()

        for label, closer in [
            ("connection_manager", state.connection_manager.stop_broadcaster),
            ("router", state.router.close),
        ]:
            try:
                await closer()
            except Exception:
                logger.exception("Error shutting down %s", label)

        for label, obj in [
            ("ledger", state.ledger),
            ("story_state", state.story_state),
            ("chapter_memory", state.chapter_memory),
            ("lore_service", state.lore_service),
        ]:
            if obj is not None and hasattr(obj, "close"):
                try:
                    obj.close()
                except Exception:
                    logger.exception("Error closing %s", label)

        logger.info("Application shut down")

    app = FastAPI(
        title="AI Writers' Room",
        description="Multi-agent fiction generation pipeline",
        version="0.5.0",
        lifespan=lifespan,
    )

    # Store AppState on the app
    app.state._app_state = AppState()

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",  # Vite dev server
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health endpoint
    @app.get("/api/health")
    async def health(request: Request):
        state = get_app_state(request)
        return {
            "status": "ok",
            "deployment_mode": state.router.mode if state.router else "unknown",
            "phase": state.phase,
            "pipeline_state": state.pipeline_manager.state.value,
        }

    # Register route modules
    from src.ui.routes.pipeline import router as pipeline_router
    from src.ui.routes.chapters import router as chapters_router
    from src.ui.routes.story_state import router as story_state_router
    from src.ui.routes.scene_cards import router as scene_cards_router
    from src.ui.routes.ledger import router as ledger_router
    from src.ui.routes.websocket import router as websocket_router
    from src.ui.routes.worldbuilding import router as worldbuilding_router

    app.include_router(pipeline_router, prefix="/api")
    app.include_router(chapters_router, prefix="/api")
    app.include_router(story_state_router, prefix="/api")
    app.include_router(scene_cards_router, prefix="/api")
    app.include_router(ledger_router, prefix="/api")
    app.include_router(websocket_router, prefix="/api")
    app.include_router(worldbuilding_router, prefix="/api")

    # Serve static files (React build) if available
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists() and any(static_dir.iterdir()):
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


def _init_story_state(state: AppState, concept_seed_path: str, pipeline_cfg: dict,
                      paths: "ProjectPaths | None" = None) -> None:
    """Initialize Phase 2 story state components."""
    try:
        from src.memory.story_state import StoryState
        from src.memory.knowledge_layers import KnowledgeLayers

        state_db_path = str(paths.story_state_db) if paths else pipeline_cfg.get(
            "story_state_path", "data/story_state.db"
        )
        state.story_state = StoryState(db_path=state_db_path)
        state.story_state.init_from_concept_seed(state.concept_seed)
        state.knowledge_layers = KnowledgeLayers(state.story_state)

        # Chapter memory
        try:
            from src.memory.chapter_memory import ChapterMemory
            from src.rag.embedding import get_embedding_function

            ef = get_embedding_function(use_mock=True)
            state.embedding_function = ef
            chapter_memory_dir = str(paths.chapter_memory_dir) if paths else pipeline_cfg.get(
                "chapter_memory_dir", "data/chapter_memory"
            )
            state.chapter_memory = ChapterMemory(
                persist_directory=chapter_memory_dir,
                embedding_function=ef,
            )
        except (ImportError, Exception) as e:
            logger.warning("ChapterMemory not available: %s", e)

    except ImportError as e:
        logger.warning("Phase 2 components not available: %s", e)


def _init_worldbuilding(state: AppState, config: dict,
                        paths: "ProjectPaths | None" = None) -> None:
    """Initialize the worldbuilding persistence layer."""
    try:
        from src.worldbuilding.worldbuilding_db import WorldbuildingDB
        from src.worldbuilding.lore_vectorstore import LoreVectorStore
        from src.worldbuilding.lore_service import LoreService

        wb_config = config.get("worldbuilding", {})
        db_path = wb_config.get("db_path", str(paths.worldbuilding_db) if paths else "data/worldbuilding.db")
        vectors_dir = wb_config.get(
            "vectors_dir", str(paths.worldbuilding_vectors_dir) if paths else "data/worldbuilding_vectors"
        )

        ef = state.embedding_function
        wb_db = WorldbuildingDB(db_path=db_path)
        wb_vs = LoreVectorStore(persist_directory=vectors_dir, embedding_function=ef)
        state.lore_service = LoreService(db=wb_db, vectorstore=wb_vs)

        logger.info("Worldbuilding service initialized (db=%s)", db_path)
    except (ImportError, Exception) as e:
        logger.warning("Worldbuilding service not available: %s", e)


def _init_phase4_components(state: AppState) -> None:
    """Initialize Phase 4 components (pipeline session, export, scene card gen)."""
    try:
        from src.pipeline_session import PipelineSession
        state.pipeline_session = PipelineSession()
    except ImportError:
        pass

    try:
        from src.export.export_manager import ExportManager
        if state.concept_seed:
            state.export_manager = ExportManager(state.manuscripts_dir, state.concept_seed)
    except ImportError:
        pass

    try:
        from src.planning.scene_card_generator import SceneCardGenerator
        from src.planning.physics_enforcer import PhysicsEnforcer
        if state.concept_seed and state.router:
            pe = PhysicsEnforcer(state.concept_seed)
            state.scene_card_generator = SceneCardGenerator(state.router, pe)
    except ImportError:
        pass
