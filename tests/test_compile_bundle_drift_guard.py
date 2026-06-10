"""Hand-edit drift guard — compile must not clobber hand-maintained outputs.

Regression for the Unfinished Shadow shape: ``workflows/`` holds a stale
idea-session skeleton while ``concept_seed.json`` + ``scene_cards/`` are
hand-maintained directly and ``compile_bundle`` was never run there (no
``compile_report.json``). Recompiling would regress the seed and wipe the
hand-authored cards, so ``compile_bundle`` now refuses unless
``--force-overwrite-newer`` is passed.

The guard is pure mtime + existence checks; recompiles over artifacts the
compiler itself wrote stay idempotent (exempted via compile_report.json's
mtime), and workflow surfaces edited *after* the hand edits signal intent
to recompile and pass.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from scripts.compile_bundle import compile_bundle, main, report_has_failures
from src.project_paths import ProjectPaths

FRANCHISE = "test-franchise"
BOOK = "test-book"


def _stage_minimal_workflows(tmp_path: Path) -> ProjectPaths:
    paths = ProjectPaths(
        BOOK, base_dir=str(tmp_path), franchise_slug=FRANCHISE,
    )
    paths.ensure_dirs()
    paths.workflows_dir.mkdir(parents=True, exist_ok=True)
    (paths.workflows_dir / "universe.json").write_text(
        json.dumps({"meta": {"project_title": "Test"}}), encoding="utf-8",
    )
    for name in ("canon", "voice", "characters", "outline"):
        (paths.workflows_dir / f"{name}.json").write_text("{}", encoding="utf-8")
    return paths


def _set_mtime(path: Path, ts: float) -> None:
    os.utime(path, (ts, ts))


def _stage_hand_authored_artifacts(paths: ProjectPaths) -> tuple[Path, Path]:
    """Hand-written seed + card, mtimes well ahead of the workflow surfaces."""
    base = time.time()
    for surface in paths.workflows_dir.glob("*.json"):
        _set_mtime(surface, base - 7200)

    seed_path = paths.concept_seed_path
    seed_path.write_text(
        json.dumps({"meta": {"hand_marker": True}}) + "\n", encoding="utf-8",
    )
    paths.scene_cards_dir.mkdir(parents=True, exist_ok=True)
    card_path = paths.scene_cards_dir / "chapter_01_scene_01.json"
    card_path.write_text(
        json.dumps({"chapter_number": 1, "scene_number": 1}) + "\n",
        encoding="utf-8",
    )
    _set_mtime(seed_path, base)
    _set_mtime(card_path, base)
    return seed_path, card_path


def test_fresh_compile_proceeds(tmp_path):
    paths = _stage_minimal_workflows(tmp_path)

    report = compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )

    assert report.preflight_errors == []
    assert paths.concept_seed_path.exists()
    assert (paths.book_dir / "compile_report.json").exists()


def test_blocks_hand_authored_artifacts_without_prior_report(tmp_path):
    paths = _stage_minimal_workflows(tmp_path)
    seed_path, card_path = _stage_hand_authored_artifacts(paths)
    seed_before = seed_path.read_text(encoding="utf-8")
    card_before = card_path.read_text(encoding="utf-8")

    report = compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )

    assert len(report.preflight_errors) == 1
    msg = report.preflight_errors[0]
    assert "hand-edit drift guard" in msg
    assert "compile_report.json" in msg
    assert "newest compiled artifact" in msg
    assert "newest workflow surface" in msg
    assert "--force-overwrite-newer" in msg
    assert report_has_failures(report, strict=False)
    # Nothing overwritten, and no report stamped that would let a second
    # invocation sail past the never-compiled-here check.
    assert seed_path.read_text(encoding="utf-8") == seed_before
    assert card_path.read_text(encoding="utf-8") == card_before
    assert not (paths.book_dir / "compile_report.json").exists()


def test_force_overwrite_newer_unblocks_via_cli(tmp_path):
    paths = _stage_minimal_workflows(tmp_path)
    seed_path, _ = _stage_hand_authored_artifacts(paths)

    main([
        "--franchise", FRANCHISE,
        "--book", BOOK,
        "--base-dir", str(tmp_path),
        "--force-overwrite-newer",
    ])

    compiled_seed = json.loads(seed_path.read_text(encoding="utf-8"))
    assert "hand_marker" not in compiled_seed.get("meta", {})
    assert compiled_seed["meta"]["project_title"] == "Test"
    assert (paths.book_dir / "compile_report.json").exists()


def test_recompile_after_clean_compile_not_blocked(tmp_path):
    _stage_minimal_workflows(tmp_path)
    first = compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )
    assert first.preflight_errors == []

    second = compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )
    assert second.preflight_errors == []


def test_blocks_hand_edits_made_after_compile(tmp_path):
    paths = _stage_minimal_workflows(tmp_path)
    compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )
    report_mtime = (paths.book_dir / "compile_report.json").stat().st_mtime
    _set_mtime(paths.concept_seed_path, report_mtime + 3600)

    report = compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )

    assert len(report.preflight_errors) == 1
    assert "modified after the last compile" in report.preflight_errors[0]


def test_workflow_edits_newer_than_hand_edits_unblock(tmp_path):
    paths = _stage_minimal_workflows(tmp_path)
    compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )
    report_mtime = (paths.book_dir / "compile_report.json").stat().st_mtime
    _set_mtime(paths.concept_seed_path, report_mtime + 3600)
    _set_mtime(paths.workflows_dir / "universe.json", report_mtime + 7200)

    report = compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )

    assert report.preflight_errors == []


def test_managed_by_direct_blocks_even_clean_mtimes(tmp_path):
    """A seed stamped compile_metadata.managed_by='direct' refuses recompile
    regardless of mtime forensics — declared provenance beats inference."""
    paths = _stage_minimal_workflows(tmp_path)
    first = compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )
    assert first.preflight_errors == []

    seed = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
    assert seed["compile_metadata"]["managed_by"] == "workflow_kit"
    seed["compile_metadata"]["managed_by"] = "direct"
    paths.concept_seed_path.write_text(
        json.dumps(seed) + "\n", encoding="utf-8",
    )

    blocked = compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
    )
    assert len(blocked.preflight_errors) == 1
    assert "managed_by='direct'" in blocked.preflight_errors[0]

    forced = compile_bundle(
        franchise_slug=FRANCHISE, book_slug=BOOK, base_dir=str(tmp_path),
        force_overwrite_newer=True,
    )
    assert forced.preflight_errors == []
    reseeded = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
    assert reseeded["compile_metadata"]["managed_by"] == "workflow_kit"
