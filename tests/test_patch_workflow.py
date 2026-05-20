"""Slice 6 patch-workflow CLI tests.

End-to-end smoke tests that construct a synthetic book + run dir under
``tmp_path`` and drive ``scripts/patch_workflow.py`` through each subcommand.
Uses ``--no-ledger`` to avoid the real RunLedger so tests stay hermetic.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.memory.promise_ledger import PromiseLedger
from src.memory.story_state import StoryState


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "patch_workflow.py"


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


def _make_project(tmp_path: Path, *, with_quarantine: bool = False) -> tuple[Path, Path]:
    """Construct the synthetic book + run-dir layout. Returns (seed_path, run_dir)."""
    franchise = "scratch-franchise"
    book = "scratch-book"
    book_dir = tmp_path / "data" / "franchises" / franchise / "books" / book
    book_dir.mkdir(parents=True)
    seed_path = book_dir / "concept_seed.json"
    seed_path.write_text(
        json.dumps({
            "meta": {"franchise": franchise, "project_title": book},
            "story_physics": {
                "promise_payoff_ledger": [
                    {"promise_id": "PP01", "description": "d",
                     "planted_chapter": 1, "payoff_chapter": 3,
                     "type": "plot", "status": "unfulfilled"},
                ],
            },
            "relationship_arcs": [
                {"dyad": "A/B", "arc_type": "stable_alliance"},
            ],
        }),
        encoding="utf-8",
    )
    (book_dir / "scene_cards").mkdir()
    card_path = book_dir / "scene_cards" / "chapter_01_scene_02.json"
    card_path.write_text(
        json.dumps({
            "chapter_number": 1, "scene_number": 2,
            "structural_phase": "setup",
            "pov_character": "A", "mission": "m", "conflict": "c", "turning_point": "tp",
            "promises_planted": ["PP01"],
            "promises_progressed": ["PP01"],
            "relationship_deltas": [
                {"subject": "A", "object": "B", "trust_delta": 0.2},
            ],
        }),
        encoding="utf-8",
    )

    run_dir = tmp_path / "output" / franchise / book / "runs" / "2026-04-21"
    (run_dir / "chapters").mkdir(parents=True)
    state_dir = tmp_path / "output" / franchise / book / "state"
    state_dir.mkdir(parents=True)

    # Seed the scoped stores so the patch workflow has something to replay into.
    with PromiseLedger(db_path=str(state_dir / "promise_ledger.db")) as pl:
        pl.initialize_from_planning(
            concept_seed=json.loads(seed_path.read_text(encoding="utf-8")),
            scene_cards=[],
        )
    # Open an empty story_state.db so resolve_gap has a schema to write to.
    story = StoryState(db_path=str(state_dir / "story_state.db"))
    if with_quarantine:
        # Synthesize a quarantined scene + open gap.
        q_scene = run_dir / "quarantine" / "ch01_sc02"
        q_scene.mkdir(parents=True)
        (q_scene / "prose.md").write_text(
            "Quarantined prose for ch01 sc02.\n", encoding="utf-8",
        )
        story.record_gap({
            "gap_id": "gap_test_01",
            "isolated_scene": "ch01_sc02",
            "blocker_categories": ["test"],
            "affected_scenes": ["ch01_sc03", "ch02_sc01"],
        })
    story.close()
    return seed_path, run_dir


def _run_cli(args: list[str], *, base_dir: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT)] + args + ["--no-ledger"]
    if base_dir is not None:
        cmd += ["--base-dir", str(base_dir)]
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=REPO_ROOT,
    )


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_accept_isolated_promotes_quarantined_prose(tmp_path: Path):
    seed_path, run_dir = _make_project(tmp_path, with_quarantine=True)

    result = _run_cli([
        "accept-isolated", "ch01_sc02",
        "--seed", str(seed_path), "--run-dir", str(run_dir),
        "--notes", "human accepted",
    ], base_dir=tmp_path)
    assert result.returncode == 0, result.stderr

    target = run_dir / "chapters" / "chapter_01_scene_02.md"
    assert target.exists()
    assert "Quarantined prose" in target.read_text(encoding="utf-8")

    # Gap resolved; downstream markers written.
    state_dir = tmp_path / "output" / "scratch-franchise" / "scratch-book" / "state"
    story = StoryState(db_path=str(state_dir / "story_state.db"))
    try:
        assert story.list_open_gaps() == []
    finally:
        story.close()
    markers = list((run_dir / "chapter_packets").glob("*_overlay.STALE"))
    assert {m.name for m in markers} == {
        "chapter_01_sc_03_overlay.STALE",
        "chapter_02_sc_01_overlay.STALE",
    }


def test_accept_isolated_replays_promise(tmp_path: Path):
    seed_path, run_dir = _make_project(tmp_path, with_quarantine=True)
    result = _run_cli([
        "accept-isolated", "ch01_sc02",
        "--seed", str(seed_path), "--run-dir", str(run_dir),
    ], base_dir=tmp_path)
    assert result.returncode == 0, result.stderr

    state_dir = tmp_path / "output" / "scratch-franchise" / "scratch-book" / "state"
    with PromiseLedger(db_path=str(state_dir / "promise_ledger.db")) as pl:
        row = pl.get("PP01")
    assert row is not None
    # Progression logged via replay.
    assert any(
        entry["scene_id"] == "ch01_sc02" and entry["source"] == "scene_card"
        for entry in row["progression_log"]
    )


def test_replace_overwrites_prose_and_marks_stale(tmp_path: Path):
    seed_path, run_dir = _make_project(tmp_path, with_quarantine=True)
    # Pre-place a saved scene to replace.
    target = run_dir / "chapters" / "chapter_01_scene_02.md"
    target.write_text("Original prose.\n", encoding="utf-8")

    edited = tmp_path / "edited.md"
    edited.write_text("Replacement prose.\n", encoding="utf-8")

    result = _run_cli([
        "replace", "ch01_sc02",
        "--seed", str(seed_path), "--run-dir", str(run_dir),
        "--from", str(edited),
        "--gap", "gap_test_01",
        "--notes", "human edited",
    ], base_dir=tmp_path)
    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == "Replacement prose.\n"

    state_dir = tmp_path / "output" / "scratch-franchise" / "scratch-book" / "state"
    story = StoryState(db_path=str(state_dir / "story_state.db"))
    try:
        assert story.list_open_gaps() == []
    finally:
        story.close()


def test_overrule_resolves_gap_without_prose_change(tmp_path: Path):
    seed_path, run_dir = _make_project(tmp_path, with_quarantine=True)
    result = _run_cli([
        "overrule", "gap_test_01",
        "--seed", str(seed_path), "--run-dir", str(run_dir),
        "--notes", "out of scope",
    ], base_dir=tmp_path)
    assert result.returncode == 0, result.stderr

    state_dir = tmp_path / "output" / "scratch-franchise" / "scratch-book" / "state"
    story = StoryState(db_path=str(state_dir / "story_state.db"))
    try:
        all_rows = [
            row for row in story.conn.execute("SELECT * FROM gap_notes").fetchall()
        ]
    finally:
        story.close()
    assert len(all_rows) == 1
    assert all_rows[0]["status"] == "overruled"
    assert all_rows[0]["resolved_by"] == "overrule"
    assert all_rows[0]["resolution_notes"] == "out of scope"


def test_apply_manuscript_patch_routes_entries(tmp_path: Path):
    seed_path, run_dir = _make_project(tmp_path, with_quarantine=True)
    patch = {
        "version": "2026-04-21",
        "source_pass": "manual",
        "entries": [
            {"action": "accept-isolated", "scene_id": "ch01_sc02"},
        ],
    }
    patch_path = tmp_path / "patch.json"
    patch_path.write_text(json.dumps(patch), encoding="utf-8")

    result = _run_cli([
        "apply-manuscript-patch", str(patch_path),
        "--seed", str(seed_path), "--run-dir", str(run_dir),
    ], base_dir=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (run_dir / "chapters" / "chapter_01_scene_02.md").exists()


def test_apply_manuscript_patch_rejects_duplicate_replace(tmp_path: Path):
    seed_path, run_dir = _make_project(tmp_path, with_quarantine=True)
    patch = {
        "version": "2026-04-21",
        "entries": [
            {"action": "replace", "scene_id": "ch01_sc02", "prose_path": "x.md"},
            {"action": "replace", "scene_id": "ch01_sc02", "prose_path": "y.md"},
        ],
    }
    patch_path = tmp_path / "patch.json"
    patch_path.write_text(json.dumps(patch), encoding="utf-8")

    result = _run_cli([
        "apply-manuscript-patch", str(patch_path),
        "--seed", str(seed_path), "--run-dir", str(run_dir),
    ], base_dir=tmp_path)
    assert result.returncode == 2
    assert "duplicate replace" in (result.stdout + result.stderr)
