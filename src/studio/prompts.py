"""Message builders for the studio. Pure functions over a StoryProject.

Every call sends the whole book: the story bible, the outline and every
drafted chapter in full. Nothing is summarised or retrieved. The stable
material comes first so providers with prefix caching can reuse it across
calls; the task comes last, where the model attends to it most reliably.
"""

from __future__ import annotations

from pathlib import Path

from src.studio.project import ChapterPlan, StoryProject, estimate_tokens

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts" / "studio"

POLISH_NOTE = (
    "Give this chapter a light line edit for flow and freshness, guided by the "
    "'On the page' and 'machine-made' sections of the craft guide. Smooth "
    "clumsy sentences, vary rhythm, cut repeated phrases and images, and make "
    "vague description specific. Keep every event, what each line of dialogue "
    "means, and roughly the same length."
)

_DEFAULT_LENGTH = (
    "Write it at the length the chapter needs. Most novel chapters run 2,000 "
    "to 4,000 words; play scenes out in full rather than summarising them."
)


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _system(role_prompt: str) -> dict:
    return {
        "role": "system",
        "content": role_prompt + "\n\n---\n\n" + _prompt("craft_guide"),
    }


def _book_sections(project: StoryProject, chapters: dict[int, str], heading: str) -> list[str]:
    parts = ["# Story bible\n\n" + (project.read_bible().strip() or "(empty)")]
    if project.characters_path.exists():
        parts.append("# Characters\n\n" + (project.read_characters().strip() or "(empty)"))
    parts.append("# Outline\n\n" + (project.read_outline().strip() or "(empty)"))
    if chapters:
        parts.append(f"# {heading}\n\n" + "\n\n".join(t.strip() for t in chapters.values()))
    else:
        parts.append(f"# {heading}\n\n(No chapters written yet.)")
    return parts


def _chapter_label(plan: ChapterPlan) -> str:
    return f"Chapter {plan.number}" + (f": {plan.title}" if plan.title else "")


def draft_messages(
    project: StoryProject,
    plan: ChapterPlan,
    words: int | None = None,
    note: str | None = None,
) -> list[dict]:
    earlier = {n: t for n, t in project.drafted_chapters().items() if n < plan.number}
    task = [
        f"# Task\n\nWrite {_chapter_label(plan)}.",
        "Outline notes for this chapter:\n\n" + (plan.notes or "(none: use the outline as a whole)"),
        f"Aim for roughly {words:,} words." if words else _DEFAULT_LENGTH,
    ]
    if note:
        task.append("Note from the author:\n\n" + note.strip())
    user = _book_sections(project, earlier, "The book so far") + ["\n\n".join(task)]
    return [_system(_prompt("drafter")), {"role": "user", "content": "\n\n".join(user)}]


def revise_messages(project: StoryProject, number: int, note: str) -> list[dict]:
    chapters = project.drafted_chapters()
    current = chapters.pop(number)
    task = (
        f"# Chapter {number} (the chapter to revise)\n\n{current.strip()}\n\n"
        f"# Author's note\n\n{note.strip()}"
    )
    user = _book_sections(
        project, chapters, f"The rest of the book (chapter {number} is shown separately below)"
    ) + [task]
    return [_system(_prompt("reviser")), {"role": "user", "content": "\n\n".join(user)}]


def review_messages(project: StoryProject) -> list[dict]:
    chapters = project.drafted_chapters()
    task = f"# Task\n\nWrite your reader notes on the {len(chapters)} chapter(s) above."
    user = _book_sections(project, chapters, "The book so far") + [task]
    return [_system(_prompt("reviewer")), {"role": "user", "content": "\n\n".join(user)}]


def message_tokens(messages: list[dict]) -> int:
    return estimate_tokens("".join(m["content"] for m in messages))
