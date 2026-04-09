"""Tests for the EpubExporter."""

import zipfile
from pathlib import Path

import pytest

# Skip all tests if ebooklib is not installed
epub_lib = pytest.importorskip("ebooklib")

from src.export.epub_exporter import EpubExporter


@pytest.fixture
def sample_md():
    """Sample assembled markdown for testing."""
    return (
        "# Test Story\n\n"
        "---\n\n"
        "# Chapter 1\n\n"
        "Ben stared at the holographic star chart.\n\n"
        "The wound regions pulsed.\n\n"
        "# Chapter 2\n\n"
        "The ship dropped out of hyperspace.\n\n"
        "Something was wrong.\n"
    )


@pytest.fixture
def seed():
    return {
        "meta": {
            "project_title": "Test Story",
            "franchise": "Star Wars",
        },
        "premise": {
            "logline": "A crew ventures into Force wounds.",
        },
    }


class TestEpubExporter:

    def test_export_creates_file(self, sample_md, seed, temp_dir):
        exporter = EpubExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.epub")
        path = exporter.export(sample_md, output)

        assert path.exists()
        assert path.suffix == ".epub"

    def test_epub_is_valid_zip(self, sample_md, seed, temp_dir):
        exporter = EpubExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.epub")
        exporter.export(sample_md, output)

        # EPUB files are ZIP archives
        assert zipfile.is_zipfile(output)

    def test_epub_has_chapters(self, sample_md, seed, temp_dir):
        exporter = EpubExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.epub")
        exporter.export(sample_md, output)

        from ebooklib import epub as epub_mod
        book = epub_mod.read_epub(output)
        items = list(book.get_items_of_type(epub_lib.ITEM_DOCUMENT))
        # Should have at least 2 chapter items (plus nav)
        chapter_items = [i for i in items if "chapter_" in i.file_name]
        assert len(chapter_items) == 2

    def test_epub_chapter_content(self, sample_md, seed, temp_dir):
        exporter = EpubExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.epub")
        exporter.export(sample_md, output)

        from ebooklib import epub as epub_mod
        book = epub_mod.read_epub(output)
        items = list(book.get_items_of_type(epub_lib.ITEM_DOCUMENT))
        chapter_items = [i for i in items if "chapter_" in i.file_name]
        content = chapter_items[0].get_content().decode("utf-8")
        assert "holographic star chart" in content

    def test_epub_has_metadata(self, sample_md, seed, temp_dir):
        exporter = EpubExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.epub")
        exporter.export(sample_md, output)

        from ebooklib import epub as epub_mod
        book = epub_mod.read_epub(output)
        title = book.get_metadata("DC", "title")
        assert title
        assert title[0][0] == "Test Story"

    def test_parse_chapters(self, sample_md, seed):
        exporter = EpubExporter(concept_seed=seed)
        chapters = exporter._parse_chapters(sample_md)
        assert len(chapters) == 2
        assert chapters[0]["number"] == 1
        assert chapters[1]["number"] == 2
