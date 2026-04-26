#!/usr/bin/env python3
"""Create and inspect an idea-session capture workspace.

The capture workspace is a front door for author-led planning. It does not
replace the six workflow-kit surfaces; it gives a planning chat somewhere
structured to land before those surfaces are authored.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_paths import ProjectPaths, _slugify_franchise, slugify_title  # noqa: E402


SURFACES: tuple[str, ...] = (
    "universe",
    "canon",
    "voice",
    "characters",
    "outline",
    "scene_cards",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _paths(*, title: str, franchise: str, base_dir: str) -> ProjectPaths:
    return ProjectPaths(
        slugify_title(title),
        base_dir=base_dir,
        franchise_slug=_slugify_franchise(franchise),
    )


def _idea_dir(paths: ProjectPaths) -> Path:
    return paths.workflows_dir / "idea_session"


def _default_capture(
    *,
    title: str,
    franchise: str,
    session_name: str,
    transcript_path: str | None,
    project_scope: str,
    canon_status: str | None,
    series_id: str | None,
    book_number: int | None,
    cosmology_id: str | None,
    source_franchise: str | None,
    source_work: str | None,
    parent_project: str | None,
    branch_point: str | None,
    base_source: str | None,
) -> dict:
    relationship = {
        "project_scope": project_scope,
        "canon_status": canon_status,
        "series_id": series_id,
        "book_number": book_number,
        "cosmology_id": cosmology_id,
        "source_franchise": source_franchise,
        "source_work": source_work,
        "parent_project": parent_project,
        "branch_point": branch_point,
        "base_source": base_source,
    }
    return {
        "surface": "idea-session-capture",
        "schema_version": "1.0",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "project": {
            "title": title,
            "franchise": franchise,
            "book_slug": slugify_title(title),
            "franchise_slug": _slugify_franchise(franchise),
            "session_name": session_name,
        },
        "relationship": relationship,
        "source": {
            "transcript_path": transcript_path,
            "raw_transcript_file": "raw_transcript.md" if transcript_path else None,
        },
        "north_star": {
            "one_sentence_pitch": "",
            "reader_promise": "",
            "emotional_core": "",
            "author_intent": "",
            "non_negotiables": [],
            "avoid": [],
        },
        "depth_ladder": [
            {
                "stage": "spark",
                "goal": "Find the idea, promise, and emotional pressure.",
                "status": "open",
            },
            {
                "stage": "foundation",
                "goal": "Set universe, continuity, tone, premise, conflict, and theme.",
                "status": "open",
            },
            {
                "stage": "deepening",
                "goal": "Develop characters, setting logic, voice, structure, and recurring choices.",
                "status": "open",
            },
            {
                "stage": "production_handoff",
                "goal": "Turn settled decisions into six workflow-kit surfaces.",
                "status": "open",
            },
        ],
        "decisions": [],
        "open_questions": [],
        "surface_handoffs": {
            surface: {
                "status": "not_started",
                "settled_inputs": [],
                "questions_to_resolve": [],
                "notes": "",
            }
            for surface in SURFACES
        },
        "parking_lot": [],
        "next_steps": [
            "Fill session.md during the idea chat.",
            "Move settled notes into capture.json decisions and surface_handoffs.",
            "Author the six workflow-kit surfaces from the handoff briefs.",
            "Run scripts/compile_bundle.py after the six surfaces are ready.",
        ],
    }


def _session_markdown(title: str, franchise: str) -> str:
    return dedent(
        f"""\
        # Idea Session - {title}

        Franchise / universe: {franchise}

        ## Relationship To Existing Work

        - Project scope:
        - Canon status:
        - Series ID / book number:
        - Shared cosmology ID:
        - Source franchise / source work:
        - Parent project:
        - Branch point:
        - Base source:

        ## North Star

        - One-sentence pitch:
        - Reader promise:
        - Emotional core:
        - Author intent:
        - Non-negotiables:
        - Avoid:

        ## Session Ladder

        ### 1. Spark

        What is the first image, dilemma, relationship, or question that makes this book feel alive?

        ### 2. Foundation

        What must be true about the setting, timeline, canon status, tone, premise, conflict, and theme?

        ### 3. Deepening

        What does the book become when we push on character wounds, contradictions, setting pressures, and moral cost?

        ### 4. Production Handoff

        Which decisions are settled enough to hand to universe, canon, voice, characters, outline, and scene cards?

        ## Settled Decisions

        - 

        ## Open Questions

        - 

        ## Surface Notes

        ### Universe

        ### Canon

        ### Voice

        ### Characters

        ### Outline

        ### Scene Cards

        ## Parking Lot

        - 
        """
    )


def _surface_handoff_markdown(surface: str) -> str:
    titles = {
        "universe": "Universe Builder",
        "canon": "Canon Drafter",
        "voice": "Voice Discovery",
        "characters": "Character Forge",
        "outline": "Outline Planner",
        "scene_cards": "Scene Card Authoring",
    }
    prompts = {
        "universe": "Premise, conflict, theme, setting scope, canon status, era, tone, target shape.",
        "canon": "Continuity rules, constraints, terminology, allowed references, mechanics.",
        "voice": "POV, register, prose rules, anti-patterns, dialogue texture, character voices.",
        "characters": "Cast, wants, needs, wounds, contradictions, relationships, arc types.",
        "outline": "Act structure, promises, reveals, reversals, subplots, chapter turns.",
        "scene_cards": "Scene-by-scene beats, POV, characters present, turning points, hooks.",
    }
    return dedent(
        f"""\
        # {titles[surface]} Handoff

        Purpose: {prompts[surface]}

        ## Settled Inputs

        - 

        ## Open Questions

        - 

        ## Must Preserve

        - 

        ## Avoid

        - 

        ## Notes For Surface Session

        """
    )


def _write_text(path: Path, text: str, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _write_json(path: Path, payload: dict, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def init_command(args: argparse.Namespace) -> int:
    paths = _paths(title=args.title, franchise=args.franchise, base_dir=args.base_dir)
    idea_dir = _idea_dir(paths)
    transcript_path = str(Path(args.from_transcript)) if args.from_transcript else None
    transcript: Path | None = Path(args.from_transcript) if args.from_transcript else None
    if transcript is not None and not transcript.exists():
        raise FileNotFoundError(f"transcript not found: {transcript}")
    capture = _default_capture(
        title=args.title,
        franchise=args.franchise,
        session_name=args.session_name,
        transcript_path=transcript_path,
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
    )

    written: list[Path] = []
    skipped: list[Path] = []

    targets = [
        (idea_dir / "capture.json", capture, "json"),
        (idea_dir / "session.md", _session_markdown(args.title, args.franchise), "text"),
        (
            idea_dir / "README.md",
            dedent(
                """\
                # Idea Session Capture

                This folder is the author-facing front door for planning. It is not
                read by compile_bundle.py. Use it to hold chat notes, settled
                decisions, open questions, and handoffs into the six workflow-kit
                surfaces.

                Files:

                - capture.json: machine-readable session state.
                - session.md: live planning notes.
                - raw_transcript.md: optional pasted/exported chat transcript.
                - surface_handoffs/*.md: notes to carry into each workflow surface.
                """
            ),
            "text",
        ),
    ]
    for path, payload, kind in targets:
        ok = (
            _write_json(path, payload, force=args.force)
            if kind == "json"
            else _write_text(path, payload, force=args.force)
        )
        (written if ok else skipped).append(path)

    handoff_dir = idea_dir / "surface_handoffs"
    for surface in SURFACES:
        path = handoff_dir / f"{surface}.md"
        ok = _write_text(path, _surface_handoff_markdown(surface), force=args.force)
        (written if ok else skipped).append(path)

    if args.from_transcript:
        raw_path = idea_dir / "raw_transcript.md"
        ok = _write_text(raw_path, transcript.read_text(encoding="utf-8"), force=args.force)
        (written if ok else skipped).append(raw_path)

    print(f"Idea session workspace: {idea_dir}")
    if written:
        print("Wrote:")
        for path in written:
            print(f"- {path}")
    if skipped:
        print("Skipped existing files (use --force to overwrite):")
        for path in skipped:
            print(f"- {path}")
    return 0


def status_command(args: argparse.Namespace) -> int:
    paths = _paths(title=args.title, franchise=args.franchise, base_dir=args.base_dir)
    capture_path = _idea_dir(paths) / "capture.json"
    if not capture_path.exists():
        print(f"No idea-session capture found at {capture_path}")
        return 1
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    decisions = capture.get("decisions") or []
    questions = capture.get("open_questions") or []
    handoffs = capture.get("surface_handoffs") or {}
    relationship = capture.get("relationship") or {}
    print(f"Idea session: {capture['project']['title']} ({capture['project']['franchise']})")
    print(f"Updated: {capture.get('updated_at')}")
    print(
        "Relationship: "
        f"{relationship.get('project_scope', 'unknown')}"
        + (f", series={relationship['series_id']}" if relationship.get("series_id") else "")
        + (f", cosmology={relationship['cosmology_id']}" if relationship.get("cosmology_id") else "")
        + (f", base={relationship['base_source']}" if relationship.get("base_source") else "")
    )
    print(f"Decisions: {len(decisions)}")
    print(f"Open questions: {len(questions)}")
    print("Surface handoffs:")
    for surface in SURFACES:
        data = handoffs.get(surface) or {}
        settled = len(data.get("settled_inputs") or [])
        unresolved = len(data.get("questions_to_resolve") or [])
        print(f"- {surface}: {data.get('status', 'missing')} ({settled} settled, {unresolved} questions)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create an idea-session capture workspace.")
    init.add_argument("--title", required=True)
    init.add_argument("--franchise", required=True)
    init.add_argument("--session-name", default="initial-idea-session")
    init.add_argument("--from-transcript", default=None, help="Optional markdown/text transcript to copy in.")
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
        help="Optional canon status to preserve for the universe-builder handoff.",
    )
    init.add_argument("--series-id", default=None)
    init.add_argument("--book-number", type=int, default=None)
    init.add_argument("--cosmology-id", default=None)
    init.add_argument("--source-franchise", default=None)
    init.add_argument("--source-work", default=None)
    init.add_argument("--parent-project", default=None)
    init.add_argument("--branch-point", default=None)
    init.add_argument("--base-source", default=None)
    init.add_argument("--base-dir", default=".")
    init.add_argument("--force", action="store_true", help="Overwrite existing capture files.")
    init.set_defaults(func=init_command)

    status = sub.add_parser("status", help="Summarize an existing idea-session capture.")
    status.add_argument("--title", required=True)
    status.add_argument("--franchise", required=True)
    status.add_argument("--base-dir", default=".")
    status.set_defaults(func=status_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
