"""Compile-time physics enforcement — the Phase A/B refactor.

Covers:

1. A clean Ruusan compile populates ``report.physics`` and stamps
   ``compile_metadata.physics_validated`` into the persisted seed.
2. A compile whose scene-card corpus has a missing ``why_now`` flips the
   stamp to False, surfaces critical issues in the report, and fails
   ``report_has_failures`` even in non-strict mode (criticals always block).
3. ``--strict`` mode treats warn-only physics findings as a failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.compile_bundle import compile_bundle, report_has_failures
from src.project_paths import ProjectPaths
from workflows._shared.io import write_artifact
from workflows._shared.legacy_seed_loader import load_seed
from workflows.canon_drafter.importers.legacy_seed import import_from_seed as cd_import
from workflows.canon_drafter.validate import validate as v_cd
from workflows.character_forge.importers.legacy_seed import import_from_seed as cf_import
from workflows.character_forge.validate import validate as v_cf
from workflows.outline_planner.importers.legacy_seed import import_from_seed as op_import
from workflows.outline_planner.validate import validate as v_op
from workflows.scene_card_authoring.importers.legacy_seed import import_from_seed as sca_import
from workflows.scene_card_authoring.validate import validate as v_sca
from workflows.universe_builder.importers.legacy_seed import import_from_seed as ub_import
from workflows.universe_builder.validate import validate as v_ub
from workflows.voice_discovery.importers.legacy_seed import import_from_seed as vd_import
from workflows.voice_discovery.validate import validate as v_vd

REPO_ROOT = Path(__file__).resolve().parents[1]
RUUSAN_BOOK_DIR = (
    REPO_ROOT / "data" / "franchises" / "star-wars-legends-eu"
    / "books" / "the-ruusan-atonement"
)
RUUSAN_SEED = RUUSAN_BOOK_DIR / "concept_seed.json"
RUUSAN_SCENE_CARDS = RUUSAN_BOOK_DIR / "scene_cards"
RUUSAN_FRANCHISE_META = (
    REPO_ROOT / "data" / "franchises" / "star-wars-legends-eu" / "franchise_meta.json"
)

pytestmark = pytest.mark.skipif(
    not RUUSAN_SEED.exists() or not RUUSAN_SCENE_CARDS.exists(),
    reason="Ruusan committed artifacts missing (skipped instead of failing)",
)


def _stage_ruusan(tmp_path: Path) -> ProjectPaths:
    """Drive all six importers into a tmp workflows/ tree."""
    seed = load_seed(RUUSAN_SEED)
    paths = ProjectPaths(
        "the-ruusan-atonement", base_dir=str(tmp_path),
        franchise_slug="star-wars-legends-eu",
    )
    paths.ensure_dirs()
    paths.workflows_dir.mkdir(parents=True, exist_ok=True)
    write_artifact(
        paths.workflows_dir / "universe.json",
        ub_import(seed, franchise_meta_path=RUUSAN_FRANCHISE_META),
        surface="universe-builder", validator=v_ub,
    )
    write_artifact(
        paths.workflows_dir / "canon.json",
        cd_import(seed),
        surface="canon-drafter", validator=v_cd,
    )
    write_artifact(
        paths.workflows_dir / "voice.json",
        vd_import(seed),
        surface="voice-discovery", validator=v_vd,
    )
    write_artifact(
        paths.workflows_dir / "characters.json",
        cf_import(seed),
        surface="character-forge", validator=v_cf,
    )
    write_artifact(
        paths.workflows_dir / "outline.json",
        op_import(seed, extracted_scene_cards_dir=RUUSAN_SCENE_CARDS),
        surface="outline-planner", validator=v_op,
    )
    write_artifact(
        paths.workflows_dir / "scene_cards.json",
        sca_import(seed, extracted_scene_cards_dir=RUUSAN_SCENE_CARDS),
        surface="scene-card-authoring", validator=v_sca,
    )
    return paths


def _strip_why_now_in_envelope(paths: ProjectPaths, chapter: int, scene: int) -> None:
    """Rewrite scene_cards.json envelope with why_now removed on one card."""
    envelope_path = paths.workflows_dir / "scene_cards.json"
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    cards = envelope.get("scene_cards", [])
    for card in cards:
        if (
            card.get("chapter_number") == chapter
            and card.get("scene_number") == scene
        ):
            card.pop("why_now", None)
            # workshop cards embed a workshop block that may also hold it
            workshop = card.get("workshop", {})
            if isinstance(workshop, dict):
                workshop.pop("why_now", None)
    envelope_path.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_clean_compile_populates_physics_and_stamps_seed(tmp_path):
    paths = _stage_ruusan(tmp_path)
    report = compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )
    assert report.physics, "physics section missing from report"
    assert "critical_count" in report.physics
    assert "warn_count" in report.physics
    assert "by_category" in report.physics
    # Ruusan is hand-authored; it should have zero critical physics issues.
    assert report.physics["critical_count"] == 0, (
        f"unexpected criticals on Ruusan: {report.physics['issues']}"
    )
    seed = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
    assert (
        seed.get("compile_metadata", {}).get("physics_validated") is True
    ), f"expected stamp=True, got: {seed.get('compile_metadata')}"


def test_missing_why_now_fails_physics_and_unstamps(tmp_path):
    paths = _stage_ruusan(tmp_path)
    # Pick a mid-book scene and strip its why_now.
    _strip_why_now_in_envelope(paths, chapter=13, scene=1)

    report = compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )
    assert report.physics["critical_count"] >= 1
    assert any(
        i.get("issue_type") == "missing_why_now"
        for i in report.physics["issues"]
    )
    seed = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
    assert (
        seed.get("compile_metadata", {}).get("physics_validated") is False
    ), (
        f"expected stamp=False after breaking a card, got: "
        f"{seed.get('compile_metadata')}"
    )
    # Criticals block exit even without --strict (mirrors compliance).
    assert report_has_failures(report, strict=False) is True


def test_strict_promotes_warn_to_failure(tmp_path):
    """In strict mode, any physics warning count > 0 fails the compile.

    We assert the semantics directly via ``report_has_failures`` against a
    fabricated report so the test does not depend on Ruusan happening to
    carry any warn-level findings.
    """
    from scripts.compile_bundle import CompileReport

    report = CompileReport(franchise="x", book="y")
    report.physics = {
        "passed": True,
        "critical_count": 0,
        "warn_count": 3,
        "issues": [],
        "by_category": {},
    }
    report.compliance = {"passed": True, "critical_failures": [], "warnings": []}

    assert report_has_failures(report, strict=False) is False
    assert report_has_failures(report, strict=True) is True
