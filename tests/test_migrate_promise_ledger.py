"""End-to-end smoke test for scripts/migrations/migrate_promise_ledger.py (Slice 3).

Constructs a synthetic franchise + book + output/state/ tree under tmp_path
and runs the migration wrapper in-process; asserts the SQLite DB is populated
from planning artifacts and re-running leaves it idempotent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.memory.promise_ledger import PromiseLedger

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_fixture(base: Path) -> tuple[Path, Path]:
    franchise = "scratch-franchise"
    book = "scratch-book"
    book_dir = base / "data" / "franchises" / franchise / "books" / book
    book_dir.mkdir(parents=True)
    (book_dir / "concept_seed.json").write_text(
        json.dumps({
            "meta": {"franchise": franchise, "project_title": "Scratch"},
            "story_physics": {
                "promise_payoff_ledger": [
                    {
                        "promise_id": "PP01",
                        "description": "Hero confronts the mentor",
                        "planted_chapter": 1,
                        "payoff_chapter": 3,
                        "type": "character",
                        "status": "unfulfilled",
                    },
                ],
            },
        }),
        encoding="utf-8",
    )
    cards_dir = book_dir / "scene_cards"
    cards_dir.mkdir()
    (cards_dir / "chapter_01_scene_01.json").write_text(
        json.dumps({
            "chapter_number": 1, "scene_number": 1,
            "structural_phase": "setup",
            "pov_character": "Hero", "mission": "m", "conflict": "c",
            "turning_point": "tp",
            "promises_planted": ["PP01"],
        }),
        encoding="utf-8",
    )
    state_dir = base / "output" / franchise / book / "state"
    state_dir.mkdir(parents=True)
    return book_dir, state_dir


def test_migration_seeds_empty_state_dir(tmp_path: Path):
    _, state_dir = _write_fixture(tmp_path)
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "migrations" / "migrate_promise_ledger.py"),
        "--base-dir", str(tmp_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr

    db_path = state_dir / "promise_ledger.db"
    assert db_path.exists()
    ledger = PromiseLedger(db_path=str(db_path))
    try:
        rows = ledger.list_all()
    finally:
        ledger.close()
    assert [r["promise_id"] for r in rows] == ["PP01"]


def test_migration_is_idempotent(tmp_path: Path):
    _, state_dir = _write_fixture(tmp_path)
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "migrations" / "migrate_promise_ledger.py"),
        "--base-dir", str(tmp_path),
    ]
    for _ in range(2):
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0, result.stderr

    ledger = PromiseLedger(db_path=str(state_dir / "promise_ledger.db"))
    try:
        rows = ledger.list_all()
    finally:
        ledger.close()
    assert [r["promise_id"] for r in rows] == ["PP01"]


def test_migration_dry_run_does_not_write(tmp_path: Path):
    _, state_dir = _write_fixture(tmp_path)
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "migrations" / "migrate_promise_ledger.py"),
        "--base-dir", str(tmp_path), "--dry-run",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert not (state_dir / "promise_ledger.db").exists()


def test_migration_seeds_series_scoped_state_dir(tmp_path: Path):
    """Series-scoped layout: output/<franchise>/<series>/state/ has no
    same-named book dir; the resolver falls back to books whose
    concept_seed.meta.series_id matches the state dir name.
    """
    franchise = "scratch-franchise"
    book_dir = tmp_path / "data" / "franchises" / franchise / "books" / "scratch-book"
    book_dir.mkdir(parents=True)
    (book_dir / "concept_seed.json").write_text(
        json.dumps({
            "meta": {
                "franchise": franchise,
                "project_title": "Scratch",
                "series_id": "scratch-cycle",
            },
            "story_physics": {
                "promise_payoff_ledger": [
                    {
                        "promise_id": "PP01",
                        "description": "Hero confronts the mentor",
                        "planted_chapter": 1,
                        "payoff_chapter": 3,
                        "type": "character",
                        "status": "unfulfilled",
                    },
                ],
            },
        }),
        encoding="utf-8",
    )
    cards_dir = book_dir / "scene_cards"
    cards_dir.mkdir()
    (cards_dir / "chapter_01_scene_01.json").write_text(
        json.dumps({
            "chapter_number": 1, "scene_number": 1,
            "structural_phase": "setup",
            "pov_character": "Hero", "mission": "m", "conflict": "c",
            "turning_point": "tp",
            "promises_planted": ["PP01"],
        }),
        encoding="utf-8",
    )
    series_state_dir = tmp_path / "output" / franchise / "scratch-cycle" / "state"
    series_state_dir.mkdir(parents=True)

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "migrations" / "migrate_promise_ledger.py"),
        "--base-dir", str(tmp_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    assert "scratch-cycle" in result.stdout

    db_path = series_state_dir / "promise_ledger.db"
    assert db_path.exists(), result.stdout
    ledger = PromiseLedger(db_path=str(db_path))
    try:
        rows = ledger.list_all()
    finally:
        ledger.close()
    assert [r["promise_id"] for r in rows] == ["PP01"]
