"""Tests for the post-polish guards in Orchestrator.run_chapter.

1. **Compression guard (revert-on-regression)**: polish output below 60% of
   gate-passed word count is treated as damaged. The saved prose reverts to
   the gate-passed draft and a `compression_guard_fired` warn event fires
   with `reverted: True` in the payload. This is the only place in the
   forward-only relay where a later stage can overwrite an earlier stage's
   output, justified by "polish collapsed the scene, the earlier draft is
   safer."

2. **Final Gate advisory**: non-pass verdicts emit `final_gate_rejection`
   with `advisory_only: True`. The polished prose is still saved.

Save-blocker enforcement (distinct from these gates, covered by save_blockers
tests) handles the three hard-blocking categories: character-presence
violation, canon critical/moderate failure, and POV violation.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator import Orchestrator
from src.run_ledger import RunLedger


@pytest.fixture
def ledger(temp_dir):
    _ledger = RunLedger(db_path=str(Path(temp_dir) / "test_ledger.db"))
    yield _ledger
    _ledger.close()


@pytest.fixture
def mock_assembler():
    assembler = MagicMock()
    assembler.get_bible_summary.return_value = "Test bible summary"
    assembler.assemble.return_value = "Test assembled context"
    assembler.get_negative_constraints.return_value = "Test constraints"
    return assembler


def _make_gate_pass_dict() -> dict:
    return {
        "verdict": "pass",
        "failure_codes": [],
        "severity": "non_blocking",
        "route_to": None,
        "structural_score": 0.85,
        "voice_score": 0.80,
        "polish_score": 0.75,
    }


class TestCompressionGuard:
    async def test_reverts_to_draft_below_60_percent(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Polish < 60% of gate-passed triggers revert-to-draft."""
        # Prose Stylist: 100 words. Quality Polish: 50 words (50% — clearly below the 60% revert threshold)
        gate_prose = " ".join(["word"] * 100)
        polished_prose = " ".join(["polish"] * 50)

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return gate_prose
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

        result = await orchestrator.run_chapter(sample_scene_card)

        # Warn event emitted with reverted=True and advisory_only=False.
        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "compression_guard_fired" in event_types
        compression_events = [e for e in ledger.get_events() if e["event_type"] == "compression_guard_fired"]
        payload = compression_events[0]["payload"]
        assert payload.get("reverted") is True
        assert payload.get("advisory_only") is False

        # Final Gate still runs on the reverted (gate-passed) prose.
        assert "final_gate_complete" in event_types or "final_gate_rejection" in event_types

        # SAVED PROSE IS THE GATE-PASSED DRAFT — revert-on-regression.
        output_path = Path(result["output_path"])
        saved_text = output_path.read_text(encoding="utf-8")
        assert saved_text == gate_prose, "Compression guard must revert to the gate-passed draft when polish collapses below 60%."
        assert not result.get("polish_rejected")

    async def test_advisory_does_not_fire_above_threshold(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Polish at 90% of gate-passed stays above the 60% advisory threshold."""
        gate_prose = " ".join(["word"] * 100)
        polished_prose = " ".join(["polish"] * 90)

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return gate_prose
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

        result = await orchestrator.run_chapter(sample_scene_card)

        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "compression_guard_fired" not in event_types
        assert "final_gate_complete" in event_types
        assert not result.get("polish_rejected")


class TestFinalGateRejection:
    async def test_final_gate_advisory_logs_without_reverting(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Final Gate non-pass emits advisory; polished prose is still saved (relay refactor)."""
        gate_prose = " ".join(["word"] * 100)
        polished_prose = " ".join(["polish"] * 95)  # above compression floor

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return gate_prose
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        gate_pass = _make_gate_pass_dict()
        # Forward Relay v4: CHARACTER_PRESENCE_VIOLATION is out of scope for
        # FinalGate (PresenceChecker is the sole authority). Assert the
        # rejection path with a still-in-scope structural code instead.
        final_gate_fail = {
            "verdict": "fail_structural",
            "failure_codes": [{
                "code": "CLOSING_HOOK_VIOLATION",
                "location": "paragraph 2",
                "description": "polish extended past the closing hook",
                "fix_hint": "trim trailing content",
            }],
        }

        async def fake_structured(agent_role, messages, *args, **kwargs):
            if agent_role == "gate_critic":
                return gate_pass
            if agent_role == "final_gate":
                return final_gate_fail
            return gate_pass

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(side_effect=fake_structured)

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

        result = await orchestrator.run_chapter(sample_scene_card)

        # Advisory event emitted.
        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "final_gate_rejection" in event_types
        assert "final_gate_complete" not in event_types

        # Rejection payload is flagged advisory_only.
        rejections = [e for e in ledger.get_events() if e["event_type"] == "final_gate_rejection"]
        assert len(rejections) == 1
        assert rejections[0]["payload"].get("advisory_only") is True
        assert "CLOSING_HOOK_VIOLATION" in rejections[0]["payload"]["failure_codes"]

        # SAVED PROSE IS THE POLISHED OUTPUT — no reversion in forward-only pipeline.
        # Save-blocker layer (Stage 1f) handles CHARACTER_PRESENCE via a distinct
        # enforcement path; final_gate is telemetry only under the relay.
        saved = Path(result["output_path"]).read_text(encoding="utf-8")
        assert saved == polished_prose, "Relay refactor: final_gate advisory must not revert to pre-polish prose."
        assert not result.get("polish_rejected")

    async def test_accepts_polish_when_final_gate_passes(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Final Gate pass -> save the polished prose."""
        gate_prose = " ".join(["gate"] * 100)
        polished_prose = " ".join(["polished"] * 95)

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return gate_prose
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

        result = await orchestrator.run_chapter(sample_scene_card)

        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "final_gate_complete" in event_types
        assert "final_gate_rejection" not in event_types

        # Saved file is the polished prose
        saved = Path(result["output_path"]).read_text(encoding="utf-8")
        assert saved == polished_prose
        assert not result.get("polish_rejected")

    async def test_final_gate_pass_prints_console_line(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card, capsys
    ):
        """Phase 1.5: Final Gate pass must print an explicit console line so the
        run output self-documents (mirrors the existing rejection print)."""
        gate_prose = " ".join(["gate"] * 100)
        polished_prose = " ".join(["polished"] * 95)

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return gate_prose
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )

        await orchestrator.run_chapter(sample_scene_card)

        captured = capsys.readouterr()
        assert "Final Gate: pass" in captured.out, (
            "Phase 1.5 regression: orchestrator must print an explicit "
            "'Final Gate: pass' line on success to match the rejection print."
        )


class TestRawDraftBypass:
    async def test_raw_draft_skips_polish_and_final_gate(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """--raw-draft saves the gate-passed draft directly; neither polish nor Final Gate run."""
        gate_prose = " ".join(["word"] * 100)

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return gate_prose
            # quality_polish should NEVER be called
            if agent_role == "quality_polish":
                raise AssertionError("Quality Polish must not be invoked under --raw-draft")
            return "mock"

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            raw_draft=True,
        )

        result = await orchestrator.run_chapter(sample_scene_card)

        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "final_gate_complete" not in event_types
        assert "final_gate_rejection" not in event_types
        assert "compression_guard_fired" not in event_types

        saved = Path(result["output_path"]).read_text(encoding="utf-8")
        assert saved == gate_prose


class TestLeanProseOnlyBypass:
    async def test_lean_prose_only_saves_drafter_output_without_checks(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Lean mode is PlotArchitect -> ProseStylist -> save, with checks bypassed."""
        brief = {
            "scene_objective": "Mock objective.",
            "turning_point": {"trigger": "t", "shift": "s", "cost": "c"},
            "closing_beat": "Mock closing beat.",
            "emotional_arc": {"start": "a", "shift": "b", "end": "c"},
            "target_word_count": 1000,
        }
        prose = "DeepSeek Pro drafter output, preserved exactly."

        async def fake_structured(agent_role, messages, *args, **kwargs):
            if agent_role == "plot_architect":
                return brief
            raise AssertionError(f"{agent_role} must not run in lean_prose_only mode")

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return prose
            raise AssertionError(f"{agent_role} must not run in lean_prose_only mode")

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(side_effect=fake_structured)

        canon_expert = MagicMock()
        canon_expert.run = AsyncMock(
            side_effect=AssertionError("CanonExpert must not run in lean_prose_only mode")
        )
        presence_checker = MagicMock()
        presence_checker.run = AsyncMock(
            side_effect=AssertionError("PresenceChecker must not run in lean_prose_only mode")
        )
        summarizer = MagicMock()
        summarizer.run = AsyncMock(
            side_effect=AssertionError("Summarizer must not run in lean_prose_only mode")
        )

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            runtime_flags={"runtime": {"lean_prose_only": {"enabled": True}}},
            canon_expert=canon_expert,
            presence_checker=presence_checker,
            summarizer=summarizer,
        )

        result = await orchestrator.run_chapter(sample_scene_card)

        assert result["lean_prose_only"] is True
        assert result["evaluation"]["verdict"] == "skipped"
        assert result["evaluation"]["skip_reason"] == "lean_prose_only"
        saved = Path(result["output_path"]).read_text(encoding="utf-8")
        assert saved == prose

        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "lean_prose_only_saved" in event_types
        assert "gate_pass" not in event_types
        assert "gate_fail" not in event_types
        assert "final_gate_complete" not in event_types
        assert "final_gate_rejection" not in event_types
        assert "compression_guard_fired" not in event_types

    async def test_lean_prose_only_can_apply_configured_line_edit(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Lean mode may run the bounded LineWriter pass, then save directly."""
        brief = {
            "scene_objective": "Mock objective.",
            "turning_point": {"trigger": "t", "shift": "s", "cost": "c"},
            "closing_beat": "Mock closing beat.",
            "emotional_arc": {"start": "a", "shift": "b", "end": "c"},
            "target_word_count": 1000,
        }
        prose = "DeepSeek Pro drafter output."
        edited = "DeepSeek Flash line-edited output."

        async def fake_structured(agent_role, messages, *args, **kwargs):
            if agent_role == "plot_architect":
                return brief
            raise AssertionError(f"{agent_role} must not run in lean line-edit mode")

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return prose
            raise AssertionError(f"{agent_role} must not run directly")

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(side_effect=fake_structured)

        line_writer = MagicMock()
        line_writer.run = AsyncMock(return_value={"prose": edited})

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            runtime_flags={
                "runtime": {
                    "lean_prose_only": {
                        "enabled": True,
                        "line_edit": {"enabled": True},
                    }
                }
            },
            line_writer=line_writer,
        )

        result = await orchestrator.run_chapter(sample_scene_card)

        assert result["lean_prose_only"] is True
        assert result["line_edit_applied"] is True
        saved = Path(result["output_path"]).read_text(encoding="utf-8")
        assert saved == edited
        line_writer.run.assert_awaited_once()

        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "lean_prose_only_saved" in event_types
        assert "gate_pass" not in event_types
        assert "final_gate_complete" not in event_types
