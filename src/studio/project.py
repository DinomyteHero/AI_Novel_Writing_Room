"""A studio book: plain Markdown files a writer can open and edit directly.

An original book lives at ``data/projects/<title-slug>/story/``; a fanfiction
book at ``data/franchises/<franchise-slug>/books/<title-slug>/story/``::

    story_bible.md          the author's notes on premise, feel, world, voice
    characters.md           one ``## Name`` sheet per character, plus minor characters
    outline.md              loose per-chapter plan, one ``## Chapter N`` section each
    chapters/chapter_NN.md  drafted chapters
    chapters/.history/      earlier versions, kept whenever a chapter is replaced
    notes/                  reader reviews
    export/manuscript.md    the stitched book
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "story"

_CHAPTER_HEADING = re.compile(
    r"^#{1,3}[ \t]*chapter[ \t]+(\d+)\b[ \t]*[:.\-–—]?[ \t]*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_CHAPTER_FILE = re.compile(r"^chapter_(\d+)\.md$")


@dataclass(frozen=True)
class ChapterPlan:
    number: int
    title: str
    notes: str


def slugify(name: str) -> str:
    """'Star Wars (Legends EU)' -> 'star-wars-legends-eu'"""
    slug = re.sub(r"[^a-z0-9\s_-]", "", name.lower().strip())
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def book_root(title: str, franchise: str | None = None, base_dir: str = ".") -> Path:
    base = Path(base_dir) / "data"
    if franchise:
        return base / "franchises" / slugify(franchise) / "books" / slugify(title) / "story"
    return base / "projects" / slugify(title) / "story"


def estimate_tokens(text: str) -> int:
    return len(text) // 4


class StoryProject:
    def __init__(self, root: Path, title: str | None = None):
        self.root = Path(root)
        self.title = title or self.root.parent.name

    @classmethod
    def for_book(
        cls, title: str, franchise: str | None = None, base_dir: str = "."
    ) -> "StoryProject":
        return cls(book_root(title, franchise, base_dir), title=title)

    @property
    def bible_path(self) -> Path:
        return self.root / "story_bible.md"

    @property
    def characters_path(self) -> Path:
        return self.root / "characters.md"

    @property
    def outline_path(self) -> Path:
        return self.root / "outline.md"

    @property
    def chapters_dir(self) -> Path:
        return self.root / "chapters"

    @property
    def history_dir(self) -> Path:
        return self.chapters_dir / ".history"

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def export_path(self) -> Path:
        return self.root / "export" / "manuscript.md"

    def exists(self) -> bool:
        return self.bible_path.exists()

    def create(self) -> list[Path]:
        """Write starter files that don't exist yet. Returns the files written."""
        self.chapters_dir.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for name, target in (
            ("story_bible.md", self.bible_path),
            ("characters.md", self.characters_path),
            ("outline.md", self.outline_path),
        ):
            if target.exists():
                continue
            template = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
            target.write_text(template.replace("{title}", self.title), encoding="utf-8")
            written.append(target)
        return written

    def read_bible(self) -> str:
        return self.bible_path.read_text(encoding="utf-8") if self.bible_path.exists() else ""

    def read_characters(self) -> str:
        if not self.characters_path.exists():
            return ""
        return self.characters_path.read_text(encoding="utf-8")

    def read_outline(self) -> str:
        return self.outline_path.read_text(encoding="utf-8") if self.outline_path.exists() else ""

    def outline_chapters(self) -> dict[int, ChapterPlan]:
        text = self.read_outline()
        matches = list(_CHAPTER_HEADING.finditer(text))
        plans: dict[int, ChapterPlan] = {}
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            number = int(match.group(1))
            plans[number] = ChapterPlan(
                number=number,
                title=match.group(2).strip(),
                notes=text[match.end():end].strip(),
            )
        return plans

    def chapter_path(self, number: int) -> Path:
        return self.chapters_dir / f"chapter_{number:02d}.md"

    def drafted_chapters(self) -> dict[int, str]:
        if not self.chapters_dir.exists():
            return {}
        chapters = {}
        for path in self.chapters_dir.iterdir():
            match = _CHAPTER_FILE.match(path.name)
            if match and path.is_file():
                chapters[int(match.group(1))] = path.read_text(encoding="utf-8")
        return dict(sorted(chapters.items()))

    def write_chapter(self, number: int, text: str) -> Path:
        """Save a chapter, moving any existing version into ``.history/``."""
        path = self.chapter_path(number)
        if path.exists():
            self.history_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self.history_dir / f"{path.stem}.{stamp}.md"
            suffix = 2
            while target.exists():
                target = self.history_dir / f"{path.stem}.{stamp}-{suffix}.md"
                suffix += 1
            path.replace(target)
        self.chapters_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(text.strip() + "\n", encoding="utf-8")
        return path

    def total_tokens(self) -> int:
        return estimate_tokens(
            self.read_bible()
            + self.read_characters()
            + self.read_outline()
            + "".join(self.drafted_chapters().values())
        )
