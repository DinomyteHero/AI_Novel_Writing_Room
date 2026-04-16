"""Tests for the Orchestrator pipeline."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator import Orchestrator
from src.run_ledger import RunLedger


def _well_formed_brief() -> dict:
    """Minimal generation brief satisfying every required field.

    Used in side_effect lists where Plot Architect is the first structured
    call and the test focuses on downstream gate/polish behavior.
    """
    return {
        "scene_objective": "Mock objective.",
        "turning_point": {"trigger": "t", "shift": "s", "cost": "c"},
        "closing_beat": "Mock closing beat.",
        "emotional_arc": {"start": "a", "shift": "b", "end": "c"},
        "target_word_count": 1000,
    }


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
        # Final Gate replaces the craft-edit completion event as the
        # final pre-save validation marker.
        assert "final_gate_complete" in event_types

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
        # Sequence: Plot Architect brief, Scene Gate fail_structural, Scene Gate pass, Final Gate pass
        mock_router.complete_structured = AsyncMock(side_effect=[
            # Plot Architect typed brief (first structured call in the pipeline)
            _well_formed_brief(),
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
            # Final Gate verdict on polished prose
            {"verdict": "pass", "failure_codes": []},
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
        # Sequence: Plot Architect brief, Scene Gate fail_voice, Scene Gate pass, Final Gate pass
        mock_router.complete_structured = AsyncMock(side_effect=[
            _well_formed_brief(),
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
            # Final Gate verdict on polished prose
            {"verdict": "pass", "failure_codes": []},
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
    async def test_polish_failure_proceeds_to_quality_polish_and_final_gate(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """A fail_polish gate verdict does not retry — it proceeds to Quality
        Polish, which is then validated by Final Gate."""
        mock_router.complete_structured = AsyncMock(return_value={
            "verdict": "fail_polish",
            "failure_codes": [{"code": "PACING_FLATLINE", "location": "whole scene", "description": "Flat pacing"}],
            "severity": "non_blocking",
            "route_to": None,
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

        await orchestrator.run_chapter(sample_scene_card)
        # Polish failures do not retry; Final Gate still runs on the polish output.
        event_types = [e["event_type"] for e in ledger.get_events()]
        # Final Gate should emit either a pass (final_gate_complete) or a
        # rejection (final_gate_rejection) — never neither — since the pipeline
        # proceeds past the gate failure.
        assert "final_gate_complete" in event_types or "final_gate_rejection" in event_types


class TestOrchestratorCanonContext:
    """Phase 0 regression: orchestrator must pass a non-empty concept_seed to
    CanonExpert, read from the ContextAssembler rather than the previously
    absent ``self.concept_seed`` attribute."""

    @pytest.fixture
    def ledger(self, temp_dir):
        _ledger = RunLedger(db_path=str(Path(temp_dir) / "test_ledger.db"))
        yield _ledger
        _ledger.close()

    @pytest.fixture
    def mock_assembler_with_seed(self):
        assembler = MagicMock()
        assembler.get_bible_summary.return_value = "Test bible summary"
        assembler.assemble.return_value = "Test assembled context"
        assembler.get_negative_constraints.return_value = "Test constraints"
        # The load-bearing assertion target for this test class.
        assembler.concept_seed = {
            "meta": {"project_title": "Canon Context Test"},
            "premise": {"logline": "Testing canon context flow"},
        }
        return assembler

    @pytest.mark.asyncio
    async def test_canon_expert_receives_non_empty_concept_seed(
        self,
        mock_router,
        mock_assembler_with_seed,
        ledger,
        temp_dir,
        sample_scene_card,
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

        canon_expert = MagicMock()
        canon_expert.run = AsyncMock(return_value={
            "verdict": "pass",
            "canon_notes": "",
            "violations": [],
        })

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler_with_seed,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            canon_expert=canon_expert,
        )

        await orchestrator.run_chapter(sample_scene_card)

        assert canon_expert.run.await_count >= 1, "CanonExpert should have been invoked"
        first_call_context = canon_expert.run.await_args_list[0].args[0]
        assert first_call_context["concept_seed"] == mock_assembler_with_seed.concept_seed, (
            "CanonExpert received an empty concept_seed — the orchestrator must "
            "read it from the assembler, not from a never-set self.concept_seed."
        )
