"""Studio CLI: plan in two Markdown files, then draft a book chapter by chapter.

Examples:
    python scripts/studio.py new --title "My Novel"
    python scripts/studio.py new --title "My Fic" --franchise "Star Wars (Legends EU)"
    python scripts/studio.py status --title "My Novel"
    python scripts/studio.py draft next --title "My Novel"
    python scripts/studio.py draft 3 --title "My Novel" --words 3000 --note "open on the storm"
    python scripts/studio.py revise 3 --title "My Novel" --note "more banter, less brooding"
    python scripts/studio.py polish 3 --title "My Novel"
    python scripts/studio.py review --title "My Novel"
    python scripts/studio.py export --title "My Novel"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.studio import (  # noqa: E402
    StoryProject,
    StudioError,
    draft_chapter,
    export_book,
    next_chapter,
    polish_chapter,
    review_book,
    revise_chapter,
)


def _words(text: str) -> int:
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return len(" ".join(lines).split())


def _chapter_number(project: StoryProject, value: str) -> int:
    if value == "next":
        return next_chapter(project)
    try:
        return int(value)
    except ValueError:
        raise StudioError(f"'{value}' isn't a chapter number (or 'next').") from None


def cmd_new(project: StoryProject, args: argparse.Namespace) -> None:
    written = project.create()
    print(f"Book folder: {project.root}")
    for path in written:
        print(f"  created {path.name}")
    if not written:
        print("  (all starter files already exist; nothing overwritten)")
    print("\nNext: fill in story_bible.md, characters.md and outline.md (or plan them")
    print("in a chat with the story-session skill), then run:")
    print(f'  python scripts/studio.py draft next --title "{project.title}"')


def cmd_status(project: StoryProject, args: argparse.Namespace) -> None:
    plans = project.outline_chapters()
    drafted = project.drafted_chapters()
    print(f"{project.title}  ({project.root})")
    if not plans and not drafted:
        print("  The outline has no '## Chapter N' sections yet.")
    total = 0
    for number in sorted(set(plans) | set(drafted)):
        title = plans[number].title if number in plans else "(not in outline)"
        if number in drafted:
            count = _words(drafted[number])
            total += count
            state = f"{count:,} words"
        else:
            state = "not drafted"
        print(f"  Chapter {number:>2}  {title or '':<40} {state}")
    print(f"\n  {len(drafted)} of {len(plans)} outlined chapters drafted, {total:,} words.")
    print(f"  Whole book is about {project.total_tokens():,} tokens of context per call.")


async def cmd_draft(project, args, router) -> Path:
    number = _chapter_number(project, args.chapter)
    print(f"Drafting chapter {number}...")
    return await draft_chapter(
        project, router, number, words=args.words, note=args.note, force=args.force
    )


async def cmd_revise(project, args, router) -> Path:
    print(f"Revising chapter {args.chapter}...")
    return await revise_chapter(project, router, args.chapter, args.note)


async def cmd_polish(project, args, router) -> Path:
    print(f"Polishing chapter {args.chapter}...")
    return await polish_chapter(project, router, args.chapter)


async def cmd_review(project, args, router) -> Path:
    print("Reading the whole book...")
    return await review_book(project, router)


async def _run_model_command(project: StoryProject, args: argparse.Namespace) -> None:
    from src.model_router import ModelRouter

    router = ModelRouter(args.config)
    try:
        path = await args.handler(project, args, router)
    finally:
        await router.close()
    if path.parent == project.chapters_dir:
        print(f"Saved {path} ({_words(path.read_text(encoding='utf-8')):,} words)")
    else:
        print(f"Saved {path}")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--title", required=True, help="Your book's title")
    common.add_argument(
        "--franchise",
        help="For fanfiction, the source world (e.g. 'Star Wars (Legends EU)'). "
        "Leave out for an original book.",
    )
    common.add_argument("--base-dir", default=".", help=argparse.SUPPRESS)
    common.add_argument("--config", default="config/settings.yaml", help=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("new", parents=[common], help="Create a book folder").set_defaults(
        handler=cmd_new, uses_model=False
    )
    sub.add_parser("status", parents=[common], help="Show chapters and progress").set_defaults(
        handler=cmd_status, uses_model=False
    )
    sub.add_parser("export", parents=[common], help="Stitch chapters into one file").set_defaults(
        handler=lambda project, args: print(f"Saved {export_book(project)}"), uses_model=False
    )

    draft = sub.add_parser("draft", parents=[common], help="Draft a chapter from the outline")
    draft.add_argument("chapter", help="Chapter number, or 'next'")
    draft.add_argument("--words", type=int, help="Rough length to aim for")
    draft.add_argument("--note", help="Anything extra for this chapter")
    draft.add_argument("--force", action="store_true", help="Redraft an existing chapter")
    draft.set_defaults(handler=cmd_draft, uses_model=True)

    revise = sub.add_parser("revise", parents=[common], help="Change a chapter with a note")
    revise.add_argument("chapter", type=int)
    revise.add_argument("--note", required=True, help="What you'd like changed")
    revise.set_defaults(handler=cmd_revise, uses_model=True)

    polish = sub.add_parser("polish", parents=[common], help="Light line edit of a chapter")
    polish.add_argument("chapter", type=int)
    polish.set_defaults(handler=cmd_polish, uses_model=True)

    sub.add_parser("review", parents=[common], help="Reader notes on the whole book").set_defaults(
        handler=cmd_review, uses_model=True
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project = StoryProject.for_book(args.title, args.franchise, base_dir=args.base_dir)
    try:
        if args.command != "new" and not project.exists():
            raise StudioError(f"No book folder at {project.root}. Run 'new' first.")
        if args.uses_model:
            asyncio.run(_run_model_command(project, args))
        else:
            args.handler(project, args)
    except StudioError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
