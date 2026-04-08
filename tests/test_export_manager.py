"""Tests for the ExportManager."""

from pathlib import Path

import pytest

from src.export.export_manager import ExportManager


@pytest.fixture
def manuscript_dir(temp_dir):
    """Create a temp manuscripts directory with sample chapter files."""
    ms_dir = Path(temp_dir) / "manuscripts"
    ms_dir.mkdir()

    (ms_dir / "chapter_01_scene_01.md").write_text(
        "Ben stared at the star chart.\n\nThe wound regions pulsed.",
        encoding="utf-8",
    )
    (ms_dir / "chapter_02_scene_01.md").write_text(
        "The ship dropped out of hyperspace.\n\nSomething was wrong.",
        encoding="utf-8",
    )

    return str(ms_dir)


@pytest.fixture
def seed():
    return {
        "meta": {
            "project_title": "Beyond the Veil",
            "franchise": "Star Wars",
        },
    }


class TestExportManager:

    def test_export_markdown_only(self, manuscript_dir, seed, temp_dir):
        mgr = ExportManager(manuscripts_dir=manuscript_dir, concept_seed=seed)
        output_dir = str(Path(temp_dir) / "export")
        results = mgr.export_all(output_dir=output_dir, formats=["md"])

        assert "md" in results
        assert results["md"] is not None
        assert results["md"].exists()

    def test_export_all_returns_dict(self, manuscript_dir, seed, temp_dir):
        mgr = ExportManager(manuscripts_dir=manuscript_dir, concept_seed=seed)
        output_dir = str(Path(temp_dir) / "export")
        results = mgr.export_all(output_dir=output_dir, formats=["md"])

        assert isinstance(results, dict)

    def test_export_markdown_content(self, manuscript_dir, seed, temp_dir):
        mgr = ExportManager(manuscripts_dir=manuscript_dir, concept_seed=seed)
        output_dir = str(Path(temp_dir) / "export")
        results = mgr.export_all(output_dir=output_dir, formats=["md"])

        content = results["md"].read_text(encoding="utf-8")
        assert "Beyond the Veil" in content
        assert "Chapter 1" in content

    def test_export_unknown_format(self, manuscript_dir, seed, temp_dir):
        mgr = ExportManager(manuscripts_dir=manuscript_dir, concept_seed=seed)
        output_dir = str(Path(temp_dir) / "export")
        results = mgr.export_all(output_dir=output_dir, formats=["xyz"])

        assert results["xyz"] is None

    def test_export_markdown_method(self, manuscript_dir, seed, temp_dir):
        mgr = ExportManager(manuscripts_dir=manuscript_dir, concept_seed=seed)
        output_dir = str(Path(temp_dir) / "export")
        path = mgr.export_markdown(output_dir=output_dir)

        assert path.exists()
        assert path.suffix == ".md"
