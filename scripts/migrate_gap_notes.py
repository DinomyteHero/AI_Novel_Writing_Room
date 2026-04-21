#!/usr/bin/env python3
"""Wrapper that walks the repo for ``story_state.db`` files and applies the
v6→v7 migration (adds the ``gap_notes`` table used by the state firewall).

The heavy lifting is already done by the schema migration in
``src.memory.story_state`` — opening a DB through ``StoryState`` triggers
``_run_migrations`` which applies every pending version, including v7.

This script iterates every project DB and opens each through ``StoryState``
so the migration fires in one pass. Idempotent (CREATE IF NOT EXISTS).

Usage:
    py -3 scripts/migrate_gap_notes.py [--dry-run] [--base-dir <path>]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


DEFAULT_SEARCH_ROOTS = (
    Path("data/franchises"),
    Path("data/projects"),
    Path("output"),
)


def find_story_state_dbs(roots: list[Path]) -> list[Path]:
    hits: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        hits.extend(sorted(root.rglob("story_state.db")))
    return hits


def table_exists(db_path: Path, table: str) -> bool:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List affected DBs and whether gap_notes already exists; do not open for write.",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Root directory to walk (default: current directory).",
    )
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    roots = [base / r for r in DEFAULT_SEARCH_ROOTS]
    db_paths = find_story_state_dbs(roots)

    if not db_paths:
        print("No story_state.db files found.")
        return 0

    print(f"Found {len(db_paths)} story_state.db file(s) under {base}")
    print()

    applied = 0
    already = 0
    errors = 0
    for db in db_paths:
        has_table = table_exists(db, "gap_notes")
        marker = "[exists]" if has_table else "[pending]"
        print(f"  {marker}  {db.relative_to(base)}")

        if args.dry_run:
            continue

        try:
            # Importing here means a failure in the import path bubbles up cleanly.
            from src.memory.story_state import StoryState  # noqa: PLC0415
            store = StoryState(db_path=str(db))
            version = store.get_schema_version()
            store.close()
            if has_table:
                already += 1
            else:
                applied += 1
            print(f"        → schema_version={version}")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"        ! ERROR: {exc}")

    print()
    if args.dry_run:
        print("Dry run complete; no writes.")
    else:
        print(f"Summary: applied={applied}  already_had_table={already}  errors={errors}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
