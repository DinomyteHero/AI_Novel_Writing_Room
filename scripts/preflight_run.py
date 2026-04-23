"""Validate current planning artifacts before spending drafting API calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline.run_preflight import (  # noqa: E402
    format_preflight_summary,
    validate_current_run,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--franchise", required=True, help="Franchise slug")
    parser.add_argument("--book", required=True, help="Book slug")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument("--chapter", type=int, help="Only validate one chapter")
    parser.add_argument("--scene", type=int, help="Only validate one scene number")
    parser.add_argument(
        "--allow-unapproved-plan",
        action="store_true",
        help="Do not fail when compile_metadata.plan_approved is missing/false.",
    )
    parser.add_argument(
        "--allow-missing-canon-guidance",
        action="store_true",
        help="Do not fail when selected canon guidance sidecars are missing/stale.",
    )
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Exit non-zero when warnings remain.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    report = validate_current_run(
        franchise_slug=args.franchise,
        book_slug=args.book,
        base_dir=args.base_dir,
        chapter=args.chapter,
        scene=args.scene,
        require_plan_approval=not args.allow_unapproved_plan,
        require_canon_guidance=False if args.allow_missing_canon_guidance else None,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_preflight_summary(report))
    if not report.passed:
        return 1
    if args.strict_warnings and report.warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
