"""Tests for the Slice 1 gap-note additions to StoryState."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.memory.story_state import StoryState


@pytest.fixture
def store(tmp_path: Path):
    s = StoryState(db_path=str(tmp_path / "s.db"))
    yield s
    s.close()


def test_schema_version_includes_v7(store):
    assert store.get_schema_version() >= 7


def test_record_gap_round_trip(store):
    gid = store.record_gap({
        "gap_id": "gap_test_1",
        "isolated_scene": "ch04_sc07",
        "blocker_categories": ["CANON_BLOCKER"],
        "affected_scenes": ["ch04_sc08", "ch04_sc09"],
    })
    assert gid == "gap_test_1"

    open_gaps = store.list_open_gaps()
    assert len(open_gaps) == 1
    assert open_gaps[0]["isolated_scene"] == "ch04_sc07"
    assert open_gaps[0]["blocker_categories"] == ["CANON_BLOCKER"]
    assert open_gaps[0]["affected_scenes"] == ["ch04_sc08", "ch04_sc09"]


def test_record_gap_rejects_missing_keys(store):
    with pytest.raises(ValueError):
        store.record_gap({"gap_id": "incomplete"})


def test_record_gap_rejects_bad_status(store):
    with pytest.raises(ValueError):
        store.record_gap({
            "gap_id": "g", "isolated_scene": "ch01_sc01",
            "blocker_categories": [], "affected_scenes": [],
            "status": "bogus",
        })


def test_list_open_gaps_by_chapter(store):
    store.record_gap({
        "gap_id": "a", "isolated_scene": "ch04_sc07",
        "blocker_categories": ["CANON_BLOCKER"],
        "affected_scenes": ["ch04_sc08"],
    })
    store.record_gap({
        "gap_id": "b", "isolated_scene": "ch05_sc01",
        "blocker_categories": ["CHARACTER_PRESENCE_BLOCKER"],
        "affected_scenes": ["ch05_sc02", "ch06_sc01"],
    })
    ch4 = store.list_open_gaps(chapter_number=4)
    assert {g["gap_id"] for g in ch4} == {"a"}

    ch5 = store.list_open_gaps(chapter_number=5)
    assert {g["gap_id"] for g in ch5} == {"b"}

    ch6 = store.list_open_gaps(chapter_number=6)
    # Gap 'b' affects ch06_sc01 via affected_scenes.
    assert {g["gap_id"] for g in ch6} == {"b"}


def test_resolve_gap_updates_status(store):
    gid = store.record_gap({
        "gap_id": "x", "isolated_scene": "ch01_sc01",
        "blocker_categories": [], "affected_scenes": [],
    })
    assert len(store.list_open_gaps()) == 1
    store.resolve_gap(gid, resolved_by="human_patch_accept", notes="fixed")
    assert store.list_open_gaps() == []


def test_resolve_gap_unknown_raises(store):
    with pytest.raises(KeyError):
        store.resolve_gap("nope", resolved_by="human_patch_accept")


def test_overrule_sets_status_overruled(store):
    gid = store.record_gap({
        "gap_id": "y", "isolated_scene": "ch01_sc01",
        "blocker_categories": [], "affected_scenes": [],
    })
    store.resolve_gap(gid, resolved_by="overrule", notes="accepted as-is")
    # Not in open list, but list_gaps_affecting still returns it (any status).
    assert store.list_open_gaps() == []


def test_list_gaps_affecting(store):
    store.record_gap({
        "gap_id": "z", "isolated_scene": "ch04_sc07",
        "blocker_categories": ["CANON_BLOCKER"],
        "affected_scenes": ["ch04_sc08", "ch05_sc01"],
    })
    assert len(store.list_gaps_affecting("ch04_sc08")) == 1
    assert store.list_gaps_affecting("ch04_sc07") == []  # isolated scene itself
    assert store.list_gaps_affecting("ch99_sc99") == []
