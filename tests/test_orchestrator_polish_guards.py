"""Tests for the post-polish guards in Orchestrator.run_chapter.

Two guards protect the final saved prose from bad polish output:

1. **Compression guard** (numeric, cheap): if the polish output dropped below
   80% of the gate-passed word count, revert to the gate-passed draft and skip
   Final Gate.

2. **Final Gate** (LLM, slower): if the Final Gate verdict is not `pass`,
   revert to the gate-passed draft and log a rejection event.

These tests exercise the orchestrator wiring directly with mocked agents.
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
    async def test_fires_when_polish_cuts_below_80_percent(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Polish output below 80% of gate-passed -> revert, emit ledger event, skip Final Gate."""
        # Prose Stylist returns 100 words; Quality Polish returns 60 words (60% of gate-passed)
        gate_prose = " ".join(["word"] * 100)
        polished_prose = " ".join(["word"] * 60)

        call_count = {"n": 0}

        async def fake_complete(agent_role, messages, *args, **kwargs):
            call_count["n"] += 1
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

        # Compression guard event was emitted
        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "compression_guard_fired" in event_types
        # Final Gate should have been skipped — no final_gate_* event
        assert "final_gate_complete" not in event_types
        assert "final_gate_rejection" not in event_types

        # The saved file should contain the gate-passed prose, not the polished prose
        output_path = Path(result["output_path"])
        saved_text = output_path.read_text(encoding="utf-8")
        assert saved_text == gate_prose
        # Result flag surfaces the rejection
        assert result.get("polish_rejected") is True
        assert result.get("polish_rejection_reason") == "compression_guard"

    async def test_does_not_fire_when_polish_stays_above_floor(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Polish output at 90% of gate-passed -> proceed to Final Gate."""
        gate_prose = " ".join(["word"] * 100)
        polished_prose = " ".join(["word"] * 90)

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
        # Final Gate should have been invoked and passed (mock always returns pass)
        assert "final_gate_complete" in event_types
        assert not result.get("polish_rejected")


class TestFinalGateRejection:
    async def test_rejects_polish_on_structural_failure(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Final Gate returns non-pass -> revert to gate-passed draft, emit rejection event."""
        gate_prose = " ".join(["word"] * 100)
        polished_prose = " ".join(["word"] * 95)  # above compression floor

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return gate_prose
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        gate_pass = _make_gate_pass_dict()
        final_gate_fail = {
            "verdict": "fail_structural",
            "failure_codes": [{
                "code": "CHARACTER_PRESENCE_VIOLATION",
                "location": "paragraph 2",
                "description": "character not in scene card speaks",
                "fix_hint": "remove",
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

        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "final_gate_rejection" in event_types
        assert "final_gate_complete" not in event_types

        # Saved file is the gate-passed prose
        saved = Path(result["output_path"]).read_text(encoding="utf-8")
        assert saved == gate_prose

        # Result flag surfaces the rejection and reason
        assert result.get("polish_rejected") is True
        assert result.get("polish_rejection_reason") == "final_gate"

        # Rejection payload logs the failure codes
        rejections = [
            e for e in ledger.get_events() if e["event_type"] == "final_gate_rejection"
        ]
        assert len(rejections) == 1
        assert "CHARACTER_PRESENCE_VIOLATION" in rejections[0]["payload"]["failure_codes"]

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
