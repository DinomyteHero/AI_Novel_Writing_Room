"""Export assembled markdown manuscript to EPUB 3.0 format."""

import re
import uuid
from pathlib import Path

try:
    from ebooklib import epub

    HAS_EPUB = True
except ImportError:
    HAS_EPUB = False


class EpubExporter:
    """Convert a markdown manuscript string to a valid EPUB ebook.

    Creates an EPUB 3.0 file with one XHTML file per chapter,
    embedded CSS for typography, and proper metadata.
    """

    def __init__(self, concept_seed: dict = None):
        self.concept_seed = concept_seed or {}

    def export(
        self,
        manuscript_md: str,
        output_path: str = "data/export/manuscript.epub",
    ) -> Path:
        """Convert markdown manuscript to EPUB.

        Args:
            manuscript_md: The assembled markdown manuscript string.
            output_path: Where to save the EPUB file.

        Returns:
            Path to the created file.
        """
        if not HAS_EPUB:
            raise ImportError(
                "ebooklib is required for EPUB export. "
                "Install with: pip install ebooklib>=0.18"
            )

        book = epub.EpubBook()
        self._set_metadata(book)

        # Parse chapters from markdown
        chapters_data = self._parse_chapters(manuscript_md)

        # Create stylesheet
        css = epub.EpubItem(
            uid="style",
            file_name="style/default.css",
            media_type="text/css",
            content=self._get_stylesheet().encode("utf-8"),
        )
        book.add_item(css)

        # Create chapter XHTML items
        epub_chapters = []
        for ch_data in chapters_data:
            chapter = self._create_chapter_html(
                ch_data["number"], ch_data["content"]
            )
            chapter.add_item(css)
            book.add_item(chapter)
            epub_chapters.append(chapter)

        # Table of contents
        book.toc = [
            epub.Link(ch.file_name, ch.title, ch.file_name.replace("/", "_"))
            for ch in epub_chapters
        ]

        # Spine and navigation
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav"] + epub_chapters

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        epub.write_epub(str(output), book, {})
        return output

    def _set_metadata(self, book: "epub.EpubBook") -> None:
        """Set EPUB metadata from concept seed."""
        meta = self.concept_seed.get("meta", {})
        title = meta.get("project_title", "Untitled Manuscript")
        premise = self.concept_seed.get("premise", {})
        logline = premise.get("logline", "")

        book.set_identifier(str(uuid.uuid4()))
        book.set_title(title)
        book.set_language("en")
        book.add_author("AI Writers' Room")

        if logline:
            book.add_metadata("DC", "description", logline)

    def _parse_chapters(self, manuscript_md: str) -> list[dict]:
        """Parse markdown into chapter blocks."""
        chapters = []
        parts = re.split(r"^# Chapter (\d+)\s*$", manuscript_md, flags=re.MULTILINE)

        for i in range(1, len(parts) - 1, 2):
            chapter_num = int(parts[i])
            content = parts[i + 1].strip()
            chapters.append({"number": chapter_num, "content": content})

        return chapters

    def _create_chapter_html(
        self, chapter_num: int, content: str
    ) -> "epub.EpubHtml":
        """Create an XHTML chapter item from markdown content."""
        # Convert markdown paragraphs to HTML
        html_parts = [f"<h1>Chapter {chapter_num}</h1>"]

        scenes = re.split(r"\n\s*\*\s*\*\s*\*\s*\n", content)
        for scene_idx, scene_text in enumerate(scenes):
            if scene_idx > 0:
                html_parts.append('<div class="scene-break">* * *</div>')

            paragraphs = [
                p.strip()
                for p in scene_text.strip().split("\n\n")
                if p.strip()
            ]
            for p_idx, para_text in enumerate(paragraphs):
                if para_text.startswith("#") or para_text == "---":
                    continue
                # Escape HTML entities
                safe_text = (
                    para_text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                css_class = "first-paragraph" if p_idx == 0 else "body-text"
                html_parts.append(f'<p class="{css_class}">{safe_text}</p>')

        html_body = "\n".join(html_parts)

        chapter = epub.EpubHtml(
            title=f"Chapter {chapter_num}",
            file_name=f"chapter_{chapter_num:02d}.xhtml",
            lang="en",
        )
        chapter.content = (
            f'<html xmlns="http://www.w3.org/1999/xhtml">'
            f"<head><title>Chapter {chapter_num}</title></head>"
            f"<body>{html_body}</body></html>"
        ).encode("utf-8")

        return chapter

    def _get_stylesheet(self) -> str:
        """Return the embedded CSS for EPUB typography."""
        return """
body {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1em;
    line-height: 1.6;
    margin: 1em;
}

h1 {
    text-align: center;
    font-size: 1.5em;
    margin-top: 2em;
    margin-bottom: 1.5em;
    page-break-before: always;
}

p.first-paragraph {
    text-indent: 0;
    margin-top: 0.5em;
    margin-bottom: 0.3em;
}

p.body-text {
    text-indent: 1.5em;
    margin-top: 0;
    margin-bottom: 0.3em;
}

.scene-break {
    text-align: center;
    margin: 1.5em 0;
    font-size: 1em;
}
"""
