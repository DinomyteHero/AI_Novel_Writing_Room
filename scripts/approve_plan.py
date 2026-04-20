"""Stamp a plan as approved for drafting.

The compile step produces (a) a deterministic physics verdict stamped as
``compile_metadata.physics_validated`` and (b) an advisory editorial
review written to ``editorial_reviews/review_<ts>.md``. Neither of those
is the green light to start drafting. This CLI is: a human author reads
the review, decides whether to revise or proceed, and — if proceeding —
runs ``scripts/approve_plan.py`` to stamp ``compile_metadata.plan_approved``
into the seed.

``src/main.py`` refuses to run the drafting pipeline on a seed without
that stamp (unless ``--allow-unapproved-plan`` is passed).

Usage:
    python scripts/approve_plan.py --franchise <slug> --book <slug>
                                   [--reviewer <name>]
                                   [--notes "short note"]
                                   [--base-dir .]
                                   [--unapprove]

Rewriting approval is explicit: re-running the command overwrites the
stamp with a fresh timestamp. ``--unapprove`` sets the flag back to
False (useful when you spot a problem after approving).

The command also appends one line per invocation to
``editorial_reviews/approvals.jsonl`` so the decision trail is auditable.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_paths import ProjectPaths  # noqa: E402


def approve_plan(
    *,
    franchise_slug: str,
    book_slug: str,
    base_dir: str = ".",
    reviewer: str | None = None,
    notes: str = "",
    unapprove: bool = False,
) -> dict:
    """Stamp or clear ``compile_metadata.plan_approved`` on the book's seed.

    Returns the approval record that was appended to approvals.jsonl.
    Raises FileNotFoundError when the seed is missing.
    """
    paths = ProjectPaths(
        book_slug, base_dir=base_dir, franchise_slug=franchise_slug,
    )
    if not paths.concept_seed_path.exists():
        raise FileNotFoundError(
            f"concept_seed.json not found at {paths.concept_seed_path}. "
            "Run scripts/compile_bundle.py first."
        )

    seed = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
    meta = seed.setdefault("compile_metadata", {})

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reviewer = reviewer or getpass.getuser() or "unknown"

    if unapprove:
        meta["plan_approved"] = False
        meta["plan_approved_at"] = None
        meta["plan_approved_by"] = None
    else:
        meta["plan_approved"] = True
        meta["plan_approved_at"] = ts
        meta["plan_approved_by"] = reviewer

    paths.concept_seed_path.write_text(
        json.dumps(seed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    record = {
        "timestamp": ts,
        "reviewer": reviewer,
        "action": "unapprove" if unapprove else "approve",
        "notes": notes,
        "physics_validated": meta.get("physics_validated"),
    }
    reviews_dir = paths.book_dir / "editorial_reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    approvals_path = reviews_dir / "approvals.jsonl"
    with approvals_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stamp compile_metadata.plan_approved on a book's concept_seed.",
    )
    parser.add_argument("--franchise", required=True, help="Franchise slug")
    parser.add_argument("--book", required=True, help="Book slug")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument(
        "--reviewer",
        default=None,
        help="Reviewer name/handle (defaults to the OS username).",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional free-text notes appended to approvals.jsonl.",
    )
    parser.add_argument(
        "--unapprove",
        action="store_true",
        help="Revoke prior approval (sets plan_approved=False).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        record = approve_plan(
            franchise_slug=args.franchise,
            book_slug=args.book,
            base_dir=args.base_dir,
            reviewer=args.reviewer,
            notes=args.notes,
            unapprove=args.unapprove,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    action = record["action"]
    print(
        f"Plan {action}d for {args.franchise}/{args.book} "
        f"by {record['reviewer']} at {record['timestamp']}."
    )
    if args.notes:
        print(f"Notes: {args.notes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
