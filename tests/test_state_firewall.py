"""Tests for the Slice 1 state firewall.

Focus: the firewall isolates a scene (manifest + gap row + ledger events)
and returns a continuation decision driven by the successor classifier.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.memory.story_state import StoryState
from src.pipeline.save_blockers import Blocker, should_abort_run
from src.pipeline.state_firewall import (
    FirewallDecision,
    StateFirewall,
    _derive_gap_id,
)
from src.pipeline.successor_classifier import SuccessorClassifier
from src.run_ledger import RunLedger


# --- should_abort_run --------------------------------------------------

def test_should_abort_run_default_is_true():
    """With no runtime_flags (or flag unset), preserve pre-Slice-1 behavior."""
    assert should_abort_run(None) is True
    assert should_abort_run({}) is True
    assert should_abort_run({"runtime": {}}) is True
    assert should_abort_run({"runtime": {"firewall": {}}}) is True
    assert should_abort_run({"runtime": {"firewall": {"enabled": False}}}) is True


def test_should_abort_run_when_firewall_on_is_false():
    assert should_abort_run({"runtime": {"firewall": {"enabled": True}}}) is False


def test_derive_gap_id_shape():
    gid = _derive_gap_id("ch04_sc07")
    assert gid.startswith("gap_")
    assert gid.endswith("_ch04_sc07")


# --- fixtures ----------------------------------------------------------

@pytest.fixture
def fresh_stack(tmp_path: Path):
    """Per-test isolated StoryState + RunLedger + paths shim."""
    state_db = tmp_path / "story_state.db"
    ledger_db = tmp_path / "run_ledger.db"
    quarantine = tmp_path / "quarantine"

    story_state = StoryState(db_path=str(state_db))
    ledger = RunLedger(db_path=str(ledger_db), run_id="test-run")
    paths_shim = SimpleNamespace(quarantine_dir=quarantine)

    yield SimpleNamespace(
        story_state=story_state,
        ledger=ledger,
        paths_shim=paths_shim,
        quarantine=quarantine,
    )

    story_state.close()
    ledger.close()


def _mk_card(chapter: int, scene: int, *, pov="A", phase="setup", cast=None):
    return {
        "chapter_number": chapter,
        "scene_number": scene,
        "pov_character": pov,
        "structural_phase": phase,
        "characters_present": cast or [pov],
    }


def _mk_blocker(code="CANON_BLOCKER") -> Blocker:
    return Blocker(
        code=code, severity="critical",
        description="test blocker", evidence="line 42",
    )


# --- handle_blocker end-to-end ----------------------------------------

def test_handle_blocker_writes_manifest_and_records_gap(fresh_stack):
    """Gap manifest lands beside the quarantined scene; SQLite row is written.

    Classifier off → conservative soft-halt → continue_run=False.
    """
    blocked = _mk_card(4, 7, pov="Hunter", phase="midpoint",
                       cast=["Hunter", "Jora"])
    successors = [
        _mk_card(4, 8, pov="Hunter", phase="attack",
                 cast=["Hunter"]),
        _mk_card(5, 1, pov="Leia", phase="response",
                 cast=["Leia"]),
    ]

    firewall = StateFirewall(
        project_paths=fresh_stack.paths_shim,
        story_state=fresh_stack.story_state,
        classifier=SuccessorClassifier(),
        ledger=fresh_stack.ledger,
        runtime_flags={"runtime": {"firewall": {"enabled": True}}},
        # classifier sub-flag not set → defaults to False (conservative)
    )

    decision = firewall.handle_blocker(
        scene_card=blocked,
        prose="",
        brief=None,
        blockers=[_mk_blocker()],
        subsequent_scenes=successors,
    )

    assert isinstance(decision, FirewallDecision)
    assert decision.isolated is True
    assert decision.gap_id.startswith("gap_")
    # Classifier disabled → every successor is soft_halt.
    assert decision.continue_run is False
    assert set(decision.soft_halted_scenes) == {"ch04_sc08", "ch05_sc01"}

    # Gap manifest on disk
    manifest_path = fresh_stack.quarantine / "ch04_sc07" / "gap_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["isolated_scene"] == "ch04_sc07"
    assert manifest["blocker_categories"] == ["CANON_BLOCKER"]
    assert manifest["gap_id"] == decision.gap_id
    assert len(manifest["successor_decisions"]) == 2

    # SQLite row
    open_gaps = fresh_stack.story_state.list_open_gaps()
    assert len(open_gaps) == 1
    assert open_gaps[0]["gap_id"] == decision.gap_id
    assert open_gaps[0]["status"] == "open"
    assert open_gaps[0]["blocker_categories"] == ["CANON_BLOCKER"]


def test_handle_blocker_continues_when_classifier_allows(fresh_stack):
    """When the classifier is on and all successors are continue_with_note,
    the firewall returns continue_run=True."""
    blocked = _mk_card(4, 7, pov="Hunter", phase="midpoint",
                       cast=["Hunter"])
    # Distant, disjoint successor → rule 5 (loose_downstream, continue_with_note).
    successors = [
        _mk_card(9, 9, pov="Zora", phase="resolution",
                 cast=["Zora"]),
    ]

    firewall = StateFirewall(
        project_paths=fresh_stack.paths_shim,
        story_state=fresh_stack.story_state,
        classifier=SuccessorClassifier(),
        ledger=fresh_stack.ledger,
        runtime_flags={
            "runtime": {"firewall": {
                "enabled": True,
                "successor_classifier": {"enabled": True},
            }},
        },
    )

    decision = firewall.handle_blocker(
        scene_card=blocked,
        prose="",
        brief=None,
        blockers=[_mk_blocker()],
        subsequent_scenes=successors,
    )
    assert decision.continue_run is True
    assert decision.soft_halted_scenes == []
    assert decision.continue_with_gap_note == ["ch09_sc09"]


def test_handle_blocker_soft_halts_when_any_successor_is_dependent(fresh_stack):
    """Explicit depends_on → soft_halt → continue_run=False even with one
    matching successor in a larger list."""
    blocked = _mk_card(4, 7, pov="Hunter", phase="midpoint",
                       cast=["Hunter"])
    successors = [
        _mk_card(9, 9, pov="Zora", phase="resolution", cast=["Zora"]),
        {
            **_mk_card(10, 1, pov="Joe", phase="attack", cast=["Joe"]),
            "depends_on": ["ch04_sc07"],
        },
    ]

    firewall = StateFirewall(
        project_paths=fresh_stack.paths_shim,
        story_state=fresh_stack.story_state,
        classifier=SuccessorClassifier(),
        ledger=fresh_stack.ledger,
        runtime_flags={
            "runtime": {"firewall": {
                "enabled": True,
                "successor_classifier": {"enabled": True},
            }},
        },
    )

    decision = firewall.handle_blocker(
        scene_card=blocked,
        prose="",
        brief=None,
        blockers=[_mk_blocker()],
        subsequent_scenes=successors,
    )
    assert decision.continue_run is False
    assert "ch10_sc01" in decision.soft_halted_scenes
    assert "ch09_sc09" in decision.continue_with_gap_note


def test_handle_blocker_emits_scene_isolated_and_gap_note_ledger_events(fresh_stack):
    blocked = _mk_card(4, 7, pov="Hunter")
    firewall = StateFirewall(
        project_paths=fresh_stack.paths_shim,
        story_state=fresh_stack.story_state,
        classifier=SuccessorClassifier(),
        ledger=fresh_stack.ledger,
        runtime_flags={"runtime": {"firewall": {"enabled": True}}},
    )
    firewall.handle_blocker(
        scene_card=blocked,
        prose="",
        brief=None,
        blockers=[_mk_blocker()],
        subsequent_scenes=[],
    )
    # Pull the two events we expect
    events = fresh_stack.ledger.get_events(chapter_number=4)
    event_types = {e["event_type"] for e in events}
    assert "scene_isolated" in event_types
    assert "gap_note_recorded" in event_types
    # scene_isolated should carry error-level semantics
    scene_isolated = next(e for e in events if e["event_type"] == "scene_isolated")
    assert scene_isolated["payload"].get("level") == "error"
    gap_note = next(e for e in events if e["event_type"] == "gap_note_recorded")
    assert gap_note["payload"].get("level") == "warn"


def test_handle_blocker_with_no_successors_continues(fresh_stack):
    """Blocker on last scene of a chapter with no next-chapter scenes: no
    successors to classify, so the firewall permits continuation."""
    blocked = _mk_card(10, 9, pov="A")
    firewall = StateFirewall(
        project_paths=fresh_stack.paths_shim,
        story_state=fresh_stack.story_state,
        classifier=SuccessorClassifier(),
        ledger=fresh_stack.ledger,
        runtime_flags={
            "runtime": {"firewall": {
                "enabled": True,
                "successor_classifier": {"enabled": True},
            }},
        },
    )
    decision = firewall.handle_blocker(
        scene_card=blocked,
        prose="",
        brief=None,
        blockers=[_mk_blocker("CHARACTER_PRESENCE_BLOCKER")],
        subsequent_scenes=[],
    )
    assert decision.continue_run is True
    assert decision.soft_halted_scenes == []
    assert decision.continue_with_gap_note == []
