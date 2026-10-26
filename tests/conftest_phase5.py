"""Shared test fixtures for read-only API tests.

Manually initializes app state because ASGITransport does not run the FastAPI
lifespan.
"""

import json
import tempfile
from pathlib import Path

import yaml


def create_test_app(
    settings_yaml: str,
    concept_seed_path: str,
    phase: int = 1,
    manuscripts_dir: str = "",
    scene_cards_dir: str = "",
):
    """Create a FastAPI app with read-only state initialized (no lifespan)."""
    from src.run_ledger import RunLedger
    from src.ui.app import AppState, create_app

    app = create_app(
        config_path=settings_yaml,
        concept_seed_path=concept_seed_path,
        phase=phase,
    )
    state: AppState = app.state._app_state

    with open(settings_yaml, encoding="utf-8") as f:
        state.config = yaml.safe_load(f) or {}
    state.phase = phase
    state.concept_seed_path = concept_seed_path
    with open(concept_seed_path, encoding="utf-8") as f:
        state.concept_seed = json.load(f)

    pipeline_cfg = state.config.get("pipeline", {})
    state.manuscripts_dir = manuscripts_dir or pipeline_cfg.get(
        "chapter_output_dir", "data/manuscripts",
    )
    state.ledger = RunLedger(
        db_path=str(Path(tempfile.mkdtemp()) / "test_ledger.db")
    )
    return app
