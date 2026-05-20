"""Tests for the lean Orchestrator pipeline.

The relay refactor removed the gate/polish/canon/save-blocker stack. The
orchestrator now runs a forward-only lean path: PlotArchitect -> ProseStylist
-> [LineWriter] -> [RhythmValidator/Editor] -> save. These tests pin the
lean flow and its ledger telemetry.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator import Orchestrator
from src.run_ledger import RunLedger


class TestOrchestratorPipeline:
    """Test the orchestrator's lean pipeline flow."""

    @pytest.fixture
    def ledger(self, temp_dir):
        _ledger = RunLedger(db_path=str(Path(temp_dir) / "test_ledger.db"))
        yield _ledger
        _ledger.close()

    @pytest.fixture
    def mock_assembler(self):
        assembler = MagicMock()
        assembler.get_bible_summary.return_value = "Test bible summary"
        assembler.assemble.return_value = "Test assembled context"
        assembler.get_negative_constraints.return_value = "Test constraints"
        return assembler

    @pytest.fixture
    def orchestrator(self, mock_router, mock_assembler, ledger, temp_dir):
        # Configure mock router for the lean pipeline.
        mock_router.complete = AsyncMock(return_value="Mock prose output for the scene.")
        mock_router.complete_structured = AsyncMock(return_value={
            "scene_objective": "Mock objective.",
            "turning_point": {"trigger": "t", "shift": "s", "cost": "c"},
            "closing_beat": "Mock closing beat.",
            "emotional_arc": {"start": "a", "shift": "b", "end": "c"},
            "target_word_count": 1000,
        })

        return Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

    @pytest.mark.asyncio
    async def test_single_chapter_pipeline(self, orchestrator, sample_scene_card, ledger):
        result = await orchestrator.run_chapter(sample_scene_card)

        assert result["chapter_number"] == 1
        assert result["scene_number"] == 1
        assert result["evaluation"]["verdict"] == "skipped"
        assert result["word_count"] > 0
        assert Path(result["output_path"]).exists()

    @pytest.mark.asyncio
    async def test_pipeline_emits_events(self, orchestrator, sample_scene_card, ledger):
        await orchestrator.run_chapter(sample_scene_card)

        events = ledger.get_events()
        event_types = [e["event_type"] for e in events]
        assert "chapter_start" in event_types
        assert "agent_start" in event_types
        assert "agent_complete" in event_types
        # The lean path saves prose directly and emits the lean save marker.
        assert "lean_prose_only_saved" in event_types

    @pytest.mark.asyncio
    async def test_pipeline_saves_chapter(self, orchestrator, sample_scene_card, temp_dir):
        result = await orchestrator.run_chapter(sample_scene_card)
        output_path = Path(result["output_path"])
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert len(content) > 0

    @pytest.mark.asyncio
    async def test_full_pipeline_with_multiple_scenes(self, orchestrator, sample_scene_card, ledger):
        scene_card_2 = {**sample_scene_card, "chapter_number": 2}
        results = await orchestrator.run_pipeline([sample_scene_card, scene_card_2])

        assert len(results) == 2
        assert results[0]["chapter_number"] == 1
        assert results[1]["chapter_number"] == 2

        # Check pipeline events
        events = ledger.get_events(limit=100)
        event_types = [e["event_type"] for e in events]
        assert "pipeline_start" in event_types
        assert "pipeline_complete" in event_types
