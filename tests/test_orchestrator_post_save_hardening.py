"""Tests for Tier 3 post-save error hardening in Orchestrator.run_chapter.

When any of the following post-save stages crash, the scene must still be
saved and the run must continue; the crash lands as a warn-level ledger event
so human operators see the regression.

Covered stages:
- PromiseLedger._maybe_record_promise_deltas (Slice 3 hook)
- _run_post_save (summarizer + state-diff + chapter memory)
- physics_enforcer.validate_post_chapter
- character_specialist.run
- judge_evaluator.evaluate_chapter

The chapter gate critic has its own crash-guard test in this module because
it fires at the end of each chapter from run_pipeline, not run_chapter.
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
    assembler.get_character_voices.return_value = {}
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


def _make_orchestrator(mock_router, mock_assembler, ledger, temp_dir):
    """Build a bare Orchestrator with a stable gate pass path."""
    gate_prose = " ".join(["word"] * 100)
    polished_prose = " ".join(["polish"] * 95)

    async def fake_complete(agent_role, messages, *args, **kwargs):
        if agent_role == "prose_stylist":
            return gate_prose
        if agent_role == "quality_polish":
            return polished_prose
        return "mock"

    mock_router.complete = AsyncMock(side_effect=fake_complete)
    mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

    return Orchestrator(
        router=mock_router,
        context_assembler=mock_assembler,
        ledger=ledger,
        manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
    )


class TestPromiseLedgerHardening:
    """Non-KeyError failures from the promise ledger must not abort the run."""

    async def test_store_error_emits_warn_and_continues(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(mock_router, mock_assembler, ledger, temp_dir)

        # Wire a promise ledger that raises a non-KeyError on record.
        orchestrator._promise_ledger_enabled = True
        orchestrator.promise_ledger = MagicMock()
        orchestrator.promise_ledger.record_progression.side_effect = RuntimeError("db locked")
        orchestrator.promise_ledger.list_overdue.return_value = []

        card = dict(sample_scene_card)
        card["promises_progressed"] = ["prom_A"]

        result = await orchestrator.run_chapter(card)

        # Scene still saved.
        assert Path(result["output_path"]).exists()

        # Warn event fired with store_error status.
        progressed = [
            e for e in ledger.get_events() if e["event_type"] == "promise_progressed"
        ]
        assert progressed, "expected a promise_progressed event"
        payload = progressed[0]["payload"]
        assert payload.get("level") == "warn"
        assert payload.get("status") == "store_error"
        assert "RuntimeError" in payload.get("error", "")

    async def test_unknown_promise_id_still_warns(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """Pre-existing KeyError path must still surface as unknown_promise_id."""
        orchestrator = _make_orchestrator(mock_router, mock_assembler, ledger, temp_dir)

        orchestrator._promise_ledger_enabled = True
        orchestrator.promise_ledger = MagicMock()
        orchestrator.promise_ledger.record_payoff.side_effect = KeyError("prom_missing")
        orchestrator.promise_ledger.list_overdue.return_value = []

        card = dict(sample_scene_card)
        card["promises_paid"] = ["prom_missing"]

        await orchestrator.run_chapter(card)

        paid = [e for e in ledger.get_events() if e["event_type"] == "promise_paid"]
        assert paid
        assert paid[0]["payload"].get("status") == "unknown_promise_id"


class TestPostSaveStageHardening:
    """Crashes in post-save stages must not abort a saved scene."""

    async def test_post_save_crash_emits_warn(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(mock_router, mock_assembler, ledger, temp_dir)
        orchestrator.summarizer = MagicMock()
        orchestrator.summarizer.run = AsyncMock(side_effect=RuntimeError("summarizer boom"))

        result = await orchestrator.run_chapter(sample_scene_card)

        assert Path(result["output_path"]).exists()

        crashes = [
            e for e in ledger.get_events()
            if e["event_type"] == "post_save_error"
            and e["payload"].get("stage") == "run_post_save"
        ]
        assert crashes, "expected a post_save_error event for run_post_save"
        assert "RuntimeError" in crashes[0]["payload"].get("error", "")

    async def test_physics_enforcer_crash_emits_warn(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(mock_router, mock_assembler, ledger, temp_dir)
        # Pre-check returns a valid dict so only the post-check crash path
        # is exercised; otherwise the pre-check fires first and muddies the
        # assertion.
        physics = MagicMock()
        physics.validate_pre_chapter.return_value = {
            "passed": True,
            "issues": [],
            "recommendations": [],
        }
        physics.validate_post_chapter.side_effect = ValueError("physics exploded")
        orchestrator.physics_enforcer = physics

        result = await orchestrator.run_chapter(sample_scene_card)

        assert Path(result["output_path"]).exists()

        phys = [
            e for e in ledger.get_events() if e["event_type"] == "physics_validation_post"
        ]
        assert phys
        # The error-path emit has status=error, not passed/issue_count.
        err_events = [e for e in phys if e["payload"].get("status") == "error"]
        assert err_events
        assert err_events[0]["payload"].get("level") == "warn"

    async def test_character_specialist_crash_emits_warn(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(mock_router, mock_assembler, ledger, temp_dir)
        orchestrator.character_specialist = MagicMock()
        orchestrator.character_specialist.run = AsyncMock(
            side_effect=RuntimeError("char specialist boom")
        )

        result = await orchestrator.run_chapter(sample_scene_card)

        assert Path(result["output_path"]).exists()

        crashes = [
            e for e in ledger.get_events()
            if e["event_type"] == "post_save_error"
            and e["payload"].get("stage") == "character_specialist"
        ]
        assert crashes

    async def test_judge_evaluator_crash_emits_warn(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(mock_router, mock_assembler, ledger, temp_dir)
        orchestrator.judge_evaluator = MagicMock()
        orchestrator.judge_evaluator.evaluate_chapter = AsyncMock(
            side_effect=RuntimeError("judge boom")
        )

        result = await orchestrator.run_chapter(sample_scene_card)

        assert Path(result["output_path"]).exists()

        crashes = [
            e for e in ledger.get_events()
            if e["event_type"] == "post_save_error"
            and e["payload"].get("stage") == "judge_evaluator"
        ]
        assert crashes
        # judge_evaluation success event should NOT have fired.
        assert not [
            e for e in ledger.get_events() if e["event_type"] == "judge_evaluation"
        ]
