"""Tests for scripts/init_project.py.

The scaffold must produce a directory tree and a schema-valid concept_seed.json
for every depth. Tests run with base_dir=tmp_path so nothing touches the
committed repo tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema", reason="jsonschema not installed")

from scripts.init_project import CANON_PROFILE_TEMPLATES, init_project


REPO_ROOT = Path(__file__).resolve().parents[1]
CONCEPT_SEED_SCHEMA = REPO_ROOT / "schemas" / "concept_seed.json"


@pytest.fixture
def seed_schema() -> dict:
    return json.loads(CONCEPT_SEED_SCHEMA.read_text(encoding="utf-8"))


class TestInitProjectScaffoldsEveryDepth:
    @pytest.mark.parametrize("depth", sorted(CANON_PROFILE_TEMPLATES))
    def test_depth_produces_valid_scaffold(self, depth, tmp_path, seed_schema):
        paths = init_project(
            title="Test Novel",
            franchise="Test Franchise",
            depth=depth,
            base_dir=str(tmp_path),
        )
        assert paths.concept_seed_path.exists(), (
            f"concept_seed.json should exist at {paths.concept_seed_path}"
        )
        seed = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=seed, schema=seed_schema)

    @pytest.mark.parametrize("depth", sorted(CANON_PROFILE_TEMPLATES))
    def test_canon_profile_injected(self, depth, tmp_path):
        init_project(
            title="Test Novel",
            franchise="Test Franchise",
            depth=depth,
            base_dir=str(tmp_path),
        )
        seed_path = (
            tmp_path
            / "data"
            / "franchises"
            / "test-franchise"
            / "books"
            / "test-novel"
            / "concept_seed.json"
        )
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        assert "canon_profile" in seed
        assert seed["canon_profile"].get("franchise") is not None
        # _template_notes must be stripped before injection.
        assert "_template_notes" not in seed["canon_profile"]
        # Scaffold should record which template was used.
        assert seed["extended_metadata"]["scaffold_origin"][
            "canon_profile_template"
        ] == depth

    def test_voice_definition_injected(self, tmp_path):
        init_project(
            title="Test Novel",
            franchise="Test Franchise",
            depth="original_light",
            base_dir=str(tmp_path),
        )
        seed_path = (
            tmp_path / "data" / "franchises" / "test-franchise" / "books"
            / "test-novel" / "concept_seed.json"
        )
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        voice = seed["voice_definition"]
        assert "pov_approach" in voice
        assert "anti_slop_rules" in voice
        assert "_template_notes" not in voice


class TestInitProjectDirectoryLayout:
    def test_franchise_meta_created(self, tmp_path):
        init_project(
            title="Test Novel",
            franchise="Test Franchise",
            depth="original_light",
            base_dir=str(tmp_path),
        )
        franchise_meta = (
            tmp_path / "data" / "franchises" / "test-franchise" / "franchise_meta.json"
        )
        assert franchise_meta.exists()
        meta = json.loads(franchise_meta.read_text(encoding="utf-8"))
        assert meta.get("franchise") == "Test Franchise"

    def test_scene_cards_directory_created_empty(self, tmp_path):
        init_project(
            title="Test Novel",
            franchise="Test Franchise",
            depth="original_light",
            base_dir=str(tmp_path),
        )
        scene_cards_dir = (
            tmp_path / "data" / "franchises" / "test-franchise" / "books"
            / "test-novel" / "scene_cards"
        )
        assert scene_cards_dir.exists()
        assert list(scene_cards_dir.iterdir()) == []


class TestInitProjectCosmology:
    def test_cosmology_meta_created_when_requested(self, tmp_path):
        init_project(
            title="Test Novel",
            franchise="Test Franchise",
            depth="original_deep",
            cosmology_id="test-cosmology",
            base_dir=str(tmp_path),
        )
        cosmology_meta = (
            tmp_path / "data" / "cosmologies" / "test-cosmology" / "cosmology_meta.json"
        )
        assert cosmology_meta.exists()
        cm = json.loads(cosmology_meta.read_text(encoding="utf-8"))
        assert cm.get("cosmology_id") == "test-cosmology"

    def test_cosmology_id_recorded_in_meta(self, tmp_path):
        init_project(
            title="Test Novel",
            franchise="Test Franchise",
            depth="original_deep",
            cosmology_id="test-cosmology",
            base_dir=str(tmp_path),
        )
        seed_path = (
            tmp_path / "data" / "franchises" / "test-franchise" / "books"
            / "test-novel" / "concept_seed.json"
        )
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        assert seed["meta"].get("cosmology_id") == "test-cosmology"

    def test_no_cosmology_dir_when_not_requested(self, tmp_path):
        init_project(
            title="Test Novel",
            franchise="Test Franchise",
            depth="original_light",
            base_dir=str(tmp_path),
        )
        cosmology_root = tmp_path / "data" / "cosmologies"
        assert not cosmology_root.exists() or list(cosmology_root.iterdir()) == []


class TestInitProjectSeriesId:
    def test_series_id_recorded_in_meta(self, tmp_path):
        init_project(
            title="Test Novel",
            franchise="Test Franchise",
            depth="original_light",
            series_id="test-series",
            base_dir=str(tmp_path),
        )
        seed_path = (
            tmp_path / "data" / "franchises" / "test-franchise" / "books"
            / "test-novel" / "concept_seed.json"
        )
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        assert seed["meta"].get("series_id") == "test-series"


class TestInitProjectValidation:
    def test_unknown_depth_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="unknown canon_profile template"):
            init_project(
                title="X",
                franchise="Y",
                depth="not-a-template",
                base_dir=str(tmp_path),
            )

    def test_canon_status_matches_profile_default(self, tmp_path):
        """Each profile's seed should have the canon_status that matches
        that profile's locked default — AU for Elseworlds, canon_compliant
        for fanfic_compliant, original for the three original modes."""
        expectations = {
            "fanfic_elseworlds": "AU",
            "fanfic_compliant": "canon_compliant",
            "original_deep": "original",
            "original_light": "original",
            "realistic": "original",
        }
        for depth, expected in expectations.items():
            run_dir = tmp_path / depth
            init_project(
                title="Test Novel",
                franchise="Test Franchise",
                depth=depth,
                base_dir=str(run_dir),
            )
            seed_path = (
                run_dir / "data" / "franchises" / "test-franchise" / "books"
                / "test-novel" / "concept_seed.json"
            )
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
            assert seed["meta"]["canon_status"] == expected, (
                f"{depth} should default canon_status to {expected!r}"
            )
