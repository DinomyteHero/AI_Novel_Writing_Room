#!/usr/bin/env python3
"""CLI for the idea-session capture workspace.

Thin wrapper around `workflows.idea_session_capture.IdeaSessionCapture`.
The same Python entry points are used by the Claude Code skill and the
Codex AGENTS.md flow, so the CLI here just translates argparse into api
calls and renders human-readable output.

Subcommands:
    init     scaffold workflows/idea_session/ for a new project
    status   summarize a capture's readiness for expand/compile
    expand   pre-seed workflows/{universe,canon,voice,characters,outline}.json
             (and scene_cards/_intent.md) from the capture
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workflows.idea_session_capture.api import (  # noqa: E402
    SURFACES,
    IdeaSessionCapture,
)


def _make_capture(args: argparse.Namespace) -> IdeaSessionCapture:
    return IdeaSessionCapture(
        title=args.title,
        franchise=args.franchise,
        base_dir=args.base_dir,
    )


def init_command(args: argparse.Namespace) -> int:
    capture = _make_capture(args)
    result = capture.init_workspace(
        session_name=args.session_name,
        transcript_path=args.from_transcript,
        project_scope=args.project_scope,
        canon_status=args.canon_status,
        series_id=args.series_id,
        book_number=args.book_number,
        cosmology_id=args.cosmology_id,
        source_franchise=args.source_franchise,
        source_work=args.source_work,
        parent_project=args.parent_project,
        branch_point=args.branch_point,
        base_source=args.base_source,
        force=args.force,
    )
    print(f"Idea session workspace: {capture.workspace}")
    if result["written"]:
        print("Wrote:")
        for path in result["written"]:
            print(f"- {path}")
    if result["skipped"]:
        print("Skipped existing files (use --force to overwrite):")
        for path in result["skipped"]:
            print(f"- {path}")
    return 0


def status_command(args: argparse.Namespace) -> int:
    capture = _make_capture(args)
    try:
        snapshot = capture.status()
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    rel = snapshot.relationship
    print(f"Idea session: {snapshot.title} ({snapshot.franchise})")
    print(f"Updated: {snapshot.updated_at}")
    rel_bits = [f"scope={rel.get('project_scope', 'unknown')}"]
    for key in ("series_id", "cosmology_id", "base_source"):
        if rel.get(key):
            rel_bits.append(f"{key}={rel[key]}")
    print("Relationship: " + ", ".join(rel_bits))
    print(f"Decisions: {snapshot.decisions_count}")
    print(f"Open questions: {snapshot.open_questions_count}")
    print(
        "Ready for expand: "
        + ("yes" if snapshot.ready_for_expand else "no (set north_star pitch + add a decision)")
    )
    print("Surface handoffs:")
    for surface in SURFACES:
        block = snapshot.handoff_status.get(surface, {})
        print(
            f"- {surface}: {block.get('status', 'missing')} "
            f"({block.get('settled', 0)} settled, {block.get('questions', 0)} questions)"
        )
    return 0


def expand_command(args: argparse.Namespace) -> int:
    capture = _make_capture(args)
    try:
        result = capture.expand_to_surface_drafts(
            force=args.force,
            surfaces=args.only or None,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"expand failed: {exc}")
        return 1
    print(f"Expanded capture into surface drafts under {capture.paths.workflows_dir}")
    if result["written"]:
        print("Wrote:")
        for path in result["written"]:
            print(f"- {path}")
    if result["skipped"]:
        print("Skipped existing files (use --force to overwrite):")
        for path in result["skipped"]:
            print(f"- {path}")
    print(
        "\nNext: open each surface (universe-builder, canon-drafter, voice-discovery,"
        " character-forge, outline-planner, scene-card-authoring)\nto deepen the seeded drafts."
    )
    return 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title", required=True)
    parser.add_argument("--franchise", required=True)
    parser.add_argument("--base-dir", default=".")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create an idea-session capture workspace.")
    _add_common_args(init)
    init.add_argument("--session-name", default="initial-idea-session")
    init.add_argument(
        "--from-transcript",
        default=None,
        help="Optional markdown/text transcript to copy in.",
    )
    init.add_argument(
        "--project-scope",
        default="standalone",
        choices=[
            "standalone",
            "planned_series",
            "continuation",
            "spinoff",
            "shared_universe_entry",
            "alternate_universe",
            "anthology_entry",
        ],
    )
    init.add_argument(
        "--canon-status",
        default=None,
        choices=["canon_compliant", "AU", "original"],
        help="Optional canon status for the universe-builder handoff.",
    )
    init.add_argument("--series-id", default=None)
    init.add_argument("--book-number", type=int, default=None)
    init.add_argument("--cosmology-id", default=None)
    init.add_argument("--source-franchise", default=None)
    init.add_argument("--source-work", default=None)
    init.add_argument("--parent-project", default=None)
    init.add_argument("--branch-point", default=None)
    init.add_argument("--base-source", default=None)
    init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing capture files.",
    )
    init.set_defaults(func=init_command)

    status = sub.add_parser(
        "status", help="Summarize an existing idea-session capture."
    )
    _add_common_args(status)
    status.set_defaults(func=status_command)

    expand = sub.add_parser(
        "expand",
        help="Pre-seed the six surface drafts from a populated capture.",
    )
    _add_common_args(expand)
    expand.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing surface drafts.",
    )
    expand.add_argument(
        "--only",
        nargs="+",
        choices=list(SURFACES),
        default=None,
        help="Limit expansion to specific surfaces.",
    )
    expand.set_defaults(func=expand_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
