"""The press: turns a finished plan into chapters without the writer present.

For each chapter, in order:

    draft (writer model)
      -> critique (critic model) -> revise (writer model)   x revision_rounds
      -> save to manuscript/

A revision that comes back much shorter than the text it revised is
discarded. Each build gets a run folder holding a snapshot of the plan, every
draft, critique and revision, and a report, so the writer can see exactly what
the automatic revision changed and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.studio import prompts
from src.studio.llm import CRITIC_ROLE, LONG_PROMPT_TOKENS, NOTES_ROLE, WRITER_ROLE, Usage, complete
from src.studio.project import Book, ChapterPlan, Plan, StudioError, count_words

if TYPE_CHECKING:
    from src.model_router import ModelRouter

TOKENS_PER_WORD = 1.33
_CRITIQUE_TOKENS = 800
_SYSTEM_TOKENS = 2_500


@dataclass(frozen=True)
class PressSettings:
    revision_rounds: int = 1
    default_chapter_words: int = 3000
    length_calibration: float = 1.0
    min_revision_ratio: float = 0.6

    @classmethod
    def from_config(cls, config: dict) -> "PressSettings":
        press = config.get("press") or {}
        defaults = cls()
        return cls(
            revision_rounds=int(press.get("revision_rounds", defaults.revision_rounds)),
            default_chapter_words=int(
                press.get("default_chapter_words", defaults.default_chapter_words)
            ),
            length_calibration=float(
                press.get("length_calibration", defaults.length_calibration)
            ),
            min_revision_ratio=float(
                press.get("min_revision_ratio", defaults.min_revision_ratio)
            ),
        )

    def target_words(self, chapter: ChapterPlan) -> int:
        return chapter.words or self.default_chapter_words

    def asked_words(self, chapter: ChapterPlan) -> int:
        return round(self.target_words(chapter) * self.length_calibration)


def select_chapters(book: Book, plan: Plan, which: str) -> list[int]:
    """'next', 'all', or a chapter number."""
    outlined = sorted(plan.chapters())
    if not outlined:
        raise StudioError("The outline has no '## Chapter N' sections yet, so there's nothing to build.")
    missing = [n for n in outlined if book.chapter_state(n, plan) == "missing"]
    chapters = plan.chapters()

    def unplanned(number: int) -> StudioError:
        return StudioError(
            f"Chapter {number} has no notes in the outline yet, so there's nothing to build it "
            "from. Say what happens in it (a line is enough), in the chat or in outline.md, "
            "then build."
        )

    if which == "next":
        if not missing:
            raise StudioError("Every chapter in the outline is written. Add chapters, or rebuild one by number.")
        if chapters[missing[0]].blank:
            raise unplanned(missing[0])
        return missing[:1]
    if which == "all":
        if not missing:
            raise StudioError("Every chapter in the outline is written. Rebuild one by number if you want.")
        # Chapters build in order, so stop before the first one with no notes.
        ready = []
        for n in missing:
            if chapters[n].blank:
                break
            ready.append(n)
        if not ready:
            raise unplanned(missing[0])
        return ready
    try:
        number = int(which)
    except ValueError:
        raise StudioError(f"'{which}' isn't 'next', 'all' or a chapter number.") from None
    if number not in outlined:
        raise StudioError(f"outline.md has no '## Chapter {number}' section.")
    if chapters[number].blank:
        raise unplanned(number)
    return [number]


@dataclass(frozen=True)
class Estimate:
    calls: int
    input_tokens: int
    output_tokens: int
    largest_call: int = 0
    # The critic's share of the tokens above; the writer has the rest.
    critic_input_tokens: int = 0
    critic_output_tokens: int = 0

    def describe(self) -> str:
        text = (
            f"about {self.calls} model call(s), roughly {self.input_tokens:,} tokens in "
            f"and {self.output_tokens:,} out"
        )
        if self.largest_call > LONG_PROMPT_TOKENS:
            text += (
                f". The largest call sends about {self.largest_call:,} tokens; models read "
                "prompts that long less reliably, so if earlier books are finished, "
                "story-so-far notes for them would help"
            )
        return text


def estimate(book: Book, plan: Plan, numbers: list[int], settings: PressSettings) -> Estimate:
    """A rough upper-bound guess, from the plan size and planned chapter lengths."""
    base = prompts.plan_tokens(plan) + _SYSTEM_TOKENS
    existing = {n: count_words(t) * TOKENS_PER_WORD for n, t in book.drafted_chapters().items()}
    chapters = plan.chapters()
    calls = input_tokens = output_tokens = largest = critic_input = critic_output = 0
    for number in numbers:
        before = sum(t for n, t in existing.items() if n < number)
        draft = settings.asked_words(chapters[number]) * TOKENS_PER_WORD
        largest = max(largest, base + before + (draft + _CRITIQUE_TOKENS if settings.revision_rounds else 0))
        calls += 1 + 2 * settings.revision_rounds
        input_tokens += base + before
        output_tokens += draft
        for _ in range(settings.revision_rounds):
            input_tokens += (base + before + draft) + (base + before + draft + _CRITIQUE_TOKENS)
            output_tokens += _CRITIQUE_TOKENS + draft
            critic_input += base + before + draft
            critic_output += _CRITIQUE_TOKENS
        existing[number] = draft
    return Estimate(calls, int(input_tokens), int(output_tokens), int(largest), int(critic_input), int(critic_output))


@dataclass
class ChapterResult:
    number: int
    title: str
    target_words: int
    draft_words: int
    final_words: int = 0
    revisions_kept: int = 0
    notes: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class BuildResult:
    run_dir: Path
    chapters: list[ChapterResult]
    usage: Usage
    outline_changed: list[int]
    plan_changed: list[int]
    report_path: Path


def _declined(draft: str, target: int) -> bool:
    """A short reply that isn't a chapter: a refusal or a question back. The
    drafter always starts a chapter with its heading."""
    return not draft.lstrip().startswith("#") and count_words(draft) < 0.3 * target


def _is_no_changes(critique: str) -> bool:
    return critique.strip().strip("*#_ ").lower().startswith(prompts.NO_CHANGES.lower())


async def _build_chapter(
    book: Book,
    router: "ModelRouter",
    plan: Plan,
    chapter: ChapterPlan,
    settings: PressSettings,
    run_dir: Path,
    on_step: Callable[[int, str], None] | None = None,
) -> ChapterResult:
    step = on_step or (lambda number, name: None)
    start = len(router.usage_log)
    folder = run_dir / f"chapter_{chapter.number:02d}"
    folder.mkdir(parents=True)
    chapters = book.drafted_chapters()
    target = settings.target_words(chapter)

    step(chapter.number, "drafting")
    text = await complete(
        router,
        WRITER_ROLE,
        prompts.draft_messages(plan, chapter, chapters, settings.asked_words(chapter)),
    )
    (folder / "draft.md").write_text(text + "\n", encoding="utf-8")
    if _declined(text, target):
        raise StudioError(
            f"Chapter {chapter.number} came back as {count_words(text):,} words with no chapter "
            "heading, which usually means the model declined or answered something else. "
            f"Nothing was saved; its reply is in runs/{run_dir.name}/chapter_{chapter.number:02d}/draft.md. "
            "Read it, adjust the outline notes if it explains why, or choose another writer model "
            "in Settings, then build again."
        )
    result = ChapterResult(chapter.number, chapter.title, target, count_words(text))

    for round_number in range(1, settings.revision_rounds + 1):
        step(chapter.number, "critiquing")
        critique = await complete(
            router, CRITIC_ROLE, prompts.critique_messages(plan, chapter, chapters, text, target)
        )
        (folder / f"critique_{round_number}.md").write_text(critique + "\n", encoding="utf-8")
        if _is_no_changes(critique):
            result.notes.append(f"Round {round_number}: the critic asked for no changes.")
            break
        step(chapter.number, "revising")
        revised = await complete(
            router,
            WRITER_ROLE,
            prompts.revise_messages(plan, chapters, chapter.number, text, critique),
        )
        (folder / f"revision_{round_number}.md").write_text(revised + "\n", encoding="utf-8")
        ratio = count_words(revised) / max(count_words(text), 1)
        if ratio < settings.min_revision_ratio:
            result.notes.append(
                f"Round {round_number}: the revision came back at {ratio:.0%} of the "
                "length it revised, so it was discarded and the earlier text kept."
            )
            break
        text = revised
        result.revisions_kept += 1

    book.write_chapter(chapter.number, text, plan, source="build")
    result.final_words = count_words(text)
    if result.final_words < 0.75 * target:
        result.notes.append(
            f"Came in at {result.final_words:,} of the planned {target:,} words. If this "
            "keeps happening, raise press.length_calibration in config/settings.yaml."
        )
    result.usage = Usage.since(router, start)
    return result


def _write_report(book: Book, result: BuildResult, settings: PressSettings) -> None:
    lines = [
        f"# Build report: {book.label}",
        "",
        f"Run folder: `{result.run_dir.name}`. Revision rounds per chapter: "
        f"{settings.revision_rounds}. Length calibration: {settings.length_calibration}.",
        "",
        "| Chapter | Planned words | Draft words | Final words | Revisions kept | Usage |",
        "|---|---|---|---|---|---|",
    ]
    for ch in result.chapters:
        title = f"{ch.number}" + (f": {ch.title}" if ch.title else "")
        lines.append(
            f"| {title} | {ch.target_words:,} | {ch.draft_words:,} | {ch.final_words:,} | "
            f"{ch.revisions_kept} | {ch.usage.describe()} |"
        )
    notes = [f"- Chapter {ch.number}: {note}" for ch in result.chapters for note in ch.notes]
    if notes:
        lines += ["", "## Notes", "", *notes]
    if result.outline_changed:
        listed = ", ".join(str(n) for n in result.outline_changed)
        lines += [
            "",
            "## Out of date",
            "",
            f"The outline for chapter(s) {listed} changed after they were built. Rebuild, "
            "revise with a note, or keep them as they are.",
        ]
    if result.plan_changed:
        lines += [
            "",
            f"{len(result.plan_changed)} chapter(s) were built before later changes to the "
            "bible or character sheets. That's usually fine; the review will flag anything "
            "that now contradicts the plan.",
        ]
    lines += ["", f"Total: {result.usage.describe()}.", ""]
    result.report_path.write_text("\n".join(lines), encoding="utf-8")


async def build(
    book: Book,
    router: "ModelRouter",
    numbers: list[int],
    settings: PressSettings,
    plan: Plan | None = None,
    on_start: Callable[[ChapterPlan], None] | None = None,
    on_done: Callable[[ChapterResult], None] | None = None,
    on_step: Callable[[int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> BuildResult:
    """Build ``numbers`` in order. ``should_stop`` is checked before each
    chapter, so a stop request finishes the chapter in progress first."""
    plan = plan or book.read_plan()
    run_dir = book.runs_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = 2
    while run_dir.exists():
        run_dir = run_dir.with_name(f"{run_dir.name.split('_')[0]}_{suffix}")
        suffix += 1
    (run_dir / "plan").mkdir(parents=True)
    for name, text in plan.files().items():
        target = run_dir / "plan" / name
        target.parent.mkdir(parents=True, exist_ok=True)  # reference notes sit in a subfolder
        target.write_text(text, encoding="utf-8")

    chapters = plan.chapters()
    results: list[ChapterResult] = []
    total = Usage()
    for number in numbers:
        if should_stop and should_stop():
            break
        if on_start:
            on_start(chapters[number])
        chapter_result = await _build_chapter(
            book, router, plan, chapters[number], settings, run_dir, on_step
        )
        if on_done:
            on_done(chapter_result)
        results.append(chapter_result)
        total.add(chapter_result.usage)

    live = book.read_plan()
    states = {n: book.chapter_state(n, live) for n in sorted(live.chapters())}
    result = BuildResult(
        run_dir,
        results,
        total,
        outline_changed=[n for n, s in states.items() if s == "outline changed"],
        plan_changed=[n for n, s in states.items() if s == "plan changed"],
        report_path=run_dir / "report.md",
    )
    _write_report(book, result, settings)
    return result


async def story_so_far(book: Book, router: "ModelRouter") -> Path:
    chapters = book.drafted_chapters()
    if not chapters:
        raise StudioError("This book has no chapters yet, so there's no story so far to write.")
    text = await complete(
        router, NOTES_ROLE, prompts.story_so_far_messages(book.read_plan(), chapters)
    )
    if book.story_so_far_path.exists():
        book.history_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        book.story_so_far_path.replace(book.history_dir / f"story_so_far.{stamp}.md")
    book.story_so_far_path.write_text(text + "\n", encoding="utf-8")
    return book.story_so_far_path


def export_book(book: Book) -> Path:
    chapters = book.drafted_chapters()
    if not chapters:
        raise StudioError("There are no chapters to export yet.")
    book.export_path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(text.strip() for text in chapters.values())
    book.export_path.write_text(f"# {book.title}\n\n{body}\n", encoding="utf-8")
    return book.export_path
