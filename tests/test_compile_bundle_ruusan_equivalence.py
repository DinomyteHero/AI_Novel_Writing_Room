"""Phase 4 acceptance gate #3 — Ruusan re-extraction equivalence.

Drives all six legacy_seed importers against the committed Ruusan
``concept_seed.json`` + extracted ``scene_cards/`` tree, then runs
``scripts/compile_bundle.py`` over the produced surface artifacts and
asserts:

1. Every per-surface importer + validator pair returns zero errors.
2. The bundle compiler produces a seed that passes both
   ``jsonschema.validate(concept_seed_schema)`` and
   ``compliance_validator.validate_concept_seed`` with zero critical
   failures.
3. The compiled bundle preserves Ruusan's content shape: 87 extracted
   scene cards, 6 ensemble cast members, 28-chapter outline derived
   from the cards, 44 terminology entries.
4. Re-running compile_bundle on the same workflow inputs is byte-stable
   (idempotency).
"""

from __future__ import annotations

import json
import shutil
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


def _drive_importers_and_write(seed: dict, paths: ProjectPaths) -> None:
    """Run each legacy_seed importer and persist to paths.workflows_dir."""
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


def test_importers_produce_valid_artifacts(tmp_path):
    """Each surface's legacy_seed importer + validator returns zero errors."""
    seed = load_seed(RUUSAN_SEED)

    cases = [
        ("universe-builder", ub_import(seed, franchise_meta_path=RUUSAN_FRANCHISE_META), v_ub),
        ("canon-drafter", cd_import(seed), v_cd),
        ("voice-discovery", vd_import(seed), v_vd),
        ("character-forge", cf_import(seed), v_cf),
        ("outline-planner", op_import(seed, extracted_scene_cards_dir=RUUSAN_SCENE_CARDS), v_op),
        ("scene-card-authoring", sca_import(seed, extracted_scene_cards_dir=RUUSAN_SCENE_CARDS), v_sca),
    ]
    for name, artifact, validator in cases:
        errors = validator(artifact)
        assert errors == [], f"{name} validator returned errors: {errors}"


def test_bundle_compiles_and_validates(tmp_path):
    """compile_bundle on importer-driven workflow tree passes compliance."""
    seed = load_seed(RUUSAN_SEED)
    paths = ProjectPaths(
        "the-ruusan-atonement", base_dir=str(tmp_path),
        franchise_slug="star-wars-legends-eu",
    )
    paths.ensure_dirs()
    _drive_importers_and_write(seed, paths)

    report = compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )

    assert report.surfaces_missing == []
    assert report.schema_errors == [], (
        f"schema errors: {report.schema_errors}"
    )
    assert report.scene_card_errors == [], (
        f"scene card errors: {report.scene_card_errors}"
    )
    assert report.compliance.get("passed") is True, (
        "compliance failed: critical_failures="
        f"{report.compliance.get('critical_failures')}"
    )
    assert report.compliance.get("critical_failures") == []
    assert not report_has_failures(report, strict=False)


def test_bundle_preserves_ruusan_shape(tmp_path):
    """The compiled bundle has 87 cards, 6 cast, 28 chapter outline, 44 terms."""
    seed = load_seed(RUUSAN_SEED)
    paths = ProjectPaths(
        "the-ruusan-atonement", base_dir=str(tmp_path),
        franchise_slug="star-wars-legends-eu",
    )
    paths.ensure_dirs()
    _drive_importers_and_write(seed, paths)

    report = compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )
    assert report.scene_card_count == 87, (
        f"expected 87 scene cards, got {report.scene_card_count}"
    )

    compiled_seed = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
    assert len(compiled_seed.get("ensemble_cast", [])) == 6
    assert len(compiled_seed.get("terminology_registry", [])) == 44

    outline = json.loads(
        (paths.workflows_dir / "outline.json").read_text(encoding="utf-8")
    )
    assert len(outline.get("outline", [])) == 28


def test_bundle_compile_is_idempotent(tmp_path):
    """Re-running compile_bundle produces byte-identical seed and per-card output."""
    seed = load_seed(RUUSAN_SEED)
    paths = ProjectPaths(
        "the-ruusan-atonement", base_dir=str(tmp_path),
        franchise_slug="star-wars-legends-eu",
    )
    paths.ensure_dirs()
    _drive_importers_and_write(seed, paths)

    compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )
    seed_first = paths.concept_seed_path.read_bytes()
    cards_first = {
        p.name: p.read_bytes()
        for p in sorted(paths.scene_cards_dir.glob("chapter_*_scene_*.json"))
    }

    compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )
    seed_second = paths.concept_seed_path.read_bytes()
    cards_second = {
        p.name: p.read_bytes()
        for p in sorted(paths.scene_cards_dir.glob("chapter_*_scene_*.json"))
    }

    assert seed_first == seed_second, "concept_seed.json drifted between runs"
    assert cards_first.keys() == cards_second.keys()
    for name in cards_first:
        assert cards_first[name] == cards_second[name], (
            f"{name} drifted between runs"
        )


def test_compiled_seed_matches_committed_ruusan_shape(tmp_path):
    """Spot-check semantic equivalence to the committed Ruusan seed.

    Compares parsed JSON dicts on selected fields rather than byte-for-byte
    (the compiled seed may differ in field order or carry omissions like
    workshop-only embedded scene_cards). Acceptance criterion: every field
    in the committed seed that the compiler is responsible for producing
    is present and equal in the recompiled seed.
    """
    seed = load_seed(RUUSAN_SEED)
    paths = ProjectPaths(
        "the-ruusan-atonement", base_dir=str(tmp_path),
        franchise_slug="star-wars-legends-eu",
    )
    paths.ensure_dirs()
    _drive_importers_and_write(seed, paths)
    compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )
    compiled = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
    original = seed

    # Sections with deep-equality semantics.
    for section in (
        "premise",
        "conflict",
        "theme",
        "voice_definition",
        "canon_constraints",
        "canon_profile",
        "force_mechanics",
        "structural_notes",
        "ensemble_cast",
        "relationship_arcs",
        "referenced_characters",
        "subplots",
        "hooks",
        "revelation_schedule",
        "promise_payoff_ledger",
        "terminology_registry",
        "stress_test_scores",
        "quality_overrides",
        "protagonist_arc_type",
    ):
        if section in original:
            assert compiled.get(section) == original[section], (
                f"section {section!r} drifted between original and recompiled seed"
            )

    # Meta is rebuilt from the universe-builder artifact; only check that
    # all required fields survive.
    for key in (
        "project_title", "franchise", "canon_status", "era", "tone",
        "target_word_count",
    ):
        assert compiled["meta"][key] == original["meta"][key], (
            f"meta.{key} drifted"
        )
