#!/usr/bin/env python3
"""Slice 4 continuity-log migration wrapper.

Walks every ``output/**/state/`` directory and creates an empty
``continuity_log.db`` if one does not already exist. Extractor-driven
population happens at pipeline runtime \u2014 the migration's job is to ensure
the file + schema exist so the first enabled run has somewhere to write.

Idempotent \u2014 re-running is a no-op when the table already exists.

Usage:
    py -3 scripts/migrate_continuity_log.py [--dry-run] [--base-dir <path>]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


DEFAULT_SEARCH_ROOTS = (Path("output"),)


def _find_state_dirs(roots: list[Path]) -> list[Path]:
    hits: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for state_dir in sorted(root.rglob("state")):
            if state_dir.is_dir():
                hits.append(state_dir)
    return hits


def _table_exists(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='continuity_events'"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base-dir", default=".")
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    roots = [base / r for r in DEFAULT_SEARCH_ROOTS]
    state_dirs = _find_state_dirs(roots)

    if not state_dirs:
        print("No output/**/state/ directories found.")
        return 0

    print(f"Found {len(state_dirs)} state/ dir(s) under {base}")
    print()

    applied = 0
    already = 0
    errors = 0
    for state_dir in state_dirs:
        db_path = state_dir / "continuity_log.db"
        has_table = _table_exists(db_path)
        marker = "[exists]" if has_table else "[pending]"
        print(f"  {marker}  {db_path.relative_to(base)}")

        if args.dry_run:
            continue

        try:
            from src.memory.continuity_log import ContinuityLog  # noqa: PLC0415
            log = ContinuityLog(db_path=str(db_path))
            log.close()
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
        print(f"Summary: applied={applied} already_had_table={already} errors={errors}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
