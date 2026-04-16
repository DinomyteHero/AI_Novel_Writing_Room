"""Assemble generated chapter files into a single markdown manuscript."""

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


class MarkdownAssembler:
    """Assembles chapter markdown files into a single manuscript.

    Scans the manuscripts directory for chapter files, sorts them,
    and produces a unified markdown document with front matter,
    table of contents, and statistics colophon.
    """

    CHAPTER_PATTERN = re.compile(r"chapter_(\d+)_scene_(\d+)\.md")

    def __init__(
        self,
        manuscripts_dir: str = "output/_fallback/manuscripts",
        concept_seed: dict = None,
    ):
        self.manuscripts_dir = Path(manuscripts_dir)
        self.concept_seed = concept_seed or {}

    def _scan_chapters(self) -> list[tuple[int, int, Path]]:
        """Find and sort all chapter files by (chapter, scene) number."""
        results = []
        if not self.manuscripts_dir.exists():
            return results

        for path in self.manuscripts_dir.iterdir():
            match = self.CHAPTER_PATTERN.match(path.name)
            if match:
                chapter_num = int(match.group(1))
                scene_num = int(match.group(2))
                results.append((chapter_num, scene_num, path))

        results.sort(key=lambda x: (x[0], x[1]))
        return results

    def _generate_front_matter(self) -> str:
        """Generate manuscript front matter from concept seed."""
        meta = self.concept_seed.get("meta", {})
        title = meta.get("project_title", "Untitled Manuscript")
        franchise = meta.get("franchise", "")
        premise = self.concept_seed.get("premise", {})
        logline = premise.get("logline", "")

        parts = [f"# {title}"]

        if franchise:
            parts.append(f"\n*A {franchise} Novel*")

        if logline:
            parts.append(f"\n> {logline}")

        parts.append("\n---\n")
        return "\n".join(parts)

    def _generate_toc(self, chapter_groups: dict[int, list]) -> str:
        """Generate a table of contents from chapter groups."""
        if not chapter_groups:
            return ""

        lines = ["## Table of Contents\n"]
        for chapter_num in sorted(chapter_groups.keys()):
            lines.append(f"- Chapter {chapter_num}")
        lines.append("\n---\n")
        return "\n".join(lines)

    def _generate_colophon(self, manuscript_text: str) -> str:
        """Generate statistics colophon for the manuscript."""
        total_words = len(manuscript_text.split())
        generation_date = datetime.now().strftime("%Y-%m-%d")

        lines = [
            "\n---\n",
            "## Manuscript Statistics\n",
            f"- **Total word count:** {total_words:,}",
            f"- **Generation date:** {generation_date}",
        ]

        meta = self.concept_seed.get("meta", {})
        if meta.get("target_word_count"):
            target = meta["target_word_count"]
            lines.append(f"- **Target word count:** {target:,}")

        lines.append("")
        return "\n".join(lines)

    def assemble(self, include_stats: bool = True) -> str:
        """Assemble all chapters into a single markdown manuscript.

        Returns the complete manuscript as a string.
        """
        chapters = self._scan_chapters()
        if not chapters:
            front_matter = self._generate_front_matter()
            return front_matter + "\n*No chapters found.*\n"

        # Group scenes by chapter
        chapter_groups: dict[int, list[tuple[int, Path]]] = defaultdict(list)
        for chapter_num, scene_num, path in chapters:
            chapter_groups[chapter_num].append((scene_num, path))

        # Build manuscript
        parts = [self._generate_front_matter()]
        parts.append(self._generate_toc(chapter_groups))

        chapter_word_counts = {}
        for chapter_num in sorted(chapter_groups.keys()):
            scenes = sorted(chapter_groups[chapter_num], key=lambda x: x[0])

            parts.append(f"# Chapter {chapter_num}\n")

            scene_texts = []
            chapter_words = 0
            for scene_num, path in scenes:
                text = path.read_text(encoding="utf-8").strip()
                scene_texts.append(text)
                chapter_words += len(text.split())

            chapter_word_counts[chapter_num] = chapter_words
            parts.append("\n\n* * *\n\n".join(scene_texts))
            parts.append("\n")

        body = "\n".join(parts)

        if include_stats:
            colophon = self._generate_colophon(body)
            # Add per-chapter word counts
            chapter_lines = []
            for ch, wc in sorted(chapter_word_counts.items()):
                chapter_lines.append(f"  - Chapter {ch}: {wc:,} words")
            if chapter_lines:
                colophon += "- **Per-chapter word counts:**\n" + "\n".join(chapter_lines) + "\n"
            body += colophon

        return body

    def save(
        self,
        output_path: str = "output/_fallback/export/manuscript.md",
        include_stats: bool = True,
    ) -> Path:
        """Assemble and save the manuscript to a file."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        manuscript = self.assemble(include_stats=include_stats)
        output.write_text(manuscript, encoding="utf-8")
        return output
