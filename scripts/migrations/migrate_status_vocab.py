#!/usr/bin/env python3
"""One-shot script to migrate project ``story_state.db`` files to the Stage 1i
status vocabulary.

The heavy lifting is already done by the schema migration in
``src.memory.story_state`` — opening a DB through ``StoryState`` triggers
auto-migration through all pending versions, including the v5→v6 remap
that collapses the six-value revision_status enum to
``{draft, saved_clean, saved_with_advisory, quarantined}``.

This script walks the repo for ``story_state.db`` files, opens each one
through ``StoryState`` to let the auto-migration run, and prints a
summary of how many rows were remapped per DB. Safe to re-run — the
migration is idempotent.

Usage:
    python scripts/migrations/migrate_status_vocab.py [--dry-run] [--root <path>]

With ``--dry-run``, the script lists DBs and reports their pre-migration
statuses without opening them for write (no auto-migration runs).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


DEFAULT_SEARCH_ROOTS = (
    Path("data/franchises"),
    Path("data/projects"),
    Path("output"),
)


LEGACY_STATUS_VALUES = {
    "gate_failed",
    "gate_passed",
    "polished",
    "final_gate_rejected",
    "approved",
    "craft_edited",
    "revised",
    "gate_skipped",
}


def find_story_state_dbs(roots: list[Path]) -> list[Path]:
    """Walk roots and return every ``story_state.db`` path found."""
    hits: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        hits.extend(sorted(root.rglob("story_state.db")))
    return hits


def snapshot_statuses(db_path: Path) -> dict[str, dict[str, int]]:
    """Return ``{table: {status: count}}`` for the log tables.

    Uses a plain read-only sqlite connection so no schema migration
    runs. Falls back gracefully when tables or columns are missing
    (e.g., very old fixtures).
    """
    result: dict[str, dict[str, int]] = {"chapter_log": {}, "scene_log": {}}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return result
    try:
        for table in ("chapter_log", "scene_log"):
            try:
                rows = conn.execute(
                    f"SELECT revision_status, COUNT(*) FROM {table} "
                    f"GROUP BY revision_status"
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            result[table] = {
                (status or "<NULL>"): count for status, count in rows
            }
    finally:
        conn.close()
    return result


def migrate_db(db_path: Path) -> dict:
    """Open the DB through StoryState, triggering auto-migration.

    Returns a report dict with before/after status counts and whether the
    migration actually changed anything.
    """
    from src.memory.story_state import StoryState

    before = snapshot_statuses(db_path)

    # Opening through StoryState runs all pending migrations.
    state = StoryState(db_path=str(db_path))
    try:
        version = state.get_schema_version()
    finally:
        state.close()

    after = snapshot_statuses(db_path)

    remapped = before != after
    return {
        "path": str(db_path),
        "schema_version": version,
        "before": before,
        "after": after,
        "remapped": remapped,
    }


def format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "  (empty)"
    lines = []
    for status, n in sorted(counts.items()):
        lines.append(f"    {status}: {n}")
    return "\n".join(lines)


def run(roots: list[Path], dry_run: bool) -> int:
    dbs = find_story_state_dbs(roots)
    if not dbs:
        print(f"No story_state.db found under: {[str(r) for r in roots]}")
        return 0

    changed = 0
    for db_path in dbs:
        print(f"\n== {db_path} ==")
        if dry_run:
            snap = snapshot_statuses(db_path)
            legacy_present = any(
                status in LEGACY_STATUS_VALUES
                for t in snap.values()
                for status in t.keys()
            )
            print("  chapter_log:")
            print(format_counts(snap.get("chapter_log", {})))
            print("  scene_log:")
            print(format_counts(snap.get("scene_log", {})))
            print(f"  legacy values present: {legacy_present}")
            continue

        report = migrate_db(db_path)
        print(f"  schema_version: {report['schema_version']}")
        print("  before:")
        print(format_counts(report["before"].get("chapter_log", {})))
        print(format_counts(report["before"].get("scene_log", {})))
        print("  after:")
        print(format_counts(report["after"].get("chapter_log", {})))
        print(format_counts(report["after"].get("scene_log", {})))
        if report["remapped"]:
            print("  => rows remapped")
            changed += 1
        else:
            print("  => no changes (already at target vocab)")

    total = len(dbs)
    print(
        f"\nProcessed {total} DB(s); "
        f"{changed} had status-vocab changes."
        f"{' [dry-run only]' if dry_run else ''}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report status counts without opening DBs for write.",
    )
    parser.add_argument(
        "--root",
        action="append",
        default=None,
        help=(
            "Search root for story_state.db files. Repeat for multiple roots. "
            f"Defaults: {', '.join(str(r) for r in DEFAULT_SEARCH_ROOTS)}"
        ),
    )
    args = parser.parse_args()

    roots = [Path(r) for r in (args.root or DEFAULT_SEARCH_ROOTS)]
    return run(roots=roots, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
