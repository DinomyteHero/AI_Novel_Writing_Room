"""Tests for the MarkdownAssembler."""

import os
from pathlib import Path

import pytest

from src.export.markdown_assembler import MarkdownAssembler


@pytest.fixture
def manuscript_dir(temp_dir):
    """Create a temp manuscripts directory with sample chapter files."""
    ms_dir = Path(temp_dir) / "manuscripts"
    ms_dir.mkdir()

    # Write sample chapter files
    (ms_dir / "chapter_01_scene_01.md").write_text(
        "Ben stared at the holographic star chart.\n\nThe wound regions pulsed.",
        encoding="utf-8",
    )
    (ms_dir / "chapter_01_scene_02.md").write_text(
        "He turned to the viewport.\n\nCoruscant's evening traffic wove patterns.",
        encoding="utf-8",
    )
    (ms_dir / "chapter_02_scene_01.md").write_text(
        "The ship dropped out of hyperspace.\n\nSomething was wrong.",
        encoding="utf-8",
    )
    (ms_dir / "chapter_03_scene_01.md").write_text(
        "Darkness surrounded them.\n\nThe Force felt hollow here.",
        encoding="utf-8",
    )

    return str(ms_dir)


@pytest.fixture
def seed():
    """Minimal concept seed for testing."""
    return {
        "meta": {
            "project_title": "Beyond the Veil",
            "franchise": "Star Wars",
            "target_word_count": 75000,
        },
        "premise": {
            "logline": "A crew ventures into Force wounds.",
        },
    }


class TestMarkdownAssembler:

    def test_scan_chapters_finds_files(self, manuscript_dir):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir)
        chapters = assembler._scan_chapters()
        assert len(chapters) == 4

    def test_scan_chapters_sorted(self, manuscript_dir):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir)
        chapters = assembler._scan_chapters()
        numbers = [(ch, sc) for ch, sc, _ in chapters]
        assert numbers == [(1, 1), (1, 2), (2, 1), (3, 1)]

    def test_assemble_produces_markdown(self, manuscript_dir, seed):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir, concept_seed=seed)
        result = assembler.assemble()

        assert "# Beyond the Veil" in result
        assert "# Chapter 1" in result
        assert "# Chapter 2" in result
        assert "# Chapter 3" in result
        assert "* * *" in result  # scene break between ch1 scenes

    def test_assemble_contains_front_matter(self, manuscript_dir, seed):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir, concept_seed=seed)
        result = assembler.assemble()

        assert "Star Wars" in result
        assert "A crew ventures into Force wounds." in result

    def test_assemble_contains_toc(self, manuscript_dir, seed):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir, concept_seed=seed)
        result = assembler.assemble()

        assert "Table of Contents" in result
        assert "Chapter 1" in result
        assert "Chapter 2" in result

    def test_assemble_contains_colophon(self, manuscript_dir, seed):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir, concept_seed=seed)
        result = assembler.assemble(include_stats=True)

        assert "Manuscript Statistics" in result
        assert "Total word count" in result
        assert "Generation date" in result

    def test_assemble_no_stats(self, manuscript_dir, seed):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir, concept_seed=seed)
        result = assembler.assemble(include_stats=False)

        assert "Manuscript Statistics" not in result

    def test_assemble_empty_dir(self, temp_dir):
        empty_dir = Path(temp_dir) / "empty"
        empty_dir.mkdir()
        assembler = MarkdownAssembler(manuscripts_dir=str(empty_dir))
        result = assembler.assemble()

        assert "No chapters found" in result

    def test_save_writes_file(self, manuscript_dir, seed, temp_dir):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir, concept_seed=seed)
        output_path = str(Path(temp_dir) / "export" / "test.md")
        path = assembler.save(output_path=output_path)

        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "# Beyond the Veil" in content

    def test_per_chapter_word_counts(self, manuscript_dir, seed):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir, concept_seed=seed)
        result = assembler.assemble(include_stats=True)

        assert "Per-chapter word counts" in result
        assert "Chapter 1:" in result
        assert "Chapter 2:" in result

    def test_scene_break_between_scenes(self, manuscript_dir, seed):
        assembler = MarkdownAssembler(manuscripts_dir=manuscript_dir, concept_seed=seed)
        result = assembler.assemble()

        # Chapter 1 has 2 scenes — should have a scene break
        ch1_start = result.index("# Chapter 1")
        ch2_start = result.index("# Chapter 2")
        ch1_content = result[ch1_start:ch2_start]
        assert "* * *" in ch1_content
