"""The room's conversation, for the app: a chat model that edits the plan files.

The Claude plugin doesn't need this: there Claude itself follows the
story-session skill and edits the files. In the app, a model from the
writer's own provider plays the same part, following the same skill, with a
small set of tools.

Each turn sends the conversation so far (plain text only) and, with the
writer's newest message, every planning file as it is right now. Earlier
messages are never changed, so providers that cache prompts or bind
reasoning to the conversation see an append-only history.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.studio import press, prompts, room
from src.studio.llm import CHAT_ROLE, MAX_PROMPT_TOKENS, TOO_LONG, too_long
from src.studio.project import (
    REFERENCE_SUFFIXES,
    Book,
    Series,
    StudioError,
    estimate_tokens,
)

if TYPE_CHECKING:
    from src.model_router import ModelRouter

SKILL_PATH = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "story-session" / "SKILL.md"
MAX_STEPS = 24
BOOK_FILES = ("story_bible.md", "characters.md", "outline.md", "story_so_far.md")

_id = iter(range(1, 10**9))


def new_id(prefix: str = "i") -> str:
    from datetime import datetime

    return f"{prefix}{datetime.now():%Y%m%d%H%M%S}{next(_id)}"


def system_prompt() -> str:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    if skill.startswith("---"):
        skill = skill.split("---", 2)[2].lstrip()
    return "\n\n---\n\n".join(
        [prompts._prompt("room_chat"), skill, prompts._prompt("craft_guide")]
    )


# --- files the chat may touch ---------------------------------------------


def resolve(series: Series, rel: str) -> Path:
    path = (series.root / rel.strip().lstrip("/")).resolve()
    root = series.root.resolve()
    if path != root and root not in path.parents:
        raise StudioError(f"'{rel}' is outside this project.")
    return path


def writable(series: Series, path: Path) -> bool:
    """Planning files, reference notes and story-so-far notes. Chapters change
    only through revise_chapter or a build, so their history is kept."""
    parts = path.resolve().relative_to(series.root.resolve()).parts
    if parts == ("series_bible.md",):
        return True
    if len(parts) == 2 and parts[0] == "reference":
        return path.suffix.lower() in REFERENCE_SUFFIXES
    if len(parts) == 3 and parts[0] == "books":
        return parts[2] in BOOK_FILES
    if len(parts) == 4 and parts[0] == "books" and parts[2] == "reference":
        return path.suffix.lower() in REFERENCE_SUFFIXES
    return False


def rel(series: Series, path: Path) -> str:
    return path.resolve().relative_to(series.root.resolve()).as_posix()


def project_files(series: Series) -> list[str]:
    files = [rel(series, p) for p in series.plan_files()]
    if series.reference_dir.is_dir():
        files += [rel(series, p) for p in sorted(series.reference_dir.iterdir()) if p.is_file()]
    for book in series.books():
        for path in book.plan_files():
            name = rel(series, path)
            if name not in files:
                files.append(name)
        if book.story_so_far_path.exists():
            files.append(rel(series, book.story_so_far_path))
        files += [rel(series, p) for p in sorted(book.manuscript_dir.glob("chapter_*.md"))]
    return files


def files_message(series: Series, book: Book) -> str:
    """Everything the chat needs to see, as it is right now."""
    plan = book.read_plan()
    base = f"books/{book.root.name}"
    parts = [
        "# The project's files right now",
        f"Project: {series.title}. You are working on book {book.number}, "
        f"\"{book.title}\" (folder {base}/).",
        "Files in the project:\n" + "\n".join(f"- {name}" for name in project_files(series)),
    ]
    if plan.series_bible.strip():
        parts.append(prompts._section("series_bible.md", plan.series_bible))
    for name, text in plan.reference:
        parts.append(prompts._section(f"Reference: {name}", text))
    for earlier in plan.earlier_books:
        kind = "story so far" if earlier.is_summary else "full text"
        parts.append(prompts._section(f"Earlier book {earlier.number}: {earlier.title} ({kind})", earlier.text))
    parts.append(prompts._section(f"{base}/story_bible.md", plan.story_bible))
    parts.append(prompts._section(f"{base}/characters.md", plan.characters))
    parts.append(prompts._section(f"{base}/outline.md", plan.outline))
    chapters = book.drafted_chapters()
    parts.append(prompts._chapters_section(f"{base}/manuscript (the chapters so far)", chapters))
    return "\n\n".join(parts)


# --- tools ----------------------------------------------------------------


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_PATH = {"type": "string", "description": "Path relative to the project folder."}
_SUMMARY = {"type": "string", "description": "One plain line for the writer, e.g. \"Added Mara's fear of deep water\"."}

TOOLS = [
    {
        "name": "edit_passage",
        "description": "Change the writer's selected passage in its document. Read the document first and copy the exact old_text, including Markdown. Keep everything outside that passage unchanged. Available only when the writer selected text; preserves chapter history.",
        "parameters": _schema({"old_text": {"type": "string"}, "new_text": {"type": "string"}, "summary": _SUMMARY}, ["old_text", "new_text", "summary"]),
    },
    {
        "name": "read_file",
        "description": "Read any file in the project, e.g. an earlier book's characters.md or a chapter.",
        "parameters": _schema({"path": _PATH}, ["path"]),
    },
    {
        "name": "edit_file",
        "description": (
            "Replace one exact passage in a planning file with new text. old_text must appear "
            "exactly once. Use for targeted changes; re-read the file first if unsure."
        ),
        "parameters": _schema(
            {
                "path": _PATH,
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "summary": _SUMMARY,
            },
            ["path", "old_text", "new_text", "summary"],
        ),
    },
    {
        "name": "write_file",
        "description": (
            "Write a whole planning file: series_bible.md, a book's story_bible.md, characters.md, "
            "outline.md or story_so_far.md, or a reference note. Use for a new or starter file; "
            "prefer edit_file once it has the writer's material in it."
        ),
        "parameters": _schema(
            {"path": _PATH, "content": {"type": "string"}, "summary": _SUMMARY},
            ["path", "content", "summary"],
        ),
    },
    {
        "name": "rename",
        "description": (
            "Rename a person, place or thing everywhere in the series: plans, chapters and "
            "story-so-far notes (whole words only). Preview with apply=false, tell the writer the "
            "count, and apply only after they agree."
        ),
        "parameters": _schema(
            {"old": {"type": "string"}, "new": {"type": "string"}, "apply": {"type": "boolean"}},
            ["old", "new", "apply"],
        ),
    },
    {
        "name": "add_book",
        "description": (
            "Add the next book to the series (turning a standalone into a series). Its "
            "characters.md starts as a copy of the previous book's. Then work on the new book."
        ),
        "parameters": _schema({"title": {"type": "string"}}, ["title"]),
    },
    {
        "name": "review",
        "description": (
            "Ask a second model for a review of the current book. Takes a minute or two. Only "
            "when the writer wants a second opinion; then go through the points with them."
        ),
        "parameters": _schema({}, []),
    },
    {
        "name": "revise_chapter",
        "description": "Rewrite a written chapter of the current book following the writer's note.",
        "parameters": _schema(
            {"chapter": {"type": "integer"}, "note": {"type": "string"}}, ["chapter", "note"]
        ),
    },
    {
        "name": "status",
        "description": "Chapters, word counts and what's out of date in the current book.",
        "parameters": _schema({}, []),
    },
    {
        "name": "propose_build",
        "description": (
            "Offer to build chapters with the press: 'next', 'all', or a chapter number. Shows "
            "the writer a card with an estimate and a Build button; they decide."
        ),
        "parameters": _schema({"which": {"type": "string"}}, ["which"]),
    },
    {
        "name": "story_so_far",
        "description": (
            "Write story-so-far notes for the current (finished) book, which later books read "
            "instead of its full text."
        ),
        "parameters": _schema({}, []),
    },
]


@dataclass
class TurnResult:
    reply: str
    items: list[dict] = field(default_factory=list)
    book: Book | None = None


class _Tools:
    def __init__(self, series: Series, book: Book, router: "ModelRouter", settings: press.PressSettings, write_lock=None, selection=None):
        self.series = series
        self.book = book
        self.router = router
        self.settings = settings
        self.items: list[dict] = []
        self.write_lock = write_lock or threading.RLock()
        self.selection = selection
        self.seen = {p: p.read_text(encoding="utf-8") for p in book.plan_files() if p.is_file()}

    def _activity(self, verb: str, path: Path, summary: str, before: str | None, after: str | None) -> None:
        self.items.append({
            "kind": "activity", "id": new_id("a"), "verb": verb, "file": rel(self.series, path),
            "text": summary.strip() or f"{verb} {path.name}", "before": before, "after": after,
        })

    def _write(self, path: Path, text: str, expected: str | None) -> None:
        with self.write_lock:
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != expected:
                raise StudioError(f"{rel(self.series, path)} changed while I was working. Read it again before editing.")
            save_text(path, text)
            self.seen[path] = text

    async def run(self, name: str, args: dict) -> str:
        handler = getattr(self, f"t_{name}", None)
        if handler is None:
            raise StudioError(f"There's no tool called '{name}'.")
        if "_invalid_json" in args:
            raise StudioError("The tool arguments weren't valid JSON; try again.")
        return await handler(**args)

    async def t_read_file(self, path: str) -> str:
        target = resolve(self.series, path)
        if not target.is_file():
            raise StudioError(f"{path} doesn't exist.")
        text = target.read_text(encoding="utf-8")
        self.seen[target] = text
        return text

    async def t_edit_file(self, path: str, old_text: str, new_text: str, summary: str = "") -> str:
        target = resolve(self.series, path)
        if not writable(self.series, target):
            raise StudioError(f"{path} isn't a planning file you can edit. Use revise_chapter for chapters.")
        if not target.is_file():
            raise StudioError(f"{path} doesn't exist yet; use write_file.")
        text = target.read_text(encoding="utf-8")
        count = text.count(old_text) if old_text else 0
        if count != 1:
            raise StudioError(
                f"old_text appears {count} times in {path}; it must appear exactly once. "
                "Read the file and copy a longer, exact passage."
            )
        updated = text.replace(old_text, new_text)
        self._write(target, updated, text)
        self._activity("Edited", target, summary, text, updated)
        return f"Saved {path}."

    async def t_edit_passage(self, old_text: str, new_text: str, summary: str) -> str:
        if not self.selection:
            raise StudioError("The writer hasn't selected a passage.")
        target = resolve(self.series, self.selection["path"])
        with self.write_lock:
            before = target.read_text(encoding="utf-8")
            if version(before) != self.selection["version"]:
                raise StudioError("The selected document changed. Ask the writer to select the passage again.")
            if not old_text or before.count(old_text) != 1:
                raise StudioError("Read the document and copy one exact, unique passage, including its Markdown.")
            after = before.replace(old_text, new_text, 1)
            chapter = re.fullmatch(r"chapter_(\d+)\.md", target.name) if target.parent.name == "manuscript" else None
            if chapter:
                selected_book = next((b for b in self.series.books() if b.manuscript_dir == target.parent), None)
                if selected_book is None:
                    raise StudioError("That chapter isn't in this series.")
                selected_book.write_chapter(int(chapter[1]), after, selected_book.read_plan(), "passage")
                after = target.read_text(encoding="utf-8")
            elif writable(self.series, target):
                self._write(target, after, before)
            else:
                raise StudioError("That document can't be edited here.")
            self.selection = {**self.selection, "version": version(after)}
            self._activity("Edited passage", target, summary, before, after)
        return f"Saved the passage in {rel(self.series, target)}."

    async def t_write_file(self, path: str, content: str, summary: str = "") -> str:
        target = resolve(self.series, path)
        if not writable(self.series, target):
            raise StudioError(f"{path} isn't a planning file you can write. Use revise_chapter for chapters.")
        before = target.read_text(encoding="utf-8") if target.exists() else None
        if before is not None and self.seen.get(target) != before:
            raise StudioError(f"Read {path} again before replacing it; it may have changed.")
        text = content.rstrip() + "\n"
        self._write(target, text, before)
        self._activity("Created" if before is None else "Filled", target, summary, before, text)
        return f"Saved {path}."

    async def t_rename(self, old: str, new: str, apply: bool = False) -> str:
        hits = room.apply_rename(self.book, old, new) if apply else room.find_name(self.book, old)
        if not hits:
            return f"'{old}' doesn't appear anywhere in the series."
        total = sum(h.count for h in hits)
        lines = [f"- {rel(self.series, h.path)}: {h.count}" for h in hits]
        if apply:
            self.items.append({
                "kind": "activity", "id": new_id("a"), "verb": "Renamed", "file": f"{old} → {new}",
                "text": f"{total} change(s) in {len(hits)} file(s). Earlier versions of chapters stay in history.",
                "before": None, "after": None,
            })
            return f"Replaced {total} occurrence(s) in {len(hits)} file(s):\n" + "\n".join(lines)
        return (
            f"Preview only, nothing changed: {total} occurrence(s) in {len(hits)} file(s):\n"
            + "\n".join(lines)
        )

    async def t_add_book(self, title: str) -> str:
        book, written = self.series.add_book(title)
        self.book = book
        self.seen.update({p: p.read_text(encoding="utf-8") for p in written})
        self.items.append({
            "kind": "activity", "id": new_id("a"), "verb": "Added", "file": f"Book {book.number}: {title}",
            "text": "With its own story bible, characters (copied from the previous book) and outline.",
            "before": None, "after": None,
        })
        return "Created:\n" + "\n".join(f"- {rel(self.series, p)}" for p in written)

    async def t_review(self) -> str:
        path = await room.review(self.book, self.router)
        self.items.append({"kind": "review", "id": new_id("r"), "file": rel(self.series, path)})
        return path.read_text(encoding="utf-8")

    async def t_revise_chapter(self, chapter: int, note: str) -> str:
        before = self.book.chapter_path(int(chapter)).read_text(encoding="utf-8") if self.book.chapter_path(int(chapter)).exists() else None
        path = await room.revise_chapter(self.book, self.router, int(chapter), note)
        self.items.append({
            "kind": "activity", "id": new_id("a"), "verb": "Revised", "file": rel(self.series, path),
            "text": note.strip()[:200] + " (the earlier version is in manuscript/.history/)",
            "before": before, "after": path.read_text(encoding="utf-8"),
        })
        return f"Revised chapter {chapter}; the earlier version is kept in history."

    async def t_status(self) -> str:
        report = room.status(self.book)
        lines = [f"{self.book.label}: {report.total_words:,} words written."]
        for row in report.chapters:
            lines.append(f"- Chapter {row.number} {row.title}: {row.words:,} words, {row.state}")
        if report.latest_review is None:
            lines.append("No review yet.")
        elif report.plan_changed_since_review:
            lines.append("The plan has changed since the last review.")
        return "\n".join(lines)

    async def t_propose_build(self, which: str) -> str:
        plan = self.book.read_plan()
        numbers = press.select_chapters(self.book, plan, str(which).strip())
        guess = press.estimate(self.book, plan, numbers, self.settings)
        listed = ", ".join(str(n) for n in numbers)
        existing = [n for n in numbers if self.book.chapter_path(n).exists()]
        detail = guess.describe().capitalize() + "."
        if existing:
            detail += " This replaces the current version; the old one is kept in history."
        self.items.append({
            "kind": "approval", "id": new_id("b"), "book": self.book.root.name, "which": str(which),
            "numbers": numbers, "title": f"Build chapter{'s' if len(numbers) > 1 else ''} {listed}?",
            "detail": detail, "status": "pending",
        })
        return "The writer now sees a build card with Build and Not now buttons. Don't start it yourself."

    async def t_story_so_far(self) -> str:
        path = await press.story_so_far(self.book, self.router)
        self._activity("Wrote", path, "Story-so-far notes for later books", None, path.read_text(encoding="utf-8"))
        return f"Saved {rel(self.series, path)}."


def _transcript_line(item: dict) -> str | None:
    if item["kind"] == "assistant":
        return item["text"]
    if item["kind"] == "activity":
        return f"[{item['verb']} {item['file']}: {item['text']}]"
    if item["kind"] == "approval":
        return f"[Offered a build card: {item['title']}]"
    if item["kind"] == "review":
        return f"[Ran a review: {item['file']}]"
    return None


def version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def save_text(path: Path, text: str) -> None:
    """Keep the writer's previous text beside the file before replacing it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        history = path.parent / ".history"
        history.mkdir(exist_ok=True)
        (history / f"{path.stem}.{new_id('v')}{path.suffix}").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(text, encoding="utf-8")


class TurnStopped(Exception):
    pass


async def _cancellable(work, should_stop):
    task = asyncio.create_task(work)
    try:
        while not task.done():
            if should_stop():
                raise TurnStopped()
            await asyncio.wait({task}, timeout=0.1)
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def run_turn(
    series: Series,
    book: Book,
    router: "ModelRouter",
    history: list[dict],
    text: str,
    settings: press.PressSettings,
    attachments: list[tuple[str, str]] = (),
    on_event: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    explore: bool = False,
    write_lock=None,
    selection: dict | None = None,
) -> TurnResult:
    """One writer message and everything the chat does in reply.

    ``history`` holds earlier turns as plain ``user``/``assistant`` messages and
    is not changed; the caller appends ``user_entry`` and the returned reply.
    """
    emit = on_event or (lambda event: None)
    tools = _Tools(series, book, router, settings, write_lock, selection)
    message = files_message(series, book)
    for name, body in attachments:
        message += "\n\n" + prompts._section(f"Attached by the writer: {name}", body)
    message += "\n\n# The writer says\n\n" + (text.strip() or "(only the attachment above)")
    system = system_prompt()
    if explore:
        message += "\n\nFor this turn, just explore ideas. Do not change any files or start work."
    # One part, cached whole: each step of this turn re-sends it unchanged.
    messages = list(history) + [{"role": "user", "content": message, "parts": [message]}]

    reply = ""
    for _ in range(MAX_STEPS):
        if should_stop():
            raise TurnStopped()
        size = estimate_tokens(system + "".join(str(m.get("content", "")) for m in messages))
        if size > MAX_PROMPT_TOKENS:
            raise StudioError(
                f"This chat would send about {size:,} tokens, more than the {MAX_PROMPT_TOKENS:,} "
                "the tool allows. Start a new chat, or write story-so-far notes for finished books."
            )
        emit({"kind": "phase", "text": "Thinking about your story…"})
        available = [t for t in TOOLS if (not explore or t["name"] in ("read_file", "status")) and (selection or t["name"] != "edit_passage")]
        kwargs = {"on_text": lambda text: emit({"kind": "text", "text": text})} if on_event else {}
        try:
            answer = await _cancellable(router.chat(CHAT_ROLE, system, messages, available, **kwargs), should_stop)
        except Exception as exc:
            if too_long(exc):
                raise StudioError(TOO_LONG + " Or start a new chat.") from exc
            raise
        messages.append({"role": "assistant", **answer})
        if not answer["tool_calls"]:
            reply = answer["content"].strip()
            break
        if answer["content"].strip():
            emit({"kind": "item", "item": {"kind": "assistant", "id": new_id("m"), "text": answer["content"].strip()}})
        for call in answer["tool_calls"]:
            if should_stop():
                raise TurnStopped()
            labels = {"read_file": "Reading", "edit_file": "Updating", "write_file": "Writing", "edit_passage": "Updating the selected passage…",
                      "review": "Reading the book for a second opinion…", "revise_chapter": "Revising the chapter…",
                      "rename": "Checking names…", "add_book": "Adding the next book…",
                      "status": "Checking the book…", "propose_build": "Preparing a build estimate…",
                      "story_so_far": "Writing story-so-far notes…"}
            emit({"kind": "phase", "text": labels.get(call["name"], "Working…") + (" " + call["arguments"].get("path", "") if call["name"] in ("read_file", "edit_file", "write_file") else "")})
            start = len(tools.items)
            try:
                if explore and call["name"] not in ("read_file", "status"):
                    raise StudioError("This turn is for exploring only. No files were changed.")
                result = await _cancellable(tools.run(call["name"], dict(call["arguments"])), should_stop)
                error = False
            except StudioError as exc:
                result, error = f"Error: {exc}", True
            except TypeError as exc:
                result, error = f"Error: wrong arguments for {call['name']} ({exc}).", True
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result, "is_error": error})
            for item in tools.items[start:]:
                emit({"kind": "item", "item": item, "book": tools.book.root.name})
    else:
        reply = "I stopped there because that was a lot of steps at once. Tell me what to do next."
    if not reply:
        reply = "Done." if tools.items else "Sorry, I didn't get an answer back. Try again?"
    return TurnResult(reply, tools.items, tools.book)


def history_entries(text: str, attachments: list[tuple[str, str]], result: TurnResult) -> list[dict]:
    """What a finished turn adds to the plain-text history sent with later turns."""
    user = text.strip()
    if attachments:
        user += "\n\n[Attached: " + ", ".join(name for name, _ in attachments) + "]"
    lines = [line for line in (_transcript_line(i) for i in result.items) if line]
    return [
        {"role": "user", "content": user or "(attachment)"},
        {"role": "assistant", "content": "\n".join(lines + [result.reply])},
    ]


def undo(series: Series, item: dict) -> dict:
    """Swap a file back to how it was before (or after, to redo) an activity."""
    if item.get("after") is None and item.get("before") is None:
        raise StudioError("This change can't be undone from here.")
    path = resolve(series, item["file"])
    undone = bool(item.get("undone"))
    expected, restore = (item["before"], item["after"]) if undone else (item["after"], item["before"])
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current != expected:
        raise StudioError(
            f"{item['file']} has changed since then, so undoing would lose those changes. "
            "Open the file to change it by hand, or ask in the chat."
        )
    if restore is None:
        path.unlink()
    else:
        save_text(path, restore)
    return {**item, "undone": not undone}


_POINT = re.compile(r"^###\s*(\d+)\.\s*(.+)$", re.MULTILINE)


def review_points(text: str) -> list[dict]:
    """The numbered points in a review, with any call already made."""
    matches = list(_POINT.finditer(text))
    points = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end]
        stop = re.search(r"^#{1,3}\s", body, re.MULTILINE)
        body = body[: stop.start()] if stop else body
        call = re.search(r"\*\*Your call:\*\*[ \t]*(.*)", body)
        points.append({
            "number": int(match.group(1)),
            "title": match.group(2).strip(),
            "body": body.split("**Your call:**")[0].strip(),
            "call": call.group(1).strip() if call else "",
        })
    return points


def record_call(path: Path, number: int, call: str) -> None:
    """Fill in a review point's "Your call" line."""
    text = path.read_text(encoding="utf-8")
    matches = list(_POINT.finditer(text))
    for i, match in enumerate(matches):
        if int(match.group(1)) != number:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[match.start():end]
        updated, count = re.subn(
            r"\*\*Your call:\*\*[ \t]*.*", lambda _: f"**Your call:** {call.strip()}", section, count=1
        )
        if not count:
            updated = section.rstrip() + f"\n\n**Your call:** {call.strip()}\n\n"
        path.write_text(text[:match.start()] + updated + text[end:], encoding="utf-8")
        return
    raise StudioError(f"The review has no point {number}.")
