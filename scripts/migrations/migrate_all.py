#!/usr/bin/env python3
"""Architecture upgrade migration wrapper (spec \u00a711.5).

Runs every per-slice migration script in the canonical order and reports
``{applied, already_had_table, rows_migrated, errors}`` per slice. Fails
fast on the first non-zero exit so CI does not continue past a broken
migration.

Scripts invoked (in order):
    scripts/migrations/migrate_gap_notes.py         (Slice 1)
    scripts/migrations/migrate_revision_debt.py     (Slice 2)
    scripts/migrations/migrate_promise_ledger.py    (Slice 3)
    scripts/migrations/migrate_continuity_log.py    (Slice 4)
    scripts/migrations/migrate_sociogram.py         (Slice 5)

Usage:
    py -3 scripts/migrations/migrate_all.py [--dry-run] [--base-dir <path>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


MIGRATIONS: list[tuple[str, str]] = [
    ("Slice 1 - gap_notes",         "scripts/migrations/migrate_gap_notes.py"),
    ("Slice 2 - revision_debt",     "scripts/migrations/migrate_revision_debt.py"),
    ("Slice 3 - promise_ledger",    "scripts/migrations/migrate_promise_ledger.py"),
    ("Slice 4 - continuity_log",    "scripts/migrations/migrate_continuity_log.py"),
    ("Slice 5 - sociogram",         "scripts/migrations/migrate_sociogram.py"),
]


def _run_one(script: Path, *, dry_run: bool, base_dir: Path) -> int:
    cmd = [sys.executable, str(script), "--base-dir", str(base_dir)]
    if dry_run:
        cmd.append("--dry-run")
    # stdout passes through so per-script "[exists]" / "[pending]" markers
    # land in the same terminal. stderr likewise - errors are loud.
    result = subprocess.run(cmd)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base-dir", default=".")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    base = Path(args.base_dir).resolve()
    any_error = 0
    for label, rel_path in MIGRATIONS:
        script = repo_root / rel_path
        print(f"\n--- {label} ---")
        if not script.exists():
            print(f"  ! script missing: {script}")
            any_error |= 2
            continue
        rc = _run_one(script, dry_run=args.dry_run, base_dir=base)
        if rc != 0:
            print(f"  ! {rel_path} exited with code {rc}")
            # Spec \u00a711.5: fail fast on the first non-zero exit so CI
            # surfaces the broken migration rather than masking it behind
            # later successful passes.
            return rc

    if any_error:
        return any_error
    print("\nAll migrations complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
