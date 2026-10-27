"""Press builds running in the background, for the app and the plugin's tools.

A build can take a long while, so it runs on its own thread with its own
event loop, and anyone can read its progress or ask it to stop after the
chapter in progress. One build per book at a time.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime
from typing import Callable

from src.studio import press
from src.studio.llm import provider_error
from src.studio.project import Book, StudioError

logger = logging.getLogger(__name__)

_jobs: dict[str, "BuildJob"] = {}
_lock = threading.Lock()


class BuildJob:
    def __init__(
        self,
        book: Book,
        make_router: Callable,
        numbers: list[int],
        settings: press.PressSettings,
        on_finish: Callable[["BuildJob"], None] | None = None,
    ):
        self.book = book
        self.make_router = make_router
        self.numbers = list(numbers)
        self.settings = settings
        self.on_finish = on_finish
        self.state = "running"  # running | finished | stopped | failed
        self.current: int | None = None
        self.step: str | None = None
        self.results: list[dict] = []
        self.error: str | None = None
        self.report: str | None = None
        self.usage: str | None = None
        self.stop_requested = False
        self.started = datetime.now().isoformat(timespec="seconds")
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "BuildJob":
        self._thread.start()
        return self

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def stop(self) -> None:
        self.stop_requested = True

    def _run(self) -> None:
        try:
            asyncio.run(self._build())
        finally:
            if self.on_finish:
                try:
                    self.on_finish(self)
                except Exception:
                    logger.exception("Build finish callback failed")

    async def _build(self) -> None:
        def started(chapter):
            self.current, self.step = chapter.number, "drafting"

        def stepped(number, name):
            self.current, self.step = number, name

        def finished(result):
            self.results.append({
                "number": result.number,
                "title": result.title,
                "words": result.final_words,
                "target": result.target_words,
                "revisions": result.revisions_kept,
                "calls": result.usage.calls,
                "notes": list(result.notes),
            })

        try:
            router = self.make_router()
        except StudioError as exc:
            self.state, self.error = "failed", str(exc)
            return
        try:
            result = await press.build(
                self.book, router, self.numbers, self.settings,
                on_start=started, on_done=finished, on_step=stepped,
                should_stop=lambda: self.stop_requested,
            )
            self.report = str(result.report_path)
            self.usage = result.usage.describe()
            self.state = "stopped" if len(self.results) < len(self.numbers) else "finished"
        except StudioError as exc:
            self.state, self.error = "failed", str(exc)
        except Exception as exc:  # shown to the writer rather than lost on a thread
            explained = provider_error(exc)
            if explained is None:
                logger.exception("Build failed")
            self.state = "failed"
            self.error = (
                f"{explained} Chapters finished before this were saved; nothing half-done was."
                if explained else f"The build stopped unexpectedly: {exc}"
            )
        finally:
            self.current = self.step = None
            await router.close()

    def snapshot(self) -> dict:
        return {
            "book": self.book.root.name,
            "state": self.state,
            "numbers": self.numbers,
            "current": self.current,
            "step": self.step,
            "results": list(self.results),
            "error": self.error,
            "report": self.report,
            "usage": self.usage,
            "stopping": self.stop_requested and self.state == "running",
            "started": self.started,
        }


def start_build(
    book: Book,
    make_router: Callable,
    numbers: list[int],
    settings: press.PressSettings,
    on_finish: Callable[[BuildJob], None] | None = None,
) -> BuildJob:
    with _lock:
        existing = _jobs.get(str(book.root))
        if existing and existing.state == "running":
            raise StudioError("This book is already building. Stop it, or wait for it to finish.")
        job = BuildJob(book, make_router, numbers, settings, on_finish)
        _jobs[str(book.root)] = job
    return job.start()


def job_for(book: Book) -> BuildJob | None:
    return _jobs.get(str(book.root))
