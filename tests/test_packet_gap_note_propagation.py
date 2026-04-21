"""Tests for Slice 1 \u2192 Slice 2 gap-note propagation.

The firewall (Slice 1) records gap notes in ``story_state.db``. Slice 2's
overlay compilation pulls open gaps affecting the current chapter into the
packet's ``trusted_state_gap_notes`` field, and the packet's markdown render
surfaces them under "Narrative Continuity Gaps" with a template that steers
the drafter toward narrative gap-writing instead of confabulation.

Spec \u00a76.4: "a drafter run on a scene flagged ``continue_with_note``
produces prose that does **not** reference specific facts invented for the
isolated scene. Measured by: if isolated scene's ``turning_point`` or
``revelations[]`` text appears verbatim in successor prose, test fails."

This module covers the plumbing: overlay carries the gap, render surfaces it
with the right template, and downstream prompt assembly includes it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.memory.story_state import StoryState
from src.pipeline.chapter_packet import ChapterPacketCompiler


@pytest.fixture
def blueprint() -> dict:
    return {
        "chapter_number": 1,
        "chapter_mission": "Establish",
        "chapter_turn": "Turn",
        "pov_allocation": ["Ben"],
        "scene_plan": [
            {"scene_number": 1, "role": "hook"},
            {"scene_number": 2, "role": "reveal"},
            {"scene_number": 3, "role": "decision"},
        ],
    }


@pytest.fixture
def story_state_with_gap(tmp_path: Path) -> StoryState:
    db_path = tmp_path / "story_state.db"
    store = StoryState(db_path=str(db_path))
    store.record_gap({
        "gap_id": "gap_20260420_ch01_sc02",
        "isolated_scene": "ch01_sc02",
        "blocker_categories": ["CANON_BLOCKER"],
        "affected_scenes": ["ch01_sc03"],
        "created_at": "2026-04-20T12:00:00+00:00",
    })
    return store


def test_overlay_surfaces_open_gap_for_successor_scene(
    blueprint, story_state_with_gap,
):
    compiler = ChapterPacketCompiler(
        concept_seed={"meta": {"project_title": "t", "franchise": "f"}},
        blueprints={1: blueprint},
        story_state=story_state_with_gap,
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 3},
    )
    assert len(overlay.trusted_state_gap_notes) == 1
    note = overlay.trusted_state_gap_notes[0]
    assert note["gap_id"] == "gap_20260420_ch01_sc02"
    assert "CANON_BLOCKER" in note["blocker_categories"]
    assert note["status"] == "open"


def test_render_uses_gap_note_template(blueprint, story_state_with_gap):
    compiler = ChapterPacketCompiler(
        concept_seed={"meta": {"project_title": "t", "franchise": "f"}},
        blueprints={1: blueprint},
        story_state=story_state_with_gap,
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 3},
    )
    md = overlay.render_markdown()
    # Template anchors \u2014 must steer the drafter toward narrative gap-writing.
    assert "Narrative Continuity Gaps" in md
    assert "ch01_sc02" in md
    assert "do not assume any facts" in md.lower()
    assert ("unclear" in md.lower()) or ("write around" in md.lower())


def test_resolved_gap_does_not_propagate(blueprint, tmp_path):
    store = StoryState(db_path=str(tmp_path / "story_state.db"))
    store.record_gap({
        "gap_id": "gap_resolved",
        "isolated_scene": "ch01_sc02",
        "blocker_categories": ["CANON_BLOCKER"],
        "affected_scenes": ["ch01_sc03"],
    })
    store.resolve_gap("gap_resolved", resolved_by="human_patch_accept", notes="patched")

    compiler = ChapterPacketCompiler(
        concept_seed={"meta": {"project_title": "t", "franchise": "f"}},
        blueprints={1: blueprint},
        story_state=store,
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 3},
    )
    # list_open_gaps filters by status='open', so resolved gaps are absent.
    assert overlay.trusted_state_gap_notes == []
    md = overlay.render_markdown()
    assert "Narrative Continuity Gaps" not in md
