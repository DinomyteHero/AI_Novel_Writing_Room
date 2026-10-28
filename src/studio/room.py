"""The room: where the writer plans, reviews and directs changes.

Everything here is something the writer asks for and reacts to. Automated,
unattended work lives in ``press.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.studio import prompts
from src.studio.llm import READER_ROLE, WRITER_ROLE, complete
from src.studio.project import (
    REFERENCE_SUFFIXES,
    Book,
    StudioError,
    count_words,
    estimate_tokens,
    read_text,
    save_with_history,
)

if TYPE_CHECKING:
    from src.model_router import ModelRouter


async def revise_chapter(
    book: Book, router: "ModelRouter", number: int, note: str, source: str = "revise",
    apply: bool = True,
) -> Path | str:
    chapters = book.drafted_chapters()
    if number not in chapters:
        raise StudioError(f"Chapter {number} hasn't been written yet.")
    if not note.strip():
        raise StudioError('Say what you\'d like changed, e.g. --note "more banter, less brooding".')
    plan = book.read_plan()
    messages = prompts.revise_messages(plan, chapters, number, chapters[number], note)
    text = await complete(router, WRITER_ROLE, messages)
    if read_text(book.chapter_path(number)).strip() != chapters[number].strip():
        raise StudioError("This chapter changed while I was revising it. Your edit was kept; ask me to revise it again.")
    if not apply:
        return text
    return book.write_chapter(number, text, plan, source)


async def polish_chapter(book: Book, router: "ModelRouter", number: int) -> Path:
    return await revise_chapter(book, router, number, prompts.POLISH_NOTE, source="polish")


async def review(book: Book, router: "ModelRouter") -> Path:
    """A second model reads the plan and any chapters and writes numbered points."""
    plan = book.read_plan()
    if not (plan.story_bible.strip() or plan.outline.strip()):
        raise StudioError("There's nothing to review yet. Fill in the story bible or outline first.")
    text = await complete(router, READER_ROLE, prompts.review_messages(plan, book.drafted_chapters()))
    return _save_note(book, "review", text)


async def ideas(book: Book, router: "ModelRouter") -> Path:
    """A second model offers options where the plan is thinnest, in the same
    numbered shape as a review, so the writer picks one point at a time."""
    plan = book.read_plan()
    if not (plan.story_bible.strip() or plan.outline.strip()):
        raise StudioError("There's nothing to build on yet. Tell the chat your idea, or fill in the story bible first.")
    text = await complete(router, READER_ROLE, prompts.ideas_messages(plan, book.drafted_chapters()))
    return _save_note(book, "ideas", text)


async def fresh_eyes(book: Book, router: "ModelRouter", number: int) -> Path:
    """A reader with only one chapter: no plan, no earlier chapters, no craft guide."""
    chapters = book.drafted_chapters()
    if number not in chapters:
        raise StudioError(f"Chapter {number} hasn't been written yet.")
    text = await complete(router, READER_ROLE, prompts.fresh_eyes_messages(chapters[number]))
    return _save_note(book, "fresh_eyes", text)


def _save_note(book: Book, kind: str, text: str) -> Path:
    book.notes_dir.mkdir(parents=True, exist_ok=True)
    path = book.notes_dir / f"{kind}_{datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text(text + "\n", encoding="utf-8")
    return path


async def check(router: "ModelRouter") -> tuple[bool, str]:
    return await router.health_check()


@dataclass(frozen=True)
class RenameHit:
    path: Path
    count: int
    examples: tuple[str, ...]


def _name_pattern(name: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")


def rename_scope(book: Book) -> list[Path]:
    """Every file a rename touches: the series' plans and reference notes, every
    book's plan, reference notes, chapters and story-so-far notes. History, runs
    and reviews are left as a record of what was."""
    files = list(book.series.plan_files())
    for folder in (book.series.reference_dir,):
        if folder.is_dir():
            files += [p for p in sorted(folder.iterdir())
                      if p.is_file() and p.suffix.lower() in REFERENCE_SUFFIXES]
    for other in book.series.books():
        files += [p for p in (other.bible_path, other.characters_path, other.outline_path) if p.exists()]
        if other.reference_dir.is_dir():
            files += [p for p in sorted(other.reference_dir.iterdir())
                      if p.is_file() and p.suffix.lower() in REFERENCE_SUFFIXES]
        files += sorted(other.manuscript_dir.glob("chapter_*.md"))
        if other.story_so_far_path.exists():
            files.append(other.story_so_far_path)
    return files


def find_name(book: Book, name: str) -> list[RenameHit]:
    if not name.strip():
        raise StudioError("Give the name to look for.")
    pattern = _name_pattern(name)
    hits = []
    for path in rename_scope(book):
        lines = read_text(path).splitlines()
        matching = [line.strip() for line in lines if pattern.search(line)]
        count = sum(len(pattern.findall(line)) for line in lines)
        if count:
            hits.append(RenameHit(path, count, tuple(m[:120] for m in matching[:2])))
    return hits


def apply_rename(book: Book, old: str, new: str) -> list[RenameHit]:
    """Replace a name everywhere in scope. Chapters that were up to date with
    their plan stay up to date: the rename changed both sides consistently."""
    if not new.strip():
        raise StudioError("Give the new name.")
    hits = find_name(book, old)
    current = {}
    for other in book.series.books():
        plan = other.read_plan()
        current[other.root] = [
            n for n in other.drafted_chapters() if other.chapter_state(n, plan) == "current"
        ]
    pattern = _name_pattern(old)
    for hit in hits:
        text = read_text(hit.path)
        save_with_history(hit.path, pattern.sub(new, text))
    for other in book.series.books():
        plan = other.read_plan()
        for number in current[other.root]:
            other.record(number, plan, source="rename")
    return hits


@dataclass(frozen=True)
class ChapterStatus:
    number: int
    title: str
    words: int
    state: str


@dataclass(frozen=True)
class BookStatus:
    chapters: tuple[ChapterStatus, ...]
    total_words: int
    context_tokens: int
    latest_review: Path | None
    plan_changed_since_review: bool


def status(book: Book) -> BookStatus:
    plan = book.read_plan()
    outlined = plan.chapters()
    drafted = book.drafted_chapters()
    rows = []
    for number in sorted(set(outlined) | set(drafted)):
        title = outlined[number].title if number in outlined else ""
        words = count_words(drafted[number]) if number in drafted else 0
        rows.append(ChapterStatus(number, title, words, book.chapter_state(number, plan)))
    return BookStatus(
        chapters=tuple(rows),
        total_words=sum(row.words for row in rows),
        context_tokens=prompts.plan_tokens(plan)
        + estimate_tokens("".join(drafted.values())),
        latest_review=book.latest_review(),
        plan_changed_since_review=book.plan_changed_since_review(),
    )
