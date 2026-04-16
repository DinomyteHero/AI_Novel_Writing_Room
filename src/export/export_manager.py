"""Unified export manager for all manuscript formats."""

import logging
from pathlib import Path

from src.export.markdown_assembler import MarkdownAssembler

logger = logging.getLogger(__name__)


class ExportManager:
    """Orchestrate manuscript export to multiple formats.

    Assembles markdown first, then converts to DOCX and/or EPUB
    as requested. Gracefully handles missing optional libraries.
    """

    SUPPORTED_FORMATS = {"md", "docx", "epub"}

    def __init__(
        self,
        manuscripts_dir: str = "output/_fallback/manuscripts",
        concept_seed: dict = None,
    ):
        self.manuscripts_dir = manuscripts_dir
        self.concept_seed = concept_seed
        self._assembler = MarkdownAssembler(manuscripts_dir, concept_seed)

    def export_all(
        self,
        output_dir: str = "output/_fallback/export",
        formats: list[str] = None,
    ) -> dict:
        """Export manuscript to all requested formats.

        Args:
            output_dir: Directory for output files.
            formats: List of format strings ("md", "docx", "epub").
                     Defaults to all three.

        Returns:
            Dict mapping format name to output Path (or None if unavailable).
        """
        if formats is None:
            formats = ["md", "docx", "epub"]

        results = {}

        # Always assemble markdown first (needed by other exporters)
        manuscript_md = self._assembler.assemble(include_stats=True)

        for fmt in formats:
            if fmt not in self.SUPPORTED_FORMATS:
                logger.warning(f"Unknown export format: {fmt}")
                results[fmt] = None
                continue

            try:
                if fmt == "md":
                    results["md"] = self._export_md(manuscript_md, output_dir)
                elif fmt == "docx":
                    results["docx"] = self._export_docx(manuscript_md, output_dir)
                elif fmt == "epub":
                    results["epub"] = self._export_epub(manuscript_md, output_dir)
            except ImportError as e:
                logger.warning(f"Cannot export {fmt}: {e}")
                results[fmt] = None
            except Exception as e:
                logger.error(f"Error exporting {fmt}: {e}")
                results[fmt] = None

        return results

    def export_markdown(self, output_dir: str = "output/_fallback/export") -> Path:
        """Export manuscript as markdown."""
        manuscript_md = self._assembler.assemble(include_stats=True)
        return self._export_md(manuscript_md, output_dir)

    def export_docx(self, output_dir: str = "output/_fallback/export") -> Path:
        """Export manuscript as DOCX."""
        manuscript_md = self._assembler.assemble(include_stats=True)
        return self._export_docx(manuscript_md, output_dir)

    def export_epub(self, output_dir: str = "output/_fallback/export") -> Path:
        """Export manuscript as EPUB."""
        manuscript_md = self._assembler.assemble(include_stats=True)
        return self._export_epub(manuscript_md, output_dir)

    def _export_md(self, manuscript_md: str, output_dir: str) -> Path:
        """Save assembled markdown to file."""
        output = Path(output_dir) / "manuscript.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(manuscript_md, encoding="utf-8")
        return output

    def _export_docx(self, manuscript_md: str, output_dir: str) -> Path:
        """Convert and save as DOCX."""
        from src.export.docx_exporter import DocxExporter

        exporter = DocxExporter(self.concept_seed)
        output_path = str(Path(output_dir) / "manuscript.docx")
        return exporter.export(manuscript_md, output_path)

    def _export_epub(self, manuscript_md: str, output_dir: str) -> Path:
        """Convert and save as EPUB."""
        from src.export.epub_exporter import EpubExporter

        exporter = EpubExporter(self.concept_seed)
        output_path = str(Path(output_dir) / "manuscript.epub")
        return exporter.export(manuscript_md, output_path)
