from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.commercial_rewrite import CommercialRewrite
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
    assembler.get_negative_constraints.return_value = "Avoid generic filler."
    assembler.get_pov_approach.return_value = "third-person limited"
    assembler.get_franchise_profile_text.return_value = ""
    assembler.get_bible_summary.return_value = ""
    assembler.assemble.return_value = ""
    return assembler


def _make_orchestrator(mock_router, mock_assembler, ledger, temp_dir, *, flags):
    return Orchestrator(
        router=mock_router,
        context_assembler=mock_assembler,
        ledger=ledger,
        manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        runtime_flags={"runtime": {"commercial_rewrite": flags}},
    )


def _evaluation_with(code: str) -> dict:
    return {
        "verdict": "fail_voice",
        "failure_codes": [
            {
                "code": code,
                "location": "paragraph 3",
                "description": "too much narrator explanation",
                "fix_hint": "show the reaction through behavior",
            }
        ],
    }


class TestCommercialRewriteAgent:
    async def test_strips_markdown_wrapping(self, mock_router):
        mock_router.complete = AsyncMock(return_value="```markdown\nClean revised prose.\n```")
        agent = CommercialRewrite(mock_router)

        result = await agent.run(
            {
                "source_prose": "Draft.",
                "scene_card": {"characters_present": ["A"], "closing_hook": "end"},
                "generation_brief": {"scene_objective": "objective"},
                "quality_metrics": {"flags": ["telling"]},
            }
        )

        assert result["prose"] == "Clean revised prose."

    def test_prompt_is_franchise_agnostic(self, mock_router):
        agent = CommercialRewrite(mock_router)
        prompt = agent._format_context(
            {
                "source_prose": "Draft.",
                "scene_card": {"characters_present": ["A"], "closing_hook": "end"},
                "generation_brief": {"scene_objective": "objective"},
                "diagnostic_reasons": ["Quality metric flag: telling"],
            }
        )

        assert "Star Wars" not in prompt
        assert "Ruusan" not in prompt
        assert "MiniMax" not in prompt
        assert "declared prose register" in prompt
        assert "franchise terminology" in prompt


class TestCommercialRewriteOrchestrator:
    async def test_flag_off_is_noop(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(
            mock_router,
            mock_assembler,
            ledger,
            temp_dir,
            flags={"enabled": False, "trigger_failure_codes": ["TELLING_NOT_SHOWING"]},
        )
        prose = " ".join(["draft"] * 100)

        result = await orchestrator._maybe_commercial_rewrite(
            scene_card=sample_scene_card,
            generation_brief={"scene_objective": "x"},
            prose=prose,
            evaluation=_evaluation_with("TELLING_NOT_SHOWING"),
            quality_metrics=None,
        )

        assert result == prose
        assert "commercial_rewrite_fired" not in [e["event_type"] for e in ledger.get_events()]

    async def test_fires_on_gate_trigger(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(
            mock_router,
            mock_assembler,
            ledger,
            temp_dir,
            flags={
                "enabled": True,
                "trigger_failure_codes": ["TELLING_NOT_SHOWING"],
                "trigger_flag_keywords": [],
                "min_word_count_ratio": 0.75,
                "max_word_count_ratio": 1.35,
            },
        )
        prose = " ".join(["draft"] * 100)
        revised = " ".join(["revised"] * 105)
        orchestrator.commercial_rewrite.run = AsyncMock(return_value={"prose": revised})

        result = await orchestrator._maybe_commercial_rewrite(
            scene_card=sample_scene_card,
            generation_brief={"scene_objective": "x"},
            prose=prose,
            evaluation=_evaluation_with("TELLING_NOT_SHOWING"),
            quality_metrics=None,
        )

        assert result == revised
        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "commercial_rewrite_fired" in event_types
        assert "commercial_rewrite_complete" in event_types

    async def test_rejects_collapsed_output(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(
            mock_router,
            mock_assembler,
            ledger,
            temp_dir,
            flags={
                "enabled": True,
                "trigger_failure_codes": ["TELLING_NOT_SHOWING"],
                "trigger_flag_keywords": [],
                "min_word_count_ratio": 0.75,
                "max_word_count_ratio": 1.35,
            },
        )
        prose = " ".join(["draft"] * 100)
        collapsed = " ".join(["short"] * 20)
        orchestrator.commercial_rewrite.run = AsyncMock(return_value={"prose": collapsed})

        result = await orchestrator._maybe_commercial_rewrite(
            scene_card=sample_scene_card,
            generation_brief={"scene_objective": "x"},
            prose=prose,
            evaluation=_evaluation_with("TELLING_NOT_SHOWING"),
            quality_metrics=None,
        )

        assert result == prose
        rejected = [e for e in ledger.get_events() if e["event_type"] == "commercial_rewrite_rejected"]
        assert len(rejected) == 1
        assert rejected[0]["payload"]["reason"] == "below_word_count_floor"

    async def test_rejects_empty_source_without_calling_agent(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(
            mock_router,
            mock_assembler,
            ledger,
            temp_dir,
            flags={
                "enabled": True,
                "trigger_failure_codes": ["OPENING_HOOK_MISMATCH"],
                "trigger_flag_keywords": [],
                "min_word_count_ratio": 0.75,
                "max_word_count_ratio": 1.35,
            },
        )
        orchestrator.commercial_rewrite.run = AsyncMock(
            return_value={"prose": " ".join(["replacement"] * 100)}
        )

        result = await orchestrator._maybe_commercial_rewrite(
            scene_card=sample_scene_card,
            generation_brief={"scene_objective": "x"},
            prose="",
            evaluation=_evaluation_with("OPENING_HOOK_MISMATCH"),
            quality_metrics=None,
        )

        assert result == ""
        orchestrator.commercial_rewrite.run.assert_not_called()
        rejected = [e for e in ledger.get_events() if e["event_type"] == "commercial_rewrite_rejected"]
        assert len(rejected) == 1
        assert rejected[0]["payload"]["reason"] == "empty_source_prose"

    async def test_fires_on_quality_flag(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(
            mock_router,
            mock_assembler,
            ledger,
            temp_dir,
            flags={
                "enabled": True,
                "trigger_failure_codes": [],
                "trigger_flag_keywords": ["scene type imbalance"],
                "min_word_count_ratio": 0.75,
                "max_word_count_ratio": 1.35,
            },
        )
        prose = " ".join(["draft"] * 100)
        revised = " ".join(["revised"] * 100)
        orchestrator.commercial_rewrite.run = AsyncMock(return_value={"prose": revised})

        result = await orchestrator._maybe_commercial_rewrite(
            scene_card=sample_scene_card,
            generation_brief={"scene_objective": "x"},
            prose=prose,
            evaluation={"verdict": "pass", "failure_codes": []},
            quality_metrics={
                "overall_score": 0.8,
                "flags": ["Scene type imbalance: >60% description"],
            },
        )

        assert result == revised
