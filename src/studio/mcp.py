"""The Claude plugin's tools: a small MCP server over stdin and stdout.

In Cowork or Claude Code, Claude follows the story-session skill and edits
the plan files itself. These tools give it what it can't do with files alone:
start books, second opinions, renames, and the press, which runs in the
background on the writer's own model provider.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Callable, TextIO

from src.studio import jobs, press, room
from src.studio.llm import provider_error
from src.studio.project import Book, Library, StudioError

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_VERSION = "2025-06-18"
INSTRUCTIONS = (
    "Writers Room keeps books as Markdown files in a library folder (list_books shows where). "
    "Plan with the writer by following the story-session skill and editing the files directly; "
    "use these tools for new books, reviews, renames and building chapters."
)

_BOOK = {
    "title": {"type": "string", "description": "The book's title; not needed when the library has one book."},
    "series": {"type": "string", "description": "The series, when two series share a book title."},
}


def _schema(properties: dict, required: list[str] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required)}


TOOLS = [
    {"name": "list_books", "description": "Every book in the library, with its folder and chapters written. Start here.",
     "inputSchema": _schema({})},
    {"name": "new_book",
     "description": "Start a book, or add the next book to a series (pass series). A new book in a series "
                    "starts with a copy of the previous book's characters.md.",
     "inputSchema": _schema({"new_title": {"type": "string"}, "series": _BOOK["series"]}, ["new_title"])},
    {"name": "status", "description": "Chapters, word counts and what's out of date.", "inputSchema": _schema(_BOOK)},
    {"name": "review",
     "description": "A second model reviews the plan and chapters and saves numbered points with a blank "
                    "'Your call' line. Takes a minute or two. Returns the review.",
     "inputSchema": _schema(_BOOK)},
    {"name": "ideas",
     "description": "A second model offers two or three options for each of the thinnest parts of the plan, "
                    "with a blank 'Your call' line each. For when the writer is stuck. Returns the ideas.",
     "inputSchema": _schema(_BOOK)},
    {"name": "rename",
     "description": "Rename someone or something everywhere in the series (whole words). apply=false previews; "
                    "apply only after the writer agrees.",
     "inputSchema": _schema({**_BOOK, "old": {"type": "string"}, "new": {"type": "string"},
                             "apply": {"type": "boolean"}}, ["old", "new"])},
    {"name": "estimate_build",
     "description": "How many model calls and tokens building 'next', 'all' or a chapter number would take. "
                    "Show the writer before start_build.",
     "inputSchema": _schema({**_BOOK, "which": {"type": "string"}}, ["which"])},
    {"name": "start_build",
     "description": "Start the press in the background: draft, critique, revise and save each chapter. "
                    "Only after the writer agrees. Rebuilding a written chapter needs rebuild=true "
                    "(the old version is kept in history). Check progress with build_status.",
     "inputSchema": _schema({**_BOOK, "which": {"type": "string"}, "rebuild": {"type": "boolean"}}, ["which"])},
    {"name": "build_status", "description": "Progress of the current or last build.", "inputSchema": _schema(_BOOK)},
    {"name": "stop_build", "description": "Stop the build after the chapter in progress.", "inputSchema": _schema(_BOOK)},
    {"name": "revise_chapter", "description": "Rewrite a written chapter following the writer's note.",
     "inputSchema": _schema({**_BOOK, "chapter": {"type": "integer"}, "note": {"type": "string"}},
                            ["chapter", "note"])},
    {"name": "story_so_far",
     "description": "Notes on a finished book that later books in the series read instead of its full text.",
     "inputSchema": _schema(_BOOK)},
    {"name": "export", "description": "Stitch the chapters into one Markdown file.", "inputSchema": _schema(_BOOK)},
    {"name": "check", "description": "Check that the model provider key works.", "inputSchema": _schema({})},
    {"name": "craft_guide", "description": "The loose craft guide the story-session skill thinks with.",
     "inputSchema": _schema({})},
]


def default_library() -> Path:
    configured = os.environ.get("WRITERS_ROOM_LIBRARY", "").strip()
    if configured:
        return Path(configured).expanduser()
    project = os.environ.get("WRITERS_ROOM_PROJECT_DIR", "").strip() or os.getcwd()
    return Path(project) / "library"


class Tools:
    def __init__(self, library: Library, make_router: Callable, config_path: Path):
        self.library = library
        self.make_router = make_router
        self.config_path = config_path

    def _book(self, args: dict) -> Book:
        if not self.library.all_books():
            raise StudioError("The library is empty. Start a book with new_book.")
        return self.library.find_book(args.get("title"), args.get("series"))

    def _settings(self) -> press.PressSettings:
        from src.model_router import load_config

        return press.PressSettings.from_config(load_config(self.config_path))

    def _with_router(self, work):
        async def go():
            router = self.make_router()
            try:
                return await work(router)
            finally:
                await router.close()

        return asyncio.run(go())

    def list_books(self, args: dict) -> str:
        lines = [f"Library: {self.library.root}"]
        for series in self.library.all_series():
            books = series.books()
            if len(books) > 1 or series.bible_path.exists():
                lines.append(f"{series.title} (series, folder {series.root})")
            for book in books:
                plan = book.read_plan()
                lines.append(
                    f"- {book.label}: {len(book.drafted_chapters())} of {len(plan.chapters())} "
                    f"outlined chapter(s) written. Folder: {book.root}"
                )
        if len(lines) == 1:
            lines.append("No books yet. Start one with new_book.")
        return "\n".join(lines)

    def new_book(self, args: dict) -> str:
        book, written = self.library.new_book(args["new_title"], args.get("series"))
        return f"{book.label}\nFolder: {book.root}\n" + "\n".join(f"Created {p}" for p in written)

    def status(self, args: dict) -> str:
        book = self._book(args)
        report = room.status(book)
        lines = [f"{book.label} ({book.root})"]
        for row in report.chapters:
            words = f"{row.words:,} words" if row.words else ""
            lines.append(f"Chapter {row.number} {row.title}: {words} {row.state}".strip())
        lines.append(f"{report.total_words:,} words. Each model call sends about {report.context_tokens:,} tokens.")
        if report.latest_review is None:
            lines.append("No review yet.")
        elif report.plan_changed_since_review:
            lines.append(f"The plan has changed since the last review ({report.latest_review}).")
        return "\n".join(lines)

    def review(self, args: dict) -> str:
        book = self._book(args)
        path = self._with_router(lambda r: room.review(book, r))
        return f"Saved {path}\n\n" + path.read_text(encoding="utf-8")

    def ideas(self, args: dict) -> str:
        book = self._book(args)
        path = self._with_router(lambda r: room.ideas(book, r))
        return f"Saved {path}\n\n" + path.read_text(encoding="utf-8")

    def rename(self, args: dict) -> str:
        book = self._book(args)
        apply = bool(args.get("apply"))
        hits = room.apply_rename(book, args["old"], args["new"]) if apply else room.find_name(book, args["old"])
        if not hits:
            return f"'{args['old']}' doesn't appear anywhere in {book.series.title}."
        total = sum(h.count for h in hits)
        lines = [f"{h.path}: {h.count}" for h in hits]
        head = "Replaced" if apply else "Preview only, nothing changed:"
        return f"{head} {total} occurrence(s) in {len(hits)} file(s).\n" + "\n".join(lines)

    def estimate_build(self, args: dict) -> str:
        book = self._book(args)
        plan = book.read_plan()
        numbers = press.select_chapters(book, plan, str(args["which"]))
        guess = press.estimate(book, plan, numbers, self._settings())
        existing = [n for n in numbers if book.chapter_path(n).exists()]
        note = f" Chapter(s) {', '.join(map(str, existing))} already exist." if existing else ""
        return f"Chapter(s) {', '.join(map(str, numbers))}: {guess.describe()}.{note}"

    def start_build(self, args: dict) -> str:
        book = self._book(args)
        plan = book.read_plan()
        numbers = press.select_chapters(book, plan, str(args["which"]))
        existing = [n for n in numbers if book.chapter_path(n).exists()]
        if existing and not args.get("rebuild"):
            raise StudioError(
                f"Chapter {existing[0]} already exists. Ask the writer, then pass rebuild=true "
                "(the current version is kept in manuscript/.history/)."
            )
        self.make_router()  # explain a missing key now rather than on the build thread
        jobs.start_build(book, self.make_router, numbers, self._settings())
        return f"Building chapter(s) {', '.join(map(str, numbers))} of {book.label} in the background. Check build_status."

    def build_status(self, args: dict) -> str:
        job = jobs.job_for(self._book(args))
        if not job:
            return "No build has run since the tools started."
        snap = job.snapshot()
        lines = [f"State: {snap['state']}" + (" (stopping after this chapter)" if snap["stopping"] else "")]
        if snap["current"]:
            lines.append(f"Now: chapter {snap['current']}, {snap['step']}.")
        for r in snap["results"]:
            lines.append(f"Chapter {r['number']}: {r['words']:,} words (planned {r['target']:,}), "
                         f"{r['revisions']} revision(s) kept. " + " ".join(r["notes"]))
        if snap["error"]:
            lines.append(snap["error"])
        if snap["report"]:
            lines.append(f"Report: {snap['report']}. {snap['usage']}")
        return "\n".join(lines)

    def stop_build(self, args: dict) -> str:
        job = jobs.job_for(self._book(args))
        if not job or job.state != "running":
            return "Nothing is building."
        job.stop()
        return "Stopping after the chapter in progress."

    def revise_chapter(self, args: dict) -> str:
        book = self._book(args)
        path = self._with_router(lambda r: room.revise_chapter(book, r, int(args["chapter"]), args["note"]))
        return f"Saved {path}; the earlier version is in manuscript/.history/."

    def story_so_far(self, args: dict) -> str:
        book = self._book(args)
        path = self._with_router(lambda r: press.story_so_far(book, r))
        return f"Saved {path}. Later books in the series read this instead of the full text."

    def export(self, args: dict) -> str:
        return f"Saved {press.export_book(self._book(args))}"

    def craft_guide(self, args: dict) -> str:
        return (ROOT / "prompts" / "studio" / "craft_guide.md").read_text(encoding="utf-8")

    def check(self, args: dict) -> str:
        ok, message = self._with_router(room.check)
        return ("Ready: " if ok else "Problem: ") + message


def handle(tools: Tools, message: dict) -> dict | None:
    """One JSON-RPC message in, the reply out (None for notifications)."""
    method, mid = message.get("method"), message.get("id")
    if mid is None:
        return None
    if method == "initialize":
        version = (message.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "writers-room", "version": "1.0.0"},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in {t["name"] for t in TOOLS}:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        try:
            text, error = getattr(tools, name)(args), False
        except StudioError as exc:
            text, error = str(exc), True
        except KeyError as exc:
            text, error = f"Missing argument {exc}.", True
        except Exception as exc:
            explained = provider_error(exc)
            if explained is None:
                raise
            text, error = f"{explained} The check tool tests the key.", True
        result = {"content": [{"type": "text", "text": text}], "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(tools: Tools, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(tools, message)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


def make_router_factory(config_path: Path) -> Callable:
    def make():
        from src.model_router import ModelRouter

        router = ModelRouter(str(config_path))
        missing = router.missing_keys()
        if missing:
            raise StudioError(
                f"No API key for {', '.join(missing)}. Add it in the Writers Room plugin's settings "
                "(or in the app's Settings), then try again."
            )
        return router

    return make
