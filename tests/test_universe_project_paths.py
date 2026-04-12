"""Tests for universe-scoped ProjectPaths and backward compatibility."""

import json
import pytest
from pathlib import Path

from src.project_paths import ProjectPaths, slugify_title, _slugify_franchise


class TestSlugification:
    def test_slugify_title(self):
        assert slugify_title("The Ruusan Atonement") == "the-ruusan-atonement"

    def test_slugify_franchise(self):
        assert _slugify_franchise("Star Wars (Legends EU)") == "star-wars-legends-eu"
        assert _slugify_franchise("Original") == "original"


class TestFlatPaths:
    """Backward compat: no universe_slug produces flat paths."""

    def test_project_root_flat(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        assert p.project_root == tmp_path / "data" / "projects" / "my-book"

    def test_manuscripts_flat(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        assert p.manuscripts_dir == tmp_path / "output" / "my-book" / "chapters"

    def test_universe_root_is_none(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        assert p.universe_root is None
        assert p.universe_meta_path is None

    def test_display_name_flat(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        assert p.display_name == "my-book"


class TestUniverseScopedPaths:
    """Universe-scoped paths nest project under universe."""

    def test_project_root_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), universe_slug="star-wars")
        assert p.project_root == tmp_path / "data" / "projects" / "star-wars" / "my-book"

    def test_manuscripts_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), universe_slug="star-wars")
        assert p.manuscripts_dir == tmp_path / "output" / "star-wars" / "my-book" / "chapters"

    def test_universe_root(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), universe_slug="star-wars")
        assert p.universe_root == tmp_path / "data" / "universes" / "star-wars"

    def test_worldbuilding_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), universe_slug="star-wars")
        assert p.worldbuilding_db == tmp_path / "data" / "universes" / "star-wars" / "worldbuilding.db"

    def test_canon_db_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), universe_slug="star-wars")
        assert p.canon_dbs_dir == tmp_path / "data" / "universes" / "star-wars" / "canon_db"

    def test_display_name_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), universe_slug="star-wars")
        assert p.display_name == "star-wars/my-book"


class TestFromConceptSeed:
    def test_derives_universe_from_franchise(self, tmp_path):
        seed = {
            "meta": {
                "project_title": "The Ruusan Atonement",
                "franchise": "Star Wars Legends",
            },
        }
        p = ProjectPaths.from_concept_seed(seed, base_dir=str(tmp_path))
        assert p.project_slug == "the-ruusan-atonement"
        assert p.universe_slug == "star-wars-legends"

    def test_no_franchise_means_no_universe(self, tmp_path):
        seed = {
            "meta": {
                "project_title": "My Original Novel",
                "franchise": "",
            },
        }
        p = ProjectPaths.from_concept_seed(seed, base_dir=str(tmp_path))
        assert p.universe_slug is None


class TestFromConceptSeedPath:
    def test_flat_structure(self, tmp_path):
        # Set up: data/projects/my-book/concept_seed.json
        project_dir = tmp_path / "data" / "projects" / "my-book"
        project_dir.mkdir(parents=True)
        seed_path = project_dir / "concept_seed.json"
        seed_path.write_text(json.dumps({
            "meta": {"project_title": "My Book", "franchise": "Test Franchise"}
        }))
        p = ProjectPaths.from_concept_seed_path(str(seed_path), base_dir=str(tmp_path))
        assert p.project_slug == "my-book"
        assert p.universe_slug == "test-franchise"

    def test_universe_scoped_structure(self, tmp_path):
        # Set up: data/projects/test-universe/my-book/concept_seed.json
        project_dir = tmp_path / "data" / "projects" / "test-universe" / "my-book"
        project_dir.mkdir(parents=True)
        seed_path = project_dir / "concept_seed.json"
        seed_path.write_text(json.dumps({"meta": {"project_title": "My Book"}}))
        p = ProjectPaths.from_concept_seed_path(str(seed_path), base_dir=str(tmp_path))
        assert p.project_slug == "my-book"
        assert p.universe_slug == "test-universe"


class TestEnsureDirs:
    def test_creates_all_dirs(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), universe_slug="test-u")
        p.ensure_dirs()
        assert p.story_state_db.parent.exists()
        assert p.chapter_memory_dir.exists()
        assert p.manuscripts_dir.exists()
        assert p.universe_root.exists()


class TestEnsureUniverseMeta:
    def test_creates_meta_file(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), universe_slug="test-u")
        p.ensure_dirs()
        seed = {"meta": {"franchise": "Test", "canon_status": "AU"}}
        p.ensure_universe_meta(seed)
        assert p.universe_meta_path.exists()
        meta = json.loads(p.universe_meta_path.read_text())
        assert meta["franchise"] == "Test"
        assert meta["canon_status"] == "AU"

    def test_no_universe_is_noop(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        p.ensure_universe_meta()  # Should not raise
