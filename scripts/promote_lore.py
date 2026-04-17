"""Phase 7.3 — provisional → canonical lore promotion CLI.

Lists provisional lore entries for a universe, shows any conflict flags
the LoreConflictDetector raises against each, and lets the operator
approve (→ canonical) or reject (→ deprecated) per entry. Interactive
mode is the default; --accept-all / --reject-all are available for
scripted pipelines.

Usage:
    python scripts/promote_lore.py --franchise <slug> [--book <slug>]
        [--category faction] [--interactive | --accept-all | --reject-all]
        [--dry-run] [--json-out report.json]

Exits 0 on clean runs (including "no provisional entries to review");
non-zero exits reserved for hard errors (universe not found, DB open
failure, etc.).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_paths import ProjectPaths  # noqa: E402
from src.worldbuilding.lore_conflict_detector import (  # noqa: E402
    ConflictFlag,
    LoreConflictDetector,
)


PromptFn = Callable[[str], str]


# ---------------------------------------------------------------------------
# Decision record
# ---------------------------------------------------------------------------


@dataclass
class PromotionDecision:
    entry_id: str
    title: str
    category: str
    decision: str  # "promote" | "reject" | "skip"
    conflict_flags: list[dict] = field(default_factory=list)
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "title": self.title,
            "category": self.category,
            "decision": self.decision,
            "conflict_flags": self.conflict_flags,
            "reason": self.reason,
        }


@dataclass
class PromotionReport:
    universe_id: str
    total_provisional: int = 0
    decisions: list[PromotionDecision] = field(default_factory=list)
    dry_run: bool = False

    @property
    def promoted(self) -> list[PromotionDecision]:
        return [d for d in self.decisions if d.decision == "promote"]

    @property
    def rejected(self) -> list[PromotionDecision]:
        return [d for d in self.decisions if d.decision == "reject"]

    @property
    def skipped(self) -> list[PromotionDecision]:
        return [d for d in self.decisions if d.decision == "skip"]

    def to_dict(self) -> dict:
        return {
            "universe_id": self.universe_id,
            "total_provisional": self.total_provisional,
            "dry_run": self.dry_run,
            "promoted_count": len(self.promoted),
            "rejected_count": len(self.rejected),
            "skipped_count": len(self.skipped),
            "decisions": [d.to_dict() for d in self.decisions],
        }


# ---------------------------------------------------------------------------
# Core promotion logic
# ---------------------------------------------------------------------------


def _flags_for_entry(
    detector: LoreConflictDetector, entry_id: str, universe_id: str,
) -> list[ConflictFlag]:
    scan = detector.scan_provisional_batch([entry_id], universe_id)
    return scan.flags


def _format_entry_summary(entry: dict, flags: list[ConflictFlag]) -> str:
    title = entry.get("title", "<untitled>")
    category = entry.get("category", "?")
    content = (entry.get("content") or "").strip()
    preview = content[:160] + ("..." if len(content) > 160 else "")
    lines = [
        f"[{entry.get('entry_id')}] ({category}) {title}",
        f"  {preview}" if preview else "  <empty content>",
    ]
    if flags:
        lines.append(f"  ⚑ {len(flags)} conflict flag(s):")
        for f in flags:
            lines.append(
                f"    - {f.conflict_type} ({f.severity}): {f.rationale}"
            )
    else:
        lines.append("  ⚑ clean (no conflict flags)")
    return "\n".join(lines)


def _prompt_decision(prompt: PromptFn) -> str:
    """Prompt the operator for a per-entry decision. Returns one of
    'promote', 'reject', 'skip', 'quit'."""
    valid = {
        "p": "promote", "promote": "promote", "y": "promote",
        "r": "reject", "reject": "reject", "n": "reject",
        "s": "skip", "skip": "skip",
        "q": "quit", "quit": "quit",
    }
    while True:
        raw = prompt(
            "  Decision: [P]romote / [R]eject / [S]kip / [Q]uit > "
        ).strip().lower()
        if raw in valid:
            return valid[raw]
        # Retry silently — invalid input.


def promote_lore(
    *,
    lore_service,
    universe_id: str,
    canon_profile: Optional[dict] = None,
    category: Optional[str] = None,
    dry_run: bool = False,
    mode: str = "interactive",  # "interactive" | "accept-all" | "reject-all"
    prompt: PromptFn = input,
    printer: Callable[[str], None] = print,
) -> PromotionReport:
    """Run the promotion flow against a LoreService.

    Returns a PromotionReport summarizing decisions. When ``dry_run`` is
    True, no status changes are written to the DB, but the report is
    populated with what *would* have been done.
    """
    report = PromotionReport(universe_id=universe_id, dry_run=dry_run)

    # List provisional entries (optionally category-filtered).
    provisional = lore_service.db.list_lore_entries(
        universe_id=universe_id,
        category=category,
        status="provisional",
    )
    report.total_provisional = len(provisional)
    if not provisional:
        printer(f"No provisional entries to review for universe '{universe_id}'.")
        return report

    detector = LoreConflictDetector(lore_service, canon_profile=canon_profile)
    printer(
        f"Reviewing {len(provisional)} provisional entry/entries in "
        f"universe '{universe_id}'"
        + (f" (category={category})" if category else "")
        + f" — mode: {mode}"
        + (" [DRY-RUN]" if dry_run else "")
    )

    quit_requested = False
    for entry in provisional:
        entry_id = entry["entry_id"]
        flags = _flags_for_entry(detector, entry_id, universe_id)

        if quit_requested:
            decision = "skip"
        elif mode == "accept-all":
            decision = "promote"
        elif mode == "reject-all":
            decision = "reject"
        else:
            printer("")
            printer(_format_entry_summary(entry, flags))
            raw_decision = _prompt_decision(prompt)
            if raw_decision == "quit":
                quit_requested = True
                decision = "skip"
            else:
                decision = raw_decision

        report.decisions.append(
            PromotionDecision(
                entry_id=entry_id,
                title=entry.get("title", ""),
                category=entry.get("category", ""),
                decision=decision,
                conflict_flags=[f.to_dict() for f in flags],
            )
        )

        if dry_run or decision == "skip":
            continue
        if decision == "promote":
            lore_service.promote_entry(entry_id)
        elif decision == "reject":
            # Deprecated status keeps the audit trail in the DB.
            lore_service.db.update_lore_entry(entry_id, status="deprecated")

    return report


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _format_summary(report: PromotionReport) -> str:
    lines = [
        f"Promotion summary (universe={report.universe_id})"
        + (" [DRY-RUN]" if report.dry_run else ""),
        f"  total provisional reviewed: {report.total_provisional}",
        f"  promoted: {len(report.promoted)}",
        f"  rejected: {len(report.rejected)}",
        f"  skipped:  {len(report.skipped)}",
    ]
    if report.promoted:
        lines.append("  Promoted entries:")
        for d in report.promoted:
            lines.append(f"    + {d.entry_id} ({d.category}) {d.title}")
    if report.rejected:
        lines.append("  Rejected (→ deprecated) entries:")
        for d in report.rejected:
            lines.append(f"    - {d.entry_id} ({d.category}) {d.title}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_lore_service(
    *, franchise_slug: str, base_dir: str = ".", use_mock_embeddings: bool = True,
):
    """Instantiate the LoreService stack for CLI use.

    Defaults to mock embeddings so the CLI doesn't require API keys to
    run a promotion pass. Real embeddings are not needed for promotion
    itself — only for retrieval.
    """
    from src.worldbuilding.lore_service import LoreService
    from src.worldbuilding.lore_vectorstore import LoreVectorStore
    from src.worldbuilding.worldbuilding_db import WorldbuildingDB

    paths = ProjectPaths(
        project_slug="unused",  # universe-scoped — book slug is optional
        base_dir=base_dir,
        franchise_slug=franchise_slug,
    )
    paths.ensure_dirs()
    wb_db = WorldbuildingDB(db_path=str(paths.worldbuilding_db))
    ef = None
    if use_mock_embeddings:
        try:
            from src.rag.embedding import get_embedding_function
            ef = get_embedding_function(use_mock=True)
        except Exception:
            pass
    vs = LoreVectorStore(
        persist_directory=str(paths.worldbuilding_vectors_dir),
        embedding_function=ef,
    )
    return LoreService(db=wb_db, vectorstore=vs)


def _load_canon_profile(
    *, franchise_slug: str, book_slug: Optional[str], base_dir: str,
) -> Optional[dict]:
    """Try to locate the project's canon_profile so the conflict detector
    can apply cross_continuity_violations / anachronistic_terms checks.

    Returns None if no book slug is supplied or if the seed can't be
    loaded — the detector then runs with only the title/timeline passes.
    """
    if not book_slug:
        return None
    paths = ProjectPaths(
        project_slug=book_slug,
        base_dir=base_dir,
        franchise_slug=franchise_slug,
    )
    seed_path = paths.concept_seed_path
    if not seed_path.exists():
        return None
    try:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return seed.get("canon_profile")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Review provisional lore entries and promote / reject them "
            "into the canonical bucket."
        ),
    )
    parser.add_argument("--franchise", required=True, help="Franchise slug")
    parser.add_argument(
        "--book",
        default=None,
        help=(
            "Book slug — used to locate the project's canon_profile for "
            "conflict detection. Optional; detector still runs without it."
        ),
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Filter to a single category (faction, location, ...).",
    )
    parser.add_argument("--base-dir", default=".", help="Repository root")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--accept-all",
        action="store_true",
        help="Promote every provisional entry without prompting.",
    )
    mode.add_argument(
        "--reject-all",
        action="store_true",
        help="Reject every provisional entry without prompting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print decisions but do not write to the DB.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Write the full decision report to this JSON path.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.accept_all:
        mode = "accept-all"
    elif args.reject_all:
        mode = "reject-all"
    else:
        mode = "interactive"

    try:
        lore_service = _build_lore_service(
            franchise_slug=args.franchise, base_dir=args.base_dir,
        )
    except Exception as exc:
        print(f"ERROR: failed to open worldbuilding DB: {exc}", file=sys.stderr)
        return 2

    canon_profile = _load_canon_profile(
        franchise_slug=args.franchise,
        book_slug=args.book,
        base_dir=args.base_dir,
    )

    report = promote_lore(
        lore_service=lore_service,
        universe_id=args.franchise,
        canon_profile=canon_profile,
        category=args.category,
        dry_run=args.dry_run,
        mode=mode,
    )

    print("")
    print(_format_summary(report))

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Decision report written: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
