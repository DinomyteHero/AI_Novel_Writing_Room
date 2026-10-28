"""Message builders. Pure functions over a Plan and the chapters on disk.

Every call sends the whole book: the series and book plans, any earlier books,
and every relevant chapter in full. Nothing is summarised or retrieved by the
tool itself. Stable material comes first so providers with prefix caching can
reuse it across calls; the task comes last, where models attend most reliably.

The user message also carries its sections as ``parts``, each chapter its own,
with ``cache_upto`` counting the parts that come before the task. Providers
that need explicit cache markers (Anthropic) cache at a part boundary, so the
next chapter's call can reuse everything up to the chapter before it.
"""

from __future__ import annotations

from pathlib import Path

from src.studio.project import ChapterPlan, Plan, estimate_tokens

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "studio"

POLISH_NOTE = (
    "Give this chapter a light line edit for flow and freshness, guided by the "
    "'On the page' and 'machine-made' sections of the craft guide. Smooth "
    "clumsy sentences, vary rhythm, cut repeated phrases and images, and make "
    "vague description specific. Keep every event, what each line of dialogue "
    "means, and roughly the same length."
)

NO_CHANGES = "No changes needed"


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _system(role_prompt: str) -> dict:
    return {
        "role": "system",
        "content": role_prompt + "\n\n---\n\n" + _prompt("craft_guide"),
    }


def _section(heading: str, text: str) -> str:
    return f"# {heading}\n\n" + (text.strip() or "(empty)")


def _plan_sections(plan: Plan) -> list[str]:
    parts = []
    if plan.series_bible.strip():
        parts.append(_section("Series bible", plan.series_bible))
    for name, text in plan.reference:
        parts.append(_section(f"Reference: {name}", text))
    for book in plan.earlier_books:
        kind = "story so far" if book.is_summary else "full text"
        parts.append(_section(f"Earlier book {book.number}: {book.title} ({kind})", book.text))
    parts.append(_section("Story bible", plan.story_bible))
    parts.append(_section("Characters", plan.characters))
    parts.append(_section("Outline", plan.outline))
    return parts


def _chapters_parts(heading: str, chapters: dict[int, str]) -> list[str]:
    if not chapters:
        return [f"# {heading}\n\n(No chapters written yet.)"]
    return [f"# {heading}"] + [text.strip() for text in chapters.values()]


def _chapters_section(heading: str, chapters: dict[int, str]) -> str:
    return "\n\n".join(_chapters_parts(heading, chapters))


def _messages(role: str, parts: list[str]) -> list[dict]:
    """The last part is the task; everything before it is the cacheable book."""
    user = {"role": "user", "content": "\n\n".join(parts), "parts": parts, "cache_upto": len(parts) - 1}
    return [_system(_prompt(role)), user]


def _label(chapter: ChapterPlan) -> str:
    return f"Chapter {chapter.number}" + (f": {chapter.title}" if chapter.title else "")


def _before(chapters: dict[int, str], number: int) -> dict[int, str]:
    return {n: text for n, text in chapters.items() if n < number}


def _notes(chapter: ChapterPlan) -> str:
    return chapter.notes or "(none: use the outline as a whole)"


def draft_messages(
    plan: Plan,
    chapter: ChapterPlan,
    chapters: dict[int, str],
    words: int,
    note: str | None = None,
) -> list[dict]:
    task = [
        f"# Task\n\nWrite {_label(chapter)}.",
        "Outline notes for this chapter:\n\n" + _notes(chapter),
        f"Aim for roughly {words:,} words. Play scenes out in full rather than "
        "summarising them.",
    ]
    if note:
        task.append("Note from the author:\n\n" + note.strip())
    return _messages(
        "drafter",
        _plan_sections(plan)
        + _chapters_parts("The book so far", _before(chapters, chapter.number))
        + ["\n\n".join(task)],
    )


def critique_messages(
    plan: Plan,
    chapter: ChapterPlan,
    chapters: dict[int, str],
    draft: str,
    target_words: int,
) -> list[dict]:
    task = (
        f"# Draft of {_label(chapter)}\n\n{draft.strip()}\n\n"
        f"# Task\n\nCritique this draft. Outline notes for this chapter:\n\n"
        f"{_notes(chapter)}\n\nThe author planned roughly {target_words:,} words."
    )
    return _messages(
        "critic",
        _plan_sections(plan)
        + _chapters_parts("The book so far", _before(chapters, chapter.number))
        + [task],
    )


def revise_messages(
    plan: Plan, chapters: dict[int, str], number: int, current: str, note: str
) -> list[dict]:
    rest = {n: text for n, text in chapters.items() if n != number}
    task = (
        f"# Chapter {number} (the chapter to revise)\n\n{current.strip()}\n\n"
        f"# Revision notes\n\n{note.strip()}"
    )
    return _messages(
        "reviser",
        _plan_sections(plan)
        + _chapters_parts("The rest of the book (the chapter to revise is shown below)", rest)
        + [task],
    )


def review_messages(plan: Plan, chapters: dict[int, str]) -> list[dict]:
    if chapters:
        task = f"# Task\n\nReview the plan and the {len(chapters)} drafted chapter(s) above."
    else:
        task = "# Task\n\nReview the plan above. No chapters have been drafted yet."
    return _messages(
        "reviewer",
        _plan_sections(plan) + _chapters_parts("The book so far", chapters) + [task],
    )


def ideas_messages(plan: Plan, chapters: dict[int, str]) -> list[dict]:
    task = "# Task\n\nOffer ideas where the plan above is thinnest."
    return _messages(
        "ideas",
        _plan_sections(plan) + _chapters_parts("The book so far", chapters) + [task],
    )


def story_so_far_messages(plan: Plan, chapters: dict[int, str]) -> list[dict]:
    task = "# Task\n\nWrite the story-so-far notes for the finished book above."
    return _messages(
        "story_so_far",
        _plan_sections(plan) + _chapters_parts("The finished book", chapters) + [task],
    )


def fresh_eyes_messages(text: str) -> list[dict]:
    """A reader who has not seen the plan; deliberately no plan or craft guide."""
    return [
        {"role": "system", "content": _prompt("fresh_eyes")},
        {"role": "user", "content": text.strip()},
    ]


def message_tokens(messages: list[dict]) -> int:
    return estimate_tokens("".join(m["content"] for m in messages))


def plan_tokens(plan: Plan) -> int:
    return estimate_tokens("".join(_plan_sections(plan)))
