"""Smoke test for scripts/migrations/migrate_all.py \u2014 exercises the wrapper end-to-end
against a synthetic output/ tree under tmp_path.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrations" / "migrate_all.py"


def _make_project(tmp_path: Path) -> None:
    book_dir = tmp_path / "data" / "franchises" / "f" / "books" / "b"
    book_dir.mkdir(parents=True)
    (book_dir / "concept_seed.json").write_text(
        json.dumps({
            "meta": {"franchise": "f", "project_title": "b"},
            "story_physics": {
                "promise_payoff_ledger": [
                    {"promise_id": "PP01", "description": "d",
                     "planted_chapter": 1, "payoff_chapter": 2,
                     "type": "plot", "status": "unfulfilled"},
                ],
            },
            "relationship_arcs": [
                {"dyad": "A/B", "arc_type": "stable_alliance"},
            ],
        }),
        encoding="utf-8",
    )
    (tmp_path / "output" / "f" / "b" / "state").mkdir(parents=True)


def test_migrate_all_runs_every_script(tmp_path: Path):
    _make_project(tmp_path)
    # Seed a story_state.db so the Slice 1 migration has something to touch
    # (migrate_gap_notes.py operates on existing DBs only; fresh books get
    # their story_state.db on first pipeline run, not from this migration).
    from src.memory.story_state import StoryState
    state_dir = tmp_path / "output" / "f" / "b" / "state"
    s = StoryState(db_path=str(state_dir / "story_state.db"))
    s.close()

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--base-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    # Slice 2/3/4/5 migrations seed their DBs fresh.
    assert (state_dir / "revision_debt.db").exists()
    assert (state_dir / "promise_ledger.db").exists()
    assert (state_dir / "continuity_log.db").exists()
    assert (state_dir / "sociogram.db").exists()


def test_migrate_all_is_idempotent(tmp_path: Path):
    _make_project(tmp_path)
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--base-dir", str(tmp_path)],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr


def test_migrate_all_dry_run_does_not_write(tmp_path: Path):
    _make_project(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--base-dir", str(tmp_path), "--dry-run"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    state_dir = tmp_path / "output" / "f" / "b" / "state"
    # Dry-run must not create the Slice 3/4/5 DBs. Slice 1/2 scripts already
    # respected --dry-run before this wave; Slice 3/4/5 wrappers are new.
    assert not (state_dir / "promise_ledger.db").exists()
    assert not (state_dir / "continuity_log.db").exists()
    assert not (state_dir / "sociogram.db").exists()
