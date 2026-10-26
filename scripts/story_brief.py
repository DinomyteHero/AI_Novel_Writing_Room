"""CLI for the Story Brief / claim ledger.

Examples:
    python scripts/story_brief.py init --title "My Novel" --franchise "Original"
    python scripts/story_brief.py status --title "My Novel" --franchise "Original"
    python scripts/story_brief.py gaps --title "My Novel" --franchise "Original"
    python scripts/story_brief.py claim add --title ... --franchise ... \
        --type character --id mara --field want --value "To clear her name"
    python scripts/story_brief.py fill --title ... --franchise ... \
        --gap character:mara:want --mode delegate
    python scripts/story_brief.py sheets --title ... --franchise ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflows.idea_session_capture import IdeaSessionCapture  # noqa: E402


def _capture(args: argparse.Namespace) -> IdeaSessionCapture:
    return IdeaSessionCapture(
        title=args.title,
        franchise=args.franchise,
        base_dir=args.base_dir,
    )


def _print_coverage(cap: IdeaSessionCapture) -> None:
    cov = cap.story_coverage()
    print(f"Story Brief: {cap.title}")
    print(f"  confirmed claims: {cov['claims_confirmed']}")
    print(f"  proposed claims:  {cov['claims_proposed']}")
    print(f"  entities:         {cov['entities']}")
    print(f"  essential gaps:   {cov['gaps_essential']}")
    print(f"  recommended gaps: {cov['gaps_recommended']}")
    print(f"  blocking questions: {cov['open_blocking_questions']}")
    print(f"  ready for sheets: {cov['ready_for_sheets']}")
    if cov["next_gaps"]:
        print("\nNext gaps:")
        for gap in cov["next_gaps"]:
            print(f"  {gap['gap_id']} ({gap['action']}): {gap['prompt']}")


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--title", required=True)
    common.add_argument("--franchise", required=True)
    common.add_argument("--base-dir", default=".")

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", parents=[common], help="Create the capture workspace + Story Brief.")
    sub.add_parser("status", parents=[common], help="Show claim/gap coverage.")
    sub.add_parser("gaps", parents=[common], help="List gaps by leverage.")
    sub.add_parser("sheets", parents=[common], help="Write reviewable Markdown sheets.")

    claim = sub.add_parser("claim", help="Add or transition a claim.")
    claim_sub = claim.add_subparsers(dest="claim_cmd", required=True)
    add = claim_sub.add_parser("add", parents=[common])
    add.add_argument("--type", required=True, dest="entity_type")
    add.add_argument("--id", default=None, dest="entity_id")
    add.add_argument("--field", required=True)
    add.add_argument("--value", required=True)
    add.add_argument("--origin", default="author",
                     choices=["author", "inferred", "delegated", "import"])
    add.add_argument("--status", default=None,
                     choices=["proposed", "confirmed", "rejected"])
    add.add_argument("--quote", default="")
    for name in ("confirm", "reject"):
        p = claim_sub.add_parser(name, parents=[common])
        p.add_argument("claim_id")
    delegate = claim_sub.add_parser("delegate", parents=[common])
    delegate.add_argument("claim_id")
    delegate.add_argument("--rationale", default="")

    fill = sub.add_parser("fill", parents=[common], help="Fill a gap with a value or delegated option.")
    fill.add_argument("--gap", required=True)
    fill.add_argument("--value", default=None)
    fill.add_argument("--mode", default="delegate",
                      choices=["author", "delegate", "propose"])
    fill.add_argument("--rationale", default="")

    args = parser.parse_args(argv)
    cap = _capture(args)

    if args.cmd != "init" and not cap.capture_path.exists():
        print(
            f"No idea-session workspace at {cap.workspace}; "
            "run `story_brief.py init` first."
        )
        return 1

    if args.cmd == "init":
        result = cap.init_workspace()
        print(f"wrote {len(result['written'])} file(s) under {cap.workspace}")
        return 0
    if args.cmd == "status":
        _print_coverage(cap)
        return 0
    if args.cmd == "gaps":
        for gap in cap.next_questions(20):
            print(f"{gap['gap_id']}  [{gap['importance']}/{gap['action']}]  {gap['prompt']}")
        return 0
    if args.cmd == "sheets":
        paths = cap.write_review_sheets()
        for path in paths:
            print(path)
        return 0
    if args.cmd == "claim":
        if args.claim_cmd == "add":
            claim = cap.add_claim(
                entity_type=args.entity_type,
                entity_id=args.entity_id,
                field=args.field,
                value=args.value,
                origin=args.origin,
                status=args.status,
                source_quote=args.quote,
            )
            print(json.dumps(claim, indent=2))
        elif args.claim_cmd == "confirm":
            print(json.dumps(cap.confirm_claim(args.claim_id), indent=2))
        elif args.claim_cmd == "reject":
            print(json.dumps(cap.reject_claim(args.claim_id), indent=2))
        elif args.claim_cmd == "delegate":
            print(json.dumps(cap.delegate_claim(args.claim_id, rationale=args.rationale), indent=2))
        return 0
    if args.cmd == "fill":
        claim = cap.fill_gap(
            args.gap, value=args.value, mode=args.mode, rationale=args.rationale,
        )
        print(json.dumps(claim, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
