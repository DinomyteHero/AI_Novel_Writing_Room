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
    apply_canon_profile,
    apply_force_mechanics,
    apply_hooks,
    apply_promise_payoff_ledger,
    apply_quality_overrides,
    apply_referenced_characters,
    apply_relationship_arcs,
    apply_revelation_schedule,
    apply_stress_test_scores,
    apply_subplots,
    apply_terminology_registry,
    apply_voice_definition,
    apply_workshop_origin,
    move_to_extended_metadata,
    normalize_enums,
)


def _replay_legacy_transforms(raw: dict, patch: dict) -> dict:
    """Reconstruct the installer's full transform sequence inline.

    This mirrors exactly what ``scripts/install_seed.py._apply_workshop_patch``
    does. Originally this replay covered only the pre-Phase-3 transforms
    (the parity guard for the Ruusan wrapper refactor); the drift-closure
    work extended both ``_apply_workshop_patch`` and this replay in lock-step.
    If the two sequences drift, the parity test below fails.
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
    apply_subplots(seed, patch.get("subplots"))
    apply_hooks(seed, patch.get("hooks"))
    apply_revelation_schedule(seed, patch.get("revelation_schedule"))
    apply_terminology_registry(seed, patch.get("terminology_registry"))
    apply_relationship_arcs(seed, patch.get("relationship_arcs"))
    apply_canon_profile(seed, patch.get("canon_profile"))
    apply_force_mechanics(seed, patch.get("force_mechanics"))
    apply_canon_constraints(seed, patch.get("canon_constraints"))
    apply_referenced_characters(seed, patch.get("referenced_characters"))
    apply_quality_overrides(seed, patch.get("quality_overrides"))
    apply_workshop_origin(seed, patch.get("workshop_origin"))
    apply_stress_test_scores(seed, patch.get("stress_test_scores"))
    move_to_extended_metadata(seed, patch.get("extended_metadata_fields"))
    # install_seed also clears embedded scene_cards after extraction.
    if "scene_cards" in seed:
        seed["scene_cards"] = []
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

    def test_reinstall_produces_87_scene_cards(self, tmp_path):
        """Raw carries 87 per-scene canonical cards (post-drift-closure
        expansion). The installer writes one file per card."""
        result = install_seed(
            input_path=RUUSAN_RAW,
            workshop_patch_path=RUUSAN_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        assert result.scene_card_count == 87

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

    def test_structural_overrides_applied(self, tmp_path):
        """workshop_patch.json ships structural_overrides for Ch10-11
        ('first_pinch') and Ch26 ('climax'). The translator must respect
        all of them regardless of what the raw scene card declared."""
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
        expected = {
            10: "first_pinch",
            11: "first_pinch",
            26: "climax",
        }
        for chapter, expected_phase in expected.items():
            matches = list(scene_cards_dir.glob(f"chapter_{chapter:02d}_scene_*.json"))
            assert matches, f"no scene cards extracted for chapter {chapter}"
            for path in matches:
                card = json.loads(path.read_text(encoding="utf-8"))
                assert card["structural_phase"] == expected_phase, (
                    f"{path.name} structural_phase={card['structural_phase']!r} "
                    f"(expected {expected_phase!r})"
                )

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

        # The concept_workshop modules above are Phase-4 back-compat shims
        # that re-export from workflows/_shared/. Mirror that package so
        # the wrapper's import chain resolves inside the isolated tree.
        shared_dst = tmp_path / "workflows" / "_shared"
        shared_dst.mkdir(parents=True)
        (tmp_path / "workflows" / "__init__.py").touch()
        (shared_dst / "__init__.py").touch()
        shutil.copy(
            REPO_ROOT / "workflows" / "_shared" / "seed_transforms.py",
            shared_dst,
        )
        shutil.copy(
            REPO_ROOT / "workflows" / "_shared" / "scene_card_translator.py",
            shared_dst,
        )

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
