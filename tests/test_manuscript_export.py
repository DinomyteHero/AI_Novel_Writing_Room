"""Slice 6 manuscript-export stitcher tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "manuscript_export.py"


def _make_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    book_dir = tmp_path / "data" / "franchises" / "f" / "books" / "b"
    book_dir.mkdir(parents=True)
    seed_path = book_dir / "concept_seed.json"
    seed_path.write_text(
        json.dumps({"meta": {"franchise": "f", "project_title": "b"}}),
        encoding="utf-8",
    )
    run_dir = tmp_path / "output" / "f" / "b" / "runs" / "r1"
    (run_dir / "chapters").mkdir(parents=True)
    (run_dir / "chapters" / "chapter_01_scene_01.md").write_text(
        "Hook scene prose.\n", encoding="utf-8",
    )
    (run_dir / "chapters" / "chapter_01_scene_02.md").write_text(
        "Second scene prose.\n", encoding="utf-8",
    )
    (run_dir / "chapters" / "chapter_02_scene_01.md").write_text(
        "Second chapter prose.\n", encoding="utf-8",
    )
    export_dir = tmp_path / "export"
    return seed_path, run_dir, export_dir


def test_stitch_produces_manuscript_and_index(tmp_path: Path):
    seed_path, run_dir, export_dir = _make_project(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--seed", str(seed_path),
         "--run-dir", str(run_dir),
         "--export-dir", str(export_dir)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    manuscript = export_dir / "manuscript.md"
    index = export_dir / "chapter_index.md"
    assert manuscript.exists() and index.exists()
    body = manuscript.read_text(encoding="utf-8")
    assert "Chapter 1" in body and "Chapter 2" in body
    assert "Hook scene prose." in body
    assert body.index("Hook scene prose.") < body.index("Second chapter prose.")
    idx = index.read_text(encoding="utf-8")
    # Scenes 1.1 + 1.2 totals 6 words, chapter 2 totals 3 words.
    assert "Chapter 1: 6 words" in idx
    assert "Chapter 2: 3 words" in idx
    assert "Total word count: 9" in idx


def test_stitch_handles_empty_run_dir(tmp_path: Path):
    seed_path, _run_dir, export_dir = _make_project(tmp_path)
    empty_run = tmp_path / "empty_run"
    (empty_run / "chapters").mkdir(parents=True)
    result = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--seed", str(seed_path),
         "--run-dir", str(empty_run),
         "--export-dir", str(export_dir)],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    manuscript = export_dir / "manuscript.md"
    # Empty file OK; just confirm it exists and word count is 0.
    assert manuscript.exists()
    idx = (export_dir / "chapter_index.md").read_text(encoding="utf-8")
    assert "Total word count: 0" in idx
