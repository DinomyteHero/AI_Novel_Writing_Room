"""End-to-end smoke test for scripts/migrate_sociogram.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.memory.sociogram import Sociogram


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrate_sociogram.py"


def _write_fixture(base: Path) -> Path:
    book_dir = base / "data" / "franchises" / "f" / "books" / "b"
    book_dir.mkdir(parents=True)
    (book_dir / "concept_seed.json").write_text(
        json.dumps({
            "meta": {"franchise": "f", "project_title": "b"},
            "relationship_arcs": [
                {"dyad": "Ben/Luke", "arc_type": "reconciling",
                 "arc_summary": "reconcile"},
            ],
        }),
        encoding="utf-8",
    )
    state_dir = base / "output" / "f" / "b" / "state"
    state_dir.mkdir(parents=True)
    return state_dir


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, cwd=cwd,
    )


def test_migration_seeds_edges_from_planning(tmp_path: Path):
    state_dir = _write_fixture(tmp_path)
    result = _run(["--base-dir", str(tmp_path)], cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr

    store = Sociogram(db_path=str(state_dir / "sociogram.db"))
    try:
        rows = store.list_all()
    finally:
        store.close()
    assert len(rows) == 2  # A\u2192B and B\u2192A
    subjects = {r["subject"] for r in rows}
    assert subjects == {"Ben", "Luke"}


def test_migration_is_idempotent(tmp_path: Path):
    state_dir = _write_fixture(tmp_path)
    for _ in range(2):
        result = _run(["--base-dir", str(tmp_path)], cwd=REPO_ROOT)
        assert result.returncode == 0, result.stderr
    store = Sociogram(db_path=str(state_dir / "sociogram.db"))
    try:
        assert store.count() == 2
    finally:
        store.close()


def test_migration_dry_run_does_not_write(tmp_path: Path):
    state_dir = _write_fixture(tmp_path)
    result = _run(["--base-dir", str(tmp_path), "--dry-run"], cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    assert not (state_dir / "sociogram.db").exists()
