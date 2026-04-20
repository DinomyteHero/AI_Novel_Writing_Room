"""Tests for the save-blocker layer (Stage 1f of the relay refactor).

Three blocker categories covered:

- CHARACTER_PRESENCE_BLOCKER: PresenceChecker returns a violation.
- CANON_BLOCKER: canon_expert verdict=fail + severity critical/moderate.
- POV_ADVISORY: heuristic hits — advisory only in v1, never blocks.

Also covers:
- Canon minor / post_divergence_drift: advisory only.
- Orchestrator end-to-end: non-empty blockers raise SaveBlockedError,
  quarantine folder gets populated, run_pipeline aborts the run.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator import Orchestrator
from src.pipeline.save_blockers import (
    Blocker,
    SaveBlockedError,
    check_save_blockers,
    detect_pov_advisory,
    write_quarantine,
)
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


class _FakePresenceChecker:
    """Minimal stand-in for PresenceChecker that returns a canned result."""

    def __init__(self, violations: list[dict]):
        self._violations = violations

    async def run(self, context: dict) -> dict:
        return {"violations": list(self._violations)}


class _FakeCanonExpert:
    """Minimal stand-in for CanonExpert that returns a canned result."""

    def __init__(self, result: dict):
        self._result = result

    async def run(self, context: dict) -> dict:
        return dict(self._result)


# -----------------------------------------------------------------
# Pure-function tests for save_blockers module
# -----------------------------------------------------------------


class TestCheckSaveBlockersPresence:
    async def test_presence_violation_fires_blocker(self, sample_scene_card):
        checker = _FakePresenceChecker(
            violations=[{"character": "Darth Vader", "evidence": '"You failed me."'}]
        )
        blockers = await check_save_blockers(
            prose="...",
            scene_card=sample_scene_card,
            continuity_report=None,
            presence_checker=checker,
        )
        assert len(blockers) == 1
        assert blockers[0].code == "CHARACTER_PRESENCE_BLOCKER"
        assert blockers[0].severity == "critical"
        assert "Darth Vader" in blockers[0].description
        assert blockers[0].evidence == '"You failed me."'

    async def test_empty_presence_violations_no_blocker(self, sample_scene_card):
        checker = _FakePresenceChecker(violations=[])
        blockers = await check_save_blockers(
            prose="Clean prose.",
            scene_card=sample_scene_card,
            continuity_report=None,
            presence_checker=checker,
        )
        assert blockers == []

    async def test_no_presence_checker_skips_presence_check(self, sample_scene_card):
        blockers = await check_save_blockers(
            prose="Clean prose.",
            scene_card=sample_scene_card,
            continuity_report=None,
            presence_checker=None,
        )
        assert blockers == []

    async def test_presence_checker_infra_failure_is_advisory(self, sample_scene_card):
        class Broken:
            async def run(self, context):
                raise RuntimeError("network error")

        blockers = await check_save_blockers(
            prose="...",
            scene_card=sample_scene_card,
            continuity_report=None,
            presence_checker=Broken(),
        )
        # Broken infrastructure must not block saves.
        assert blockers == []

    async def test_presence_violation_filtered_when_actually_listed(self):
        """LLM misclassification: reports 'Luke Skywalker' absent when the
        card lists 'Luke Skywalker' — post-filter drops the false positive."""
        card = {
            "chapter_number": 1,
            "scene_number": 1,
            "pov_character": "Ben Skywalker",
            "characters_present": ["Ben Skywalker", "Luke Skywalker"],
        }
        checker = _FakePresenceChecker(
            violations=[
                {"character": "Luke Skywalker", "evidence": "Luke stood in the doorway"}
            ]
        )
        blockers = await check_save_blockers(
            prose="Luke stood in the doorway.",
            scene_card=card,
            continuity_report=None,
            presence_checker=checker,
        )
        assert blockers == []

    async def test_presence_violation_filtered_first_name_subset(self):
        """'Luke' in prose when list has 'Luke Skywalker' — drop false positive."""
        card = {
            "chapter_number": 1, "scene_number": 1,
            "pov_character": "Ben Skywalker",
            "characters_present": ["Ben Skywalker", "Luke Skywalker"],
        }
        checker = _FakePresenceChecker(
            violations=[{"character": "Luke", "evidence": "..."}]
        )
        blockers = await check_save_blockers(
            prose="...", scene_card=card,
            continuity_report=None, presence_checker=checker,
        )
        assert blockers == []

    async def test_presence_violation_fires_when_not_in_list(self):
        """Regression guard: a truly absent character still blocks."""
        card = {
            "chapter_number": 1, "scene_number": 1,
            "pov_character": "Ben Skywalker",
            "characters_present": ["Ben Skywalker"],
        }
        checker = _FakePresenceChecker(
            violations=[{"character": "Luke Skywalker", "evidence": "Luke entered"}]
        )
        blockers = await check_save_blockers(
            prose="Luke entered.", scene_card=card,
            continuity_report=None, presence_checker=checker,
        )
        assert len(blockers) == 1
        assert "Luke Skywalker" in blockers[0].description

    async def test_presence_violation_missing_character_field_ignored(
        self, sample_scene_card
    ):
        checker = _FakePresenceChecker(
            violations=[{"character": "", "evidence": "..."}]
        )
        blockers = await check_save_blockers(
            prose="...",
            scene_card=sample_scene_card,
            continuity_report=None,
            presence_checker=checker,
        )
        assert blockers == []


class TestCheckSaveBlockersCanon:
    async def test_canon_critical_fires_blocker(self, sample_scene_card):
        report = {
            "verdict": "fail",
            "violations": [
                {
                    "category": "cross_continuity",
                    "severity": "critical",
                    "text": "a forbidden term",
                    "explanation": "belongs to a different continuity",
                    "suggestion": "replace",
                }
            ],
            "summary": "bad",
        }
        blockers = await check_save_blockers(
            prose="...",
            scene_card=sample_scene_card,
            continuity_report=report,
            presence_checker=None,
        )
        assert len(blockers) == 1
        assert blockers[0].code == "CANON_BLOCKER"
        assert blockers[0].severity == "critical"
        assert "cross_continuity" in blockers[0].description
        assert blockers[0].evidence == "a forbidden term"

    async def test_canon_moderate_fires_blocker(self, sample_scene_card):
        report = {
            "verdict": "fail",
            "violations": [
                {
                    "category": "era_accuracy",
                    "severity": "moderate",
                    "text": "anachronistic weapon",
                    "explanation": "wrong era",
                    "suggestion": "replace",
                }
            ],
        }
        blockers = await check_save_blockers(
            prose="...",
            scene_card=sample_scene_card,
            continuity_report=report,
            presence_checker=None,
        )
        assert len(blockers) == 1
        assert blockers[0].code == "CANON_BLOCKER"
        assert blockers[0].severity == "moderate"

    async def test_canon_minor_is_advisory(self, sample_scene_card):
        report = {
            "verdict": "fail",
            "violations": [
                {
                    "category": "franchise_voice",
                    "severity": "minor",
                    "text": "slightly off phrase",
                    "explanation": "register",
                }
            ],
        }
        blockers = await check_save_blockers(
            prose="...",
            scene_card=sample_scene_card,
            continuity_report=report,
            presence_checker=None,
        )
        # Minor findings are advisory, never block.
        assert blockers == []

    async def test_canon_post_divergence_drift_is_advisory(self, sample_scene_card):
        # Even with verdict=fail and severity=critical (clamped to minor by the
        # canon expert normally), post_divergence_drift MUST NOT block.
        report = {
            "verdict": "fail",
            "violations": [
                {
                    "category": "post_divergence_drift",
                    # Severity left high on purpose — category supersedes.
                    "severity": "critical",
                    "text": "drifted fact",
                    "explanation": "AU divergence",
                }
            ],
        }
        blockers = await check_save_blockers(
            prose="...",
            scene_card=sample_scene_card,
            continuity_report=report,
            presence_checker=None,
        )
        assert blockers == []

    async def test_canon_pass_verdict_no_blocker(self, sample_scene_card):
        report = {"verdict": "pass", "violations": []}
        blockers = await check_save_blockers(
            prose="...",
            scene_card=sample_scene_card,
            continuity_report=report,
            presence_checker=None,
        )
        assert blockers == []

    async def test_all_clean_empty_blocker_list(self, sample_scene_card):
        blockers = await check_save_blockers(
            prose="Clean prose.",
            scene_card=sample_scene_card,
            continuity_report={"verdict": "pass", "violations": []},
            presence_checker=_FakePresenceChecker(violations=[]),
        )
        assert blockers == []


class TestCheckSaveBlockersCombined:
    async def test_presence_and_canon_both_fire(self, sample_scene_card):
        checker = _FakePresenceChecker(
            violations=[{"character": "Outsider", "evidence": '"Hi."'}]
        )
        report = {
            "verdict": "fail",
            "violations": [
                {
                    "category": "anachronism",
                    "severity": "critical",
                    "text": "laptop",
                    "explanation": "wrong era",
                }
            ],
        }
        blockers = await check_save_blockers(
            prose="...",
            scene_card=sample_scene_card,
            continuity_report=report,
            presence_checker=checker,
        )
        codes = {b.code for b in blockers}
        assert codes == {"CHARACTER_PRESENCE_BLOCKER", "CANON_BLOCKER"}


# -----------------------------------------------------------------
# POV advisory
# -----------------------------------------------------------------


class TestPovAdvisory:
    def test_non_pov_interiority_detected(self):
        scene_card = {
            "pov_character": "Alex",
            "characters_present": ["Alex", "Bob"],
        }
        prose = "Alex stared out the window. Bob wondered whether this was wise."
        hits = detect_pov_advisory(prose, scene_card)
        assert len(hits) == 1
        assert hits[0]["character"] == "Bob"
        assert "Bob" in hits[0]["span"]
        assert "wondered" in hits[0]["span"]

    def test_pov_interiority_not_flagged(self):
        scene_card = {
            "pov_character": "Alex",
            "characters_present": ["Alex", "Bob"],
        }
        prose = "Alex wondered whether this was wise. Bob stood silently."
        hits = detect_pov_advisory(prose, scene_card)
        # Alex is POV; their interiority is fine. Bob is not interior here.
        assert hits == []

    def test_no_pov_returns_empty(self):
        scene_card = {"pov_character": "", "characters_present": ["Alex", "Bob"]}
        hits = detect_pov_advisory("Bob felt sad.", scene_card)
        assert hits == []

    def test_empty_characters_present_returns_empty(self):
        scene_card = {"pov_character": "Alex", "characters_present": []}
        hits = detect_pov_advisory("Bob felt sad.", scene_card)
        assert hits == []


# -----------------------------------------------------------------
# write_quarantine
# -----------------------------------------------------------------


class TestWriteQuarantine:
    def test_writes_all_three_files(self, tmp_path, sample_scene_card):
        blockers = [
            Blocker(
                code="CANON_BLOCKER",
                severity="critical",
                description="era_accuracy: bad",
                evidence="laptop",
            )
        ]
        brief = {"scene_objective": "intro", "target_word_count": 1000}
        scene_dir = write_quarantine(
            quarantine_root=tmp_path / "quarantine",
            chapter_number=2,
            scene_number=3,
            prose="Some quarantined prose.",
            blockers=blockers,
            brief=brief,
            scene_card=sample_scene_card,
        )
        assert scene_dir.name == "ch02_sc03"
        assert (scene_dir / "prose.md").read_text(encoding="utf-8") == "Some quarantined prose."
        report = json.loads((scene_dir / "blockers.json").read_text(encoding="utf-8"))
        assert report["chapter_number"] == 2
        assert report["scene_number"] == 3
        assert report["blockers"][0]["code"] == "CANON_BLOCKER"
        assert report["blockers"][0]["evidence"] == "laptop"
        brief_written = json.loads((scene_dir / "brief.json").read_text(encoding="utf-8"))
        assert brief_written["scene_objective"] == "intro"

    def test_brief_optional(self, tmp_path, sample_scene_card):
        scene_dir = write_quarantine(
            quarantine_root=tmp_path / "quarantine",
            chapter_number=1,
            scene_number=1,
            prose="p",
            blockers=[
                Blocker(
                    code="CHARACTER_PRESENCE_BLOCKER",
                    severity="critical",
                    description="x",
                    evidence="y",
                )
            ],
            brief=None,
            scene_card=sample_scene_card,
        )
        assert (scene_dir / "prose.md").exists()
        assert (scene_dir / "blockers.json").exists()
        assert not (scene_dir / "brief.json").exists()


# -----------------------------------------------------------------
# Orchestrator integration: save-blocker raises + aborts run
# -----------------------------------------------------------------


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
    a.concept_seed = {}
    return a


class TestOrchestratorSaveBlockerIntegration:
    async def test_presence_violation_quarantines_and_raises(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        prose = "word " * 100
        mock_router.complete = AsyncMock(return_value=prose)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        checker = _FakePresenceChecker(
            violations=[{"character": "Outsider", "evidence": '"I am here."'}]
        )

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            presence_checker=checker,
        )

        with pytest.raises(SaveBlockedError) as excinfo:
            await orchestrator.run_chapter(sample_scene_card)

        err = excinfo.value
        assert err.chapter_number == sample_scene_card["chapter_number"]
        assert err.quarantine_path.exists()
        assert (err.quarantine_path / "prose.md").exists()
        report = json.loads((err.quarantine_path / "blockers.json").read_text())
        assert report["blockers"][0]["code"] == "CHARACTER_PRESENCE_BLOCKER"

        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "save_blocked" in event_types
        # Saved manuscript MUST NOT exist — save path was short-circuited.
        saved_glob = list((Path(temp_dir) / "manuscripts").glob("chapter_*.md"))
        assert saved_glob == []

    async def test_canon_critical_quarantines_and_raises(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        prose = "word " * 100
        mock_router.complete = AsyncMock(return_value=prose)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        canon = _FakeCanonExpert(
            result={
                "verdict": "fail",
                "violations": [
                    {
                        "category": "anachronism",
                        "severity": "critical",
                        "text": "laptop",
                        "explanation": "wrong era",
                    }
                ],
            }
        )

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            canon_expert=canon,
        )

        with pytest.raises(SaveBlockedError) as excinfo:
            await orchestrator.run_chapter(sample_scene_card)

        report = json.loads((excinfo.value.quarantine_path / "blockers.json").read_text())
        assert report["blockers"][0]["code"] == "CANON_BLOCKER"
        assert report["blockers"][0]["severity"] == "critical"

    async def test_canon_minor_does_not_block(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        prose = "word " * 100
        mock_router.complete = AsyncMock(return_value=prose)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        canon = _FakeCanonExpert(
            result={
                "verdict": "fail",
                "violations": [
                    {
                        "category": "franchise_voice",
                        "severity": "minor",
                        "text": "phrase",
                        "explanation": "light register drift",
                    }
                ],
            }
        )

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            canon_expert=canon,
        )

        # No exception — scene saves cleanly.
        result = await orchestrator.run_chapter(sample_scene_card)
        assert Path(result["output_path"]).exists()
        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "save_blocked" not in event_types
        # continuity_editor event should still fire.
        assert "continuity_editor_complete" in event_types

    async def test_all_clean_saves_successfully(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        prose = "word " * 100
        mock_router.complete = AsyncMock(return_value=prose)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            canon_expert=_FakeCanonExpert(result={"verdict": "pass", "violations": []}),
            presence_checker=_FakePresenceChecker(violations=[]),
        )

        result = await orchestrator.run_chapter(sample_scene_card)
        assert Path(result["output_path"]).exists()
        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "save_blocked" not in event_types
        assert "continuity_editor_complete" in event_types

    async def test_run_pipeline_aborts_after_save_blocker(
        self, mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
    ):
        """run_pipeline catches SaveBlockedError and does not proceed to subsequent scenes."""
        prose = "word " * 100
        mock_router.complete = AsyncMock(return_value=prose)
        mock_router.complete_structured = AsyncMock(return_value=_make_gate_pass_dict())

        # Two scenes: first has a presence violation, second is clean.
        first_card = dict(sample_scene_card)
        first_card["chapter_number"] = 1
        first_card["scene_number"] = 1
        second_card = dict(sample_scene_card)
        second_card["chapter_number"] = 1
        second_card["scene_number"] = 2

        checker = _FakePresenceChecker(
            violations=[{"character": "Intruder", "evidence": '"..."'}]
        )

        orchestrator = Orchestrator(
            router=mock_router,
            context_assembler=mock_assembler,
            ledger=ledger,
            manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
            presence_checker=checker,
        )

        results = await orchestrator.run_pipeline([first_card, second_card])

        # First scene was blocked, so nothing was appended to results.
        assert results == []
        event_types = [e["event_type"] for e in ledger.get_events()]
        assert "save_blocked" in event_types
        # Second scene should NOT have run.
        chapter_starts = [
            e for e in ledger.get_events() if e["event_type"] == "chapter_start"
        ]
        assert len(chapter_starts) == 1
        assert chapter_starts[0]["scene_number"] == 1
