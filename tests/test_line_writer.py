"""Tests for the LineWriter agent (Stage 3 of the relay v3 refactor).

Covers:
- Unit: context formatting includes source prose + preservation constraints;
  wrapping markdown fences are stripped; empty outputs are tolerated.
- Orchestrator integration: when LineWriter is wired, its output becomes the
  input to gate_critic and downstream stages; when it collapses or errors,
  the orchestrator falls back to drafter prose and emits a warn event.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.line_writer import LineWriter
from src.orchestrator import Orchestrator
from src.run_ledger import RunLedger


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


@pytest.fixture
def ledger(temp_dir):
    _ledger = RunLedger(db_path=str(Path(temp_dir) / "test_ledger.db"))
    yield _ledger
    _ledger.close()


@pytest.fixture
def mock_assembler():
    a = MagicMock()
    a.get_bible_summary.return_value = "Test bible summary"
    a.assemble.return_value = "Test assembled context"
    a.get_negative_constraints.return_value = "Test constraints"
    a.get_pov_approach.return_value = "third-limited, locked to POV character"
    a.get_franchise_profile_text.return_value = ""
    a.concept_seed = {}
    return a


class TestLineWriterAgent:
    async def test_returns_revised_prose(self):
        """Plain happy path: model returns revised prose."""
        router = MagicMock()
        router.complete = AsyncMock(return_value="Revised prose, sharper now.")
        lw = LineWriter(router)

        result = await lw.run({
            "source_prose": "Original prose.",
            "scene_card": {"chapter_number": 1, "characters_present": ["A"]},
            "generation_brief": {"scene_objective": "intro"},
            "characters_present": ["A"],
            "pov_approach": "third-limited",
            "franchise_profile_text": "",
        })
        assert result == {"prose": "Revised prose, sharper now."}

    async def test_strips_markdown_fences(self):
        """Defensive stripping of accidental ``` wrapping."""
        router = MagicMock()
        router.complete = AsyncMock(
            return_value="```\nRevised prose.\n```"
        )
        lw = LineWriter(router)

        result = await lw.run({
            "source_prose": "source",
            "scene_card": {},
            "generation_brief": {},
            "characters_present": [],
            "pov_approach": "",
            "franchise_profile_text": "",
        })
        assert result["prose"] == "Revised prose."

    async def test_strips_language_hint_fences(self):
        router = MagicMock()
        router.complete = AsyncMock(
            return_value="```markdown\nRevised prose.\n```"
        )
        lw = LineWriter(router)
        result = await lw.run({
            "source_prose": "source",
            "scene_card": {},
            "generation_brief": {},
            "characters_present": [],
            "pov_approach": "",
            "franchise_profile_text": "",
        })
        assert result["prose"] == "Revised prose."

    async def test_ben_pov_rewrites_lukes_order_planning_label(self):
        router = MagicMock()
        router.complete = AsyncMock(
            return_value="The history Luke’s Order had inherited was incomplete."
        )
        lw = LineWriter(router)

        result = await lw.run({
            "source_prose": "source",
            "scene_card": {"pov_character": "Ben Skywalker"},
            "generation_brief": {},
            "characters_present": ["Ben Skywalker"],
            "pov_approach": "third-limited",
            "franchise_profile_text": "",
        })

        assert result["prose"] == (
            "The history his father's Order had inherited was incomplete."
        )

    def test_format_context_includes_preservation_constraints(self):
        router = MagicMock()
        lw = LineWriter(router)

        prompt = lw._format_context({
            "source_prose": "Once upon a time, A walked into a room.",
            "scene_card": {"chapter_number": 2, "characters_present": ["A"]},
            "generation_brief": {"scene_objective": "show A's restraint"},
            "characters_present": ["A"],
            "pov_approach": "third-limited, locked to A",
            "franchise_profile_text": "[[this should live as system, not user]]",
        })

        # Structural contract surfaces in the prompt.
        assert "POV Approach" in prompt
        assert "third-limited, locked to A" in prompt
        assert "characters_present" in prompt
        assert "- A" in prompt
        assert "Scene Card" in prompt
        assert "Generation Brief" in prompt
        assert "show A's restraint" in prompt
        assert "Source Prose" in prompt
        assert "Once upon a time" in prompt
        # franchise_profile_text is passed separately (system message), not
        # duplicated into the user prompt.
        assert "[[this should live as system" not in prompt


class TestOrchestratorLineWriterIntegration:
    """With LineWriter wired, its revised prose flows downstream."""

    async def test_line_writer_output_feeds_gate_critic(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        drafter_prose = " ".join(["draft"] * 100)
        line_writer_prose = " ".join(["edited"] * 95)
        polished_prose = " ".join(["polished"] * 92)

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return drafter_prose
            if agent_role == "line_writer":
                return line_writer_prose
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        line_writer = LineWriter(mock_router)
        orch = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            line_writer=line_writer,
        )
        result = await orch.run_chapter(sample_scene_card)

        # Saved file is the polished line-edited prose.
        saved = Path(result["output_path"]).read_text(encoding="utf-8")
        assert saved == polished_prose

        # Ledger got an agent_complete for line_writer.
        events = ledger.get_events(agent_role="line_writer")
        event_types = {e["event_type"] for e in events}
        assert "agent_start" in event_types
        assert "agent_complete" in event_types

    async def test_line_writer_skipped_in_raw_draft_mode(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        drafter_prose = " ".join(["draft"] * 100)
        mock_router.complete = AsyncMock(return_value=drafter_prose)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        line_writer = LineWriter(mock_router)
        orch = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            line_writer=line_writer,
            raw_draft=True,
        )
        await orch.run_chapter(sample_scene_card)

        # No line_writer events in raw_draft mode.
        events = ledger.get_events(agent_role="line_writer")
        assert events == []

    async def test_line_writer_error_falls_back_to_drafter(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        drafter_prose = " ".join(["draft"] * 100)
        polished_prose = " ".join(["polished"] * 95)

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return drafter_prose
            if agent_role == "line_writer":
                raise RuntimeError("network error")
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        line_writer = LineWriter(mock_router)
        orch = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            line_writer=line_writer,
        )
        result = await orch.run_chapter(sample_scene_card)

        # Scene still saves (error is non-blocking).
        assert Path(result["output_path"]).exists()

        # Warn-level event emitted.
        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "line_writer_error" in event_types

    async def test_line_writer_collapsed_falls_back_to_drafter(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        drafter_prose = " ".join(["draft"] * 100)
        # Line writer collapses to 30 words (30% of source — below the 40% floor)
        line_writer_prose = " ".join(["collapsed"] * 30)
        polished_prose = " ".join(["polished"] * 95)

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return drafter_prose
            if agent_role == "line_writer":
                return line_writer_prose
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        line_writer = LineWriter(mock_router)
        orch = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            line_writer=line_writer,
        )
        await orch.run_chapter(sample_scene_card)

        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "line_writer_collapsed" in event_types
        # No agent_complete for line_writer when it collapsed.
        completes = [
            e for e in ledger.get_events(agent_role="line_writer")
            if e["event_type"] == "agent_complete"
        ]
        assert completes == []

    async def test_orchestrator_without_line_writer_unchanged(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """When no LineWriter is wired, the pipeline runs as pre-Stage-3."""
        drafter_prose = " ".join(["draft"] * 100)
        polished_prose = " ".join(["polished"] * 95)

        async def fake_complete(agent_role, messages, *args, **kwargs):
            if agent_role == "prose_stylist":
                return drafter_prose
            if agent_role == "quality_polish":
                return polished_prose
            return "mock"

        mock_router.complete = AsyncMock(side_effect=fake_complete)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        orch = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        )
        await orch.run_chapter(sample_scene_card)

        # No line_writer events at all.
        events = ledger.get_events(agent_role="line_writer")
        assert events == []
