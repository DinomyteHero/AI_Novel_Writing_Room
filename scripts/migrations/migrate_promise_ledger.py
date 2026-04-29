#!/usr/bin/env python3
"""Slice 3 promise-ledger migration wrapper.

Walks every ``output/<franchise>/<book>/state/`` directory and creates /
refreshes ``promise_ledger.db`` by seeding from each book's planning artifacts:

- ``concept_seed.story_physics.promise_payoff_ledger`` (chapter-level).
- Per-scene-card ``promises_planted`` / ``promises_paid`` (scene-level
  resolution when planning only named a chapter).

Idempotent \u2014 re-runs update in place without duplicating rows (SQLite UPSERT
on ``promise_id``). For books with no planning ledger present the database is
still created (empty) so later runs can append.

Usage:
    py -3 scripts/migrations/migrate_promise_ledger.py [--dry-run] [--base-dir <path>]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


DEFAULT_OUTPUT_ROOT = Path("output")
DEFAULT_DATA_ROOT = Path("data") / "franchises"


def _load_json(path: Path) -> dict | list:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _find_output_state_dirs(output_root: Path) -> list[Path]:
    if not output_root.exists():
        return []
    return sorted(p for p in output_root.rglob("state") if p.is_dir())


def _resolve_book_for_state(state_dir: Path, data_root: Path) -> Path | None:
    """Find the source book dir under ``data/franchises/`` that seeds this state dir.

    Layout: ``output/<franchise>/<book>/state/`` mirrors
    ``data/franchises/<franchise>/books/<book>/``.
    """
    try:
        book_slug = state_dir.parent.name
        franchise_slug = state_dir.parent.parent.name
    except Exception:  # noqa: BLE001
        return None
    book_dir = data_root / franchise_slug / "books" / book_slug
    if not book_dir.exists():
        return None
    return book_dir


def _load_scene_cards(book_dir: Path) -> list[dict]:
    cards_dir = book_dir / "scene_cards"
    if not cards_dir.exists():
        return []
    out: list[dict] = []
    for path in sorted(cards_dir.rglob("*.json")):
        try:
            data = _load_json(path)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, list):
            out.extend(c for c in data if isinstance(c, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


def _seed_one_book(
    *,
    state_dir: Path,
    book_dir: Path,
    dry_run: bool,
) -> tuple[int, int]:
    seed_path = book_dir / "concept_seed.json"
    if not seed_path.exists():
        return 0, 0
    concept_seed = _load_json(seed_path)
    if not isinstance(concept_seed, dict):
        return 0, 0
    scene_cards = _load_scene_cards(book_dir)

    db_path = state_dir / "promise_ledger.db"
    had_table = _table_exists(db_path)
    if dry_run:
        return (0 if had_table else 1, 0)

    from src.memory.promise_ledger import PromiseLedger  # noqa: PLC0415

    ledger = PromiseLedger(db_path=str(db_path))
    try:
        count = ledger.initialize_from_planning(
            concept_seed=concept_seed, scene_cards=scene_cards,
        )
    finally:
        ledger.close()
    return (0 if had_table else 1, count)


def _table_exists(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='promise_ledger'"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report which state/ dirs would get a ledger DB; no writes.",
    )
    parser.add_argument(
        "--base-dir", default=".",
        help="Repo root (default: cwd).",
    )
    args = parser.parse_args()

    base = Path(args.base_dir).resolve()
    output_root = base / DEFAULT_OUTPUT_ROOT
    data_root = base / DEFAULT_DATA_ROOT
    state_dirs = _find_output_state_dirs(output_root)

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
        book_dir = _resolve_book_for_state(state_dir, data_root=data_root)
        if book_dir is None:
            print(f"  [skip]   {state_dir.relative_to(base)}  (no matching book dir)")
            continue
        db_path = state_dir / "promise_ledger.db"
        marker = "[exists]" if _table_exists(db_path) else "[pending]"
        print(f"  {marker}  {db_path.relative_to(base)}")

        if args.dry_run:
            continue

        try:
            new_flag, rows = _seed_one_book(
                state_dir=state_dir, book_dir=book_dir, dry_run=False,
            )
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"        ! ERROR: {type(exc).__name__}: {exc}")
            continue
        if new_flag:
            created += 1
        else:
            already += 1
        rows_migrated += rows
        print(f"        seeded {rows} promise(s)")

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
