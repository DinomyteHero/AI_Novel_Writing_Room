#!/usr/bin/env python3
"""Slice 5 sociogram migration wrapper.

Walks every ``output/<franchise>/<book>/state/`` directory and seeds
``sociogram.db`` from the paired book's ``concept_seed.json``. Idempotent:
re-running re-upserts edges; existing trust/warmth/power state is preserved
on re-seed so scene-card deltas are not clobbered.

Usage:
    py -3 scripts/migrations/migrate_sociogram.py [--dry-run] [--base-dir <path>]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


OUTPUT_ROOT = Path("output")
DATA_ROOT = Path("data") / "franchises"


def _load_json(path: Path) -> dict | list:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _find_state_dirs(output_root: Path) -> list[Path]:
    if not output_root.exists():
        return []
    return sorted(p for p in output_root.rglob("state") if p.is_dir())


def _book_dir_for(state_dir: Path, data_root: Path) -> Path | None:
    try:
        book_slug = state_dir.parent.name
        franchise_slug = state_dir.parent.parent.name
    except Exception:  # noqa: BLE001
        return None
    book_dir = data_root / franchise_slug / "books" / book_slug
    return book_dir if book_dir.exists() else None


def _table_exists(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sociogram_edges'"
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
    output_root = base / OUTPUT_ROOT
    data_root = base / DATA_ROOT
    state_dirs = _find_state_dirs(output_root)

    if not state_dirs:
        print("No output/**/state/ directories found.")
        return 0

    print(f"Found {len(state_dirs)} state/ dir(s) under {base}")
    print()

    created = 0
    already = 0
    rows_migrated = 0
    errors = 0
    for state_dir in state_dirs:
        book_dir = _book_dir_for(state_dir, data_root=data_root)
        if book_dir is None:
            print(f"  [skip]   {state_dir.relative_to(base)} (no matching book dir)")
            continue
        seed_path = book_dir / "concept_seed.json"
        db_path = state_dir / "sociogram.db"
        marker = "[exists]" if _table_exists(db_path) else "[pending]"
        print(f"  {marker}  {db_path.relative_to(base)}")

        if args.dry_run:
            continue

        if not seed_path.exists():
            already += 1
            continue

        try:
            from src.memory.sociogram import Sociogram  # noqa: PLC0415
            seed = _load_json(seed_path)
            if not isinstance(seed, dict):
                continue
            had_table = _table_exists(db_path)
            store = Sociogram(db_path=str(db_path))
            try:
                count = store.initialize_from_planning(concept_seed=seed)
            finally:
                store.close()
            if had_table:
                already += 1
            else:
                created += 1
            rows_migrated += count
            print(f"        seeded {count} edge(s)")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"        ! ERROR: {type(exc).__name__}: {exc}")

    print()
    if args.dry_run:
        print("Dry run complete; no writes.")
    else:
        print(
            f"Summary: created={created} already_had_table={already} "
            f"rows_migrated={rows_migrated} errors={errors}"
        )
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
