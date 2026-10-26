"""What the app can do, as plain functions over the library. The web server in
``server.py`` turns HTTP requests into calls here; tests call them directly.

A project is a series folder in the library (a standalone book is a series of
one). Chats are saved next to the books, in ``<series>/chats/<id>.json``; the
project page's ongoing conversation is the chat called ``project``.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

from src.model_router import ModelRouter, load_config, local_overlay_path
from src.studio import chat, jobs, press, room
from src.studio.project import (
    REFERENCE_SUFFIXES,
    Book,
    Library,
    Series,
    StudioError,
    count_words,
    estimate_tokens,
    slugify,
)

PROJECT_CHAT = "project"
LARGE_REFERENCE_TOKENS = 50_000
PROVIDER_ORDER = ["cloud", "anthropic", "openai", "google", "local"]
ROLES = [
    ("studio_chat", "Chat", "Talks with you and edits your files."),
    ("studio_writer", "Writer", "Drafts and revises chapters."),
    ("studio_critic", "Critic", "Critiques each draft. A different model catches different things."),
    ("studio_reader", "Reviewer", "Second opinions and story-so-far notes."),
]
PROVIDER_BLURBS = {
    "cloud": "One key for every model here: DeepSeek, Gemini, Claude, GPT and more. Pay as you go.",
    "anthropic": "Claude models, directly from Anthropic.",
    "openai": "GPT models, directly from OpenAI.",
    "google": "Gemini models, directly from Google AI Studio.",
    "local": "A model running on this computer with Ollama or llama.cpp. Free and private, but slower and less capable.",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def to_text(name: str, data: bytes) -> tuple[str, str]:
    """A file the writer added, as (markdown name, text) the models can read."""
    suffix = Path(name).suffix.lower()
    if suffix in REFERENCE_SUFFIXES or suffix == ".markdown":
        return Path(name).stem + (".md" if suffix != ".txt" else ".txt"), data.decode("utf-8", errors="replace")
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
        f"I can read .md, .txt and .docx files. For {name}, copy its text into a .txt "
        "file or paste it into the chat."
    )


class App:
    def __init__(
        self,
        library: Library,
        config_path: Path,
        env_path: Path,
        make_router: Callable[[], object] | None = None,
    ):
        self.library = library
        self.config_path = Path(config_path)
        self.env_path = Path(env_path)
        self._make_router = make_router

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

    def create_project(self, idea: str, kind: str = "book") -> dict:
        if not idea.strip():
            raise StudioError("Type an idea first, even a single line.")
        self.router_check()  # fail before creating anything if no provider is set up
        if kind == "series":
            series_title = self._unique("Untitled series")
            book, _ = self.library.new_book("Untitled book", series_title=series_title)
        else:
            book, _ = self.library.new_book(self._unique("Untitled book"))
        record = self.send(book.series.root.name, PROJECT_CHAT, idea)
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
                    tokens = estimate_tokens(p.read_text(encoding="utf-8", errors="replace"))
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
        chapters = []
        for n in sorted(set(outlined) | set(drafted)):
            chapters.append({
                "number": n,
                "title": outlined[n].title if n in outlined else "",
                "words": count_words(drafted[n]) if n in drafted else 0,
                "state": book.chapter_state(n, plan),
                "path": rel(book.chapter_path(n)),
                "planned": self.press_settings().target_words(outlined[n]) if n in outlined else 0,
            })
        job = jobs.job_for(book)
        settings = self.press_settings()
        missing = [c["number"] for c in chapters if c["state"] == "missing"]
        reviews = sorted(book.notes_dir.glob("review_*.md"), reverse=True) if book.notes_dir.exists() else []
        runs = sorted((p for p in book.runs_dir.glob("*/report.md")), reverse=True) if book.runs_dir.exists() else []
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
            "runs": [{"name": p.parent.name, "path": rel(p)} for p in runs],
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
        text = target.read_text(encoding="utf-8", errors="replace")
        editable = chat.writable(series, target) or target.parent.name == "manuscript"
        result = {"path": path, "text": text, "editable": editable, "words": count_words(text)}
        if target.parent.name == "notes" and target.name.startswith("review_"):
            result["points"] = chat.review_points(text)
        return result

    def save_file(self, pid: str, path: str, text: str) -> dict:
        """The writer's own edit. A chapter's previous version goes to history."""
        series = self.series(pid)
        target = chat.resolve(series, path)
        if target.parent.name == "manuscript" and target.name.startswith("chapter_"):
            if target.exists():
                history = target.parent / ".history"
                history.mkdir(exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                (history / f"{target.stem}.{stamp}.md").write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        elif not chat.writable(series, target):
            raise StudioError(f"{path} can't be edited here.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.rstrip() + "\n", encoding="utf-8")
        return self.read_file(pid, path)

    def add_reference(self, pid: str, scope: str, folder: str | None, name: str, data_b64: str) -> dict:
        series = self.series(pid)
        target_dir = series.reference_dir if scope == "series" else self.book(series, folder).reference_dir
        filename, text = to_text(name, base64.b64decode(data_b64))
        safe = re.sub(r"[^\w.\- ]", "", filename).strip() or "reference.md"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / safe).write_text(text, encoding="utf-8")
        return self.project(pid, folder)

    def remove_reference(self, pid: str, path: str, folder: str | None = None) -> dict:
        series = self.series(pid)
        target = chat.resolve(series, path)
        if target.parent.name != "reference" or not target.is_file():
            raise StudioError("That isn't a reference file.")
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
        series = self.series(pid)
        path = self._chat_path(series, cid)
        if not path.exists():
            if cid == PROJECT_CHAT:
                return {"id": cid, "project": pid, "title": "Project chat", "book": None,
                        "created": _now(), "updated": "", "items": [], "history": []}
            raise StudioError("That chat doesn't exist.")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_chat(self, pid: str, record: dict) -> dict:
        series = self.series(pid)
        path = self._chat_path(series, record["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
        return record

    def _chat_summaries(self, series: Series) -> list[dict]:
        folder = self._chats_dir(series)
        out = []
        if folder.is_dir():
            for path in folder.glob("*.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                said = [i for i in record["items"] if i["kind"] in ("user", "assistant")]
                snippet = said[-1]["text"] if said else ""
                out.append({
                    "id": record["id"], "title": record["title"], "updated": record.get("updated", ""),
                    "snippet": snippet[:140],
                })
        out.sort(key=lambda c: c["updated"], reverse=True)
        return out

    def recents(self) -> list[dict]:
        out = []
        for project in self.projects():
            for c in project["chats"]:
                out.append({**c, "project": project["id"], "projectTitle": project["title"]})
        out.sort(key=lambda c: c["updated"], reverse=True)
        return out

    def new_chat(self, pid: str) -> dict:
        series = self.series(pid)
        record = {
            "id": chat.new_id("c"), "project": pid, "title": "New chat", "book": None,
            "created": _now(), "updated": _now(), "history": [],
            "items": [{"kind": "assistant", "id": chat.new_id("m"), "text":
                       f"What would you like to work on in {series.title}? I can see its plan, chapters and notes."}],
        }
        return self._save_chat(pid, record)

    def send(self, pid: str, cid: str, text: str, attachments: list[dict] | None = None, folder: str | None = None) -> dict:
        series = self.series(pid)
        record = self.load_chat(pid, cid)
        book = self.book(series, folder or record.get("book"))
        files = [(a["name"], a["text"]) for a in attachments or []]
        if not text.strip() and not files:
            raise StudioError("Type a message first.")
        settings = self.press_settings()
        result = self._run(lambda r: chat.run_turn(
            series, book, r, record["history"], text, settings, files
        ))
        record["items"].append({
            "kind": "user", "id": chat.new_id("m"), "text": text.strip(), "files": [n for n, _ in files],
        })
        record["items"] += result.items
        record["items"].append({"kind": "assistant", "id": chat.new_id("m"), "text": result.reply})
        record["history"] += chat.history_entries(text, files, result)
        record["book"] = result.book.root.name if result.book else book.root.name
        if record["title"] in ("New chat", "Project chat") and cid != PROJECT_CHAT and text.strip():
            words = text.split()
            record["title"] = " ".join(words[:6]) + ("…" if len(words) > 6 else "")
        record["updated"] = _now()
        self._save_chat(pid, record)
        pid = self._settle_names(pid)
        return self.load_chat(pid, cid)

    def _settle_names(self, pid: str) -> str:
        """Once an untitled project has a real name, rename its folders to match,
        so the library on disk reads like the app. Returns the project's id."""
        series = self.series(pid)
        moved: list[tuple[str, str]] = []
        for book in series.books():
            slug = slugify(book.title)
            job = jobs.job_for(book)
            if (book.slug.startswith("untitled-book") and slug and not slug.startswith("untitled")
                    and not (job and job.state == "running")):
                target = book.root.with_name(f"{book.number:02d}-{slug}")
                if not target.exists():
                    moved.append((book.root.name, target.name))
                    book.root.rename(target)
        new_pid = pid
        slug = slugify(series.title)
        if pid.startswith("untitled-") and slug and not slug.startswith("untitled"):
            target = self.library.root / slug
            if not target.exists():
                series.root.rename(target)
                new_pid = slug
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
        if target.parent.name != "notes" or not target.name.startswith("review_"):
            raise StudioError("That isn't a review.")
        chat.record_call(target, int(number), call)
        return self.read_file(pid, path)

    def review(self, pid: str, folder: str | None = None) -> dict:
        series = self.series(pid)
        book = self.book(series, folder)
        path = self._run(lambda r: room.review(book, r))
        return self.read_file(pid, chat.rel(series, path))

    # --- press ----------------------------------------------------------------

    def estimate(self, pid: str, folder: str | None, which: str) -> dict:
        series = self.series(pid)
        book = self.book(series, folder)
        plan = book.read_plan()
        numbers = press.select_chapters(book, plan, str(which))
        guess = press.estimate(book, plan, numbers, self.press_settings())
        existing = [n for n in numbers if book.chapter_path(n).exists()]
        listed = ", ".join(str(n) for n in numbers)
        detail = guess.describe().capitalize() + "."
        if existing:
            detail += " This replaces the current version; the old one is kept in history."
        return {"numbers": numbers, "title": f"Build chapter{'s' if len(numbers) > 1 else ''} {listed}?",
                "detail": detail}

    def build(self, pid: str, folder: str | None, which: str, cid: str | None = None, item_id: str | None = None) -> dict:
        series = self.series(pid)
        book = self.book(series, folder)
        plan = book.read_plan()
        numbers = press.select_chapters(book, plan, str(which))
        self.router_check()

        def finished(job: jobs.BuildJob) -> None:
            if not cid:
                return
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
                    options.append({
                        "backend": b, "model": alias,
                        "label": (model.get("label") if isinstance(model, dict) else model) or alias,
                        "provider": config["models"][b].get("label", b),
                    })
            current = {"backend": routing.get("backend"), "model": routing.get("model")}
            ok = any(o["backend"] == current["backend"] and o["model"] == current["model"] for o in options)
            roles.append({"key": role, "label": label, "blurb": blurb, "current": current,
                          "options": options, "available": ok})
        settings = press.PressSettings.from_config(config)
        return {
            "providers": providers, "roles": roles,
            "press": {"revision_rounds": settings.revision_rounds,
                      "default_chapter_words": settings.default_chapter_words},
        }

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
        with open(self.config_path, encoding="utf-8") as f:
            base = (yaml.safe_load(f) or {}).get("agent_routing", {}).get(role, {})
        params = base.get("params", {}) if (base.get("backend"), base.get("model")) == (backend, model) else {}
        overlay = self._overlay()
        overlay.setdefault("agent_routing", {})[role] = {"backend": backend, "model": model, "params": params}
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
