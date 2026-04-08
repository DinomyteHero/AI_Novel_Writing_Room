"""Shared test fixtures for Phase 5 API tests.

Manually initializes app state since ASGITransport does not run FastAPI lifespan.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def create_test_app(
    settings_yaml: str,
    concept_seed_path: str,
    phase: int = 1,
    manuscripts_dir: str = "",
    scene_cards_dir: str = "",
):
    """Create a FastAPI app with state manually initialized (no lifespan)."""
    from src.ui.app import create_app, AppState
    from src.ui.connection_manager import ConnectionManager
    from src.ui.pipeline_manager import PipelineManager
    from src.ui.websocket_ledger import WebSocketLedger
    from src.model_router import ModelRouter

    app = create_app(config_path=settings_yaml, concept_seed_path=concept_seed_path, phase=phase)

    # Manually initialize state (lifespan won't run in ASGITransport tests)
    state: AppState = app.state._app_state

    import yaml
    with open(settings_yaml, encoding="utf-8") as f:
        state.config = yaml.safe_load(f)

    state.phase = phase
    state.concept_seed_path = concept_seed_path

    with open(concept_seed_path, encoding="utf-8") as f:
        state.concept_seed = json.load(f)

    pipeline_cfg = state.config.get("pipeline", {})
    state.manuscripts_dir = manuscripts_dir or pipeline_cfg.get("chapter_output_dir", "data/manuscripts")

    if scene_cards_dir:
        state.scene_cards_dir = scene_cards_dir

    # Use a mock router (avoid real HTTP connections)
    state.router = MagicMock()
    state.router.mode = "local"
    state.router.complete = AsyncMock(return_value="Mock response")
    state.router.close = AsyncMock()

    # In-memory ledger (temp SQLite)
    import tempfile
    ledger_path = str(Path(tempfile.mkdtemp()) / "test_ledger.db")
    state.event_queue = asyncio.Queue(maxsize=10000)
    state.ledger = WebSocketLedger(db_path=ledger_path, queue=state.event_queue)

    # Connection manager (without broadcaster for tests)
    state.connection_manager = ConnectionManager(state.event_queue)

    # Pipeline manager
    state.pipeline_manager = PipelineManager()

    # Phase 2: Story state
    if phase >= 2:
        try:
            from src.memory.story_state import StoryState
            from src.memory.knowledge_layers import KnowledgeLayers

            state_path = str(Path(tempfile.mkdtemp()) / "test_state.db")
            state.story_state = StoryState(db_path=state_path)
            state.story_state.init_from_concept_seed(state.concept_seed)
            state.knowledge_layers = KnowledgeLayers(state.story_state)
        except ImportError:
            pass

    return app
