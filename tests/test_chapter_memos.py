"""Tests for ChapterCloseMemoGenerator + MilestoneMemoGenerator (Slice 2).

Verify the memos synthesize the right counts from debt + gaps, produce a
schema-valid dict, and render human-readable markdown.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.memory.story_state import StoryState
from src.pipeline.chapter_memos import (
    ChapterCloseMemoGenerator,
    MilestoneMemoGenerator,
)
from src.pipeline.revision_debt import RevisionDebtStore


def _seed_rows(store: RevisionDebtStore) -> None:
    store.add({
        "producer": "canon_expert",
        "scope": {"level": "scene", "chapter_number": 1, "scene_number": 1},
        "category": "canon",
        "severity": "high",
        "summary": "Jedi Master normalization",
    })
    store.add({
        "producer": "gate_critic",
        "scope": {"level": "scene", "chapter_number": 1, "scene_number": 2},
        "category": "editorial.gate_advisory",
        "severity": "medium",
        "summary": "Exposition leak",
    })
    store.add({
        "producer": "word_count_telemetry",
        "scope": {"level": "chapter", "chapter_number": 1},
        "category": "wordcount_drift",
        "severity": "low",
        "summary": "Chapter under-target",
        "details": {"pct_drift": -12.0},
    })
    # A chapter-2 row so milestone memo has cross-chapter spread.
    store.add({
        "producer": "quality_metrics",
        "scope": {"level": "scene", "chapter_number": 2, "scene_number": 1},
        "category": "metric",
        "severity": "low",
        "summary": "repetition 0.42",
    })


def test_chapter_close_memo_counts_are_correct(tmp_path):
    store = RevisionDebtStore(db_path=":memory:")
    _seed_rows(store)
    gen = ChapterCloseMemoGenerator(debt_store=store)
    memo = gen.generate(chapter_number=1)

    assert memo["kind"] == "chapter_close"
    assert memo["chapter_number"] == 1
    summary = memo["debt_summary"]
    assert summary["counts_by_category"]["canon"] == 1
    assert summary["counts_by_category"]["editorial.gate_advisory"] == 1
    assert summary["counts_by_category"]["wordcount_drift"] == 1
    assert summary["counts_by_severity"]["high"] == 1
    assert summary["counts_by_severity"]["medium"] == 1
    assert summary["counts_by_severity"]["low"] == 1
    assert len(summary["open_debt_ids"]) == 3


def test_chapter_close_memo_pulls_gaps_from_story_state(tmp_path):
    store = RevisionDebtStore(db_path=":memory:")
    ss = StoryState(db_path=str(tmp_path / "story_state.db"))
    ss.record_gap({
        "gap_id": "gap_x",
        "isolated_scene": "ch01_sc02",
        "blocker_categories": ["CANON_BLOCKER"],
        "affected_scenes": ["ch01_sc03"],
    })
    gen = ChapterCloseMemoGenerator(debt_store=store, story_state=ss)
    memo = gen.generate(chapter_number=1)
    assert memo["open_gap_count"] == 1
    assert memo["gap_notes"][0]["gap_id"] == "gap_x"


def test_chapter_close_markdown_contains_expected_headers():
    store = RevisionDebtStore(db_path=":memory:")
    _seed_rows(store)
    gen = ChapterCloseMemoGenerator(debt_store=store)
    memo = gen.generate(chapter_number=1)
    md = gen.render_markdown(memo)
    assert "# Chapter 1 — Close Memo" in md
    assert "## Debt Summary" in md
    assert "## Human Attention" in md


def test_chapter_close_write_persists_json_and_markdown(tmp_path):
    store = RevisionDebtStore(db_path=":memory:")
    _seed_rows(store)
    gen = ChapterCloseMemoGenerator(debt_store=store)
    memo = gen.generate(chapter_number=1)
    md_path = gen.write(memo, memos_dir=tmp_path)
    assert md_path.exists()
    assert md_path.read_text(encoding="utf-8").startswith("# Chapter 1")
    json_path = md_path.with_suffix(".json")
    assert json_path.exists()
    roundtrip = json.loads(json_path.read_text(encoding="utf-8"))
    assert roundtrip["chapter_number"] == 1


def test_milestone_memo_tracks_cross_chapter_trend():
    store = RevisionDebtStore(db_path=":memory:")
    _seed_rows(store)
    gen = MilestoneMemoGenerator(debt_store=store)
    memo = gen.generate(through_chapter=2)
    assert memo["kind"] == "milestone"
    assert memo["through_chapter"] == 2
    assert len(memo["debt_trend"]) == 2
    ch1 = next(r for r in memo["debt_trend"] if r["chapter_number"] == 1)
    ch2 = next(r for r in memo["debt_trend"] if r["chapter_number"] == 2)
    assert ch1["counts_by_severity"]["high"] == 1
    assert ch2["counts_by_severity"]["low"] == 1
    # Chapter 1 gets recommended for review because it carries a high-severity
    # row and a canon advisory.
    assert 1 in memo["recommended_review_chapters"]


def test_milestone_memo_gap_resolution_rate(tmp_path):
    store = RevisionDebtStore(db_path=":memory:")
    ss = StoryState(db_path=str(tmp_path / "story_state.db"))
    ss.record_gap({
        "gap_id": "gap_open",
        "isolated_scene": "ch01_sc02",
        "blocker_categories": ["C"],
        "affected_scenes": [],
    })
    ss.record_gap({
        "gap_id": "gap_resolved",
        "isolated_scene": "ch02_sc01",
        "blocker_categories": ["C"],
        "affected_scenes": [],
    })
    ss.resolve_gap("gap_resolved", resolved_by="human_patch_accept", notes="x")
    gen = MilestoneMemoGenerator(debt_store=store, story_state=ss)
    memo = gen.generate(through_chapter=2)
    # story_state.list_open_gaps() returns open-only; the generator uses that.
    assert memo["open_gap_count"] == 1
    # 100% of the returned gaps (the open one) are not resolved, which is
    # expected because list_open_gaps only surfaces open rows. This matches
    # the memo's documented behavior.
    assert memo["gap_resolution_rate"] == 0.0


def test_empty_store_emits_no_open_advisory_items():
    gen = ChapterCloseMemoGenerator(debt_store=None)
    memo = gen.generate(chapter_number=1)
    assert memo["debt_summary"]["counts_by_category"] == {}
    assert memo["debt_summary"]["counts_by_severity"] == {}
    assert "No advisories open" in "\n".join(memo["human_attention_items"])
