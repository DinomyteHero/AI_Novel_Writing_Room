"""Command-line front ends for the room (scripts/room.py) and the press (scripts/press.py)."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import sys
from pathlib import Path

from src.model_router import load_config
from src.studio import press, room
from src.studio.llm import provider_error
from src.studio.project import Book, Library, StudioError, count_words

ROOT = Path(__file__).resolve().parents[2]


def _library(args: argparse.Namespace) -> Library:
    return Library(Path(args.library or os.environ.get("WRITERS_ROOM_LIBRARY") or ROOT / "library"))


def _book(args: argparse.Namespace) -> Book:
    return _library(args).find_book(args.title, args.series)


def _show(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise StudioError(f"{question} Add --yes to go ahead without being asked.")
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _router(args: argparse.Namespace):
    from src.model_router import ModelRouter

    router = ModelRouter(args.config)
    missing = router.missing_keys()
    if missing:
        raise StudioError(
            f"No API key found for {', '.join(missing)}. Copy .env.example to .env, paste "
            f"your key after {missing[0]}=, then run: python scripts/room.py check"
        )
    return router


async def _with_router(args: argparse.Namespace, work):
    router = _router(args)
    try:
        return await work(router)
    finally:
        await router.close()


# --- room -----------------------------------------------------------------


def cmd_new(args: argparse.Namespace) -> None:
    book, written = _library(args).new_book(args.new_title, args.series)
    print(f"{book.label}\n  folder: {_show(book.root)}")
    for path in written:
        print(f"  created {_show(path)}")
    print(
        "\nNext: plan it in the story-session chat, or fill in the files by hand.\n"
        "When you're ready, optionally get a second opinion, then build:\n"
        f'  python scripts/room.py review --title "{book.title}"\n'
        f'  python scripts/press.py build next --title "{book.title}"'
    )


def cmd_books(args: argparse.Namespace) -> None:
    series_list = _library(args).all_series()
    if not series_list:
        print('The library is empty. Start a book with: python scripts/room.py new "Title"')
        return
    for series in series_list:
        books = series.books()
        if len(books) > 1:
            print(f"{series.title} (series)")
        for book in books:
            indent = "  " if len(books) > 1 else ""
            count = len(book.drafted_chapters())
            print(f"{indent}{book.title}: {count} chapter(s) written  [{_show(book.root)}]")


_STATE_LABELS = {"missing": "not written"}


def cmd_status(args: argparse.Namespace) -> None:
    book = _book(args)
    report = room.status(book)
    print(f"{book.label}  ({_show(book.root)})")
    if not report.chapters:
        print("  The outline has no '## Chapter N' sections yet.")
    for row in report.chapters:
        words = f"{row.words:,} words" if row.words else ""
        state = _STATE_LABELS.get(row.state, row.state)
        print(f"  Chapter {row.number:>2}  {row.title[:36]:<36} {words:>12}  {state}")
    written = sum(1 for row in report.chapters if row.state != "missing")
    print(f"\n  {written} of {len(report.chapters)} chapters written, {report.total_words:,} words.")
    print(f"  Each model call sends about {report.context_tokens:,} tokens of book.")
    if report.latest_review is None:
        print("  No review yet. Run 'room.py review' any time you'd like a second opinion.")
    elif report.plan_changed_since_review:
        print(f"  The plan has changed since the last review ({_show(report.latest_review)}).")
    else:
        print(f"  Last review: {_show(report.latest_review)}")
    stale = [row.number for row in report.chapters if row.state == "outline changed"]
    if stale:
        numbers = ", ".join(str(n) for n in stale)
        print(
            f"  Out of date: the outline for chapter(s) {numbers} changed after they were "
            "built. Rebuild with 'press.py build N', revise with a note, or keep as is."
        )
    shifted = sum(1 for row in report.chapters if row.state == "plan changed")
    if shifted:
        print(
            f"  {shifted} chapter(s) were built before later changes to the bible or "
            "character sheets. Usually fine; a review will flag any contradictions."
        )


def cmd_review(args: argparse.Namespace) -> None:
    book = _book(args)
    print(f"Asking a second model to read {book.label}...")
    path = asyncio.run(_with_router(args, lambda r: room.review(book, r)))
    print(f"Saved {_show(path)}\nGo through it point by point in the story-session chat, or open it yourself.")


def cmd_ideas(args: argparse.Namespace) -> None:
    book = _book(args)
    print(f"Asking a second model for ideas on {book.label}...")
    path = asyncio.run(_with_router(args, lambda r: room.ideas(book, r)))
    print(f"Saved {_show(path)}\nGo through them one at a time in the story-session chat, or open it yourself.")


def cmd_revise(args: argparse.Namespace) -> None:
    book = _book(args)
    print(f"Revising chapter {args.chapter}...")
    path = asyncio.run(_with_router(args, lambda r: room.revise_chapter(book, r, args.chapter, args.note)))
    print(f"Saved {_show(path)} ({count_words(path.read_text(encoding='utf-8')):,} words)")


def cmd_polish(args: argparse.Namespace) -> None:
    book = _book(args)
    print(f"Polishing chapter {args.chapter}...")
    path = asyncio.run(_with_router(args, lambda r: room.polish_chapter(book, r, args.chapter)))
    print(f"Saved {_show(path)} ({count_words(path.read_text(encoding='utf-8')):,} words)")


def cmd_rename(args: argparse.Namespace) -> None:
    book = _book(args)
    hits = room.apply_rename(book, args.old, args.new) if args.apply else room.find_name(book, args.old)
    if not hits:
        print(f"'{args.old}' doesn't appear anywhere in {book.series.title}.")
        return
    total = sum(hit.count for hit in hits)
    for hit in hits:
        print(f"  {_show(hit.path)}: {hit.count}")
        for example in hit.examples:
            print(f"      {example}")
    if args.apply:
        print(f"\nReplaced {total} occurrence(s) of '{args.old}' with '{args.new}' in {len(hits)} file(s).")
    else:
        print(
            f"\n{total} occurrence(s) in {len(hits)} file(s). Nothing has changed yet; "
            "run again with --apply to replace them."
        )


def cmd_check(args: argparse.Namespace) -> int:
    ok, message = asyncio.run(_with_router(args, room.check))
    print(("Ready: " if ok else "Problem: ") + message)
    return 0 if ok else 1


# --- press ----------------------------------------------------------------


def _settings(args: argparse.Namespace) -> press.PressSettings:
    settings = press.PressSettings.from_config(load_config(args.config))
    if args.rounds is not None:
        settings = dataclasses.replace(settings, revision_rounds=args.rounds)
    return settings


def cmd_build(args: argparse.Namespace) -> None:
    book = _book(args)
    plan = book.read_plan()
    numbers = press.select_chapters(book, plan, args.which)
    settings = _settings(args)
    guess = press.estimate(book, plan, numbers, settings)
    listed = ", ".join(str(n) for n in numbers)
    print(f"Building chapter(s) {listed} of {book.label}: {guess.describe()}.")
    existing = [n for n in numbers if book.chapter_path(n).exists()]
    if existing and not _confirm(
        f"Chapter {existing[0]} already exists. Rebuild it? The current version is kept in "
        "manuscript/.history/.",
        args.yes,
    ):
        print("Nothing built.")
        return
    if args.which == "all" and not _confirm("Go ahead?", args.yes):
        print("Nothing built.")
        return

    def started(chapter):
        print(f"  Chapter {chapter.number}: drafting, critiquing, revising...", flush=True)

    def finished(result):
        line = (
            f"  Chapter {result.number}: {result.final_words:,} words "
            f"(planned {result.target_words:,}), {result.revisions_kept} revision(s) kept"
        )
        print(line, flush=True)
        for note in result.notes:
            print(f"      {note}")

    result = asyncio.run(
        _with_router(
            args,
            lambda r: press.build(book, r, numbers, settings, plan, started, finished),
        )
    )
    print(f"\nDone: {result.usage.describe()}.\nReport: {_show(result.report_path)}")
    if result.outline_changed:
        listed = ", ".join(str(n) for n in result.outline_changed)
        print(f"Out of date: the outline for chapter(s) {listed} changed after they were built.")


def cmd_story_so_far(args: argparse.Namespace) -> None:
    book = _book(args)
    print(f"Writing story-so-far notes for {book.label}...")
    path = asyncio.run(_with_router(args, lambda r: press.story_so_far(book, r)))
    print(f"Saved {_show(path)}. Later books in the series will read this instead of the full text.")


def cmd_export(args: argparse.Namespace) -> None:
    print(f"Saved {_show(press.export_book(_book(args)))}")


# --- parsers --------------------------------------------------------------


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--title", help="The book (not needed when the library has only one)")
    common.add_argument("--series", help="The series, when titles are shared across series")
    common.add_argument("--library", help="Library folder (default: ./library)")
    common.add_argument("--config", default=str(ROOT / "config" / "settings.yaml"), help=argparse.SUPPRESS)
    return common


def room_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(
        prog="room.py", description="The room: plan, review and direct changes to your book."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", parents=[common], help="Start a book, or add one to a series")
    new.add_argument("new_title", metavar="TITLE", help="The new book's title")
    new.set_defaults(handler=cmd_new)
    sub.add_parser("books", parents=[common], help="List every book in the library").set_defaults(
        handler=cmd_books
    )
    sub.add_parser("status", parents=[common], help="Chapters, words and what's out of date").set_defaults(
        handler=cmd_status
    )
    sub.add_parser("review", parents=[common], help="A second model reviews everything so far").set_defaults(
        handler=cmd_review
    )
    sub.add_parser(
        "ideas", parents=[common], help="A second model offers options where the plan is thin"
    ).set_defaults(handler=cmd_ideas)
    revise = sub.add_parser("revise", parents=[common], help="Change a chapter with a note")
    revise.add_argument("chapter", type=int)
    revise.add_argument("--note", required=True, help="What you'd like changed")
    revise.set_defaults(handler=cmd_revise)
    polish = sub.add_parser("polish", parents=[common], help="A light line edit of a chapter")
    polish.add_argument("chapter", type=int)
    polish.set_defaults(handler=cmd_polish)
    rename = sub.add_parser("rename", parents=[common], help="Rename someone or something everywhere")
    rename.add_argument("old")
    rename.add_argument("new")
    rename.add_argument("--apply", action="store_true", help="Make the change (default: preview)")
    rename.set_defaults(handler=cmd_rename)
    sub.add_parser("check", parents=[common], help="Check that your API key works").set_defaults(
        handler=cmd_check
    )
    return parser


def press_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(
        prog="press.py", description="The press: build chapters from your finished plan."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", parents=[common], help="Draft, critique and revise chapters")
    build.add_argument("which", help="'next', 'all', or a chapter number")
    build.add_argument("--rounds", type=int, help="Critique-and-revise rounds (default from settings)")
    build.add_argument("--yes", action="store_true", help="Don't ask before building")
    build.set_defaults(handler=cmd_build)
    sub.add_parser(
        "story-so-far", parents=[common], help="Notes on a finished book for later books in the series"
    ).set_defaults(handler=cmd_story_so_far)
    sub.add_parser("export", parents=[common], help="Stitch the chapters into one file").set_defaults(
        handler=cmd_export
    )
    return parser


def _run(parser: argparse.ArgumentParser, argv: list[str] | None) -> int:
    args = parser.parse_args(argv)
    try:
        return args.handler(args) or 0
    except StudioError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        explained = provider_error(exc)
        if explained is None:
            raise
        print(
            f"Error: {explained} Anything finished before this was saved; nothing "
            "half-done was. Run 'room.py check' to test your key.",
            file=sys.stderr,
        )
        return 1


def room_main(argv: list[str] | None = None) -> int:
    return _run(room_parser(), argv)


def press_main(argv: list[str] | None = None) -> int:
    return _run(press_parser(), argv)
