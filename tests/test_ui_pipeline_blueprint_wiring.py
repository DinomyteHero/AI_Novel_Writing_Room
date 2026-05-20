"""Tests for Phase 5 wiring in src/ui/routes/pipeline.py.

Mirrors tests/test_main_blueprint_wiring.py for the UI route. Covers the
_ensure_chapter_blueprints helper (UI variant) and the PipelineStartRequest
fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.ui.routes.pipeline import (
    PipelineStartRequest,
    _ensure_chapter_blueprints,
)


@pytest.fixture
def sample_scene_cards():
    return [
        {"chapter_number": 1, "scene_number": 1, "scene_role": "hook", "target_word_count": 1000, "pov_character": "A"},
        {"chapter_number": 2, "scene_number": 1, "scene_role": "hook", "target_word_count": 1000, "pov_character": "A"},
    ]


@pytest.fixture
def mock_synthesizer_router():
    router = MagicMock()
    router.complete_structured = AsyncMock(return_value={
        "chapter_mission": "x", "chapter_turn": "y",
        "scene_purposes": [{"scene_number": 1, "purpose": "p"}],
        "pacing_curve": "rising", "exit_vector": "v",
        "relationship_turns": [], "notes": "",
    })
    return router


@pytest.fixture
def mock_ledger():
    return MagicMock()


# --------------------------------------------------------------------------- #
# PipelineStartRequest schema                                                  #
# --------------------------------------------------------------------------- #


class TestPipelineStartRequestPhase5:
    def test_generate_blueprints_defaults_true(self):
        req = PipelineStartRequest()
        assert req.generate_blueprints is True

    def test_regenerate_blueprints_defaults_false(self):
        req = PipelineStartRequest()
        assert req.regenerate_blueprints is False

    def test_can_opt_out_of_blueprint_generation(self):
        req = PipelineStartRequest(generate_blueprints=False)
        assert req.generate_blueprints is False

    def test_can_request_regeneration(self):
        req = PipelineStartRequest(regenerate_blueprints=True)
        assert req.regenerate_blueprints is True


# --------------------------------------------------------------------------- #
# _ensure_chapter_blueprints (UI variant)                                      #
# --------------------------------------------------------------------------- #


class TestUiEnsureChapterBlueprints:
    @pytest.mark.asyncio
    async def test_generates_missing_blueprints(
        self, sample_scene_cards, mock_synthesizer_router, mock_ledger,
        tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        await _ensure_chapter_blueprints(
            router=mock_synthesizer_router,
            ledger=mock_ledger,
            concept_seed={},
            scene_cards=sample_scene_cards,
            franchise_slug="ui-fr",
            book_slug="ui-bk",
        )

        bp_dir = tmp_path / "data" / "franchises" / "ui-fr" / "books" / "ui-bk" / "chapter_blueprints"
        assert (bp_dir / "chapter_01.json").exists()
        assert (bp_dir / "chapter_02.json").exists()

        # Ledger event emitted for the UI route too
        mock_ledger.emit.assert_called_once()
        args, kwargs = mock_ledger.emit.call_args
        assert args[0] == "chapter_blueprints_generated"

    @pytest.mark.asyncio
    async def test_preserves_hand_authored(
        self, sample_scene_cards, mock_synthesizer_router, mock_ledger,
        tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        bp_dir = tmp_path / "data" / "franchises" / "ui-fr" / "books" / "ui-bk" / "chapter_blueprints"
        bp_dir.mkdir(parents=True)
        sentinel = {"chapter_number": 1, "chapter_mission": "HAND"}
        (bp_dir / "chapter_01.json").write_text(json.dumps(sentinel), encoding="utf-8")

        await _ensure_chapter_blueprints(
            router=mock_synthesizer_router,
            ledger=mock_ledger,
            concept_seed={},
            scene_cards=sample_scene_cards,
            franchise_slug="ui-fr",
            book_slug="ui-bk",
        )

        loaded = json.loads((bp_dir / "chapter_01.json").read_text(encoding="utf-8"))
        assert loaded == sentinel
        assert (bp_dir / "chapter_02.json").exists()
        assert mock_synthesizer_router.complete_structured.call_count == 1

    @pytest.mark.asyncio
    async def test_noop_when_no_cards(
        self, mock_synthesizer_router, mock_ledger, tmp_path, monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        await _ensure_chapter_blueprints(
            router=mock_synthesizer_router,
            ledger=mock_ledger,
            concept_seed={},
            scene_cards=[],
            franchise_slug="ui-fr",
            book_slug="ui-bk",
        )
        mock_synthesizer_router.complete_structured.assert_not_called()
        mock_ledger.emit.assert_not_called()


# --------------------------------------------------------------------------- #
# Plumbing: blueprint helper wired into the UI start-pipeline route           #
# --------------------------------------------------------------------------- #


class TestUiPhase5Plumbing:
    """Static checks on the source of pipeline.py confirm the blueprint
    plumbing survives future edits."""

    def test_pipeline_py_passes_line_writer_to_web_orchestrator(self):
        src = (Path(__file__).parent.parent / "src" / "ui" / "routes" / "pipeline.py").read_text(encoding="utf-8")
        assert "line_writer=line_writer" in src

    def test_pipeline_py_calls_blueprint_helper_in_start_pipeline(self):
        src = (Path(__file__).parent.parent / "src" / "ui" / "routes" / "pipeline.py").read_text(encoding="utf-8")
        # Helper definition + at least one invocation
        assert src.count("_ensure_chapter_blueprints(") >= 2
