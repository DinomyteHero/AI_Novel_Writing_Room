#!/usr/bin/env python3
"""Slice 2 revision-debt CLI.

Thin human-facing wrapper around ``RevisionDebtStore`` and the chapter-memo
generators. The CLI keeps the UI path minimal for Slice 2; a future HTTP layer
can reuse the same helpers.

Usage::

    py -3 scripts/debt_cli.py --db output/<franchise>/<book>/state/revision_debt.db list --status open
    py -3 scripts/debt_cli.py --db ... update <debt_id> --status resolved --notes "..."
    py -3 scripts/debt_cli.py --db ... memo chapter --chapter 4
    py -3 scripts/debt_cli.py --db ... memo milestone --through-chapter 10

If ``--concept-seed`` is provided the CLI resolves ``ProjectPaths`` to locate
the debt DB + memos dir automatically; otherwise the caller supplies ``--db``
and ``--memos-dir`` directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _resolve_paths(concept_seed_path: str | None, db: str | None, memos_dir: str | None):
    if concept_seed_path:
        from src.project_paths import ProjectPaths  # noqa: PLC0415

        paths = ProjectPaths.from_concept_seed_path(Path(concept_seed_path))
        db = db or str(paths.state_dir / "revision_debt.db")
        # Memos are run-scoped; without a run_id we write into a shared dir.
        memos_dir = memos_dir or str(paths.project_dir / "memos")
    return db, memos_dir


def _print_rows(rows: list[dict]) -> None:
    if not rows:
        print("(no rows)")
        return
    for r in rows:
        scope = r.get("scope", {})
        ch = scope.get("chapter_number")
        sc = scope.get("scene_number")
        loc = ""
        if ch is not None:
            loc = f"ch{int(ch):02d}" + (f"_sc{int(sc):02d}" if sc is not None else "")
        print(
            f"  {r['debt_id']}  [{r['status']}]  {r['category']}/{r['severity']}  {loc}  {r.get('summary','')}"
        )


def _cmd_list(args, db: str) -> int:
    from src.pipeline.revision_debt import RevisionDebtStore  # noqa: PLC0415

    store = RevisionDebtStore(db_path=db)
    try:
        scope = {}
        if args.chapter is not None:
            scope["chapter_number"] = args.chapter
        if args.scene is not None:
            scope["scene_number"] = args.scene

        if args.status == "any":
            rows = store.list_all()
        elif args.status == "open":
            rows = store.list_open(scope=scope or None)
        else:
            rows = store.list_by_status(statuses=[args.status], scope=scope or None)

        if args.category:
            rows = [r for r in rows if r.get("category") == args.category]

        _print_rows(rows)
    finally:
        store.close()
    return 0


def _cmd_update(args, db: str) -> int:
    from src.pipeline.revision_debt import RevisionDebtStore  # noqa: PLC0415

    store = RevisionDebtStore(db_path=db)
    try:
        transition = store.update_status(
            args.debt_id, status=args.status, resolution_notes=args.notes,
        )
        print(
            f"Updated {args.debt_id}: {transition['old_status']} \u2192 {transition['new_status']}"
        )
    finally:
        store.close()
    return 0


def _cmd_memo(args, db: str, memos_dir: str | None) -> int:
    from src.pipeline.chapter_memos import (  # noqa: PLC0415
        ChapterCloseMemoGenerator,
        MilestoneMemoGenerator,
    )
    from src.pipeline.revision_debt import RevisionDebtStore  # noqa: PLC0415

    store = RevisionDebtStore(db_path=db)
    try:
        story_state = None
        if args.story_state_db:
            from src.memory.story_state import StoryState  # noqa: PLC0415

            story_state = StoryState(db_path=args.story_state_db)

        if args.memo_kind == "chapter":
            gen = ChapterCloseMemoGenerator(debt_store=store, story_state=story_state)
            memo = gen.generate(chapter_number=args.chapter)
        else:
            gen = MilestoneMemoGenerator(debt_store=store, story_state=story_state)
            memo = gen.generate(through_chapter=args.through_chapter)

        if args.json:
            print(json.dumps(memo, indent=2))
        else:
            print(gen.render_markdown(memo))

        if args.write and memos_dir:
            path = gen.write(memo, memos_dir=Path(memos_dir))
            print(f"\n[wrote {path}]")

        if story_state is not None:
            story_state.close()
    finally:
        store.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Path to revision_debt.db")
    parser.add_argument("--concept-seed", help="Path to concept_seed.json (auto-resolves paths)")
    parser.add_argument("--memos-dir", help="Where to write memo files when --write is passed")

    sub = parser.add_subparsers(dest="cmd", required=True)

    list_parser = sub.add_parser("list", help="List debt rows.")
    list_parser.add_argument(
        "--status", default="open",
        choices=["open", "deferred", "resolved", "overruled", "any"],
    )
    list_parser.add_argument("--chapter", type=int)
    list_parser.add_argument("--scene", type=int)
    list_parser.add_argument("--category")

    upd_parser = sub.add_parser("update", help="Update a debt row's status.")
    upd_parser.add_argument("debt_id")
    upd_parser.add_argument(
        "--status", required=True,
        choices=["open", "deferred", "resolved", "overruled"],
    )
    upd_parser.add_argument("--notes", default=None)

    memo_parser = sub.add_parser("memo", help="Generate a chapter or milestone memo.")
    memo_parser.add_argument("memo_kind", choices=["chapter", "milestone"])
    memo_parser.add_argument("--chapter", type=int)
    memo_parser.add_argument("--through-chapter", type=int)
    memo_parser.add_argument("--story-state-db", help="Optional story_state.db for gap-note sync")
    memo_parser.add_argument("--json", action="store_true", help="Print raw JSON instead of markdown")
    memo_parser.add_argument("--write", action="store_true", help="Persist memo under --memos-dir")

    args = parser.parse_args()

    db, memos_dir = _resolve_paths(args.concept_seed, args.db, args.memos_dir)
    if not db:
        parser.error("one of --db or --concept-seed is required")

    if args.cmd == "list":
        return _cmd_list(args, db)
    if args.cmd == "update":
        return _cmd_update(args, db)
    if args.cmd == "memo":
        if args.memo_kind == "chapter" and args.chapter is None:
            parser.error("`memo chapter` requires --chapter")
        if args.memo_kind == "milestone" and args.through_chapter is None:
            parser.error("`memo milestone` requires --through-chapter")
        return _cmd_memo(args, db, memos_dir)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
