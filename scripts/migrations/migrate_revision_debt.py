#!/usr/bin/env python3
"""Idempotent wrapper for the Slice 2 revision-debt migration.

Walks the repo for every ``state/`` directory (franchise- and book-scoped, per
``ProjectPaths``) and ensures ``revision_debt.db`` exists with the current
schema. Opening a path through ``RevisionDebtStore`` triggers the CREATE IF
NOT EXISTS path in ``src/pipeline/revision_debt.py`` so this script only needs
to enumerate target paths and instantiate the store.

Usage:
    py -3 scripts/migrations/migrate_revision_debt.py [--dry-run] [--base-dir <path>]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


DEFAULT_SEARCH_ROOTS = (
    Path("output"),
)


def find_state_dirs(roots: list[Path]) -> list[Path]:
    hits: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for state_dir in sorted(root.rglob("state")):
            if state_dir.is_dir():
                hits.append(state_dir)
    return hits


def revision_debt_table_exists(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'revision_debt'"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List affected state/ dirs; do not open stores for write.",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Root directory to walk (default: current directory).",
    )
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    roots = [base / r for r in DEFAULT_SEARCH_ROOTS]
    state_dirs = find_state_dirs(roots)

    if not state_dirs:
        print("No state/ directories found under output/.")
        return 0

    print(f"Found {len(state_dirs)} state/ dir(s) under {base}")
    print()

    applied = 0
    already = 0
    errors = 0
    for state_dir in state_dirs:
        db_path = state_dir / "revision_debt.db"
        has_table = revision_debt_table_exists(db_path)
        marker = "[exists]" if has_table else "[pending]"
        print(f"  {marker}  {db_path.relative_to(base)}")

        if args.dry_run:
            continue

        try:
            from src.pipeline.revision_debt import RevisionDebtStore  # noqa: PLC0415

            store = RevisionDebtStore(db_path=str(db_path))
            store.close()
            if has_table:
                already += 1
            else:
                applied += 1
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
