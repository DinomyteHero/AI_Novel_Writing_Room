"""Tests for Forward Relay v4 additions.

Covers the two flag-gated changes:
- Smart single corrective rerun (`runtime.corrective_rerun.enabled`)
- Slice 11.1 narrow canon repair (`runtime.canon_expert.apply_local_fixes`)

The single-shot invariant is load-bearing: ``_maybe_corrective_rerun`` must
return the unchanged prose on any skip path and must fire the drafter AT
MOST once when triggers match. These tests exercise the skip/fire logic
directly on the orchestrator method rather than driving a full ``run_chapter``
call, so the mock surface stays small and the intent of each trigger rule is
readable.
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
    assembler.get_bible_summary.return_value = ""
    assembler.assemble.return_value = ""
    assembler.get_negative_constraints.return_value = ""
    assembler.get_pov_approach.return_value = "third-person limited"
    assembler.get_franchise_profile_text.return_value = ""
    return assembler


def _make_orchestrator(
    mock_router,
    mock_assembler,
    ledger,
    temp_dir,
    *,
    runtime_flags: dict | None = None,
    **extra_kwargs,
) -> Orchestrator:
    return Orchestrator(
        router=mock_router,
        context_assembler=mock_assembler,
        ledger=ledger,
        manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        runtime_flags=runtime_flags or {},
        **extra_kwargs,
    )


def _fail_structural_eval(codes: list[str]) -> dict:
    return {
        "verdict": "fail_structural",
        "failure_codes": [
            {"code": c, "location": "paragraph 3", "description": f"{c} issue", "fix_hint": "fix it"}
            for c in codes
        ],
        "severity": "blocking",
        "route_to": "full_rewrite",
        "structural_score": 0.55,
        "voice_score": 0.80,
        "polish_score": 0.75,
    }


def _event_types(ledger) -> list[str]:
    return [e["event_type"] for e in ledger.get_events()]


# --- Corrective rerun ---------------------------------------------------------


class TestCorrectiveRerunSkipPaths:
    """Every skip path must return the unchanged prose AND never call ProseStylist."""

    async def test_flag_off_is_noop(self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card):
        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"corrective_rerun": {"enabled": False}}},
        )
        draft = " ".join(["word"] * 1000)
        result = await orchestrator._maybe_corrective_rerun(
            scene_card=sample_scene_card,
            generation_brief={"scene_objective": "x"},
            prose=draft,
            evaluation=_fail_structural_eval(["MISSING_TURNING_POINT"]),
        )
        assert result == draft
        # No rerun events at all when flag is off — not even a skipped log.
        assert "corrective_rerun_fired" not in _event_types(ledger)
        assert "corrective_rerun_skipped" not in _event_types(ledger)

    async def test_non_structural_verdict_is_noop(self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card):
        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"corrective_rerun": {
                "enabled": True,
                "trigger_codes": ["MISSING_TURNING_POINT"],
                "max_failure_codes": 3,
                "min_word_count_ratio": 0.5,
            }}},
        )
        draft = " ".join(["word"] * 1000)
        # Voice failure is out of scope — polish handles voice.
        voice_eval = {
            "verdict": "fail_voice",
            "failure_codes": [{"code": "OOC_DIALOGUE", "location": "p1", "description": "x", "fix_hint": "y"}],
        }
        result = await orchestrator._maybe_corrective_rerun(
            scene_card=sample_scene_card,
            generation_brief={"scene_objective": "x"},
            prose=draft,
            evaluation=voice_eval,
        )
        assert result == draft
        # Non-structural verdicts are returned immediately — no skip log needed
        # (the skip log is reserved for *candidate* decisions that fail a rule).
        assert "corrective_rerun_fired" not in _event_types(ledger)

    async def test_no_trigger_code_match_logs_skip(self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card):
        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"corrective_rerun": {
                "enabled": True,
                "trigger_codes": ["MISSING_TURNING_POINT", "CLOSING_HOOK_VIOLATION"],
                "max_failure_codes": 3,
                "min_word_count_ratio": 0.5,
            }}},
        )
        draft = " ".join(["word"] * 1000)
        # Structural verdict but the code isn't in the narrow trigger set.
        result = await orchestrator._maybe_corrective_rerun(
            scene_card=sample_scene_card,
            generation_brief={"scene_objective": "x"},
            prose=draft,
            evaluation=_fail_structural_eval(["STRUCTURAL_PHASE_VIOLATION"]),
        )
        assert result == draft
        skipped = [e for e in ledger.get_events() if e["event_type"] == "corrective_rerun_skipped"]
        assert len(skipped) == 1
        assert skipped[0]["payload"]["skip_reason"] == "no_trigger_code_match"

    async def test_too_many_failure_codes_logs_skip(self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card):
        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"corrective_rerun": {
                "enabled": True,
                "trigger_codes": ["MISSING_TURNING_POINT"],
                "max_failure_codes": 3,
                "min_word_count_ratio": 0.5,
            }}},
        )
        draft = " ".join(["word"] * 1000)
        # 4 codes > 3 → drafter confusion signal.
        result = await orchestrator._maybe_corrective_rerun(
            scene_card=sample_scene_card,
            generation_brief={"scene_objective": "x"},
            prose=draft,
            evaluation=_fail_structural_eval([
                "MISSING_TURNING_POINT", "MOTIVATION_GAP", "CONTINUITY_CONTRADICTION", "SUBPLOT_DRIFT",
            ]),
        )
        assert result == draft
        skipped = [e for e in ledger.get_events() if e["event_type"] == "corrective_rerun_skipped"]
        assert len(skipped) == 1
        assert skipped[0]["payload"]["skip_reason"] == "too_many_failure_codes"

    async def test_word_count_floor_skips_collapsed_draft(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"corrective_rerun": {
                "enabled": True,
                "trigger_codes": ["MISSING_TURNING_POINT"],
                "max_failure_codes": 3,
                "min_word_count_ratio": 0.5,
            }}},
        )
        # Scene card has no target_word_count by default — add one for this test.
        card = dict(sample_scene_card)
        card["target_word_count"] = 2000
        # 800 words is 40% of 2000 — below the 0.5 floor → skip.
        draft = " ".join(["word"] * 800)
        result = await orchestrator._maybe_corrective_rerun(
            scene_card=card,
            generation_brief={"scene_objective": "x"},
            prose=draft,
            evaluation=_fail_structural_eval(["MISSING_TURNING_POINT"]),
        )
        assert result == draft
        skipped = [e for e in ledger.get_events() if e["event_type"] == "corrective_rerun_skipped"]
        assert len(skipped) == 1
        assert skipped[0]["payload"]["skip_reason"] == "draft_below_word_count_floor"


class TestCorrectiveRerunFire:
    """The happy path: trigger rules satisfied, drafter is re-invoked exactly once."""

    async def test_fires_once_with_failure_context(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        # Return different prose on the rerun call so we can assert the
        # orchestrator replaced the output.
        rerun_prose = " ".join(["REDRAFT"] * 200)
        mock_router.complete = AsyncMock(return_value=rerun_prose)

        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"corrective_rerun": {
                "enabled": True,
                "trigger_codes": ["MISSING_TURNING_POINT", "CLOSING_HOOK_VIOLATION"],
                "max_failure_codes": 3,
                "min_word_count_ratio": 0.5,
            }}},
        )
        card = dict(sample_scene_card)
        card["target_word_count"] = 200  # 200-word draft is 100% of target → passes floor.
        draft = " ".join(["orig"] * 200)
        result = await orchestrator._maybe_corrective_rerun(
            scene_card=card,
            generation_brief={"scene_objective": "x", "turning_point": {"trigger": "t", "shift": "s", "cost": "c"}, "closing_beat": "end"},
            prose=draft,
            evaluation=_fail_structural_eval(["MISSING_TURNING_POINT"]),
        )
        # Prose Stylist was called exactly once (the rerun).
        assert mock_router.complete.await_count == 1
        # Output was replaced with the rerun.
        assert result == rerun_prose
        # Telemetry pair fired.
        event_types = _event_types(ledger)
        assert "corrective_rerun_fired" in event_types
        assert "corrective_rerun_complete" in event_types

        fired = [e for e in ledger.get_events() if e["event_type"] == "corrective_rerun_fired"][0]
        assert "MISSING_TURNING_POINT" in fired["payload"]["trigger_codes"]


# --- Slice 11.1: narrow canon repair ------------------------------------------


def _report_with_fix(category: str = "anachronism", pattern: str = "cell phone", replacement: str = "commlink") -> dict:
    return {
        "verdict": "fail",
        "violations": [{
            "category": category,
            "severity": "moderate",
            "text": pattern,
            "explanation": "anachronistic term",
            "suggestion": f"use '{replacement}'",
        }],
        "summary": "one anachronism",
        "local_fixes": [{
            "category": category,
            "pattern": pattern,
            "replacement": replacement,
            "reason": "terminology swap",
        }],
    }


class TestCanonLocalFixes:
    async def test_flag_off_is_noop(self, mock_router, mock_assembler, ledger, temp_dir):
        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"canon_expert": {"apply_local_fixes": False, "local_fixes_whitelist": ["anachronism"]}}},
        )
        prose = "She pulled out her cell phone."
        result = orchestrator._maybe_apply_canon_local_fixes(
            prose=prose,
            continuity_report=_report_with_fix(),
            chapter_number=1,
            scene_number=1,
        )
        assert result == prose
        assert "canon_fix_applied" not in _event_types(ledger)

    async def test_applies_whitelisted_fix(self, mock_router, mock_assembler, ledger, temp_dir):
        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"canon_expert": {"apply_local_fixes": True, "local_fixes_whitelist": ["anachronism"]}}},
        )
        prose = "She pulled out her cell phone. She put the cell phone down."
        result = orchestrator._maybe_apply_canon_local_fixes(
            prose=prose,
            continuity_report=_report_with_fix("anachronism", "cell phone", "commlink"),
            chapter_number=1,
            scene_number=1,
        )
        # Both occurrences are swapped (literal str.replace replaces all).
        assert "cell phone" not in result
        assert result.count("commlink") == 2
        fired = [e for e in ledger.get_events() if e["event_type"] == "canon_fix_applied"]
        assert len(fired) == 1

    async def test_non_whitelist_category_is_rejected(self, mock_router, mock_assembler, ledger, temp_dir):
        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"canon_expert": {
                "apply_local_fixes": True,
                # Whitelist is only terminology_registry_swap; anachronism is NOT allowed.
                "local_fixes_whitelist": ["terminology_registry_swap"],
            }}},
        )
        prose = "She pulled out her cell phone."
        result = orchestrator._maybe_apply_canon_local_fixes(
            prose=prose,
            continuity_report=_report_with_fix("anachronism", "cell phone", "commlink"),
            chapter_number=1,
            scene_number=1,
        )
        assert result == prose  # No change.
        rejected = [e for e in ledger.get_events() if e["event_type"] == "canon_fix_rejected"]
        assert len(rejected) == 1
        assert rejected[0]["payload"]["reason"] == "category_not_whitelisted"

    async def test_pattern_not_in_prose_is_rejected(self, mock_router, mock_assembler, ledger, temp_dir):
        orchestrator = _make_orchestrator(
            mock_router, mock_assembler, ledger, temp_dir,
            runtime_flags={"runtime": {"canon_expert": {
                "apply_local_fixes": True,
                "local_fixes_whitelist": ["anachronism"],
            }}},
        )
        prose = "She pulled out her commlink."
        # Model proposed a fix but the pattern doesn't actually appear in the prose.
        result = orchestrator._maybe_apply_canon_local_fixes(
            prose=prose,
            continuity_report=_report_with_fix("anachronism", "mobile phone", "commlink"),
            chapter_number=1,
            scene_number=1,
        )
        assert result == prose
        rejected = [e for e in ledger.get_events() if e["event_type"] == "canon_fix_rejected"]
        assert len(rejected) == 1
        assert rejected[0]["payload"]["reason"] == "pattern_not_in_prose"


class TestMicroRepair:
    async def test_applies_valid_presence_patch_and_reruns_canon(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        micro_repair = MagicMock()
        micro_repair.run = AsyncMock(
            return_value={
                "summary": "Removed absent-character mention.",
                "repairs": [
                    {
                        "issue_type": "presence_violation",
                        "pattern": "Luke stepped from the doorway.",
                        "replacement": "A figure stepped from the doorway.",
                        "reason": "Remove absent character reference.",
                    }
                ],
            }
        )
        canon_expert = MagicMock()
        canon_expert.run = AsyncMock(return_value={"verdict": "pass", "violations": []})
        orchestrator = _make_orchestrator(
            mock_router,
            mock_assembler,
            ledger,
            temp_dir,
            runtime_flags={
                "runtime": {"micro_repair": {"enabled": True, "max_changed_ratio": 1.0}}
            },
            micro_repair=micro_repair,
            canon_expert=canon_expert,
        )

        prose = "Luke stepped from the doorway. Ben watched him carefully."
        updated_prose, updated_report, changed = await orchestrator._maybe_micro_repair(
            prose=prose,
            scene_card=sample_scene_card,
            continuity_report={"verdict": "pass", "violations": []},
            presence_violations=[
                {
                    "character": "Luke Skywalker",
                    "evidence": "Luke stepped from the doorway.",
                }
            ],
            chapter_number=1,
            scene_number=1,
        )

        assert changed is True
        assert updated_prose == "A figure stepped from the doorway. Ben watched him carefully."
        assert updated_report == {"verdict": "pass", "violations": []}
        assert canon_expert.run.await_count == 1
        event_types = _event_types(ledger)
        assert "micro_repair_fired" in event_types
        assert "micro_repair_applied" in event_types
        assert "micro_repair_complete" in event_types

    async def test_ambiguous_pattern_is_rejected_without_text_change(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        micro_repair = MagicMock()
        micro_repair.run = AsyncMock(
            return_value={
                "summary": "Tried to remove duplicated name.",
                "repairs": [
                    {
                        "issue_type": "presence_violation",
                        "pattern": "Luke stepped from the doorway.",
                        "replacement": "A figure stepped from the doorway.",
                        "reason": "Remove absent character reference.",
                    }
                ],
            }
        )
        canon_expert = MagicMock()
        canon_expert.run = AsyncMock(return_value={"verdict": "pass", "violations": []})
        orchestrator = _make_orchestrator(
            mock_router,
            mock_assembler,
            ledger,
            temp_dir,
            runtime_flags={
                "runtime": {"micro_repair": {"enabled": True, "max_changed_ratio": 1.0}}
            },
            micro_repair=micro_repair,
            canon_expert=canon_expert,
        )

        prose = (
            "Luke stepped from the doorway. "
            "Ben froze. Luke stepped from the doorway."
        )
        updated_prose, updated_report, changed = await orchestrator._maybe_micro_repair(
            prose=prose,
            scene_card=sample_scene_card,
            continuity_report={"verdict": "pass", "violations": []},
            presence_violations=[
                {
                    "character": "Luke Skywalker",
                    "evidence": "Luke stepped from the doorway.",
                }
            ],
            chapter_number=1,
            scene_number=1,
        )

        assert changed is False
        assert updated_prose == prose
        assert updated_report == {"verdict": "pass", "violations": []}
        assert canon_expert.run.await_count == 0
        rejected = [
            e for e in ledger.get_events() if e["event_type"] == "micro_repair_rejected"
        ]
        assert len(rejected) == 1
        assert rejected[0]["payload"]["reason"] == "ambiguous_pattern_occurrences"

    async def test_forbidden_name_in_replacement_is_rejected(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        micro_repair = MagicMock()
        micro_repair.run = AsyncMock(
            return_value={
                "summary": "Attempted replacement still names the absent character.",
                "repairs": [
                    {
                        "issue_type": "presence_violation",
                        "pattern": "Luke stepped from the doorway.",
                        "replacement": "Luke Skywalker stepped from the doorway.",
                        "reason": "Expanded the same absent name.",
                    }
                ],
            }
        )
        orchestrator = _make_orchestrator(
            mock_router,
            mock_assembler,
            ledger,
            temp_dir,
            runtime_flags={
                "runtime": {"micro_repair": {"enabled": True, "max_changed_ratio": 1.0}}
            },
            micro_repair=micro_repair,
        )

        prose = "Luke stepped from the doorway. Ben watched him carefully."
        updated_prose, updated_report, changed = await orchestrator._maybe_micro_repair(
            prose=prose,
            scene_card=sample_scene_card,
            continuity_report={"verdict": "pass", "violations": []},
            presence_violations=[
                {
                    "character": "Luke Skywalker",
                    "evidence": "Luke stepped from the doorway.",
                }
            ],
            chapter_number=1,
            scene_number=1,
        )

        assert changed is False
        assert updated_prose == prose
        assert updated_report == {"verdict": "pass", "violations": []}
        rejected = [
            e for e in ledger.get_events() if e["event_type"] == "micro_repair_rejected"
        ]
        assert len(rejected) == 1
        assert rejected[0]["payload"]["reason"] == "forbidden_name_in_replacement"
