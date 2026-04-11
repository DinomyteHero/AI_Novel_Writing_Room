"""Tests for ProjectPaths helper."""

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
    def test_paths_from_slug(self, tmp_path):
        p = ProjectPaths("the-ruusan-atonement", base_dir=str(tmp_path))
        assert p.manuscripts_dir == tmp_path / "output" / "the-ruusan-atonement" / "chapters"
        assert p.story_state_db == tmp_path / "data" / "projects" / "the-ruusan-atonement" / "state" / "story_state.db"
        assert p.export_dir == tmp_path / "output" / "the-ruusan-atonement" / "export"
        assert p.worldbuilding_db == tmp_path / "data" / "universes" / "worldbuilding.db"

    def test_from_concept_seed(self):
        seed = {"meta": {"project_title": "The Ruusan Atonement"}}
        p = ProjectPaths.from_concept_seed(seed, base_dir="/tmp")
        assert p.project_slug == "the-ruusan-atonement"

    def test_ensure_dirs(self, tmp_path):
        p = ProjectPaths("test-project", base_dir=str(tmp_path))
        p.ensure_dirs()
        assert p.manuscripts_dir.exists()
        assert p.scene_cards_dir.exists()
        assert p.export_dir.exists()
        assert p.story_state_db.parent.exists()
        assert p.chapter_memory_dir.exists()
        assert p.sessions_dir.exists()

    def test_two_projects_isolated(self, tmp_path):
        p1 = ProjectPaths("project-a", base_dir=str(tmp_path))
        p2 = ProjectPaths("project-b", base_dir=str(tmp_path))
        assert p1.manuscripts_dir != p2.manuscripts_dir
        assert p1.story_state_db != p2.story_state_db
        # But shared resources are the same
        assert p1.worldbuilding_db == p2.worldbuilding_db
        assert p1.eval_corpus_dir == p2.eval_corpus_dir

    def test_project_root(self, tmp_path):
        p = ProjectPaths("my-novel", base_dir=str(tmp_path))
        assert p.project_root == tmp_path / "data" / "projects" / "my-novel"
