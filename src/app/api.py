"""What the app can do, as plain functions over the library. The web server in
``server.py`` turns HTTP requests into calls here; tests call them directly.

A project is a series folder in the library (a standalone book is a series of
one). Chats are saved next to the books, in ``<series>/chats/<id>.json``; the
project page's ongoing conversation is the chat called ``project``.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import io
import json
import logging
import os
import re
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from src import model_catalog
from src.model_router import PROVIDER_ORDER, ModelRouter, load_config, local_overlay_path
from src.studio import chat, jobs, press
from src.studio.llm import LONG_PROMPT_TOKENS, MAX_PROMPT_TOKENS, provider_error
from src.studio.project import (
    BIBLES,
    REFERENCE_SUFFIXES,
    Book,
    Library,
    Series,
    StudioError,
    count_words,
    decode_text,
    estimate_tokens,
    history_copy,
    read_text,
    slugify,
)

PROJECT_CHAT = "project"
LARGE_REFERENCE_TOKENS = 50_000
ROLES = [
    ("studio_chat", "Chat", "Talks with you and edits your files."),
    ("studio_writer", "Writer", "Drafts and revises chapters."),
    ("studio_critic", "Critic", "Critiques each draft. A different model catches different things."),
    ("studio_reader", "Reviewer", "Second opinions and fresh ideas from a different model."),
    ("studio_notes", "Story so far", "Notes on a finished book for the books after it."),
]
PRESS_ROLES = ("studio_writer", "studio_critic", "studio_reader", "studio_notes")
PROVIDER_BLURBS = {
    "cloud": "One key for every model here: DeepSeek, Gemini, Claude, GPT and more. Pay as you go.",
    "anthropic": "Claude models, directly from Anthropic.",
    "openai": "GPT models, directly from OpenAI.",
    "google": "Gemini models, directly from Google AI Studio.",
    "local": "A model running on this computer with Ollama or llama.cpp. Free and private, but slower and less capable.",
}


_WRITTEN_HEADING = re.compile(r"#\s*chapter\s+\d+\s*[:.\-–—]?\s*(.*)", re.IGNORECASE)


def context_limit(config: dict) -> int:
    """The smallest known context window among the models the roles use.

    Most configured models are ~1M; a role pointed at a smaller model (for
    example Aion's 262K) needs the meter and the build estimate to say so.
    """
    limits = []
    models = config.get("models") or {}
    for routing in (config.get("agent_routing") or {}).values():
        if not isinstance(routing, dict):
            continue
        backend = routing.get("backend")
        model = routing.get("model")
        entry = ((models.get(backend) or {}).get("models") or {}).get(model)
        if isinstance(entry, dict) and entry.get("context"):
            limits.append(int(entry["context"]))
    return min([MAX_PROMPT_TOKENS, *limits]) if limits else MAX_PROMPT_TOKENS


def _role_price(config: dict, role: str) -> dict | None:
    routing = (config.get("agent_routing") or {}).get(role) or {}
    models = ((config.get("models") or {}).get(routing.get("backend")) or {}).get("models") or {}
    entry = models.get(routing.get("model"))
    return entry.get("price") if isinstance(entry, dict) else None


def build_cost(config: dict, guess: press.Estimate) -> float | None:
    """Dollars for a build at the writer's and critic's list prices, or None
    when a price isn't known (only OpenRouter's catalog gives them)."""
    writer, critic = _role_price(config, "studio_writer"), _role_price(config, "studio_critic")
    if not writer or (guess.critic_input_tokens and not critic):
        return None
    critic = critic or {"in": 0, "out": 0}
    return (
        (guess.input_tokens - guess.critic_input_tokens) * writer["in"]
        + (guess.output_tokens - guess.critic_output_tokens) * writer["out"]
        + guess.critic_input_tokens * critic["in"]
        + guess.critic_output_tokens * critic["out"]
    ) / 1_000_000


def _written_title(text: str) -> str:
    """The title in a written chapter's own heading ("# Chapter 1: The Storm")."""
    first = text.lstrip().splitlines()[:1]
    match = _WRITTEN_HEADING.fullmatch(first[0].strip()) if first else None
    return match.group(1).strip() if match else ""


def _point_file(path: Path) -> bool:
    """A review or ideas file: numbered points, each with a "Your call" line."""
    return path.parent.name == "notes" and path.name.startswith(("review_", "ideas_"))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _html_text(markup: str) -> str:
    """Readable text from a web page or an e-book chapter."""
    import html

    markup = re.sub(r"<(script|style|head)\b.*?</\1>", "", markup, flags=re.DOTALL | re.IGNORECASE)
    markup = re.sub(r"<br\s*/?>|</(p|div|h[1-6]|li|blockquote|tr)>", "\n\n", markup, flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", "", markup))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _epub_text(data: bytes) -> str:
    """An EPUB's chapters in reading order (the spine of its package file)."""
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        container = book.read("META-INF/container.xml").decode("utf-8", errors="replace")
        opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
        opf = book.read(opf_path).decode("utf-8", errors="replace")
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        items = {}
        for tag in re.findall(r"<item\b[^>]*>", opf):
            item_id, href = re.search(r'\bid="([^"]+)"', tag), re.search(r'\bhref="([^"]+)"', tag)
            if item_id and href:
                items[item_id.group(1)] = href.group(1)
        order = re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf)
        parts = [_html_text(book.read(base + items[i]).decode("utf-8", errors="replace"))
                 for i in order if i in items]
    return "\n\n".join(p for p in parts if p)


def to_text(name: str, data: bytes) -> tuple[str, str]:
    """A file the writer added, as (markdown name, text) the models can read."""
    suffix = Path(name).suffix.lower()
    if suffix in REFERENCE_SUFFIXES or suffix == ".markdown":
        return Path(name).stem + (".md" if suffix != ".txt" else ".txt"), decode_text(data)
    if suffix in (".html", ".htm"):
        return Path(name).stem + ".md", _html_text(decode_text(data)) + "\n"
    if suffix == ".epub":
        try:
            text = _epub_text(data)
        except (zipfile.BadZipFile, KeyError, AttributeError):
            raise StudioError(f"{name} doesn't look like an EPUB I can read.") from None
        return Path(name).stem + ".md", text + "\n"
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as docx:
                xml = docx.read("word/document.xml").decode("utf-8", errors="replace")
        except (zipfile.BadZipFile, KeyError):
            raise StudioError(f"{name} doesn't look like a Word document I can read.") from None
        paragraphs = re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.DOTALL)
        text = "\n\n".join(
            "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, flags=re.DOTALL)) for p in paragraphs
        )
        import html

        return Path(name).stem + ".md", html.unescape(text).strip() + "\n"
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        raise StudioError(
            f"{name} is an image. The writing models read text, so describe what matters "
            "in it instead (a sentence or two in the chat is plenty)."
        )
    raise StudioError(
        f"I can read .md, .txt, .docx, .html and .epub files. For {name}, copy its text "
        "into a .txt file or paste it into the chat."
    )


class App:
    def __init__(
        self,
        library: Library,
        config_path: Path,
        env_path: Path,
        make_router: Callable[[], object] | None = None,
        library_source: str = "default",
        fetch_catalog: Callable[[], list[dict]] = model_catalog.fetch,
    ):
        self.library = library
        self.library_source = library_source
        self.config_path = Path(config_path)
        self.env_path = Path(env_path)
        self._make_router = make_router
        self._fetch_catalog = fetch_catalog
        self._catalog_lock = threading.Lock()
        self._catalog_failed = float("-inf")
        self._lock = threading.RLock()
        self._turns: dict[str, dict] = {}
        self._moved: dict[str, str] = {}
        self._summaries: dict[Path, tuple] = {}

    # --- models -----------------------------------------------------------

    def config(self) -> dict:
        return load_config(self.config_path)

    def router(self):
        if self._make_router:
            return self._make_router()
        router = ModelRouter(str(self.config_path))
        missing = router.missing_keys()
        if missing:
            raise StudioError(
                "Connect a model provider first: open Settings (bottom left) and add a key "
                f"({', '.join(missing)} is missing)."
            )
        return router

    def press_settings(self) -> press.PressSettings:
        return press.PressSettings.from_config(self.config())

    def _run(self, work):
        async def go():
            router = self.router()
            try:
                return await work(router)
            finally:
                await router.close()

        return asyncio.run(go())

    # --- projects -----------------------------------------------------------

    def series(self, pid: str) -> Series:
        # A page watching a turn may still ask by the name the turn just changed.
        if not (self.library.root / pid).exists():
            pid = self._moved.get(pid, pid)
        series = Series(self.library.root / pid)
        if not pid or "/" in pid or ".." in pid or not series.books():
            raise StudioError("That project isn't in the library any more.")
        return series

    def book(self, series: Series, folder: str | None = None) -> Book:
        books = series.books()
        if folder:
            for book in books:
                if book.root.name == folder:
                    return book
        return books[-1]

    def projects(self) -> list[dict]:
        out = []
        for series in self.library.all_series():
            books = series.books()
            chats = self._chat_summaries(series)
            out.append({
                "id": series.root.name,
                "title": series.title,
                "kind": (
                    f"Series · {len(books)} book{'s' if len(books) != 1 else ''}"
                    if len(books) > 1 or series.bible_path.exists()
                    else "Standalone"
                ),
                "chapters": sum(len(b.drafted_chapters()) for b in books),
                "chats": [c for c in chats if c["id"] != PROJECT_CHAT],
                "updated": max([c["updated"] for c in chats] or [""]),
            })
        out.sort(key=lambda p: p["updated"], reverse=True)
        return out

    def _unique(self, title: str) -> str:
        n, candidate = 1, title
        while (self.library.root / slugify(candidate)).exists():
            n += 1
            candidate = f"{title} {n}"
        return candidate

    def create_project(self, idea: str, kind: str = "book", defer: bool = False) -> dict:
        if not idea.strip():
            raise StudioError("Type an idea first, even a single line.")
        self.router_check()  # fail before creating anything if no provider is set up
        if kind == "series":
            series_title = self._unique("Untitled series")
            book, _ = self.library.new_book("Untitled book", series_title=series_title)
        else:
            book, _ = self.library.new_book(self._unique("Untitled book"))
        record = self.load_chat(book.series.root.name, PROJECT_CHAT) if defer else self.send(book.series.root.name, PROJECT_CHAT, idea)
        return {"project": record["project"], "chat": record}

    def project(self, pid: str, folder: str | None = None) -> dict:
        series = self.series(pid)
        book = self.book(series, folder)
        books = series.books()
        is_series = len(books) > 1 or series.bible_path.exists()
        rel = lambda p: chat.rel(series, p)  # noqa: E731

        def plan_files(b: Book) -> list[dict]:
            files = [("Story bible", b.bible_path), ("Characters", b.characters_path), ("Outline", b.outline_path)]
            if b.story_so_far_path.exists():
                files.append(("Story so far", b.story_so_far_path))
            return [{"label": label, "path": rel(p)} for label, p in files if p.exists()]

        groups = []
        if is_series:
            groups.append({
                "label": "Whole series", "status": "",
                "hint": "Shared by every book: the world, its rules, where the series goes.",
                "files": [{"label": "Series bible", "path": rel(series.bible_path)}] if series.bible_path.exists() else [],
            })
            for b in books:
                written = len(b.drafted_chapters())
                groups.append({
                    "label": f"Book {b.number} · {b.title}", "book": b.root.name,
                    "status": f"{written} chapter{'s' if written != 1 else ''} written" if written else "Planning",
                    "hint": "Only this book: its story, its characters as they are in it, its outline.",
                    "files": plan_files(b),
                })
        else:
            groups.append({"label": "Plan", "status": "", "hint": "", "files": plan_files(book)})

        def ref_group(scope: str, folder_path: Path, label: str, hint: str) -> dict:
            files = []
            if folder_path.is_dir():
                for p in sorted(folder_path.iterdir()):
                    if not p.is_file() or p.suffix.lower() not in REFERENCE_SUFFIXES:
                        continue
                    tokens = estimate_tokens(read_text(p))
                    files.append({
                        "name": p.name, "path": rel(p), "tokens": tokens,
                        "size": f"{max(1, p.stat().st_size // 1024)} KB",
                        "warn": (
                            f"Large: adds about {tokens:,} tokens to every call. Consider putting what "
                            "matters into the bible instead."
                        ) if tokens > LARGE_REFERENCE_TOKENS else "",
                    })
            return {"scope": scope, "label": label, "hint": hint, "files": files}

        if is_series:
            reference = [
                ref_group("series", series.reference_dir, "Reference · whole series",
                          f"Shared by every book in {series.title}."),
                ref_group("book", book.reference_dir, f"Reference · Book {book.number}",
                          f"Read only by book {book.number}."),
            ]
        else:
            reference = [ref_group("book", book.reference_dir, "Reference",
                                   "Read by every chat and build for this book: canon notes, research, a style sample.")]

        plan = book.read_plan()
        outlined = plan.chapters()
        drafted = book.drafted_chapters()
        settings = self.press_settings()
        chapters = []
        for n in sorted(set(outlined) | set(drafted)):
            chapters.append({
                "number": n,
                "title": (outlined[n].title if n in outlined else "") or _written_title(drafted.get(n, "")),
                "words": count_words(drafted[n]) if n in drafted else 0,
                "state": book.chapter_state(n, plan),
                "path": rel(book.chapter_path(n)),
                "planned": settings.target_words(outlined[n]) if n in outlined else 0,
            })
        job = jobs.job_for(book)
        missing =[c["number"] for c in chapters if c["state"] == "missing"]
        reviews = sorted(book.notes_dir.glob("review_*.md"), reverse=True) if book.notes_dir.exists() else []
        ideas = sorted(book.notes_dir.glob("ideas_*.md"), reverse=True) if book.notes_dir.exists() else []
        runs = sorted((p for p in book.runs_dir.glob("*/report.md")), reverse=True) if book.runs_dir.exists() else []
        interrupted = ""
        if book.runs_dir.exists() and not (job and job.state == "running"):
            # Only the newest run matters: a later build has moved past older ones.
            started = sorted(
                (p for p in book.runs_dir.iterdir() if p.is_dir() and (p / "plan").is_dir()),
                key=lambda p: p.name,
            )
            if started and not (started[-1] / "report.md").exists():
                interrupted = rel(started[-1])
        parts = [
            {"label": "Series bible", "tokens": estimate_tokens(plan.series_bible)},
            {"label": "Reference notes", "tokens": sum(estimate_tokens(t) for _, t in plan.reference)},
            {"label": "Earlier books", "tokens": sum(estimate_tokens(b.text) for b in plan.earlier_books)},
            {"label": "Story bible", "tokens": estimate_tokens(plan.story_bible)},
            {"label": "Characters", "tokens": estimate_tokens(plan.characters)},
            {"label": "Outline", "tokens": estimate_tokens(plan.outline)},
            {"label": "Chapters", "tokens": sum(estimate_tokens(t) for t in drafted.values())},
        ]
        parts = [part for part in parts if part["tokens"]]
        context = sum(part["tokens"] for part in parts)
        limit = context_limit(self.config())
        long = min(LONG_PROMPT_TOKENS, int(limit * 0.6))
        return {
            "id": pid,
            "title": series.title,
            "kind": "Series" if is_series else "Standalone",
            "isSeries": is_series,
            "book": {"folder": book.root.name, "number": book.number, "title": book.title},
            "books": [{"folder": b.root.name, "number": b.number, "title": b.title} for b in books],
            "groups": groups,
            "reference": reference,
            "referenceTokens": sum(estimate_tokens(t) for _, t in plan.reference),
            "chapters": chapters,
            "words": sum(c["words"] for c in chapters),
            "missing": missing,
            "reviews": [{"name": p.name, "path": rel(p)} for p in reviews],
            "ideas": [{"name": p.name, "path": rel(p)} for p in ideas],
            "runs": [{"name": p.parent.name, "path": rel(p)} for p in runs],
            "interrupted": interrupted,
            # What every call about this book sends, against the size limit.
            "context": {"tokens": context, "limit": limit, "long": long, "parts": parts},
            "build": self._snap(series, job),
            "defaults": (
                ("Draft only" if settings.revision_rounds == 0 else
                 f"{settings.revision_rounds} revision round{'s' if settings.revision_rounds > 1 else ''}")
                + f" · about {settings.default_chapter_words:,} words a chapter"
            ),
            "exported": rel(book.export_path) if book.export_path.exists() else "",
        }

    # --- files ----------------------------------------------------------------

    def read_file(self, pid: str, path: str) -> dict:
        series = self.series(pid)
        target = chat.resolve(series, path)
        if not target.is_file():
            raise StudioError(f"{path} doesn't exist yet.")
        text = read_text(target)
        editable = chat.writable(series, target) or target.parent.name == "manuscript"
        result = {"path": path, "text": text, "version": chat.version(text), "editable": editable, "words": count_words(text)}
        if _point_file(target):
            result["points"] = chat.review_points(text)
            result["kind"] = "ideas" if target.name.startswith("ideas_") else "review"
        return result

    def save_file(self, pid: str, path: str, text: str, expected_version: str | None = None) -> dict:
        """The writer's own edit. A chapter's previous version goes to history."""
        series = self.series(pid)
        target = chat.resolve(series, path)
        if not (target.parent.name == "manuscript" and re.fullmatch(r"chapter_\d+\.md", target.name)) and not chat.writable(series, target):
            raise StudioError(f"{path} can't be edited here.")
        with self._lock:
            current = read_text(target) if target.exists() else ""
            if expected_version is not None and chat.version(current) != expected_version:
                raise StudioError("This file changed while you were editing. Your draft is still in the editor. Copy it, then reopen the file to compare before saving.")
            if target.name in BIBLES:
                series.untie_titles()
            chat.save_text(target, text.rstrip() + "\n")
        return self.read_file(pid, path)

    def set_title(self, pid: str, title: str, folder: str | None = None) -> dict:
        """The project's name is the heading of its series bible, or of the book's
        story bible when there is no series bible. Returns the project's id,
        which changes when an untitled project's folders take the new name, and
        the open book's folder under that name."""
        title = " ".join(title.split())
        if not title:
            raise StudioError("Type a title first.")
        series = self.series(pid)
        number = self.book(series, folder).number
        target = series.bible_path if series.bible_path.exists() else self.book(series, folder).bible_path
        with self._lock:
            if pid in self._turns:
                raise StudioError("Stop the current turn, or let it finish, before renaming the book.")
            lines = read_text(target).splitlines() if target.exists() else []
            first = next((i for i, line in enumerate(lines) if line.strip()), None)
            if first is not None and lines[first].startswith("# "):
                lines[first] = f"# {title}"
            else:
                lines[:0] = [f"# {title}", ""]
            series.untie_titles()
            chat.save_text(target, "\n".join(lines).rstrip() + "\n")
            new_pid = self._settle_names(pid)
            books = self.series(new_pid).books()
            return {"project": new_pid, "book": next(b.root.name for b in books if b.number == number)}

    def _keep_reference(self, folder: Path, name: str, text: str) -> Path:
        safe = re.sub(r"[^\w.\- ]", "", Path(name).stem).strip() or "reference"
        with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{safe}.md"
            n = 2
            while target.exists():
                target = folder / f"{safe}-{n}.md"
                n += 1
            target.write_text(text, encoding="utf-8")
        return target

    def add_reference(self, pid: str, scope: str, folder: str | None, name: str, data_b64: str) -> dict:
        series = self.series(pid)
        target_dir = series.reference_dir if scope == "series" else self.book(series, folder).reference_dir
        filename, text = to_text(name, base64.b64decode(data_b64))
        self._keep_reference(target_dir, filename, text)
        return self.project(pid, folder)

    def remove_reference(self, pid: str, path: str, folder: str | None = None) -> dict:
        series = self.series(pid)
        target = chat.resolve(series, path)
        if target.parent.name != "reference" or not target.is_file():
            raise StudioError("That isn't a reference file.")
        with self._lock:
            history_copy(target)
            target.unlink()
        return self.project(pid, folder)

    def attachment(self, name: str, data_b64: str) -> dict:
        filename, text = to_text(name, base64.b64decode(data_b64))
        return {"name": name, "text": text, "tokens": estimate_tokens(text)}

    # --- chats ----------------------------------------------------------------

    def _chats_dir(self, series: Series) -> Path:
        return series.root / "chats"

    def _chat_path(self, series: Series, cid: str) -> Path:
        if not re.fullmatch(r"[\w-]+", cid):
            raise StudioError("That chat doesn't exist.")
        return self._chats_dir(series) / f"{cid}.json"

    def load_chat(self, pid: str, cid: str) -> dict:
        with self._lock:
            return self._load_chat(pid, cid)

    def _load_chat(self, pid: str, cid: str) -> dict:
        active = self._turns.get(pid)
        if active and active["record"]["id"] == cid:
            return active["record"]
        series = self.series(pid)
        path = self._chat_path(series, cid)
        if not path.exists():
            if cid == PROJECT_CHAT:
                return {"id": cid, "project": series.root.name, "title": "Project chat", "book": None,
                        "created": _now(), "updated": "", "items": [], "history": []}
            raise StudioError("That chat doesn't exist.")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("turn", {}).get("state") == "running":
            self._finish_turn(pid, record, "interrupted", "The app stopped during this turn. Completed changes have been kept. Send a follow-up to continue.")
        return record

    def _save_chat(self, pid: str, record: dict) -> dict:
        series = self.series(pid)
        path = self._chat_path(series, record["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            temporary = path.with_suffix(f".{threading.get_ident()}.tmp")
            temporary.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
            # On Windows a file being read elsewhere (OneDrive syncing it, an
            # antivirus scan) can't be replaced for a moment; wait it out.
            for attempt in range(10):
                try:
                    temporary.replace(path)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        return record

    def _chat_summaries(self, series: Series) -> list[dict]:
        folder = self._chats_dir(series)
        out = []
        if folder.is_dir():
            for path in folder.glob("*.json"):
                # Long chats carry every change's before-and-after text, so
                # read each file again only when it has changed.
                try:
                    stat = path.stat()
                    key = (stat.st_mtime_ns, stat.st_size)
                    cached = self._summaries.get(path)
                    if cached and cached[0] == key:
                        if cached[1]:
                            out.append(cached[1])
                        continue
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                items = record.get("items") if isinstance(record, dict) else None
                if not isinstance(items, list) or not record.get("id"):
                    # A half-written or older chat shouldn't take down the library;
                    # leave the file alone and show the others.
                    self._summaries[path] = (key, None)
                    continue
                said = [i for i in items if isinstance(i, dict)
                        and i.get("kind") in ("user", "assistant") and i.get("text")]
                snippet = said[-1]["text"] if said else ""
                summary = {
                    "id": record["id"], "title": record.get("title", "Untitled chat"),
                    "updated": record.get("updated", ""), "snippet": snippet[:140],
                }
                self._summaries[path] = (key, summary)
                out.append(summary)
        out.sort(key=lambda c: c["updated"], reverse=True)
        return out

    def recents(self) -> list[dict]:
        out = []
        for project in self.projects():
            for c in project["chats"]:
                out.append({**c, "project": project["id"], "projectTitle": project["title"]})
        out.sort(key=lambda c: c["updated"], reverse=True)
        return out

    def new_chat(self, pid: str, backend: str = "", model: str = "", effort: str | None = None) -> dict:
        """A new chat, on the model (and effort) picked before it started, if any."""
        series = self.series(pid)
        record = {
            "id": chat.new_id("c"), "project": pid, "title": "New chat", "book": None,
            "created": _now(), "updated": _now(), "history": [],
            "items": [{"kind": "assistant", "id": chat.new_id("m"), "text":
                       f"What would you like to work on in {series.title}? I can see its plan, chapters and notes."}],
        }
        record = self._save_chat(pid, record)
        if backend and model:
            record = self.set_chat_model(pid, record["id"], backend, model)
        if effort is not None:
            record = self.set_chat_effort(pid, record["id"], effort)
        return record

    def set_chat_model(self, pid: str, cid: str, backend: str, model: str) -> dict:
        """Choose the model for one chat. New model means the old effort is cleared."""
        config = self.config()
        models = ((config.get("models") or {}).get(backend) or {}).get("models") or {}
        entry = models.get(model)
        if entry is None or (isinstance(entry, dict) and entry.get("hidden")):
            raise StudioError("That model isn't available. Pick another in the chat.")
        with self._lock:
            record = self._load_chat(pid, cid)
            current = record.get("model") or {}
            if current.get("backend") == backend and current.get("model") == model:
                return record
            record["model"] = {"backend": backend, "model": model}
            record["effort"] = ""
            self._save_chat(pid, record)
            return record

    def set_chat_effort(self, pid: str, cid: str, effort: str) -> dict:
        """Set this chat's reasoning effort, checked against its model."""
        config = self.config()
        with self._lock:
            record = self._load_chat(pid, cid)
            chosen = record.get("model") or {}
            base = (config.get("agent_routing") or {}).get("studio_chat") or {}
            backend = chosen.get("backend") or base.get("backend")
            model = chosen.get("model") or base.get("model")
            entry = (((config.get("models") or {}).get(backend) or {}).get("models") or {}).get(model)
            efforts = entry.get("efforts") if isinstance(entry, dict) else []
            if effort and effort not in (efforts or []):
                raise StudioError("That effort isn't available for this model.")
            record["effort"] = effort
            self._save_chat(pid, record)
            return record

    def _chat_routing(self, record: dict) -> dict | None:
        """The routing for a chat's chosen model, or None to use the studio_chat role."""
        config = self.config()
        base = (config.get("agent_routing") or {}).get("studio_chat") or {}
        chosen = record.get("model") or {}
        backend = chosen.get("backend") or base.get("backend")
        model = chosen.get("model") or base.get("model")
        if not backend or not model:
            return None
        models = ((config.get("models") or {}).get(backend) or {}).get("models") or {}
        if model not in models:
            return None
        base_params = copy.deepcopy(base.get("params") or {})
        changed = (backend, model) != (base.get("backend"), base.get("model"))
        params = {} if changed else copy.deepcopy(base_params)
        # OpenRouter server tools belong to the chat wherever it runs on cloud.
        if changed and backend == "cloud" and base_params.get("tools"):
            params["tools"] = copy.deepcopy(base_params["tools"])
        if "effort" in record:
            params.pop("reasoning", None)
            effort = record.get("effort") or ""
            if effort:
                params["reasoning"] = {"effort": effort}
        if not changed and params == base_params:
            return None
        return {"backend": backend, "model": model, "params": params}

    def send(self, pid: str, cid: str, text: str, attachments: list[dict] | None = None,
             folder: str | None = None, on_event: Callable | None = None,
             selection: dict | None = None, explore: bool = False,
             edit_mode: str = "auto") -> dict:
        notify = on_event or (lambda event: None)
        edit_mode = "ask" if edit_mode == "ask" else "auto"
        with self._lock:
            if pid in self._turns:
                raise StudioError("The Room is already working in this project. Stop that turn or wait for it to finish.")
            series = self.series(pid)
            record = self.load_chat(pid, cid)
            book = self.book(series, record.get("book") or folder)
            if not text.strip() and not attachments:
                raise StudioError("Type a message first.")
            prompt = text.strip()
            if selection:
                selected = self.read_file(pid, selection["path"])
                if selected["version"] != selection.get("version"):
                    raise StudioError("The selected document changed. Open it and select the passage again.")
                prompt = f"Selected passage from {selection['path']} (as displayed):\n{selection['text']}\n\n{prompt}"
            if explore:
                prompt += "\n\n[Just exploring: do not change any files.]"
            for a in attachments or []:
                if a.get("scope", "chat") not in ("message", "chat", "book", "series") or not isinstance(a.get("text"), str) or not isinstance(a.get("name"), str):
                    raise StudioError("Choose where to keep each attachment and try again.")
            self.router_check()
            settings = self.press_settings()
            routing = self._chat_routing(record)
            files, added = [], []
            for a in attachments or []:
                scope = a.get("scope", "chat")
                entry = {"name": a["name"], "scope": scope}
                if scope == "message":
                    files.append((a["name"], a["text"]))
                else:
                    target = {"chat": self._chats_dir(series) / f"{cid}-files", "book": book.reference_dir, "series": series.reference_dir}[scope]
                    path = self._keep_reference(target, a["name"], a["text"])
                    entry["path"] = chat.rel(series, path)
                    if scope == "chat":
                        record.setdefault("attachments", []).append(entry)
                added.append(entry)
            for a in record.get("attachments", []):
                path = chat.resolve(series, a["path"])
                if path.is_file():
                    files.append((a["name"], path.read_text(encoding="utf-8")))
            record["items"].append({"kind": "user", "id": chat.new_id("m"), "text": text.strip(),
                                    "files": [a["name"] for a in added], "attachments": added,
                                    "selection": selection, "explore": explore})
            record["turn"] = {"id": chat.new_id("t"), "state": "running", "phase": "Reading your files…",
                              "text": "", "prompt": prompt, "start": len(record["items"]),
                              "files": [a["name"] for a in added], "tools": []}
            record["book"] = book.root.name
            record["edit_mode"] = edit_mode
            if record["title"] in ("New chat", "Project chat") and cid != PROJECT_CHAT and text.strip():
                record["title"] = " ".join(text.split()[:6]) + ("…" if len(text.split()) > 6 else "")
            cancel = threading.Event()
            self._turns[pid] = {"record": record, "cancel": cancel}
            history = list(record["history"])
            self._save_chat(pid, record)

        last_save = time.monotonic()

        def event(e):
            nonlocal last_save
            with self._lock:
                turn = record["turn"]
                if e["kind"] == "phase":
                    # Text still showing is a draft being redone: it stays until new text replaces it.
                    turn["phase"], turn["fresh"] = e["text"], True
                elif e["kind"] == "text":
                    if turn.pop("fresh", False):
                        turn["text"] = ""
                    turn["text"] += e["text"]
                elif e["kind"] == "item":
                    record["items"].append(e["item"])
                    record["book"] = e.get("book", record["book"])
                    turn["text"] = ""
                elif e["kind"] == "tool":
                    tools = turn.setdefault("tools", [])
                    entry = next((t for t in tools if t.get("id") == e.get("id")), None)
                    value = {k: e.get(k) for k in ("id", "name", "target", "status", "detail")}
                    if entry is None:
                        tools.append(value)
                    else:
                        entry.update(value)
                if e["kind"] != "text" or time.monotonic() - last_save > 0.5:
                    record["updated"] = _now()
                    self._save_chat(pid, record)
                    last_save = time.monotonic()
            notify(e)

        try:
            notify({"kind": "started", "record": record})
            result = self._run(lambda r: chat.run_turn(
                series, book, r, history, prompt, settings, files,
                on_event=event, should_stop=cancel.is_set, explore=explore, write_lock=self._lock,
                selection=selection, edit_mode=edit_mode, routing=routing,
            ))
            record["book"] = result.book.root.name if result.book else record["book"]
            record["turn"]["usage"] = result.usage.describe()
            self._finish_turn(pid, record, "finished", result.reply)
        except chat.TurnStopped:
            self._finish_turn(pid, record, "stopped", "Stopped. Completed changes have been kept. Send your next instruction whenever you're ready.")
        except Exception as exc:
            logging.getLogger(__name__).exception("Planning turn failed")
            detail = str(exc) if isinstance(exc, StudioError) else (
                provider_error(exc) or f"Something went wrong during this turn ({str(exc)[:200]})."
            )
            self._finish_turn(pid, record, "failed", detail + " Completed changes have been kept; send a follow-up to continue.")
        finally:
            with self._lock:
                self._turns.pop(pid, None)
                pid = self._settle_names(pid)
                record = self.load_chat(pid, cid)
        notify({"kind": "done", "record": record})
        return record

    def _finish_turn(self, pid: str, record: dict, state: str, reply: str) -> None:
        with self._lock:
            turn = record["turn"]
            for tool in turn.get("tools", []):
                if tool.get("status") == "running":
                    tool["status"] = "stopped"
            if state != "finished" and turn.get("text", "").strip():
                record["items"].append({"kind": "assistant", "id": chat.new_id("m"), "text": turn["text"], "incomplete": True})
            items = record["items"][turn["start"]:]
            record["history"] += chat.history_entries(turn["prompt"], [(n, "") for n in turn["files"]], chat.TurnResult(reply, items))
            record["items"].append({"kind": "assistant", "id": chat.new_id("m"), "text": reply})
            turn.pop("fresh", None)
            turn.update(state=state, text="", phase="")
            record["updated"] = _now()
            self._save_chat(pid, record)

    def stop_turn(self, pid: str, cid: str) -> dict:
        with self._lock:
            active = self._turns.get(pid)
            if active and active["record"]["id"] == cid:
                active["cancel"].set()
            return {"stopping": bool(active and active["record"]["id"] == cid)}

    def forget_attachment(self, pid: str, cid: str, path: str) -> dict:
        with self._lock:
            if pid in self._turns:
                raise StudioError("Stop the current turn before removing its reference.")
            record = self.load_chat(pid, cid)
            record["attachments"] = [a for a in record.get("attachments", []) if a["path"] != path]
            return self._save_chat(pid, record)

    def _settle_names(self, pid: str) -> str:
        """Once an untitled project has a real name, rename its folders to match,
        so the library on disk reads like the app. Returns the project's id."""
        series = self.series(pid)
        # A running build writes into these folders, so they keep their names
        # until it finishes; a folder Windows or OneDrive has open is tried again
        # after the next turn.
        building = any((job := jobs.job_for(b)) and job.state == "running" for b in series.books())
        moved: list[tuple[str, str]] = []
        for book in series.books():
            slug = slugify(book.title)
            if building or not book.slug.startswith("untitled-book") or not slug or slug.startswith("untitled"):
                continue
            target = book.root.with_name(f"{book.number:02d}-{slug}")
            if not target.exists():
                try:
                    book.root.rename(target)
                except OSError:
                    continue
                moved.append((book.root.name, target.name))
        new_pid = pid
        slug = slugify(series.title)
        if not building and pid.startswith("untitled-") and slug and not slug.startswith("untitled"):
            target = self.library.root / slug
            if not target.exists():
                try:
                    series.root.rename(target)
                    new_pid = slug
                    self._moved[pid] = new_pid
                except OSError:
                    pass
        if moved or new_pid != pid:
            for path in (self.library.root / new_pid / "chats").glob("*.json"):
                text = path.read_text(encoding="utf-8")
                for old, new in moved:
                    text = text.replace(f"books/{old}/", f"books/{new}/").replace(f'"{old}"', f'"{new}"')
                text = text.replace(f'"project": "{pid}"', f'"project": "{new_pid}"')
                path.write_text(text, encoding="utf-8")
        return new_pid

    def _item(self, record: dict, item_id: str) -> tuple[int, dict]:
        for i, item in enumerate(record["items"]):
            if item.get("id") == item_id:
                return i, item
        raise StudioError("That message isn't in this chat any more.")

    def undo(self, pid: str, cid: str, item_id: str) -> dict:
        with self._lock:
            if pid in self._turns:
                raise StudioError("Stop the current planning turn before undoing a change.")
            series = self.series(pid)
            record = self.load_chat(pid, cid)
            i, item = self._item(record, item_id)
            record["items"][i] = chat.undo(series, item)
            state = "undid" if record["items"][i]["undone"] else "redid"
            record["history"].append({"role": "user", "content": f"[The writer {state} the change: {item['verb']} {item['file']}: {item['text']}]"})
            record["history"].append({"role": "assistant", "content": "Noted."})
            record["updated"] = _now()
            return self._save_chat(pid, record)

    # --- review ---------------------------------------------------------------

    def review_call(self, pid: str, path: str, number: int, call: str) -> dict:
        series = self.series(pid)
        target = chat.resolve(series, path)
        if not _point_file(target):
            raise StudioError("That isn't a review or an ideas file.")
        chat.record_call(target, int(number), call)
        return self.read_file(pid, path)

    def decide_proposal(self, pid: str, cid: str, item_id: str, decision: str) -> dict:
        """Accept a staged change, or keep the writer's original text."""
        if decision not in ("accept", "keep"):
            raise StudioError("That isn't a choice for this suggestion.")
        with self._lock:
            if pid in self._turns:
                raise StudioError("Wait for the Room to finish this turn before deciding on a suggestion.")
            series = self.series(pid)
            record = self.load_chat(pid, cid)
            i, item = self._item(record, item_id)
            if item.get("kind") != "proposal":
                raise StudioError("That item isn't a suggested change.")
            if item.get("status") != "pending":
                raise StudioError("That suggestion has already been decided.")

            if decision == "keep":
                record["items"][i] = {**item, "status": "rejected"}
                record["history"] += [
                    {"role": "user", "content": f"[The writer kept their original text instead of the staged change: {item['text']}]"},
                    {"role": "assistant", "content": "Noted."},
                ]
                record["updated"] = _now()
                return self._save_chat(pid, record)

            target = chat.resolve(series, item["file"])
            current = read_text(target) if target.exists() else None
            chapter = re.fullmatch(r"chapter_(\d+)\.md", target.name) if target.parent.name == "manuscript" else None
            if not chapter and not chat.writable(series, target):
                raise StudioError("That suggestion points at a file the Room can't write.")
            if current != item.get("before"):
                record["items"][i] = {**item, "status": "stale"}
                record["history"] += [
                    {"role": "user", "content": "[The writer accepted a staged change, but the file had changed since it was staged. Both versions were kept.]"},
                    {"role": "assistant", "content": "Noted."},
                ]
                record["updated"] = _now()
                return self._save_chat(pid, record)

            if item.get("after") is None:
                raise StudioError("That suggestion has no new text to apply.")
            target_book = next((b for b in series.books() if b.manuscript_dir == target.parent), None) if chapter else None
            if chapter and not target_book:
                raise StudioError("That chapter isn't in this series any more.")
            if chapter and target_book:
                target_book.write_chapter(
                    int(chapter[1]), item["after"], target_book.read_plan(), "passage"
                )
            else:
                if target.name in BIBLES:
                    series.untie_titles()
                chat.save_text(target, item["after"])
            record["items"][i] = {
                "kind": "activity", "id": item["id"], "verb": item.get("verb", "Edited"),
                "file": item["file"], "text": item["text"], "before": item.get("before"),
                "after": item["after"],
            }
            record["history"] += [
                {"role": "user", "content": f"[The writer accepted the staged change: {item['text']}]"},
                {"role": "assistant", "content": "Noted."},
            ]
            record["updated"] = _now()
            return self._save_chat(pid, record)


    # --- press ----------------------------------------------------------------

    def estimate(self, pid: str, folder: str | None, which: str) -> dict:
        series = self.series(pid)
        book = self.book(series, folder)
        plan = book.read_plan()
        numbers = press.select_chapters(book, plan, str(which))
        settings = self.press_settings()
        guess = press.estimate(book, plan, numbers, settings)
        existing = [n for n in numbers if book.chapter_path(n).exists()]
        listed = ", ".join(str(n) for n in numbers)
        detail = guess.describe().capitalize() + "."
        config = self.config()
        cost = build_cost(config, guess)
        if cost is not None:
            detail += (f" At list prices that's roughly {'under $0.01' if cost < 0.01 else f'${cost:,.2f}'};"
                       " prompt caching usually brings it down.")
        limit = context_limit(config)
        if guess.largest_call > limit:
            detail += (
                f" The selected model can read about {limit:,} tokens, so this build would exceed "
                "its window. Choose a larger model or write story-so-far notes for finished books."
            )
        if existing:
            detail += " This replaces the current version; the old one is kept in history."
        chapters = plan.chapters().values()
        return {"numbers": numbers, "title": f"Build chapter{'s' if len(numbers) > 1 else ''} {listed}?",
                "detail": detail,
                "press": {"revision_rounds": settings.revision_rounds,
                          "default_chapter_words": settings.default_chapter_words,
                          # Chapter length only matters when the outline leaves one unsized.
                          "unsized": sum(1 for c in chapters if c.number in numbers and not c.words)}}

    def build(self, pid: str, folder: str | None, which: str, cid: str | None = None, item_id: str | None = None) -> dict:
        series = self.series(pid)
        book = self.book(series, folder)
        plan = book.read_plan()
        numbers = press.select_chapters(book, plan, str(which))
        self.router_check()

        def finished(job: jobs.BuildJob) -> None:
            if cid:
                with self._lock:  # a planning turn may be updating the same chat
                    report(job)

        def report(job: jobs.BuildJob) -> None:
            record = self.load_chat(pid, cid)
            snap = job.snapshot()
            if snap["state"] == "failed":
                text = snap["error"] or "The build stopped."
            else:
                done = ", ".join(str(r["number"]) for r in snap["results"]) or "none"
                words = sum(r["words"] for r in snap["results"])
                text = (
                    f"{'Stopped' if snap['state'] == 'stopped' else 'Finished'}: chapter(s) {done}, "
                    f"{words:,} words. {snap['usage'] or ''}"
                ).strip()
            # A discarded revision or an overlong chapter shouldn't wait to be
            # found in the report; this line also tells the chat model.
            notes = [f"Chapter {r['number']}: {note}" for r in snap["results"] for note in r["notes"]]
            if notes:
                text = " ".join([text.rstrip(".") + "."] + notes)
            record["items"].append({
                "kind": "result", "id": chat.new_id("m"), "text": text,
                "report": chat.rel(series, Path(snap["report"])) if snap["report"] else "",
            })
            record["history"] += [
                {"role": "user", "content": f"[The press built chapters: {text}]"},
                {"role": "assistant", "content": "Noted."},
            ]
            record["updated"] = _now()
            self._save_chat(pid, record)

        job = jobs.start_build(book, self.router, numbers, self.press_settings(), finished)
        if cid and item_id:
            record = self.load_chat(pid, cid)
            i, item = self._item(record, item_id)
            record["items"][i] = {**item, "status": "approved"}
            self._save_chat(pid, record)
        return self._snap(series, job)

    @staticmethod
    def _snap(series: Series, job: jobs.BuildJob | None) -> dict | None:
        if not job:
            return None
        snap = job.snapshot()
        if snap["report"]:
            snap["report"] = chat.rel(series, Path(snap["report"]))
        return snap

    def router_check(self) -> None:
        router = self.router()
        if not self._make_router:
            asyncio.run(router.close())

    def decline_build(self, pid: str, cid: str, item_id: str) -> dict:
        record = self.load_chat(pid, cid)
        i, item = self._item(record, item_id)
        record["items"][i] = {**item, "status": "declined"}
        record["history"] += [
            {"role": "user", "content": "[The writer chose not to build yet.]"},
            {"role": "assistant", "content": "Noted."},
        ]
        return self._save_chat(pid, record)

    def build_status(self, pid: str, folder: str | None = None) -> dict | None:
        series = self.series(pid)
        return self._snap(series, jobs.job_for(self.book(series, folder)))

    def stop_build(self, pid: str, folder: str | None = None) -> dict | None:
        series = self.series(pid)
        job = jobs.job_for(self.book(series, folder))
        if job:
            job.stop()
        return self._snap(series, job)

    def export(self, pid: str, folder: str | None = None) -> dict:
        series = self.series(pid)
        path = press.export_book(self.book(series, folder))
        return {"path": chat.rel(series, path), "text": path.read_text(encoding="utf-8")}

    # --- settings -------------------------------------------------------------

    def _overlay(self) -> dict:
        path = local_overlay_path(self.config_path)
        return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}

    def _write_overlay(self, overlay: dict) -> None:
        local_overlay_path(self.config_path).write_text(
            "# Written by the Writers Room app. Overrides config/settings.yaml.\n"
            + yaml.safe_dump(overlay, sort_keys=False),
            encoding="utf-8",
        )

    def _connected(self, config: dict, backend: str) -> bool:
        cfg = config["models"][backend]
        if backend == "local":
            return bool(self._overlay().get("models", {}).get("local", {}).get("base_url"))
        env = cfg.get("api_key_env")
        return bool(env and os.environ.get(env))

    def settings(self) -> dict:
        config = self.config()
        backends = [b for b in PROVIDER_ORDER if b in config["models"]]
        backends += [b for b in config["models"] if b not in backends]
        providers = []
        for b in backends:
            cfg = config["models"][b]
            env = cfg.get("api_key_env")
            key = os.environ.get(env, "") if env else ""
            providers.append({
                "key": b, "name": cfg.get("label", b), "recommended": b == "cloud",
                "blurb": PROVIDER_BLURBS.get(b, ""), "kind": "address" if b == "local" else "key",
                "env": env or "", "connected": self._connected(config, b),
                "masked": ("••••" + key[-4:]) if key else "",
                "address": cfg.get("base_url", "") if b == "local" else "",
            })
        connected = [p["key"] for p in providers if p["connected"]]
        roles = []
        for role, label, blurb in ROLES:
            routing = (config.get("agent_routing") or {}).get(role, {})
            options = []
            for b in connected:
                for alias, model in (config["models"][b].get("models") or {}).items():
                    if isinstance(model, dict) and model.get("hidden"):
                        continue
                    entry = model if isinstance(model, dict) else {}
                    context = int(entry.get("context") or 0)
                    options.append({
                        "backend": b, "model": alias,
                        "label": entry.get("label") or (model if isinstance(model, str) else "") or alias,
                        "provider": config["models"][b].get("label", b),
                        "efforts": entry.get("efforts") or [],
                        "suggested": bool(entry.get("suggested")),
                        # Dollars per million tokens read and written, from OpenRouter's catalog.
                        "price": entry.get("price"),
                        "context": context,
                        "small": 0 < context < MAX_PROMPT_TOKENS,
                    })
            current = {"backend": routing.get("backend"), "model": routing.get("model")}
            ok = any(o["backend"] == current["backend"] and o["model"] == current["model"] for o in options)
            params = routing.get("params") or {}
            model = (config["models"].get(current["backend"] or "", {}).get("models") or {}).get(current["model"])
            label_now = next((o["label"] for o in options
                              if o["backend"] == current["backend"] and o["model"] == current["model"]), current["model"])
            roles.append({
                "key": role, "label": label, "blurb": blurb, "current": current, "options": options, "available": ok,
                "currentLabel": label_now or "",
                "effort": (params.get("reasoning") or {}).get("effort", ""),
                "efforts": (model.get("efforts") if isinstance(model, dict) else None) or [],
                "web": any(t.get("type") == "openrouter:web_search" for t in params.get("tools") or []),
            })
        settings = press.PressSettings.from_config(config)
        chosen = (self._overlay().get("agent_routing") or {}).keys()
        return {
            "providers": providers, "roles": roles,
            # Automatic until the writer picks a model for one of the Press roles.
            "automatic": not any(role in chosen for role in PRESS_ROLES),
            "press": {"revision_rounds": settings.revision_rounds,
                      "default_chapter_words": settings.default_chapter_words},
            "library": {"path": str(self.library.root), "source": self.library_source},
        }

    def refresh_models(self) -> dict:
        """Update the OpenRouter model list once it's a day old. The page asks
        when Settings or the chat's model picker opens and doesn't wait; on any
        failure the lists stay as they were, and it tries again an hour later."""
        config = self.config()
        cloud = config["models"].get("cloud") or {}
        if "openrouter.ai" not in str(cloud.get("base_url", "")) or not self._connected(config, "cloud"):
            return {"updated": False}
        if not model_catalog.stale(self.config_path) or time.monotonic() - self._catalog_failed < 3600:
            return {"updated": False}
        if not self._catalog_lock.acquire(blocking=False):
            return {"updated": False}
        try:
            updated = model_catalog.refresh(self.config_path, self._fetch_catalog)
        finally:
            self._catalog_lock.release()
        if not updated:
            self._catalog_failed = time.monotonic()
        return {"updated": updated}

    def use_automatic(self) -> dict:
        """Forget the writer's model choices for the Press roles."""
        overlay = self._overlay()
        routing = overlay.get("agent_routing") or {}
        for role in PRESS_ROLES:
            routing.pop(role, None)
        if routing:
            overlay["agent_routing"] = routing
        else:
            overlay.pop("agent_routing", None)
        self._write_overlay(overlay)
        return self.settings()

    def set_library(self, path: str) -> dict:
        """Work from another library folder, and remember it for next time."""
        raw = path.strip().strip('"')
        if not raw:
            raise StudioError("Type or paste the folder's full path first.")
        folder = Path(raw).expanduser()
        if not folder.is_absolute():
            raise StudioError(f"Use the folder's full path, like C:\\Users\\you\\Documents\\Novels (not {raw}).")
        if not folder.is_dir():
            raise StudioError(f"I can't find a folder at {folder}. Create it first, or check the path.")
        overlay = self._overlay()
        overlay["library"] = str(folder)
        self._write_overlay(overlay)
        with self._lock:
            self.library = Library(folder)
            self.library_source = "saved"
        return self.settings()

    def set_key(self, backend: str, value: str) -> dict:
        config = self.config()
        if backend not in config["models"]:
            raise StudioError("Unknown provider.")
        value = value.strip()
        if "\n" in value or "\r" in value:
            raise StudioError("That doesn't look like a single key; paste it again on one line.")
        if backend == "local":
            overlay = self._overlay()
            local = overlay.setdefault("models", {}).setdefault("local", {})
            if value:
                local["base_url"] = value.rstrip("/")
            else:
                local.pop("base_url", None)
            self._write_overlay(overlay)
            return self.settings()
        env = config["models"][backend].get("api_key_env")
        if not env:
            raise StudioError("This provider doesn't use a key.")
        lines = self.env_path.read_text(encoding="utf-8").splitlines() if self.env_path.exists() else []
        lines = [line for line in lines if not line.startswith(f"{env}=")]
        if value:
            lines.append(f"{env}={value}")
            os.environ[env] = value
        else:
            os.environ.pop(env, None)
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.settings()

    def check(self, backend: str) -> dict:
        router = ModelRouter(str(self.config_path))

        async def go():
            try:
                return await router.check_backend(backend)
            finally:
                await router.close()

        ok, message = asyncio.run(go())
        if backend == "local":
            message = "Server reachable." if ok else message
        return {"ok": ok, "message": message}

    def set_role(self, role: str, backend: str, model: str) -> dict:
        if role not in dict((r, None) for r, _, _ in ROLES):
            raise StudioError("Unknown role.")
        config = self.config()
        entry = ((config.get("models") or {}).get(backend) or {}).get("models", {}).get(model)
        if entry is None or (isinstance(entry, dict) and entry.get("hidden")):
            raise StudioError("That model isn't available.")
        with open(self.config_path, encoding="utf-8") as f:
            base = (yaml.safe_load(f) or {}).get("agent_routing", {}).get(role, {})
        params = base.get("params", {}) if (base.get("backend"), base.get("model")) == (backend, model) else {}
        current = (self.config().get("agent_routing") or {}).get(role, {}).get("params") or {}
        if backend == "cloud" and "tools" in current:
            # OpenRouter's server tools (web search) work with any model there.
            params = {**params, "tools": current["tools"]}
        overlay = self._overlay()
        overlay.setdefault("agent_routing", {})[role] = {"backend": backend, "model": model, "params": params}
        self._write_overlay(overlay)
        return self.settings()

    def set_effort(self, role: str, effort: str) -> dict:
        """Set (or, with an empty effort, clear) a role's reasoning effort."""
        if role not in dict((r, None) for r, _, _ in ROLES):
            raise StudioError("Unknown role.")
        routing = (self.config().get("agent_routing") or {}).get(role) or {}
        params = {k: v for k, v in (routing.get("params") or {}).items() if k != "reasoning"}
        if effort:
            params["reasoning"] = {"effort": effort}
        overlay = self._overlay()
        overlay.setdefault("agent_routing", {})[role] = {
            "backend": routing.get("backend"), "model": routing.get("model"), "params": params,
        }
        self._write_overlay(overlay)
        return self.settings()

    def set_press(self, revision_rounds: int | None = None, default_chapter_words: int | None = None) -> dict:
        overlay = self._overlay()
        section = overlay.setdefault("press", {})
        if revision_rounds is not None:
            section["revision_rounds"] = max(0, min(3, int(revision_rounds)))
        if default_chapter_words is not None:
            section["default_chapter_words"] = max(500, int(default_chapter_words))
        self._write_overlay(overlay)
        return self.settings()
