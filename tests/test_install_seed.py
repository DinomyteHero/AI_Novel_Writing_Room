"""Tests for scripts/install_seed.py.

Runs against the minimal non-Ruusan fixture in tests/fixtures/. All
installs go to tmp_path so nothing touches the committed tree.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.install_seed import install_seed


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MINIMAL_SEED = FIXTURES_DIR / "minimal_seed.json"
MINIMAL_PATCH = FIXTURES_DIR / "minimal_workshop_patch.json"


@pytest.fixture
def minimal_seed_path(tmp_path) -> Path:
    """Return the fixture path. The fixture itself is read-only — tests
    that need to mutate it should copy into tmp_path first."""
    return MINIMAL_SEED


def _load_installed_seed(base: Path) -> dict:
    seed_path = (
        base / "data" / "franchises" / "test-franchise" / "books"
        / "test-novel" / "concept_seed.json"
    )
    return json.loads(seed_path.read_text(encoding="utf-8"))


class TestInstallSeedNoPatch:
    def test_seed_written_to_franchise_book_path(self, tmp_path, minimal_seed_path):
        result = install_seed(
            input_path=minimal_seed_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,  # translator output isn't schema-valid (see translator docstring)
        )
        expected = (
            tmp_path / "data" / "franchises" / "test-franchise" / "books"
            / "test-novel" / "concept_seed.json"
        )
        assert result.seed_path == expected
        assert expected.exists()

    def test_scene_cards_extracted(self, tmp_path, minimal_seed_path):
        result = install_seed(
            input_path=minimal_seed_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        scene_cards_dir = (
            tmp_path / "data" / "franchises" / "test-franchise" / "books"
            / "test-novel" / "scene_cards"
        )
        assert scene_cards_dir.exists()
        files = sorted(p.name for p in scene_cards_dir.glob("*.json"))
        assert files == [
            "chapter_01_scene_01.json",
            "chapter_01_scene_02.json",
        ]
        assert result.scene_card_count == 2

    def test_franchise_meta_created(self, tmp_path, minimal_seed_path):
        install_seed(
            input_path=minimal_seed_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        franchise_meta = (
            tmp_path / "data" / "franchises" / "test-franchise" / "franchise_meta.json"
        )
        assert franchise_meta.exists()

    def test_seed_untouched_when_no_patch(self, tmp_path, minimal_seed_path):
        install_seed(
            input_path=minimal_seed_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        source = json.loads(minimal_seed_path.read_text(encoding="utf-8"))
        # Without a patch the installer should not inject voice_definition,
        # promise_payoff_ledger, canon_constraints, etc. that weren't in
        # the source.
        assert installed.get("voice_definition") == source.get("voice_definition")
        assert installed.get("promise_payoff_ledger") == source.get(
            "promise_payoff_ledger"
        )
        # The input fixture carries its own canon_constraints already.
        assert installed.get("canon_constraints") == source.get("canon_constraints")

    def test_character_count_reported(self, tmp_path, minimal_seed_path):
        result = install_seed(
            input_path=minimal_seed_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        assert result.character_count == 2


class TestInstallSeedWithPatch:
    def test_voice_definition_injected(self, tmp_path, minimal_seed_path):
        install_seed(
            input_path=minimal_seed_path,
            workshop_patch_path=MINIMAL_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        assert installed["voice_definition"]["pov_approach"] == (
            "Close third limited, locked to Alice"
        )

    def test_arc_phase_maps_injected(self, tmp_path, minimal_seed_path):
        install_seed(
            input_path=minimal_seed_path,
            workshop_patch_path=MINIMAL_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        alice = next(
            c for c in installed["ensemble_cast"] if c["name"] == "Alice"
        )
        assert alice["weiland_arc"]["arc_phase_map"]["moment_of_truth"] == "Chapter 7"

    def test_promise_payoff_ledger_injected(self, tmp_path, minimal_seed_path):
        install_seed(
            input_path=minimal_seed_path,
            workshop_patch_path=MINIMAL_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        assert len(installed["promise_payoff_ledger"]) == 1
        assert installed["promise_payoff_ledger"][0]["promise_id"] == "PP01"

    def test_workshop_origin_under_extended_metadata(
        self, tmp_path, minimal_seed_path,
    ):
        install_seed(
            input_path=minimal_seed_path,
            workshop_patch_path=MINIMAL_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        origin = installed["extended_metadata"]["workshop_origin"]
        assert origin["source"] == "test_fixture"
        assert origin["date"] == "2026-04-16"

    def test_arc_type_map_normalizes_enums(self, tmp_path, minimal_seed_path):
        """Source seed already ships canonical arc_type values; normalize
        should leave them untouched."""
        install_seed(
            input_path=minimal_seed_path,
            workshop_patch_path=MINIMAL_PATCH,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        for char, expected in (("Alice", "positive_change"), ("Bob", "negative")):
            match = next(c for c in installed["ensemble_cast"] if c["name"] == char)
            assert match["weiland_arc"]["arc_type"] == expected


class TestInstallSeedStructuralOverrides:
    def test_override_applied_to_scene_card(self, tmp_path, minimal_seed_path):
        """Patch with a structural_overrides entry should coerce the
        translator's structural_phase output for the matching chapter."""
        # Build a one-off patch with an override on chapter 1.
        patch = {"structural_overrides": {"1": "climax"}}
        patch_path = tmp_path / "patch.json"
        patch_path.write_text(json.dumps(patch), encoding="utf-8")

        install_seed(
            input_path=minimal_seed_path,
            workshop_patch_path=patch_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        scene_01 = json.loads(
            (
                tmp_path / "data" / "franchises" / "test-franchise" / "books"
                / "test-novel" / "scene_cards" / "chapter_01_scene_01.json"
            ).read_text(encoding="utf-8")
        )
        assert scene_01["structural_phase"] == "climax"


class TestInstallSeedErrorPaths:
    def test_missing_input_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            install_seed(
                input_path=tmp_path / "missing.json",
                base_dir=str(tmp_path),
                validate_scene_cards=False,
            )

    def test_missing_patch_raises(self, tmp_path, minimal_seed_path):
        with pytest.raises(FileNotFoundError):
            install_seed(
                input_path=minimal_seed_path,
                workshop_patch_path=tmp_path / "missing_patch.json",
                base_dir=str(tmp_path),
                validate_scene_cards=False,
            )


class TestInstallSeedSchemaValidation:
    def test_seed_validates_against_schema(self, tmp_path, minimal_seed_path):
        """The fixture seed is deliberately schema-valid. install_seed's
        seed-level validation should not add warnings for it."""
        result = install_seed(
            input_path=minimal_seed_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
            validate_seed=True,
        )
        seed_warnings = [
            w for w in result.warnings if "enriched seed fails" in w
        ]
        assert seed_warnings == []

    def test_invalid_seed_reports_warning(self, tmp_path, minimal_seed_path):
        """If the source seed violates the schema, install_seed should
        surface the violation in result.warnings rather than raising —
        tests and tooling can decide whether to treat it as fatal."""
        broken = json.loads(minimal_seed_path.read_text(encoding="utf-8"))
        # Violate the tone enum.
        broken["meta"]["tone"] = "not_a_real_tone"
        broken_path = tmp_path / "broken_seed.json"
        broken_path.write_text(json.dumps(broken), encoding="utf-8")

        result = install_seed(
            input_path=broken_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
            validate_seed=True,
        )
        assert any("enriched seed fails" in w for w in result.warnings)


class TestBranchPointCarryover:
    """Phase 6.3b — install_seed copies branch_point from the franchise-
    scoped universe_meta into the concept_seed's meta block.

    Back-compat: when no universe_meta exists, or the file has no
    branch_point, behaviour is identical to pre-Phase-6 installs.
    """

    POPULATED_BRANCH_POINT = {
        "source_canon": "Star Wars Legends EU",
        "divergence_point": "post-Lost Tribe crisis, circa 44 ABY",
        "divergence_description": "Ruusan-style reformation path.",
    }

    @staticmethod
    def _write_universe_meta(tmp_path: Path, franchise_slug: str, meta: dict) -> Path:
        """Pre-create data/franchises/<slug>/franchise_meta.json."""
        path = (
            tmp_path / "data" / "franchises" / franchise_slug / "franchise_meta.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return path

    def test_branch_point_propagates_when_universe_meta_has_it(
        self, tmp_path, minimal_seed_path
    ):
        # Pre-create universe_meta with a populated branch_point.
        self._write_universe_meta(
            tmp_path,
            "test-franchise",
            {
                "franchise_name": "test-franchise",
                "franchise": "Test Franchise",
                "canon_status": "AU",
                "branch_point": self.POPULATED_BRANCH_POINT,
            },
        )
        install_seed(
            input_path=minimal_seed_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        assert installed["meta"]["branch_point"] == self.POPULATED_BRANCH_POINT

    def test_no_branch_point_when_universe_meta_missing(
        self, tmp_path, minimal_seed_path
    ):
        """Fresh-install path: install_seed auto-creates franchise_meta.json
        via ensure_franchise_meta, but without any branch_point content."""
        install_seed(
            input_path=minimal_seed_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        assert "branch_point" not in installed["meta"]

    def test_no_branch_point_when_universe_meta_has_empty_block(
        self, tmp_path, minimal_seed_path
    ):
        self._write_universe_meta(
            tmp_path,
            "test-franchise",
            {
                "franchise_name": "test-franchise",
                "franchise": "Test Franchise",
                "canon_status": "original",
                "branch_point": {},
            },
        )
        install_seed(
            input_path=minimal_seed_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        assert "branch_point" not in installed["meta"]

    def test_seed_level_branch_point_wins_over_universe_default(
        self, tmp_path, minimal_seed_path
    ):
        """If the source seed already declares branch_point, the installer
        must not overwrite it with the universe_meta default."""
        self._write_universe_meta(
            tmp_path,
            "test-franchise",
            {
                "franchise_name": "test-franchise",
                "franchise": "Test Franchise",
                "canon_status": "AU",
                "branch_point": self.POPULATED_BRANCH_POINT,
            },
        )
        # Author a variant seed with an explicit branch_point override.
        base_seed = json.loads(minimal_seed_path.read_text(encoding="utf-8"))
        override = {"source_canon": "Override Canon"}
        base_seed["meta"]["branch_point"] = override
        override_path = tmp_path / "seed_with_override.json"
        override_path.write_text(json.dumps(base_seed), encoding="utf-8")

        install_seed(
            input_path=override_path,
            base_dir=str(tmp_path),
            validate_scene_cards=False,
        )
        installed = _load_installed_seed(tmp_path)
        assert installed["meta"]["branch_point"] == override
