"""Smoke test for scripts/migrations/migrate_continuity_log.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.memory.continuity_log import ContinuityLog


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrations" / "migrate_continuity_log.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, cwd=cwd,
    )


def test_migration_creates_empty_db(tmp_path: Path):
    state_dir = tmp_path / "output" / "scratch-franchise" / "scratch-book" / "state"
    state_dir.mkdir(parents=True)

    result = _run(["--base-dir", str(tmp_path)], cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr

    db_path = state_dir / "continuity_log.db"
    assert db_path.exists()
    log = ContinuityLog(db_path=str(db_path))
    try:
        assert log.count() == 0
    finally:
        log.close()


def test_migration_is_idempotent(tmp_path: Path):
    state_dir = tmp_path / "output" / "f" / "b" / "state"
    state_dir.mkdir(parents=True)
    for _ in range(2):
        result = _run(["--base-dir", str(tmp_path)], cwd=REPO_ROOT)
        assert result.returncode == 0, result.stderr
    assert (state_dir / "continuity_log.db").exists()


def test_migration_dry_run_does_not_write(tmp_path: Path):
    state_dir = tmp_path / "output" / "f" / "b" / "state"
    state_dir.mkdir(parents=True)
    result = _run(["--base-dir", str(tmp_path), "--dry-run"], cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    assert not (state_dir / "continuity_log.db").exists()
