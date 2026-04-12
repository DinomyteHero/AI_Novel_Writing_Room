"""Tests for franchise-scoped ProjectPaths and backward compatibility.

Covers: franchise scoping, series linkage, run isolation, factory methods,
directory creation, and franchise metadata.
"""

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
    """Backward compat: no franchise_slug produces flat paths."""

    def test_book_dir_flat(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        assert p.book_dir == tmp_path / "data" / "projects" / "my-book"

    def test_manuscripts_flat(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        assert p.manuscripts_dir == tmp_path / "output" / "my-book" / "chapters"

    def test_franchise_dir_is_none(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        assert p.franchise_dir is None
        assert p.universe_meta_path is None

    def test_display_name_flat(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        assert p.display_name == "my-book"


class TestFranchiseScopedPaths:
    """Franchise-scoped paths nest book under franchise."""

    def test_book_dir_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="star-wars")
        assert p.book_dir == tmp_path / "data" / "franchises" / "star-wars" / "books" / "my-book"

    def test_manuscripts_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="star-wars")
        assert p.manuscripts_dir == tmp_path / "output" / "star-wars" / "my-book" / "chapters"

    def test_franchise_dir(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="star-wars")
        assert p.franchise_dir == tmp_path / "data" / "franchises" / "star-wars"

    def test_worldbuilding_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="star-wars")
        assert p.worldbuilding_db == tmp_path / "data" / "franchises" / "star-wars" / "worldbuilding.db"

    def test_canon_db_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="star-wars")
        assert p.canon_dbs_dir == tmp_path / "data" / "franchises" / "star-wars" / "canon_db"

    def test_display_name_scoped(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="star-wars")
        assert p.display_name == "star-wars/my-book"


class TestSeriesLinkage:
    """Series-scoped state sharing between books."""

    def test_state_dir_with_series(self, tmp_path):
        p = ProjectPaths("book-1", base_dir=str(tmp_path), franchise_slug="sw", series_slug="trilogy")
        assert p.state_dir == tmp_path / "output" / "sw" / "trilogy" / "state"

    def test_state_dir_without_series(self, tmp_path):
        p = ProjectPaths("book-1", base_dir=str(tmp_path), franchise_slug="sw")
        assert p.state_dir == tmp_path / "output" / "sw" / "book-1" / "state"

    def test_shared_state_across_books(self, tmp_path):
        p1 = ProjectPaths("book-1", base_dir=str(tmp_path), franchise_slug="sw", series_slug="trilogy")
        p2 = ProjectPaths("book-2", base_dir=str(tmp_path), franchise_slug="sw", series_slug="trilogy")
        assert p1.story_state_db == p2.story_state_db
        assert p1.run_ledger_db == p2.run_ledger_db

    def test_display_name_with_series(self, tmp_path):
        p = ProjectPaths("book-1", base_dir=str(tmp_path), franchise_slug="sw", series_slug="trilogy")
        assert "trilogy" in p.display_name


class TestRunIsolation:
    """Per-run output isolation."""

    def test_run_dir(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="sw", run_id="run-1")
        assert p.run_dir == tmp_path / "output" / "sw" / "my-book" / "runs" / "run-1"

    def test_manuscripts_in_run(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="sw", run_id="run-1")
        assert p.manuscripts_dir == tmp_path / "output" / "sw" / "my-book" / "runs" / "run-1" / "chapters"

    def test_config_snapshot(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="sw", run_id="run-1")
        assert p.config_snapshot_path == tmp_path / "output" / "sw" / "my-book" / "runs" / "run-1" / "config_snapshot.yaml"

    def test_no_run_dir_without_run_id(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="sw")
        assert p.run_dir is None
        assert p.config_snapshot_path is None


class TestFromConceptSeed:
    def test_derives_franchise_from_meta(self, tmp_path):
        seed = {
            "meta": {
                "project_title": "The Ruusan Atonement",
                "franchise": "Star Wars Legends",
            },
        }
        p = ProjectPaths.from_concept_seed(seed, base_dir=str(tmp_path))
        assert p.project_slug == "the-ruusan-atonement"
        assert p.franchise_slug == "star-wars-legends"

    def test_derives_series_from_meta(self, tmp_path):
        seed = {
            "meta": {
                "project_title": "Book 1",
                "franchise": "SW",
                "series_id": "My Trilogy",
            },
        }
        p = ProjectPaths.from_concept_seed(seed, base_dir=str(tmp_path))
        assert p.series_slug == "my-trilogy"

    def test_no_franchise_means_flat(self, tmp_path):
        seed = {"meta": {"project_title": "My Original Novel", "franchise": ""}}
        p = ProjectPaths.from_concept_seed(seed, base_dir=str(tmp_path))
        assert p.franchise_slug is None


class TestFromConceptSeedPath:
    def test_franchise_structure(self, tmp_path):
        # Set up: data/franchises/sw/books/my-book/concept_seed.json
        project_dir = tmp_path / "data" / "franchises" / "sw" / "books" / "my-book"
        project_dir.mkdir(parents=True)
        seed_path = project_dir / "concept_seed.json"
        seed_path.write_text(json.dumps({"meta": {"project_title": "My Book"}}))
        p = ProjectPaths.from_concept_seed_path(str(seed_path), base_dir=str(tmp_path))
        assert p.project_slug == "my-book"
        assert p.franchise_slug == "sw"

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
        assert p.franchise_slug == "test-franchise"


class TestEnsureDirs:
    def test_creates_all_dirs(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="test-f", run_id="r1")
        p.ensure_dirs()
        assert p.state_dir.exists()
        assert p.chapter_memory_dir.exists()
        assert p.manuscripts_dir.exists()
        assert p.franchise_dir.exists()
        assert p.run_dir.exists()


class TestEnsureFranchiseMeta:
    def test_creates_meta_file(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="test-f")
        p.ensure_dirs()
        seed = {"meta": {"franchise": "Test", "canon_status": "AU"}}
        p.ensure_franchise_meta(seed)
        assert p.universe_meta_path.exists()
        meta = json.loads(p.universe_meta_path.read_text())
        assert meta["franchise"] == "Test"
        assert meta["canon_status"] == "AU"

    def test_no_franchise_is_noop(self, tmp_path):
        p = ProjectPaths("my-book", base_dir=str(tmp_path))
        p.ensure_franchise_meta()  # Should not raise
