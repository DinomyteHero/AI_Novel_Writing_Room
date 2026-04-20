"""Orchestrator trusts upstream physics validation.

When the concept_seed carries ``compile_metadata.physics_validated = True``,
the compile-time validator in ``scripts/compile_bundle.py`` has already
covered the full corpus. The pipeline's per-scene pre-chapter check would
only duplicate work in that case, so the orchestrator skips it and emits
a ``physics_pre_skipped_upstream_validated`` ledger event instead.

When the flag is missing or False, the orchestrator falls through to the
advisory pre-chapter check so hand-edited seeds or legacy projects still
get coverage.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator import Orchestrator
from src.run_ledger import RunLedger


@pytest.fixture
def ledger(temp_dir):
    _ledger = RunLedger(db_path=str(Path(temp_dir) / "physics_skip_ledger.db"))
    yield _ledger
    _ledger.close()


@pytest.fixture
def mock_assembler_with_seed():
    """Assembler factory — call with a dict to set concept_seed."""
    def _make(concept_seed: dict):
        assembler = MagicMock()
        assembler.concept_seed = concept_seed
        assembler.get_bible_summary.return_value = "Test bible summary"
        assembler.assemble.return_value = "Test assembled context"
        assembler.get_negative_constraints.return_value = "Test constraints"
        return assembler
    return _make


@pytest.fixture
def mock_physics_enforcer():
    enf = MagicMock()
    enf.validate_pre_chapter.return_value = {
        "passed": True, "issues": [], "recommendations": [],
    }
    enf.validate_post_chapter.return_value = {"passed": True, "issues": []}
    return enf


def _build_orchestrator(
    mock_router, assembler, ledger, temp_dir, physics_enforcer,
):
    mock_router.complete = AsyncMock(return_value="Mock prose output for the scene.")
    mock_router.complete_structured = AsyncMock(return_value={
        "verdict": "pass",
        "failure_codes": [],
        "severity": "non_blocking",
        "route_to": None,
        "structural_score": 0.85,
        "voice_score": 0.80,
        "polish_score": 0.75,
    })
    return Orchestrator(
        router=mock_router,
        context_assembler=assembler,
        ledger=ledger,
        manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        physics_enforcer=physics_enforcer,
    )


@pytest.mark.asyncio
async def test_skips_pre_chapter_when_upstream_validated(
    mock_router, mock_assembler_with_seed, mock_physics_enforcer,
    ledger, temp_dir, sample_scene_card,
):
    seed = {"compile_metadata": {"physics_validated": True}}
    assembler = mock_assembler_with_seed(seed)
    orch = _build_orchestrator(
        mock_router, assembler, ledger, temp_dir, mock_physics_enforcer,
    )

    await orch.run_chapter(sample_scene_card)

    mock_physics_enforcer.validate_pre_chapter.assert_not_called()

    events = ledger.get_events()
    event_types = [e["event_type"] for e in events]
    assert "physics_pre_skipped_upstream_validated" in event_types
    assert "physics_validation_pre" not in event_types


@pytest.mark.asyncio
async def test_runs_pre_chapter_when_flag_absent(
    mock_router, mock_assembler_with_seed, mock_physics_enforcer,
    ledger, temp_dir, sample_scene_card,
):
    seed: dict = {}  # no compile_metadata at all
    assembler = mock_assembler_with_seed(seed)
    orch = _build_orchestrator(
        mock_router, assembler, ledger, temp_dir, mock_physics_enforcer,
    )

    await orch.run_chapter(sample_scene_card)

    mock_physics_enforcer.validate_pre_chapter.assert_called_once()
    event_types = [e["event_type"] for e in ledger.get_events()]
    assert "physics_validation_pre" in event_types
    assert "physics_pre_skipped_upstream_validated" not in event_types


@pytest.mark.asyncio
async def test_runs_pre_chapter_when_flag_false(
    mock_router, mock_assembler_with_seed, mock_physics_enforcer,
    ledger, temp_dir, sample_scene_card,
):
    seed = {"compile_metadata": {"physics_validated": False}}
    assembler = mock_assembler_with_seed(seed)
    orch = _build_orchestrator(
        mock_router, assembler, ledger, temp_dir, mock_physics_enforcer,
    )

    await orch.run_chapter(sample_scene_card)

    mock_physics_enforcer.validate_pre_chapter.assert_called_once()
    event_types = [e["event_type"] for e in ledger.get_events()]
    assert "physics_validation_pre" in event_types
