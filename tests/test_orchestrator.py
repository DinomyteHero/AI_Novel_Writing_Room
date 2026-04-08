"""Tests for the Orchestrator pipeline."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator import Orchestrator
from src.run_ledger import RunLedger


class TestOrchestratorPipeline:
    """Test the orchestrator's pipeline flow."""

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
        # Configure mock router for the pipeline
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
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

    @pytest.mark.asyncio
    async def test_single_chapter_pipeline(self, orchestrator, sample_scene_card, ledger):
        result = await orchestrator.run_chapter(sample_scene_card)

        assert result["chapter_number"] == 1
        assert result["scene_number"] == 1
        assert result["evaluation"]["verdict"] == "pass"
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
        assert "gate_pass" in event_types
        assert "craft_edit_complete" in event_types

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


class TestOrchestratorRetryLogic:
    """Test the gate critic retry behavior."""

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

    @pytest.mark.asyncio
    async def test_structural_failure_triggers_rewrite(self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card):
        # First call: fail_structural, second call: pass
        mock_router.complete_structured = AsyncMock(side_effect=[
            {
                "verdict": "fail_structural",
                "failure_codes": [{"code": "WEAK_TURNING_POINT", "location": "para 5", "description": "No shift"}],
                "severity": "blocking",
                "route_to": "full_rewrite",
                "structural_score": 0.3,
                "voice_score": 0.7,
                "polish_score": 0.7,
            },
            {
                "verdict": "pass",
                "failure_codes": [],
                "severity": "non_blocking",
                "route_to": None,
                "structural_score": 0.85,
                "voice_score": 0.80,
                "polish_score": 0.75,
            },
        ])

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

        result = await orchestrator.run_chapter(sample_scene_card)
        assert result["evaluation"]["verdict"] == "pass"

        # Verify gate_fail event was emitted
        events = ledger.get_events(event_type="gate_fail")
        assert len(events) == 1
        assert events[0]["payload"]["verdict"] == "fail_structural"

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card):
        # Always fail structural
        mock_router.complete_structured = AsyncMock(return_value={
            "verdict": "fail_structural",
            "failure_codes": [{"code": "WEAK_TURNING_POINT", "location": "para 5", "description": "No shift"}],
            "severity": "blocking",
            "route_to": "full_rewrite",
            "structural_score": 0.2,
            "voice_score": 0.7,
            "polish_score": 0.7,
        })

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            max_structural_retries=2,
        )

        result = await orchestrator.run_chapter(sample_scene_card)
        # Should proceed anyway after max retries
        assert result["evaluation"]["verdict"] == "fail_structural"

        # Should have 3 gate_fail events (initial + 2 retries)
        events = ledger.get_events(event_type="gate_fail")
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_voice_failure_triggers_targeted_revision(self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card):
        # First: fail_voice, second: pass
        mock_router.complete_structured = AsyncMock(side_effect=[
            {
                "verdict": "fail_voice",
                "failure_codes": [{"code": "OOC_DIALOGUE", "location": "para 3", "description": "Voice mismatch"}],
                "severity": "blocking",
                "route_to": "targeted_revision",
                "structural_score": 0.8,
                "voice_score": 0.3,
                "polish_score": 0.7,
            },
            {
                "verdict": "pass",
                "failure_codes": [],
                "severity": "non_blocking",
                "route_to": None,
                "structural_score": 0.85,
                "voice_score": 0.80,
                "polish_score": 0.75,
            },
        ])

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

        result = await orchestrator.run_chapter(sample_scene_card)
        assert result["evaluation"]["verdict"] == "pass"

    @pytest.mark.asyncio
    async def test_polish_failure_goes_to_craft_editor(self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card):
        mock_router.complete_structured = AsyncMock(return_value={
            "verdict": "fail_polish",
            "failure_codes": [{"code": "PACING_FLATLINE", "location": "whole scene", "description": "Flat pacing"}],
            "severity": "non_blocking",
            "route_to": "craft_edit",
            "structural_score": 0.85,
            "voice_score": 0.80,
            "polish_score": 0.4,
        })

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

        result = await orchestrator.run_chapter(sample_scene_card)
        # Polish failures proceed to craft editor without retry
        assert "craft_edit_complete" in [
            e["event_type"] for e in ledger.get_events()
        ]
