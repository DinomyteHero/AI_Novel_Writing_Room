"""The library: series and books as plain Markdown files a writer can open and edit.

    library/                              private by default (gitignored)
      <series>/
        series_bible.md                   shared world and the arc across books (series only)
        reference/                        optional: notes every book reads (canon, research)
        books/
          01-<book>/
            story_bible.md                this book's premise, feel, world and voice
            characters.md                 who everyone is in this book
            outline.md                    one "## Chapter N" section per chapter
            reference/                    optional: notes only this book reads
            manuscript/chapter_NN.md      the current chapters
            manuscript/.history/          every replaced version
            manuscript/.provenance.json   which plan each chapter was built from
            notes/                        reviews
            runs/<run-id>/                what each press build did
            story_so_far.md               optional: what later books need to know
            export/manuscript.md

A standalone book is a series of one: the series bible only appears once a
second book is added, so a single book has just three planning files.
Characters always belong to a book. A new book in a series starts with a copy
of the previous book's characters.md, so nobody is lost between books and
each book can show who its people have become.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "story"

_CHAPTER_HEADING = re.compile(
    r"^#{1,3}[ \t]*chapter[ \t]+(\d+)\b[ \t]*[:.\-–—]?[ \t]*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_WORDS_LINE = re.compile(
    r"^[ \t]*[-*]?[ \t]*\**(?:length|words)\**[ \t]*:\**[ \t]*~?[ \t]*([\d,]+)",
    re.IGNORECASE | re.MULTILINE,
)
_CHAPTER_FILE = re.compile(r"^chapter_(\d+)\.md$")
_BOOK_DIR = re.compile(r"^(\d+)-(.+)$")
REFERENCE_SUFFIXES = (".md", ".txt")


class StudioError(Exception):
    """A problem the writer can fix. The message is shown to them as-is."""


def slugify(name: str) -> str:
    """'Star Wars (Legends EU)' -> 'star-wars-legends-eu'"""
    slug = re.sub(r"[^a-z0-9\s_-]", "", name.lower().strip())
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def count_words(text: str) -> int:
    """Words of prose, ignoring a leading Markdown heading line."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return len(" ".join(lines).split())


def _digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _write_template(name: str, target: Path, title: str) -> Path:
    template = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace("{title}", title), encoding="utf-8")
    return target


def _reference(folder: Path) -> list[tuple[str, str]]:
    if not folder.is_dir():
        return []
    return [
        (path.name, _read(path))
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in REFERENCE_SUFFIXES
    ]


def _heading_title(path: Path) -> str | None:
    first = _read(path).lstrip().splitlines()[:1]
    if first and first[0].startswith("# "):
        return first[0][2:].strip() or None
    return None


@dataclass(frozen=True)
class ChapterPlan:
    number: int
    title: str
    notes: str
    words: int | None


@dataclass(frozen=True)
class EarlierBook:
    number: int
    title: str
    text: str
    is_summary: bool


@dataclass(frozen=True)
class Plan:
    """Everything a model needs to know about the book, read once.

    The press reads a Plan at the start of a build and uses it throughout, so
    edits made in the room mid-build can't leave a book half on one plan and
    half on another.
    """

    series_bible: str
    earlier_books: tuple[EarlierBook, ...]
    story_bible: str
    characters: str
    outline: str
    reference: tuple[tuple[str, str], ...] = ()

    def chapters(self) -> dict[int, ChapterPlan]:
        matches = list(_CHAPTER_HEADING.finditer(self.outline))
        plans: dict[int, ChapterPlan] = {}
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(self.outline)
            notes = self.outline[match.end():end].strip()
            words = _WORDS_LINE.search(notes)
            plans[int(match.group(1))] = ChapterPlan(
                number=int(match.group(1)),
                title=match.group(2).strip(),
                notes=notes,
                words=int(words.group(1).replace(",", "")) if words else None,
            )
        return plans

    def chapter(self, number: int) -> ChapterPlan | None:
        return self.chapters().get(number)

    def background_fingerprint(self) -> str:
        """Everything except the outline: a change here may affect any chapter."""
        return _digest(
            "\n".join(
                [self.series_bible, self.story_bible, self.characters]
                + [f"{name}\n{text}" for name, text in self.reference]
            )
        )

    def outline_fingerprint(self, number: int) -> str | None:
        plan = self.chapter(number)
        return _digest(f"{plan.title}\n{plan.notes}") if plan else None

    def files(self) -> dict[str, str]:
        """The plan as named Markdown files, for run snapshots."""
        files = {
            "story_bible.md": self.story_bible,
            "characters.md": self.characters,
            "outline.md": self.outline,
        }
        if self.series_bible:
            files["series_bible.md"] = self.series_bible
        for name, text in self.reference:
            files[f"reference/{name}"] = text
        return files


class Book:
    def __init__(self, series: "Series", root: Path):
        self.series = series
        self.root = Path(root)
        match = _BOOK_DIR.match(self.root.name)
        if not match:
            raise StudioError(f"'{self.root.name}' isn't a book folder (expected '01-title').")
        self.number = int(match.group(1))
        self.slug = match.group(2)

    @property
    def title(self) -> str:
        return _heading_title(self.bible_path) or self.slug.replace("-", " ").title()

    @property
    def label(self) -> str:
        if len(self.series.books()) > 1:
            return f"{self.series.title}, book {self.number}: {self.title}"
        return self.title

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
    def reference_dir(self) -> Path:
        return self.root / "reference"

    @property
    def manuscript_dir(self) -> Path:
        return self.root / "manuscript"

    @property
    def history_dir(self) -> Path:
        return self.manuscript_dir / ".history"

    @property
    def provenance_path(self) -> Path:
        return self.manuscript_dir / ".provenance.json"

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def story_so_far_path(self) -> Path:
        return self.root / "story_so_far.md"

    @property
    def export_path(self) -> Path:
        return self.root / "export" / "manuscript.md"

    def create(self, title: str, previous: "Book | None" = None) -> list[Path]:
        """Write any missing starter files. Never overwrites.

        With ``previous``, characters.md starts as a copy of that book's sheets.
        """
        self.manuscript_dir.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for name, target in (
            ("story_bible.md", self.bible_path),
            ("characters.md", self.characters_path),
            ("outline.md", self.outline_path),
        ):
            if target.exists():
                continue
            if target == self.characters_path and previous and previous.characters_path.exists():
                text = _read(previous.characters_path)
                heading = f"# Characters: {title}"
                lines = text.splitlines()
                if lines and lines[0].startswith("# "):
                    text = "\n".join([heading] + lines[1:]) + "\n"
                else:
                    text = heading + "\n\n" + text
                target.write_text(text, encoding="utf-8")
                written.append(target)
            else:
                written.append(_write_template(name, target, title))
        return written

    def plan_files(self) -> list[Path]:
        """Every planning file this book's chapters are built from."""
        own = [p for p in (self.bible_path, self.characters_path, self.outline_path) if p.exists()]
        refs = [
            p
            for folder in (self.series.reference_dir, self.reference_dir)
            if folder.is_dir()
            for p in sorted(folder.iterdir())
            if p.is_file() and p.suffix.lower() in REFERENCE_SUFFIXES
        ]
        return self.series.plan_files() + own + refs

    def read_plan(self) -> Plan:
        earlier = []
        for book in self.series.books():
            if book.number >= self.number:
                continue
            if book.story_so_far_path.exists():
                text = _read(book.story_so_far_path)
                earlier.append(EarlierBook(book.number, book.title, text, True))
            elif book.drafted_chapters():
                text = "\n\n".join(t.strip() for t in book.drafted_chapters().values())
                earlier.append(EarlierBook(book.number, book.title, text, False))
        return Plan(
            series_bible=_read(self.series.bible_path),
            earlier_books=tuple(earlier),
            story_bible=_read(self.bible_path),
            characters=_read(self.characters_path),
            outline=_read(self.outline_path),
            reference=tuple(_reference(self.series.reference_dir) + _reference(self.reference_dir)),
        )

    def chapter_path(self, number: int) -> Path:
        return self.manuscript_dir / f"chapter_{number:02d}.md"

    def drafted_chapters(self) -> dict[int, str]:
        if not self.manuscript_dir.exists():
            return {}
        chapters = {}
        for path in self.manuscript_dir.iterdir():
            match = _CHAPTER_FILE.match(path.name)
            if match and path.is_file():
                chapters[int(match.group(1))] = path.read_text(encoding="utf-8")
        return dict(sorted(chapters.items()))

    def _provenance(self) -> dict:
        try:
            return json.loads(_read(self.provenance_path) or "{}")
        except json.JSONDecodeError:
            return {}

    def record(self, number: int, plan: Plan, source: str) -> None:
        data = self._provenance()
        data[str(number)] = {
            "outline": plan.outline_fingerprint(number),
            "background": plan.background_fingerprint(),
            "source": source,
            "saved": datetime.now().isoformat(timespec="seconds"),
        }
        self.manuscript_dir.mkdir(parents=True, exist_ok=True)
        self.provenance_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def write_chapter(self, number: int, text: str, plan: Plan, source: str) -> Path:
        """Save a chapter, moving any existing version into ``.history/`` first."""
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
        self.manuscript_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(text.strip() + "\n", encoding="utf-8")
        self.record(number, plan, source)
        return path

    def chapter_state(self, number: int, plan: Plan) -> str:
        """One of: missing, current, outline changed, plan changed, not in outline.

        A chapter with no provenance (written by hand) counts as current.
        """
        if not self.chapter_path(number).exists():
            return "missing"
        if plan.chapter(number) is None:
            return "not in outline"
        entry = self._provenance().get(str(number))
        if not entry:
            return "current"
        if entry.get("outline") != plan.outline_fingerprint(number):
            return "outline changed"
        if entry.get("background") != plan.background_fingerprint():
            return "plan changed"
        return "current"

    def latest_review(self) -> Path | None:
        reviews = sorted(self.notes_dir.glob("review_*.md")) if self.notes_dir.exists() else []
        return reviews[-1] if reviews else None

    def plan_changed_since_review(self) -> bool:
        review = self.latest_review()
        if review is None:
            return True
        reviewed = review.stat().st_mtime
        return any(path.stat().st_mtime > reviewed for path in self.plan_files())


class Series:
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def title(self) -> str:
        heading = _heading_title(self.bible_path)
        if heading:
            return heading
        books = self.books()
        return books[0].title if len(books) == 1 else self.root.name.replace("-", " ").title()

    @property
    def bible_path(self) -> Path:
        return self.root / "series_bible.md"

    @property
    def reference_dir(self) -> Path:
        return self.root / "reference"

    @property
    def books_dir(self) -> Path:
        return self.root / "books"

    def books(self) -> list[Book]:
        if not self.books_dir.exists():
            return []
        books = [
            Book(self, path)
            for path in self.books_dir.iterdir()
            if path.is_dir() and _BOOK_DIR.match(path.name)
        ]
        return sorted(books, key=lambda b: b.number)

    def plan_files(self) -> list[Path]:
        return [self.bible_path] if self.bible_path.exists() else []

    def add_book(self, title: str, series_title: str | None = None) -> tuple[Book, list[Path]]:
        books = self.books()
        if any(book.slug == slugify(title) for book in books):
            raise StudioError(f"This series already has a book called '{title}'.")
        number = max((b.number for b in books), default=0) + 1
        book = Book(self, self.books_dir / f"{number:02d}-{slugify(title)}")
        written = book.create(title, previous=books[-1] if books else None)
        if (number > 1 or series_title) and not self.bible_path.exists():
            written.append(_write_template("series_bible.md", self.bible_path, series_title or self.title))
        return book, written


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)

    def all_series(self) -> list[Series]:
        if not self.root.exists():
            return []
        return sorted(
            (Series(p) for p in self.root.iterdir() if p.is_dir() and (p / "books").is_dir()),
            key=lambda s: s.root.name,
        )

    def all_books(self) -> list[Book]:
        return [book for series in self.all_series() for book in series.books()]

    def new_book(self, title: str, series_title: str | None = None) -> tuple[Book, list[Path]]:
        if not slugify(title):
            raise StudioError("Give the book a title with at least one letter or number.")
        if series_title is None:
            series = Series(self.root / slugify(title))
            if series.books():
                raise StudioError(
                    f"There's already a book or series called '{title}' in the library. "
                    "To add a book to a series, pass --series."
                )
            return series.add_book(title)
        if not slugify(series_title):
            raise StudioError("Give the series a title with at least one letter or number.")
        return Series(self.root / slugify(series_title)).add_book(title, series_title)

    def find_book(self, title: str | None = None, series: str | None = None) -> Book:
        books = self.all_books()
        if series:
            books = [b for b in books if b.series.root.name == slugify(series)]
        if title:
            books = [b for b in books if b.slug == slugify(title)]
        if len(books) == 1:
            return books[0]
        if not books:
            if not self.all_books():
                raise StudioError('The library is empty. Start a book with: room.py new "Title"')
            raise StudioError(
                f"No book called '{title or series}' in the library. "
                "See every book with: room.py books"
            )
        names = ", ".join(f"'{b.title}' ({b.series.root.name})" for b in books)
        raise StudioError(f"Which book? Pass --title (and --series if needed). Found: {names}")
