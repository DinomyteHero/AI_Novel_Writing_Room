"""Preflight check — franchise slug must match input path.

Regression for the Betrayal quirk: ``meta.franchise: "Star Wars"``
slugifies to ``star-wars`` while the book lived under
``data/franchises/star-wars-legends-eu/``. ``ProjectPaths.from_concept_seed``
routed outputs + scaffolds to a ghost ``output/star-wars/`` and
``data/franchises/star-wars/`` at pipeline-run time.

``compile_bundle`` now short-circuits with a preflight error when
``workflows/universe.json``'s declared franchise slugifies to anything
other than the input-path slug, so the drift is caught before any seed
or scaffold is written.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.compile_bundle import compile_bundle, report_has_failures
from src.project_paths import ProjectPaths


def _stage_minimal_workflows(
    tmp_path: Path,
    *,
    franchise_slug: str,
    book_slug: str,
    declared_franchise: str,
) -> ProjectPaths:
    paths = ProjectPaths(
        book_slug, base_dir=str(tmp_path), franchise_slug=franchise_slug,
    )
    paths.ensure_dirs()
    paths.workflows_dir.mkdir(parents=True, exist_ok=True)
    (paths.workflows_dir / "universe.json").write_text(
        json.dumps(
            {"meta": {"franchise": declared_franchise, "project_title": "Test"}}
        ),
        encoding="utf-8",
    )
    for name in ("canon", "voice", "characters", "outline"):
        (paths.workflows_dir / f"{name}.json").write_text("{}", encoding="utf-8")
    return paths


def test_preflight_blocks_on_slug_mismatch(tmp_path):
    paths = _stage_minimal_workflows(
        tmp_path,
        franchise_slug="star-wars-legends-eu",
        book_slug="test-book",
        declared_franchise="Star Wars",
    )

    report = compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="test-book",
        base_dir=str(tmp_path),
    )

    assert len(report.preflight_errors) == 1
    msg = report.preflight_errors[0]
    assert "star-wars-legends-eu" in msg
    assert "'star-wars'" in msg
    assert "'Star Wars'" in msg
    assert report_has_failures(report, strict=False)
    # Seed must not have been written when preflight blocks.
    assert not paths.concept_seed_path.exists()


def test_preflight_passes_on_slug_match(tmp_path):
    _stage_minimal_workflows(
        tmp_path,
        franchise_slug="star-wars-legends-eu",
        book_slug="test-book",
        declared_franchise="Star Wars (Legends EU)",
    )

    report = compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="test-book",
        base_dir=str(tmp_path),
    )

    assert report.preflight_errors == []


def test_preflight_noop_when_declared_franchise_empty(tmp_path):
    """Silent-pass when universe.json has no meta.franchise yet."""
    _stage_minimal_workflows(
        tmp_path,
        franchise_slug="some-franchise",
        book_slug="test-book",
        declared_franchise="",
    )

    report = compile_bundle(
        franchise_slug="some-franchise",
        book_slug="test-book",
        base_dir=str(tmp_path),
    )

    assert report.preflight_errors == []
