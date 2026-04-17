"""Phase 4 acceptance gate #2 — pipeline runs clean on the compiled bundle.

The compiled bundle must satisfy ``compliance_validator.validate_concept_seed``
(the same call ``src/main.py --validate-seed`` makes) without manual
artifact editing between compile and pipeline launch.

Drives the Ruusan importers + bundle compiler, then re-invokes
``validate_concept_seed`` against the freshly-written seed and asserts a
clean PASS — proving the bundle is pipeline-ready as authored.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.compile_bundle import compile_bundle
from src.concept_workshop.compliance_validator import validate_concept_seed
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


def test_compiled_bundle_passes_validate_seed_in_process(tmp_path):
    """In-process equivalent of ``python -m src.main --validate-seed``."""
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

    compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )

    # Now invoke the same validation call src/main.py --validate-seed runs.
    compiled = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
    report = validate_concept_seed(
        compiled,
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )
    assert report.passed, (
        "validate_concept_seed FAIL on compiled bundle:\n"
        + report.format()
    )
    assert report.critical_failures == []
