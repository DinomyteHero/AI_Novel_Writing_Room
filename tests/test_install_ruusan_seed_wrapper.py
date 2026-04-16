"""Parity and smoke tests for the deprecated scripts/install_ruusan_seed.py wrapper.

These tests guard two invariants:

1. The Ruusan install/ artifacts (concept_seed_raw.json + workshop_patch.json)
   drive the generic install_seed path to an enriched seed that matches
   every transform the pre-Phase-3 installer applied. If someone mutates
   one side but not the other, parity breaks and these tests fail.

2. The thin wrapper at scripts/install_ruusan_seed.py:
   - Still exposes the historical CLI entry point.
   - Routes through scripts/install_seed.install_seed().
   - Prints a deprecation notice.

Parity is tested structurally — we reconstruct the pre-Phase-3 sequence
in-process from the same transforms and compare to the install_seed
output. We do NOT compare against the committed data/franchises/.../
concept_seed.json because that committed seed was hand-enriched (with
canon_profile, force_mechanics, quality_overrides, etc.) beyond what
the installer itself produces.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUUSAN_INSTALL_DIR = (
    REPO_ROOT
    / "data"
    / "franchises"
    / "star-wars-legends-eu"
    / "books"
    / "the-ruusan-atonement"
    / "install"
)
RUUSAN_RAW = RUUSAN_INSTALL_DIR / "concept_seed_raw.json"
RUUSAN_PATCH = RUUSAN_INSTALL_DIR / "workshop_patch.json"

# Guard against the artifacts being deleted or relocated.
pytestmark = pytest.mark.skipif(
    not RUUSAN_RAW.exists() or not RUUSAN_PATCH.exists(),
    reason="Ruusan install/ artifacts missing (skipped instead of failing)",
)

from scripts.install_seed import install_seed  # noqa: E402
from src.concept_workshop.seed_transforms import (  # noqa: E402
    apply_arc_phase_maps,
    apply_canon_constraints,
    apply_promise_payoff_ledger,
    apply_voice_definition,
    apply_workshop_origin,
    move_to_extended_metadata,
    normalize_enums,
)


def _replay_legacy_transforms(raw: dict, patch: dict) -> dict:
    """Reconstruct the pre-Phase-3 installer's transform sequence inline.

    This mirrors exactly what scripts/install_ruusan_seed.py.main() used
    to do before it became a thin wrapper. If install_seed._apply_workshop_patch
    ever drifts from this order, the parity test fails.
    """
    seed = copy.deepcopy(raw)
    apply_voice_definition(seed, patch.get("voice_definition"))
    normalize_enums(
        seed,
        tone_fallback=patch.get("tone_fallback", "heroic_with_weight"),
        canon_status_fallback=patch.get("canon_status_fallback", "AU"),
        arc_type_map=patch.get("arc_type_map"),
    )
    apply_arc_phase_maps(seed, patch.get("arc_phase_maps"))
    apply_promise_payoff_ledger(seed, patch.get("promise_payoff_ledger"))
    move_to_extended_metadata(seed, patch.get("extended_metadata_fields"))
    apply_workshop_origin(seed, patch.get("workshop_origin"))
    apply_canon_constraints(seed, patch.get("canon_constraints"))
    return seed


class TestRuusanReinstallParity:
    def test_install_seed_matches_legacy_transform_sequence(self, tmp_path):
        raw = json.loads(RUUSAN_RAW.read_text(encoding="utf-8"))
        patch = json.loads(RUUSAN_PATCH.read_text(encoding="utf-8"))
        legacy_output = _replay_legacy_transforms(raw, patch)

        result = install_seed(
            input_path=RUUSAN_RAW,
            workshop_patch_path=RUUSAN_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = json.loads(result.seed_path.read_text(encoding="utf-8"))

        assert installed == legacy_output, (
            "install_seed() output diverged from the pre-Phase-3 transform "
            "sequence — workshop_patch contract likely regressed"
        )

    def test_reinstall_produces_28_scene_cards(self, tmp_path):
        result = install_seed(
            input_path=RUUSAN_RAW,
            workshop_patch_path=RUUSAN_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        assert result.scene_card_count == 28

    def test_reinstall_extracts_all_28_chapters(self, tmp_path):
        install_seed(
            input_path=RUUSAN_RAW,
            workshop_patch_path=RUUSAN_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        scene_cards_dir = (
            tmp_path
            / "data"
            / "franchises"
            / "star-wars-legends-eu"
            / "books"
            / "the-ruusan-atonement"
            / "scene_cards"
        )
        assert scene_cards_dir.exists()
        chapters = {
            int(p.stem.split("_")[1])
            for p in scene_cards_dir.glob("chapter_*_scene_*.json")
        }
        assert chapters == set(range(1, 29)), (
            f"expected chapters 1..28, got {sorted(chapters)}"
        )

    def test_chapter_26_override_applied(self, tmp_path):
        """workshop_patch.json ships structural_overrides={'26': 'climax'}
        and the translator must respect it — chapter 26 scene cards
        should all have structural_phase == 'climax'."""
        install_seed(
            input_path=RUUSAN_RAW,
            workshop_patch_path=RUUSAN_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        scene_cards_dir = (
            tmp_path
            / "data"
            / "franchises"
            / "star-wars-legends-eu"
            / "books"
            / "the-ruusan-atonement"
            / "scene_cards"
        )
        for path in scene_cards_dir.glob("chapter_26_scene_*.json"):
            card = json.loads(path.read_text(encoding="utf-8"))
            assert card["structural_phase"] == "climax"

    def test_voice_definition_injected_from_patch(self, tmp_path):
        result = install_seed(
            input_path=RUUSAN_RAW,
            workshop_patch_path=RUUSAN_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = json.loads(result.seed_path.read_text(encoding="utf-8"))
        patch = json.loads(RUUSAN_PATCH.read_text(encoding="utf-8"))
        assert installed["voice_definition"] == patch["voice_definition"]

    def test_enums_normalized(self, tmp_path):
        """Raw Ruusan seed ships descriptive tone + descriptive arc_types;
        the enriched seed must replace them with canonical enum values
        and preserve the descriptive strings as *_description / arc_summary."""
        result = install_seed(
            input_path=RUUSAN_RAW,
            workshop_patch_path=RUUSAN_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = json.loads(result.seed_path.read_text(encoding="utf-8"))
        assert installed["meta"]["tone"] == "heroic_with_weight"
        assert installed["meta"].get("tone_description"), (
            "descriptive tone should be preserved under tone_description"
        )
        # All canonical arc_types listed in workshop_patch.arc_type_map
        # must now hold enum values.
        patch = json.loads(RUUSAN_PATCH.read_text(encoding="utf-8"))
        arc_map = patch["arc_type_map"]
        for char in installed["ensemble_cast"]:
            name = char.get("name")
            if name in arc_map:
                assert char["weiland_arc"]["arc_type"] == arc_map[name]


class TestRuusanWrapperScript:
    def test_wrapper_prints_deprecation_and_runs(self, tmp_path):
        """Running scripts/install_ruusan_seed.py from the repo root writes
        the enriched seed to data/franchises/... under the repo. Run with
        a copy of the repo's install/ artifacts rerooted at tmp_path to
        avoid modifying the committed tree — we copy the repo root into
        tmp_path for isolation."""
        # Build a minimal mirror of the repo layout inside tmp_path that
        # the wrapper can chdir into. The wrapper resolves paths relative
        # to its own __file__, so we copy the scripts and install artifacts
        # into an isolated structure.
        import shutil

        # Mirror just what we need.
        (tmp_path / "scripts").mkdir()
        shutil.copy(REPO_ROOT / "scripts" / "install_ruusan_seed.py", tmp_path / "scripts")
        shutil.copy(REPO_ROOT / "scripts" / "install_seed.py", tmp_path / "scripts")

        src_dst = tmp_path / "src" / "concept_workshop"
        src_dst.mkdir(parents=True)
        shutil.copy(
            REPO_ROOT / "src" / "concept_workshop" / "seed_transforms.py",
            src_dst,
        )
        shutil.copy(
            REPO_ROOT / "src" / "concept_workshop" / "scene_card_translator.py",
            src_dst,
        )
        # project_paths lives one level up.
        shutil.copy(REPO_ROOT / "src" / "project_paths.py", tmp_path / "src")
        (tmp_path / "src" / "__init__.py").touch()
        (tmp_path / "src" / "concept_workshop" / "__init__.py").touch()

        # Copy schemas.
        shutil.copytree(REPO_ROOT / "schemas", tmp_path / "schemas")

        # Copy Ruusan install artifacts.
        install_dst = (
            tmp_path
            / "data"
            / "franchises"
            / "star-wars-legends-eu"
            / "books"
            / "the-ruusan-atonement"
            / "install"
        )
        install_dst.mkdir(parents=True)
        shutil.copy(RUUSAN_RAW, install_dst / "concept_seed_raw.json")
        shutil.copy(RUUSAN_PATCH, install_dst / "workshop_patch.json")

        result = subprocess.run(
            [sys.executable, "scripts/install_ruusan_seed.py"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, (
            f"wrapper exited non-zero.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "deprecated" in result.stdout.lower(), (
            f"wrapper should print deprecation notice; stdout:\n{result.stdout}"
        )
        expected_seed = (
            tmp_path
            / "data"
            / "franchises"
            / "star-wars-legends-eu"
            / "books"
            / "the-ruusan-atonement"
            / "concept_seed.json"
        )
        assert expected_seed.exists()
