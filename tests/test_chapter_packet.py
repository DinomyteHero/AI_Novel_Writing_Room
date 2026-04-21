"""Tests for ChapterPacket + ChapterPacketCompiler (Slice 2).

Covers:
- compile_base produces expected fields from blueprint + seed.
- Base is immutable after creation (frozen dataclass).
- compile_overlay never mutates the base (base.overlay_version stays 0).
- overlay_version increments monotonically per overlay.
- Overlay carries scene_card + gap notes when story_state is wired.
- render_markdown preserves section ordering required by the parity test.
- to_json / from_json roundtrip.
- Slice-3/4/5 collaborators (promise_ledger, continuity_log, sociogram) are
  treated as optional \u2014 None keeps the relevant packet fields empty.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.pipeline.chapter_packet import ChapterPacket, ChapterPacketCompiler


@pytest.fixture
def blueprint_ch1() -> dict:
    return {
        "chapter_number": 1,
        "chapter_mission": "Establish the wrongness",
        "chapter_turn": "Passive unease becomes active pursuit",
        "structural_phase": "setup",
        "pov_allocation": ["Ben Skywalker"],
        "pacing_curve": "rising",
        "scene_plan": [
            {"scene_number": 1, "role": "hook", "purpose": "physical failure in sparring"},
            {"scene_number": 2, "role": "reveal", "purpose": "Luke validates wrongness"},
            {"scene_number": 3, "role": "decision", "purpose": "departure"},
        ],
        "reveal_payload": ["R01"],
        "hook_movements": {"planted": ["H01"], "advanced": [], "resolved": []},
        "subplot_obligations": ["SP-A"],
        "relationship_turns": [
            {"dyad": "Ben/Luke", "from": "distance", "to": "private alliance"},
        ],
        "exit_vector": "Ben in hyperspace, wrongness pulling not just pointing",
    }


@pytest.fixture
def concept_seed() -> dict:
    return {
        "meta": {"project_title": "Test Book", "franchise": "test"},
        "canon_pillars": [
            {"title": "Force wrongness", "body": "Wrongness is auditory, not visual"},
        ],
    }


@pytest.fixture
def compiler(blueprint_ch1, concept_seed) -> ChapterPacketCompiler:
    return ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
    )


def test_compile_base_hydrates_mission_and_pressure(compiler):
    base = compiler.compile_base(chapter_number=1)
    assert base.chapter_number == 1
    assert base.overlay_version == 0
    assert "wrongness" in base.mission
    assert "active pursuit" in base.chapter_turn
    assert len(base.pressure_ladder) == 3
    assert base.pressure_ladder[0]["scene_number"] == 1
    assert base.pressure_ladder[0]["label"] == "hook"
    assert base.pov_arc_pressure["pov_character"] == "Ben Skywalker"
    assert base.pov_arc_pressure["structural_phase"] == "setup"


def test_compile_base_includes_canon_slices(compiler):
    base = compiler.compile_base(chapter_number=1)
    titles = [s["title"] for s in base.canon_slices]
    assert "Force wrongness" in titles


def test_compile_base_builds_next_scene_obligations(compiler):
    base = compiler.compile_base(chapter_number=1)
    kinds = [o["kind"] for o in base.next_scene_obligations]
    assert "subplot" in kinds
    assert "relationship_turn" in kinds
    assert "reveal" in kinds
    assert "hook_planted" in kinds


def test_compile_base_raises_for_missing_chapter(compiler):
    with pytest.raises(KeyError):
        compiler.compile_base(chapter_number=99)


def test_base_is_frozen_dataclass(compiler):
    base = compiler.compile_base(chapter_number=1)
    with pytest.raises(Exception):  # FrozenInstanceError subclasses AttributeError
        base.mission = "something else"
    with pytest.raises(Exception):
        base.overlay_version = 5


def test_overlay_does_not_mutate_base(compiler):
    base = compiler.compile_base(chapter_number=1)
    scene_card = {
        "chapter_number": 1, "scene_number": 1,
        "pov_character": "Ben", "mission": "spar and fail",
    }
    overlay = compiler.compile_overlay(base=base, scene_card=scene_card)
    # Base unchanged
    assert base.overlay_version == 0
    assert base.scene_card == {}
    # Overlay composed base + scene
    assert overlay.overlay_version == 1
    assert overlay.scene_number == 1
    assert overlay.scene_card["pov_character"] == "Ben"
    # Structural fields carry through
    assert overlay.mission == base.mission
    assert overlay.chapter_number == base.chapter_number
    assert overlay.pressure_ladder == base.pressure_ladder


def test_overlay_version_monotonic(compiler):
    base = compiler.compile_base(chapter_number=1)
    scene1 = {"chapter_number": 1, "scene_number": 1}
    scene2 = {"chapter_number": 1, "scene_number": 2}
    o1 = compiler.compile_overlay(base=base, scene_card=scene1)
    o2 = compiler.compile_overlay(base=base, scene_card=scene2)
    assert o1.overlay_version == 1
    assert o2.overlay_version == 1  # each overlay composes base (overlay_version 0)
    # Sequential overlays off a previous overlay also increment.
    o3 = compiler.compile_overlay(base=o2, scene_card={"chapter_number": 1, "scene_number": 3})
    assert o3.overlay_version == 2


def test_overlay_pulls_open_gap_notes(blueprint_ch1, concept_seed):
    story_state = MagicMock()
    story_state.list_open_gaps.return_value = [
        {
            "gap_id": "gap_test_1",
            "isolated_scene": "ch01_sc02",
            "blocker_categories": ["CANON_BLOCKER"],
            "affected_scenes": ["ch01_sc03"],
            "created_at": "2026-04-20T10:00:00+00:00",
            "status": "open",
        }
    ]
    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
        story_state=story_state,
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 3},
    )
    assert len(overlay.trusted_state_gap_notes) == 1
    note = overlay.trusted_state_gap_notes[0]
    assert note["gap_id"] == "gap_test_1"
    story_state.list_open_gaps.assert_called_with(chapter_number=1)


def test_overlay_gap_notes_render_with_template(blueprint_ch1, concept_seed):
    story_state = MagicMock()
    story_state.list_open_gaps.return_value = [
        {
            "gap_id": "gap_test_1",
            "isolated_scene": "ch01_sc02",
            "blocker_categories": ["CANON_BLOCKER"],
            "affected_scenes": ["ch01_sc03"],
            "created_at": "2026-04-20T10:00:00+00:00",
            "status": "open",
        }
    ]
    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
        story_state=story_state,
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 3},
    )
    rendered = overlay.render_markdown()
    assert "Narrative Continuity Gaps" in rendered
    assert "ch01_sc02" in rendered
    assert "isolated" in rendered.lower()
    # The template must steer the drafter toward narrative gap-writing, not
    # confabulation.
    assert "unclear" in rendered.lower() or "write around" in rendered.lower()


def test_render_markdown_section_ordering(compiler):
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 1, "pov_character": "Ben"},
    )
    md = overlay.render_markdown()
    # Ordering invariants checked by the parity test in tests/test_packet_parity.py:
    # packet header before scene card; scene card before flat snapshot.
    i_pkt = md.find("## Chapter Packet")
    i_card = md.find("## Scene Card")
    assert i_pkt != -1
    assert i_card != -1
    assert i_pkt < i_card


def test_to_json_roundtrip(compiler):
    base = compiler.compile_base(chapter_number=1)
    payload = base.to_json()
    assert payload["overlay_version"] == 0
    assert payload["mission"] == base.mission
    # flat_context_snapshot is stripped on to_json() to avoid duplicating
    # the legacy ContextAssembler payload on disk.
    assert "flat_context_snapshot" not in payload
    roundtripped = ChapterPacket.from_json(payload)
    assert roundtripped.chapter_number == base.chapter_number
    assert roundtripped.mission == base.mission
    assert roundtripped.pressure_ladder == base.pressure_ladder


def test_slice3_5_hooks_empty_when_collaborators_none(compiler):
    base = compiler.compile_base(chapter_number=1)
    assert base.active_promises == []
    assert base.continuity_events == []
    assert base.relationship_context == {}


def test_slice3_active_promises_pulled_when_ledger_wired(blueprint_ch1, concept_seed):
    promise_ledger = MagicMock()
    promise_ledger.active_for_chapter.return_value = [
        {"promise_id": "P1", "setup_scene": "ch01_sc01",
         "due_by_scene": "ch05_close", "status": "open"},
    ]
    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
        promise_ledger=promise_ledger,
    )
    base = compiler.compile_base(chapter_number=1)
    assert base.active_promises == [
        {"promise_id": "P1", "setup_scene": "ch01_sc01",
         "due_by_scene": "ch05_close", "status": "open"},
    ]
