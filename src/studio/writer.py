"""Studio operations: draft, revise, polish, review and export a book.

Each model operation is one call that sees the whole book. Model choice comes
from ``agent_routing.studio_writer`` / ``agent_routing.studio_reader`` in
``config/settings.yaml``.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.studio import prompts
from src.studio.project import StoryProject

if TYPE_CHECKING:
    from src.model_router import ModelRouter

WRITER_ROLE = "studio_writer"
READER_ROLE = "studio_reader"

# Headroom below the ~1M-token windows of the default models, leaving room
# for the response.
MAX_PROMPT_TOKENS = 900_000

_FENCE = re.compile(r"^```[a-zA-Z]*\n(.*)\n```$", re.DOTALL)


class StudioError(Exception):
    """A problem the writer can fix (missing outline entry, empty response, ...)."""


def _clean(text: str) -> str:
    text = text.strip()
    match = _FENCE.match(text)
    return match.group(1).strip() if match else text


async def _complete(router: "ModelRouter", role: str, messages: list[dict]) -> str:
    size = prompts.message_tokens(messages)
    if size > MAX_PROMPT_TOKENS:
        raise StudioError(
            f"The book is now about {size:,} tokens, more than the {MAX_PROMPT_TOKENS:,} "
            "this tool sends in one call. Split it into volumes or trim the story bible."
        )
    text = _clean(await router.complete(role, messages))
    if not text:
        raise StudioError("The model returned an empty response; nothing was saved.")
    return text


def next_chapter(project: StoryProject) -> int:
    """The first outlined chapter that hasn't been drafted yet."""
    drafted = project.drafted_chapters()
    for number in sorted(project.outline_chapters()):
        if number not in drafted:
            return number
    raise StudioError("Every chapter in the outline has a draft. Add chapters to outline.md.")


async def draft_chapter(
    project: StoryProject,
    router: "ModelRouter",
    number: int,
    *,
    words: int | None = None,
    note: str | None = None,
    force: bool = False,
) -> Path:
    plan = project.outline_chapters().get(number)
    if plan is None:
        raise StudioError(
            f"outline.md has no '## Chapter {number}' section. Add one, then draft it."
        )
    if project.chapter_path(number).exists() and not force:
        raise StudioError(
            f"Chapter {number} already has a draft. Use revise to change it, or "
            "--force to redraft it from scratch (the old version is kept in "
            "chapters/.history/)."
        )
    messages = prompts.draft_messages(project, plan, words=words, note=note)
    return project.write_chapter(number, await _complete(router, WRITER_ROLE, messages))


async def revise_chapter(
    project: StoryProject, router: "ModelRouter", number: int, note: str
) -> Path:
    if number not in project.drafted_chapters():
        raise StudioError(f"Chapter {number} hasn't been drafted yet.")
    if not note.strip():
        raise StudioError("Say what you'd like changed, e.g. --note \"more banter, less brooding\".")
    messages = prompts.revise_messages(project, number, note)
    return project.write_chapter(number, await _complete(router, WRITER_ROLE, messages))


async def polish_chapter(project: StoryProject, router: "ModelRouter", number: int) -> Path:
    return await revise_chapter(project, router, number, prompts.POLISH_NOTE)


async def review_book(project: StoryProject, router: "ModelRouter") -> Path:
    if not project.drafted_chapters():
        raise StudioError("There are no chapters to review yet.")
    text = await _complete(router, READER_ROLE, prompts.review_messages(project))
    project.notes_dir.mkdir(parents=True, exist_ok=True)
    path = project.notes_dir / f"review_{datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def export_book(project: StoryProject) -> Path:
    chapters = project.drafted_chapters()
    if not chapters:
        raise StudioError("There are no chapters to export yet.")
    project.export_path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(text.strip() for text in chapters.values())
    project.export_path.write_text(f"# {project.title}\n\n{body}\n", encoding="utf-8")
    return project.export_path
