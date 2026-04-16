"""Tests for ProjectPaths helper."""

import json
from pathlib import Path

import pytest

from src.project_paths import ProjectPaths, slugify_title


class TestSlugify:
    def test_basic(self):
        assert slugify_title("The Ruusan Atonement") == "the-ruusan-atonement"

    def test_apostrophe(self):
        assert slugify_title("The Purge's Echo") == "the-purges-echo"

    def test_whitespace(self):
        assert slugify_title("  Beyond the Veil  ") == "beyond-the-veil"

    def test_underscores(self):
        assert slugify_title("my_project_title") == "my-project-title"

    def test_numbers(self):
        assert slugify_title("Book 2: The Return") == "book-2-the-return"


class TestProjectPaths:
    def test_paths_flat(self, tmp_path):
        """Flat (no franchise) backward compatibility."""
        p = ProjectPaths("the-ruusan-atonement", base_dir=str(tmp_path))
        assert p.manuscripts_dir == tmp_path / "output" / "the-ruusan-atonement" / "chapters"
        assert p.story_state_db == tmp_path / "output" / "the-ruusan-atonement" / "state" / "story_state.db"
        assert p.export_dir == tmp_path / "output" / "the-ruusan-atonement" / "export"

    def test_paths_franchise_scoped(self, tmp_path):
        """Franchise-scoped paths."""
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="star-wars")
        assert p.book_dir == tmp_path / "data" / "franchises" / "star-wars" / "books" / "my-book"
        assert p.manuscripts_dir == tmp_path / "output" / "star-wars" / "my-book" / "chapters"
        assert p.story_state_db == tmp_path / "output" / "star-wars" / "my-book" / "state" / "story_state.db"

    def test_paths_with_run_id(self, tmp_path):
        """Run-scoped manuscripts go into run directory."""
        p = ProjectPaths("my-book", base_dir=str(tmp_path), franchise_slug="sw", run_id="run-1")
        assert p.manuscripts_dir == tmp_path / "output" / "sw" / "my-book" / "runs" / "run-1" / "chapters"
        assert p.run_dir == tmp_path / "output" / "sw" / "my-book" / "runs" / "run-1"

    def test_paths_with_series(self, tmp_path):
        """Series-scoped state is shared across books."""
        p = ProjectPaths("book-a", base_dir=str(tmp_path), franchise_slug="sw", series_slug="my-series")
        assert p.state_dir == tmp_path / "output" / "sw" / "my-series" / "state"
        assert p.story_state_db == tmp_path / "output" / "sw" / "my-series" / "state" / "story_state.db"
        # But manuscripts are still per-book
        assert p.manuscripts_dir == tmp_path / "output" / "sw" / "book-a" / "chapters"

    def test_from_concept_seed(self):
        seed = {"meta": {"project_title": "The Ruusan Atonement"}}
        p = ProjectPaths.from_concept_seed(seed, base_dir="/tmp")
        assert p.project_slug == "the-ruusan-atonement"

    def test_from_concept_seed_with_series(self):
        seed = {"meta": {"project_title": "Book 1", "series_id": "My Series"}}
        p = ProjectPaths.from_concept_seed(seed, base_dir="/tmp")
        assert p.series_slug == "my-series"

    def test_ensure_dirs(self, tmp_path):
        p = ProjectPaths("test-project", base_dir=str(tmp_path), franchise_slug="sw", run_id="r1")
        p.ensure_dirs()
        assert p.manuscripts_dir.exists()
        assert p.scene_cards_dir.exists()
        assert p.export_dir.exists()
        assert p.state_dir.exists()
        assert p.chapter_memory_dir.exists()
        assert p.run_dir.exists()

    def test_two_projects_isolated(self, tmp_path):
        p1 = ProjectPaths("project-a", base_dir=str(tmp_path), franchise_slug="sw")
        p2 = ProjectPaths("project-b", base_dir=str(tmp_path), franchise_slug="sw")
        assert p1.manuscripts_dir != p2.manuscripts_dir
        assert p1.story_state_db != p2.story_state_db
        # Franchise resources are shared
        assert p1.canon_dbs_dir == p2.canon_dbs_dir
        assert p1.eval_corpus_dir == p2.eval_corpus_dir

    def test_two_books_same_series_share_state(self, tmp_path):
        p1 = ProjectPaths("book-1", base_dir=str(tmp_path), franchise_slug="sw", series_slug="trilogy")
        p2 = ProjectPaths("book-2", base_dir=str(tmp_path), franchise_slug="sw", series_slug="trilogy")
        assert p1.state_dir == p2.state_dir
        assert p1.story_state_db == p2.story_state_db
        # But manuscripts are per-book
        assert p1.manuscripts_dir != p2.manuscripts_dir

    def test_project_root_backward_compat(self, tmp_path):
        p = ProjectPaths("my-novel", base_dir=str(tmp_path))
        assert p.project_root == tmp_path / "data" / "projects" / "my-novel"
        assert p.project_root == p.book_dir


class TestCosmologyLayer:
    """Phase 2: optional cosmology layer above franchise (meta-universe for
    Sanderson-style shared cosmology). Purely additive — existing layouts are
    unchanged."""

    def test_cosmology_slug_constructor_exposes_paths(self, tmp_path):
        p = ProjectPaths(
            "book-a",
            base_dir=str(tmp_path),
            franchise_slug="sw",
            cosmology_slug="my-cosmo",
        )
        assert p.cosmology_slug == "my-cosmo"
        assert p.cosmology_dir == tmp_path / "data" / "cosmologies" / "my-cosmo"
        assert p.cosmology_meta_path == (
            tmp_path / "data" / "cosmologies" / "my-cosmo" / "cosmology_meta.json"
        )

    def test_no_cosmology_returns_none(self, tmp_path):
        """Back-compat: projects without cosmology_slug get None, not a default path."""
        p = ProjectPaths("book-a", base_dir=str(tmp_path), franchise_slug="sw")
        assert p.cosmology_slug is None
        assert p.cosmology_dir is None
        assert p.cosmology_meta_path is None

    def test_cosmology_leaves_book_level_paths_unchanged(self, tmp_path):
        """Adding cosmology must not disturb franchise/book/manuscripts layout."""
        p_with = ProjectPaths(
            "book-a",
            base_dir=str(tmp_path),
            franchise_slug="sw",
            cosmology_slug="my-cosmo",
        )
        p_without = ProjectPaths(
            "book-a",
            base_dir=str(tmp_path),
            franchise_slug="sw",
        )
        assert p_with.book_dir == p_without.book_dir
        assert p_with.manuscripts_dir == p_without.manuscripts_dir
        assert p_with.state_dir == p_without.state_dir
        assert p_with.canon_dbs_dir == p_without.canon_dbs_dir

    def test_from_concept_seed_with_cosmology_id(self):
        seed = {
            "meta": {
                "project_title": "Way of Kings",
                "franchise": "stormlight-archive",
                "cosmology_id": "The Cosmere",
            }
        }
        p = ProjectPaths.from_concept_seed(seed, base_dir="/tmp")
        assert p.cosmology_slug == "the-cosmere"
        assert p.franchise_slug == "stormlight-archive"

    def test_from_concept_seed_without_cosmology_is_back_compat(self):
        """Ruusan-shaped seed (no cosmology_id) yields cosmology_slug=None."""
        seed = {
            "meta": {
                "project_title": "The Ruusan Atonement",
                "franchise": "star-wars-legends-eu",
            }
        }
        p = ProjectPaths.from_concept_seed(seed, base_dir="/tmp")
        assert p.cosmology_slug is None
        assert p.franchise_slug == "star-wars-legends-eu"
        assert p.project_slug == "the-ruusan-atonement"

    def test_from_concept_seed_path_franchise_layout_extracts_cosmology(self, tmp_path):
        seed_dir = (
            tmp_path / "data" / "franchises" / "stormlight-archive"
            / "books" / "way-of-kings"
        )
        seed_dir.mkdir(parents=True)
        seed_path = seed_dir / "concept_seed.json"
        seed_path.write_text(
            json.dumps({"meta": {"cosmology_id": "the-cosmere"}}),
            encoding="utf-8",
        )
        p = ProjectPaths.from_concept_seed_path(str(seed_path), base_dir=str(tmp_path))
        assert p.cosmology_slug == "the-cosmere"
        assert p.franchise_slug == "stormlight-archive"

    def test_ensure_dirs_creates_cosmology_dir(self, tmp_path):
        p = ProjectPaths(
            "book-a",
            base_dir=str(tmp_path),
            franchise_slug="sw",
            cosmology_slug="my-cosmo",
        )
        p.ensure_dirs()
        assert p.cosmology_dir.exists()

    def test_ensure_cosmology_meta_writes_file_when_missing(self, tmp_path):
        p = ProjectPaths(
            "book-a",
            base_dir=str(tmp_path),
            franchise_slug="sw",
            cosmology_slug="my-cosmo",
        )
        p.ensure_cosmology_meta(
            cosmology_name="My Cosmology",
            description="test description",
        )
        meta = json.loads(p.cosmology_meta_path.read_text(encoding="utf-8"))
        assert meta["cosmology_id"] == "my-cosmo"
        assert meta["cosmology_name"] == "My Cosmology"
        assert meta["description"] == "test description"

    def test_ensure_cosmology_meta_no_op_without_cosmology_slug(self, tmp_path):
        """ensure_cosmology_meta must be inert when there's no cosmology_slug."""
        p = ProjectPaths("book-a", base_dir=str(tmp_path), franchise_slug="sw")
        # Should not raise, should not create anything.
        p.ensure_cosmology_meta(cosmology_name="Irrelevant")
        # No cosmologies directory should be created.
        assert not (tmp_path / "data" / "cosmologies").exists()

    def test_display_name_includes_cosmology(self, tmp_path):
        p = ProjectPaths(
            "book-a",
            base_dir=str(tmp_path),
            franchise_slug="sw",
            cosmology_slug="my-cosmo",
        )
        assert "my-cosmo" in p.display_name
        assert "sw" in p.display_name
        assert "book-a" in p.display_name
