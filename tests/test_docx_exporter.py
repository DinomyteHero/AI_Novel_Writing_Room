"""Tests for the DocxExporter."""

from pathlib import Path

import pytest

# Skip all tests if python-docx is not installed
docx = pytest.importorskip("docx")

from src.export.docx_exporter import DocxExporter


@pytest.fixture
def sample_md():
    """Sample assembled markdown for testing."""
    return (
        "# Beyond the Veil\n\n"
        "*A Star Wars Novel*\n\n"
        "---\n\n"
        "## Table of Contents\n\n"
        "- Chapter 1\n"
        "- Chapter 2\n\n"
        "---\n\n"
        "# Chapter 1\n\n"
        "Ben stared at the holographic star chart.\n\n"
        "The wound regions pulsed like infected wounds.\n\n"
        "* * *\n\n"
        "He turned to the viewport.\n\n"
        "Coruscant's evening traffic wove patterns.\n\n"
        "# Chapter 2\n\n"
        "The ship dropped out of hyperspace.\n\n"
        "Something was wrong.\n"
    )


@pytest.fixture
def seed():
    return {
        "meta": {
            "project_title": "Beyond the Veil",
            "franchise": "Star Wars",
        }
    }


class TestDocxExporter:

    def test_export_creates_file(self, sample_md, seed, temp_dir):
        exporter = DocxExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.docx")
        path = exporter.export(sample_md, output)

        assert path.exists()
        assert path.suffix == ".docx"

    def test_docx_has_title(self, sample_md, seed, temp_dir):
        exporter = DocxExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.docx")
        exporter.export(sample_md, output)

        doc = docx.Document(output)
        # Find title in paragraphs
        texts = [p.text for p in doc.paragraphs]
        assert any("Beyond the Veil" in t for t in texts)

    def test_docx_has_chapter_headings(self, sample_md, seed, temp_dir):
        exporter = DocxExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.docx")
        exporter.export(sample_md, output)

        doc = docx.Document(output)
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
        assert any("Chapter 1" in h for h in headings)
        assert any("Chapter 2" in h for h in headings)

    def test_docx_has_body_paragraphs(self, sample_md, seed, temp_dir):
        exporter = DocxExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.docx")
        exporter.export(sample_md, output)

        doc = docx.Document(output)
        normal_paras = [p.text for p in doc.paragraphs if p.style.name == "Normal" and p.text.strip()]
        assert any("holographic star chart" in t for t in normal_paras)

    def test_docx_has_scene_break(self, sample_md, seed, temp_dir):
        exporter = DocxExporter(concept_seed=seed)
        output = str(Path(temp_dir) / "test.docx")
        exporter.export(sample_md, output)

        doc = docx.Document(output)
        texts = [p.text for p in doc.paragraphs]
        assert any("* * *" in t for t in texts)

    def test_parse_chapters(self, sample_md, seed):
        exporter = DocxExporter(concept_seed=seed)
        chapters = exporter._parse_chapters(sample_md)
        assert len(chapters) == 2
        assert chapters[0]["number"] == 1
        assert chapters[1]["number"] == 2
