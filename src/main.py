"""CLI entry point for the AI Writers' Room pipeline."""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # Load .env before any module reads os.environ

import re

from src.memory.context_assembler import ContextAssembler
from src.model_router import ModelRouter
from src.orchestrator import Orchestrator
from src.project_paths import ProjectPaths, slugify_title
from src.run_ledger import RunLedger


def _slugify_title(title: str) -> str:
    """Convert a project title to a kebab-case directory slug.

    Deprecated: use project_paths.slugify_title instead.
    """
    return slugify_title(title)


def _git_info() -> tuple[str | None, bool | None]:
    """Return (HEAD SHA, is_dirty) for the current repo, or (None, None) if git is unavailable.

    Used for run reproducibility. A run produced on a dirty tree is less
    reproducible than one on a clean tree, so both facts are captured.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None, None
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        is_dirty = bool(status.strip())
    except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
        is_dirty = None
    return sha, is_dirty


def _write_reproducibility_snapshot(
    run_dir: Path,
    args: argparse.Namespace,
    pipeline_variant: str,
) -> None:
    """Snapshot prompt files and invocation metadata into the run directory.

    Config alone is insufficient for reproducibility: prompt file contents
    and CLI flags (e.g. --no-revision) both materially change generation
    behavior. Two runs with identical `config_snapshot.yaml` can produce
    systematically different prose if either differs. This captures both.

    Writes:
      - run_dir/prompts_snapshot/  — copy of the entire prompts/ tree
      - run_dir/invocation.json    — CLI args + timestamp + git SHA + pipeline_variant
    """
    run_dir.mkdir(parents=True, exist_ok=True)

    # Copy prompts tree (small — ~19 markdown files, negligible disk cost)
    prompts_src = Path("prompts")
    if prompts_src.exists():
        prompts_dest = run_dir / "prompts_snapshot"
        # dirs_exist_ok=True so reruns of the same run_id don't crash
        shutil.copytree(prompts_src, prompts_dest, dirs_exist_ok=True)

    # Invocation metadata
    sha, dirty = _git_info()
    invocation = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": sha,
        "git_dirty": dirty,
        "python_version": sys.version,
        "pipeline_variant": pipeline_variant,
        "cli_args": {k: v for k, v in vars(args).items() if not k.startswith("_")},
    }
    (run_dir / "invocation.json").write_text(
        json.dumps(invocation, indent=2, default=str),
        encoding="utf-8",
    )


def _scene_had_advisory(result: dict) -> bool:
    """Return True if any advisory gate fired for a saved scene.

    Relay v3 (Stage 1i): a scene is considered 'saved_with_advisory' when
    the scene-level gate verdict was not 'pass', when Final Gate rejected
    the polish, when the legacy polish_rejected flag was set, or when the
    continuity editor returned a non-pass verdict (any canon finding).
    'saved_clean' means all gates green.
    """
    if result.get("polish_rejected"):
        return True
    evaluation = result.get("evaluation") or {}
    gate_verdict = evaluation.get("verdict")
    if gate_verdict not in (None, "pass", "skipped"):
        return True
    if gate_verdict == "skipped":
        # Skipped-gate scenes have no verdict; treat as advisory because the
        # save path did not go through a full gate check.
        return True
    final_gate = result.get("final_gate") or {}
    if final_gate and final_gate.get("verdict") not in (None, "pass"):
        return True
    continuity = result.get("continuity_report") or {}
    if continuity and continuity.get("verdict") == "fail":
        return True
    return False


def check_plan_approval(
    concept_seed: dict,
    *,
    allow_unapproved: bool,
    seed_path: str = "",
) -> tuple[bool, str]:
    """Return (approved, error_message).

    A plan is approved when ``compile_metadata.plan_approved`` is True or
    when the caller passes ``allow_unapproved=True`` (the override flag).
    ``error_message`` is empty on approval, a user-facing diagnostic on
    rejection.
    """
    if allow_unapproved:
        return True, ""
    meta = concept_seed.get("compile_metadata", {}) or {}
    if meta.get("plan_approved") is True:
        return True, ""
    physics_flag = meta.get("physics_validated")
    physics_note = (
        "physics_validated=True" if physics_flag is True
        else f"physics_validated={physics_flag!r}"
    )
    msg = (
        "Error: plan has not been approved for drafting.\n"
        f"  concept_seed: {seed_path or '<unspecified>'}\n"
        f"  compile_metadata: {physics_note}, plan_approved="
        f"{meta.get('plan_approved')!r}\n"
        "\n"
        "Approve via:\n"
        "  python scripts/approve_plan.py --franchise <slug> --book <slug>\n"
        "\n"
        "Or bypass this gate with --allow-unapproved-plan (not recommended)."
    )
    return False, msg


def _count_quarantined_scenes(ledger) -> int:
    """Count 'save_blocked' events in the ledger.

    Used for the three-count CLI summary. Each save_blocked event corresponds
    to one quarantined scene (the orchestrator aborts after the first one).
    """
    if ledger is None:
        return 0
    try:
        events = ledger.get_events(event_type="save_blocked", limit=1000)
    except Exception:
        return 0
    return len(events)


def load_scene_cards(scene_cards_dir: str, chapter: int | None = None) -> list[dict]:
    """Load scene cards from a directory, optionally filtering by chapter."""
    cards_path = Path(scene_cards_dir)
    if not cards_path.exists():
        print(f"Error: Scene cards directory not found: {scene_cards_dir}")
        sys.exit(1)

    cards = []
    for card_file in sorted(cards_path.glob("*.json")):
        with open(card_file, encoding="utf-8") as f:
            card = json.load(f)
            if chapter is None or card.get("chapter_number") == chapter:
                cards.append(card)

    if not cards:
        print(f"Error: No scene cards found in {scene_cards_dir}")
        if chapter:
            print(f"  (filtered for chapter {chapter})")
        sys.exit(1)

    return cards


def load_chapter_blueprints(
    paths: ProjectPaths,
    chapter: int | None = None,
) -> dict[int, dict]:
    """Load canonical chapter blueprints for chapter-packet compilation."""
    blueprints: dict[int, dict] = {}
    bp_dir = paths.chapter_blueprints_dir
    if not bp_dir.exists():
        return blueprints

    for path in sorted(bp_dir.glob("chapter_*.json")):
        try:
            chapter_number = int(path.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        if chapter is not None and chapter_number != chapter:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                blueprints[chapter_number] = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: Skipping invalid chapter blueprint {path}: {exc}")
    return blueprints


def build_chapter_packet_compiler(
    *,
    concept_seed: dict,
    paths: ProjectPaths,
    assembler: ContextAssembler,
    chapter: int | None = None,
    story_state=None,
    promise_ledger=None,
    continuity_log=None,
    sociogram=None,
):
    """Construct the runtime chapter-packet compiler used by CLI runs."""
    from src.pipeline.canon_guidance import CanonGuidanceStore
    from src.pipeline.chapter_packet import ChapterPacketCompiler

    canon_guidance_store = CanonGuidanceStore(
        paths.canon_guidance_dir,
        canon_contract_path=paths.canon_contract_path,
    )
    return ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints=load_chapter_blueprints(paths, chapter=chapter),
        assembler=assembler,
        story_state=story_state,
        promise_ledger=promise_ledger,
        continuity_log=continuity_log,
        sociogram=sociogram,
        canon_guidance_store=canon_guidance_store,
    )


def _init_phase2(concept_seed_path: str, config: dict, manuscripts_dir: str,
                  paths: "ProjectPaths | None" = None):
    """Initialize Phase 2 components. Returns (story_state, knowledge_layers,
    chapter_memory, canon_db, summarizer, state_diff_applier, contradiction_scanner)
    or all Nones if imports fail."""
    try:
        from src.agents.summarizer import Summarizer
        from src.memory.chapter_memory import ChapterMemory
        from src.memory.contradiction_scanner import ContradictionScanner
        from src.memory.knowledge_layers import KnowledgeLayers
        from src.memory.state_diff import StateDiffApplier
        from src.memory.story_state import StoryState
        from src.rag.embedding import get_embedding_function
    except ImportError as e:
        print(f"Warning: Phase 2 dependencies not available: {e}")
        return None, None, None, None, None, None, None

    # Initialize SQLite story state (project-scoped via ProjectPaths)
    state_db_path = str(paths.story_state_db) if paths else config.get(
        "pipeline", {}
    ).get("story_state_path", "output/_fallback/story_state.db")
    story_state = StoryState(db_path=state_db_path)

    # Initialize from concept seed
    with open(concept_seed_path, encoding="utf-8") as f:
        concept_seed = json.load(f)
    story_state.init_from_concept_seed(concept_seed)

    # Knowledge layers
    knowledge_layers = KnowledgeLayers(story_state)

    # Chapter memory (ChromaDB, project-scoped via ProjectPaths)
    chapter_memory_dir = str(paths.chapter_memory_dir) if paths else config.get(
        "pipeline", {}
    ).get("chapter_memory_dir", "output/_fallback/chapter_memory")
    try:
        embed_cfg = config.get("pipeline", {}).get("embeddings", {})
        use_mock = embed_cfg.get("use_mock", True)
        ef = get_embedding_function(use_mock=use_mock)
        chapter_memory = ChapterMemory(
            persist_directory=chapter_memory_dir,
            embedding_function=ef,
        )
    except Exception as e:
        print(f"Warning: ChapterMemory init failed: {e}")
        chapter_memory = None

    # Canon DB (optional, only if data exists)
    canon_db = None
    canon_db_dir = str(paths.canon_dbs_dir) if paths else config.get(
        "pipeline", {}
    ).get("canon_db_dir", "output/_fallback/canon_dbs")
    if Path(canon_db_dir).exists():
        try:
            from src.rag.canon_db import CanonDB
            canon_db = CanonDB(
                persist_directory=canon_db_dir,
                embedding_function=ef,
            )
        except Exception as e:
            print(f"Warning: CanonDB init failed: {e}")
    else:
        print(
            f"Warning: Canon DB directory not found at {canon_db_dir} — "
            f"retrieved canon evidence will be disabled"
        )

    return (
        story_state,
        knowledge_layers,
        chapter_memory,
        canon_db,
        None,  # summarizer created later with router
        None,  # state_diff_applier created later
        None,  # contradiction_scanner created later
    )


def _cli_milestone_prompt(milestone_info: dict) -> bool:
    """Prompt user at CLI for milestone gate approval."""
    print(f"\n{'='*60}")
    print(f"  MILESTONE: {milestone_info['milestone_name']}")
    print(f"  Chapter {milestone_info.get('chapter_number', '?')}")
    print(f"{'='*60}")
    print(f"\n  New phase constraints:")
    for constraint in milestone_info.get("constraints", []):
        print(f"    - {constraint}")
    response = input("\n  Continue? [y/n]: ").strip().lower()
    return response in ("y", "yes", "")


def _init_phase4(router, ledger, config, concept_seed, embedding_function,
                  no_milestones=False, judge=False):
    """Initialize Phase 4 components.

    Returns (physics_enforcer, metrics_dashboard, character_specialist,
             milestone_gates, pipeline_session, scene_card_generator,
             export_manager, judge_evaluator)
    or Nones for unavailable components.
    """
    physics_enforcer = None
    metrics_dashboard = None
    character_specialist = None
    milestone_gates = None
    pipeline_session = None
    scene_card_generator = None
    export_manager = None
    judge_evaluator = None

    # Physics enforcer
    try:
        from src.planning.physics_enforcer import PhysicsEnforcer
        physics_enforcer = PhysicsEnforcer(concept_seed)
    except ImportError as e:
        print(f"  Warning: PhysicsEnforcer not available: {e}")

    # Quality metrics and character specialist (same as Phase 3)
    try:
        from src.quality.metrics_dashboard import MetricsDashboard
        from src.agents.character_specialist import CharacterSpecialist
        from src.quality.milestone_gates import MilestoneGates

        metrics_dashboard = MetricsDashboard(
            negative_constraints_path=str(Path("config") / "negative_constraints.yaml"),
            embedding_function=embedding_function,
        )
        character_specialist = CharacterSpecialist(router)

        if not no_milestones:
            milestone_gates = MilestoneGates(
                ledger=ledger,
                on_pause_callback=_cli_milestone_prompt,
            )
    except ImportError as e:
        print(f"  Warning: Quality components not available: {e}")

    # Pipeline session
    try:
        from src.pipeline_session import PipelineSession
        pipeline_session = PipelineSession()
    except ImportError:
        pass

    # Scene card generator
    try:
        from src.planning.scene_card_generator import SceneCardGenerator
        scene_card_generator = SceneCardGenerator(router, physics_enforcer)
    except ImportError:
        pass

    # Export manager
    try:
        from src.export.export_manager import ExportManager
        manuscripts_dir = config.get("pipeline", {}).get("chapter_output_dir", "output/_fallback/manuscripts")
        export_manager = ExportManager(manuscripts_dir, concept_seed)
    except ImportError:
        pass

    # LLM Judge
    if judge:
        try:
            from src.quality.llm_judge import JudgeEvaluator
            judge_evaluator = JudgeEvaluator(router)
        except ImportError as e:
            print(f"  Warning: JudgeEvaluator not available: {e}")

    return (
        physics_enforcer, metrics_dashboard,
        character_specialist, milestone_gates, pipeline_session,
        scene_card_generator, export_manager, judge_evaluator,
    )


def _init_phase3(router, ledger, config, embedding_function, no_milestones=False):
    """Initialize Phase 3 components.

    Returns (metrics_dashboard, character_specialist, milestone_gates)
    or all Nones if imports fail.
    """
    try:
        from src.agents.character_specialist import CharacterSpecialist
        from src.quality.metrics_dashboard import MetricsDashboard
        from src.quality.milestone_gates import MilestoneGates
    except ImportError as e:
        print(f"Warning: Phase 3 dependencies not available: {e}")
        return None, None, None

    metrics_dashboard = MetricsDashboard(
        negative_constraints_path=str(Path("config") / "negative_constraints.yaml"),
        embedding_function=embedding_function,
    )

    character_specialist = CharacterSpecialist(router)

    milestone_gates = None
    if not no_milestones:
        milestone_gates = MilestoneGates(
            ledger=ledger,
            on_pause_callback=_cli_milestone_prompt,
        )

    return metrics_dashboard, character_specialist, milestone_gates


async def _ensure_chapter_blueprints(
    router,
    ledger,
    concept_seed: dict,
    scene_cards: list[dict],
    franchise_slug: str,
    book_slug: str,
    regenerate: bool = False,
) -> None:
    """Phase 5: fill in missing chapter blueprints.

    Detects which chapters in ``scene_cards`` have no blueprint at the
    canonical path and generates them. Hand-authored blueprints are
    preserved unless ``regenerate=True``. Emits the
    ``chapter_blueprints_generated`` ledger event.

    No-op when ``scene_cards`` is empty or no chapters need blueprints.
    """
    if not scene_cards:
        return

    print("Checking chapter blueprints...")
    bp_dir = (
        Path("data") / "franchises" / franchise_slug / "books" / book_slug
        / "chapter_blueprints"
    )
    existing_chapters: set[int] = set()
    if bp_dir.exists():
        for path in bp_dir.glob("chapter_*.json"):
            try:
                existing_chapters.add(int(path.stem.split("_")[1]))
            except (IndexError, ValueError):
                continue

    chapters_in_cards = {
        c["chapter_number"] for c in scene_cards if "chapter_number" in c
    }
    needed_chapters = chapters_in_cards - existing_chapters

    if not needed_chapters and not regenerate:
        print(f"  All {len(chapters_in_cards)} chapter(s) have blueprints — skipping generation")
        return

    from src.planning.chapter_blueprint_generator import (
        ChapterBlueprintGenerator,
        save_blueprints,
    )

    if regenerate:
        target_cards = scene_cards
        print(f"  Regenerating blueprints for {len(chapters_in_cards)} chapter(s)")
    else:
        target_cards = [c for c in scene_cards if c["chapter_number"] in needed_chapters]
        print(f"  Generating blueprints for {len(needed_chapters)} chapter(s) "
              f"(preserving {len(existing_chapters & chapters_in_cards)} hand-authored)")

    generator = ChapterBlueprintGenerator(router)
    new_blueprints = await generator.generate(concept_seed, target_cards)
    saved = save_blueprints(
        new_blueprints, franchise_slug, book_slug, force=regenerate,
    )
    ledger.emit(
        "chapter_blueprints_generated",
        payload={"count": len(saved), "regenerated": regenerate},
    )
    print(f"  Wrote {len(saved)} chapter blueprint file(s)")


async def main():
    parser = argparse.ArgumentParser(
        description="AI Writers' Room — Multi-agent fiction generation pipeline"
    )
    parser.add_argument(
        "concept_seed",
        nargs="?",
        default=None,
        help="Path to the concept seed JSON file",
    )
    parser.add_argument(
        "scene_cards_dir",
        nargs="?",
        default=None,
        help="Path to the directory containing scene card JSON files",
    )
    parser.add_argument(
        "--chapter",
        type=int,
        default=None,
        help="Generate only this chapter number",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Path to settings.yaml (default: config/settings.yaml)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override manuscript output directory",
    )
    parser.add_argument(
        "--phase",
        type=int,
        default=1,
        choices=[1, 2, 3, 4, 5],
        help="Pipeline phase: 1 = basic, 2 = memory/canon, 3 = quality/milestones, 4 = full, 5 = chapter blueprints + chapter gate critic (default: 1)",
    )
    parser.add_argument(
        "--no-blueprints",
        action="store_true",
        help="Phase 5: skip chapter blueprint auto-generation. "
             "Hand-authored blueprints at data/franchises/<fr>/books/<bk>/chapter_blueprints/ "
             "are still loaded by ChapterGateCritic if present.",
    )
    parser.add_argument(
        "--regenerate-blueprints",
        action="store_true",
        help="Phase 5: overwrite existing chapter blueprints. "
             "Default behaviour preserves hand-authored blueprints (skip-if-exists).",
    )
    parser.add_argument(
        "--no-revision",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--raw-draft",
        action="store_true",
        help="Baseline mode: skip Quality Polish and Final Gate. "
             "Saves the Scene-Gate-passed draft directly. Use this to measure "
             "the writer+gate loop in isolation before the polish stage.",
    )
    parser.add_argument(
        "--skip-gate-loop",
        action="store_true",
        help="Skip the Gate Critic stage entirely and synthesize a 'skipped' "
             "verdict. The forward-only relay has no rewrite loop anymore, so "
             "this flag only bypasses the gate-critic LLM call; Quality Polish "
             "and Final Gate still run (unless --raw-draft is also set). Useful "
             "for bench configs and cheap runs where gate telemetry is not needed. "
             "Flag name is historical from the retry-era pipeline.",
    )
    parser.add_argument(
        "--strict-lore",
        action="store_true",
        help="Phase 7.2: promote high-severity LoreConflictDetector flags "
             "to blocking status (default is advisory — flags are recorded "
             "in the run ledger but do not fail the scene).",
    )
    parser.add_argument(
        "--no-milestones",
        action="store_true",
        help="Skip milestone gate pausing (Phase 3/4 only)",
    )
    # Phase 4 arguments
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export manuscript after pipeline completes",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Export existing manuscript without running generation pipeline",
    )
    parser.add_argument(
        "--export-formats",
        default="md,docx,epub",
        help="Comma-separated export formats: md,docx,epub (default: all)",
    )
    parser.add_argument(
        "--generate-outline",
        action="store_true",
        help="Generate scene cards from concept seed before running pipeline",
    )
    parser.add_argument(
        "--import-summary",
        type=str,
        default=None,
        metavar="PATH",
        help="Import a planning manuscript and convert it to a concept seed. "
             "Requires --project. Positional args not needed.",
    )
    parser.add_argument(
        "--validate-seed",
        action="store_true",
        help="Run compliance validation on the concept seed and print report.",
    )
    parser.add_argument(
        "--allow-unapproved-plan",
        action="store_true",
        help=(
            "Bypass the compile_metadata.plan_approved gate. By default the "
            "pipeline refuses to run on a seed whose plan has not been "
            "explicitly approved via scripts/approve_plan.py."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from a saved pipeline session",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Session ID to resume (default: auto-generated)",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Run LLM-as-judge evaluation after generation",
    )
    parser.add_argument(
        "--runtime-flag",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help=(
            "Override a runtime flag (architecture upgrade, Slice 1+). "
            "Use dotted keys, e.g. --runtime-flag runtime.firewall.enabled=true. "
            "May be repeated. See docs/architecture/architecture_upgrade_spec.md §4.2."
        ),
    )
    parser.add_argument(
        "--franchise",
        default=None,
        dest="franchise",
        help="Franchise slug (e.g., 'star-wars-legends-eu'). "
             "Auto-derived from concept seed meta.franchise if not provided.",
    )
    parser.add_argument(
        "--universe-id",
        default=None,
        dest="franchise_legacy",
        help="Deprecated: use --franchise instead.",
    )
    parser.add_argument(
        "--series",
        default=None,
        help="Series slug for shared state across books (e.g., 'ruusan-verse'). "
             "Books with the same series share story state, character arcs, and plot threads.",
    )
    parser.add_argument(
        "--book",
        default=None,
        dest="book",
        help="Book/project ID for worldbuilding spoiler isolation.",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        dest="book_legacy",
        help="Deprecated: use --book instead.",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Custom run name (default: auto-generated timestamp). "
             "Each pipeline run creates an isolated output directory.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug (e.g., 'the-ruusan-atonement'). "
             "Auto-derived from concept seed project_title if not provided.",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="Launch the web server instead of the CLI pipeline",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Web server host (default: 127.0.0.1, only with --server)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Web server port (default: 8000, only with --server)",
    )

    args = parser.parse_args()

    if args.no_revision:
        print(
            "  Warning: --no-revision is deprecated. The 3-band revision pipeline has been "
            "removed; the flag is a no-op. Use --raw-draft for pre-polish baseline mode."
        )

    # Web server mode
    if args.server:
        try:
            from src.ui.server import run_server
            run_server(
                concept_seed_path=args.concept_seed,
                config_path=args.config,
                host=args.host,
                port=args.port,
                phase=args.phase,
            )
        except ImportError as e:
            print(f"Error: Web server dependencies not available: {e}")
            print("Run: pip install fastapi uvicorn[standard] websockets")
            sys.exit(1)
        return

    # Import summary mode — build concept seed from a planning manuscript
    if args.import_summary:
        if not Path(args.config).exists():
            print(f"Error: Config not found: {args.config}")
            sys.exit(1)
        if not args.project:
            print("Error: --project is required with --import-summary")
            sys.exit(1)
        summary_path = Path(args.import_summary)
        if not summary_path.exists():
            print(f"Error: Summary file not found: {args.import_summary}")
            sys.exit(1)

        summary_text = summary_path.read_text(encoding="utf-8")
        print("Initializing AI Writers' Room...")
        router = ModelRouter(args.config)

        if router.mode in ("cloud", "hybrid"):
            ok, msg = await router.health_check()
            if not ok:
                print(f"Error: Health check failed — {msg}")
                await router.close()
                sys.exit(1)
            print(f"  {msg}")

        from src.agents.seed_builder import SeedBuilder

        paths = ProjectPaths(args.project)
        paths.ensure_dirs()

        print(f"Building concept seed from manuscript: {args.import_summary}")
        seed_builder = SeedBuilder(router)
        seed, report = await seed_builder.build_seed(summary_text)

        print(report.format())

        if report.passed:
            seed_path = paths.concept_seed_path
            seed_path.write_text(
                json.dumps(seed, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"Concept seed saved to: {seed_path}")
        else:
            print("Seed has critical failures. Review the report above.")
            print("You can manually fix the JSON and re-validate with --validate-seed.")

        await router.close()
        return

    # Validate inputs — required for all non-import modes
    if not args.concept_seed:
        print("Error: concept_seed path is required (unless using --import-summary)")
        sys.exit(1)
    if not Path(args.concept_seed).exists():
        print(f"Error: Concept seed not found: {args.concept_seed}")
        sys.exit(1)

    if not Path(args.config).exists():
        print(f"Error: Config not found: {args.config}")
        sys.exit(1)

    # Load concept seed early (needed for Phase 4)
    with open(args.concept_seed, encoding="utf-8") as f:
        concept_seed = json.load(f)

    # Validate-seed mode — run compliance validation and exit
    if args.validate_seed:
        from src.concept_workshop.compliance_validator import (
            derive_slugs_from_path,
            validate_concept_seed,
        )
        franchise_slug, book_slug = derive_slugs_from_path(Path(args.concept_seed))
        report = validate_concept_seed(
            concept_seed,
            franchise_slug=franchise_slug,
            book_slug=book_slug,
        )
        print(report.format())
        sys.exit(0 if report.passed else 1)

    # Plan-approval gate — enforces the planning/drafting separation.
    approved, gate_msg = check_plan_approval(
        concept_seed,
        allow_unapproved=args.allow_unapproved_plan,
        seed_path=args.concept_seed,
    )
    if not approved:
        print(gate_msg)
        sys.exit(1)

    # Load config
    print("Initializing AI Writers' Room...")
    router = ModelRouter(args.config)

    # Health check — verify API connectivity before proceeding
    if router.mode in ("cloud", "hybrid"):
        ok, msg = await router.health_check()
        if not ok:
            print(f"Error: Health check failed — {msg}")
            print("Ensure OPENROUTER_API_KEY is set and network is available.")
            await router.close()
            sys.exit(1)
        print(f"  {msg}")

    import yaml
    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    pipeline_cfg = config.get("pipeline", {})
    # Architecture upgrade runtime flags (settings.yaml + per-book overrides +
    # CLI overrides). Resolve before the reproducibility snapshot so the run
    # records the actual active pipeline shape.
    from src.runtime_flags import load_runtime_flags as _load_runtime_flags
    runtime_flags = _load_runtime_flags(
        concept_seed=concept_seed,
        cli_overrides=getattr(args, "runtime_flag", None),
    )
    lean_prose_only = bool(
        ((runtime_flags.get("runtime") or {}).get("lean_prose_only") or {}).get(
            "enabled", False
        )
    )
    _lean_cfg = (runtime_flags.get("runtime") or {}).get("lean_prose_only") or {}
    _lean_line_edit_cfg = _lean_cfg.get("line_edit", {})
    if isinstance(_lean_line_edit_cfg, dict):
        lean_line_edit = bool(_lean_line_edit_cfg.get("enabled", False))
    else:
        lean_line_edit = bool(_lean_line_edit_cfg)

    # Resolve franchise/series/run parameters (support deprecated aliases)
    franchise_slug = args.franchise or args.franchise_legacy
    book_id = args.book or args.book_legacy
    from src.project_paths import generate_run_id
    run_id = args.run_name or generate_run_id()
    series_slug = args.series

    # Resolve project paths (franchise/book/series/run scoping)
    if args.project:
        paths = ProjectPaths(
            args.project,
            franchise_slug=franchise_slug,
            series_slug=series_slug,
            run_id=run_id,
        )
    else:
        paths = ProjectPaths.from_concept_seed(concept_seed, run_id=run_id)
        # CLI overrides for franchise/series
        if franchise_slug:
            paths.franchise_slug = franchise_slug
        if series_slug:
            paths.series_slug = series_slug
    paths.ensure_dirs()
    paths.ensure_franchise_meta(concept_seed)
    print(f"  Project: [{paths.display_name}]")

    # Save config snapshot for this run
    if paths.config_snapshot_path:
        import yaml as _yaml_snap
        paths.config_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_snapshot_path.write_text(
            _yaml_snap.dump(config, default_flow_style=False),
            encoding="utf-8",
        )
        print(f"  Config snapshot: {paths.config_snapshot_path}")

    # Reproducibility snapshot: prompt files + CLI args + git SHA.
    # Config alone isn't enough — run13 and run14 had byte-identical
    # config_snapshot.yaml but produced materially different prose because
    # prompt text changed between them.
    if paths.run_dir is not None:
        # Record which post-gate variant ran: the pipeline has one canonical
        # polish stage now (Quality Polish + Final Gate). Raw-draft skips it.
        if lean_prose_only:
            _pipeline_variant = (
                "lean_prose_line_edit" if lean_line_edit else "lean_prose_only"
            )
        else:
            _pipeline_variant = (
                "raw_draft" if args.raw_draft else "quality_polish"
            )
        _write_reproducibility_snapshot(paths.run_dir, args, _pipeline_variant)
        print(f"  Prompt + invocation snapshot: {paths.run_dir}")

    ledger_path = str(paths.run_ledger_db)
    manuscripts_dir = args.output_dir or pipeline_cfg.get(
        "chapter_output_dir", str(paths.manuscripts_dir)
    )
    export_dir = str(paths.export_dir)

    # Phase 4: Export-only mode — skip everything else
    if args.export_only:
        try:
            from src.export.export_manager import ExportManager
            export_manager = ExportManager(manuscripts_dir, concept_seed)
            formats = [f.strip() for f in args.export_formats.split(",")]
            print(f"Exporting to: {', '.join(formats)}")
            results = export_manager.export_all(output_dir=export_dir, formats=formats)
            for fmt, path in results.items():
                if path:
                    print(f"  {fmt}: {path}")
                else:
                    print(f"  {fmt}: skipped (library not available)")
        except ImportError as e:
            print(f"Error: Export dependencies not available: {e}")
        finally:
            await router.close()
        return

    # Initialize Phase 2 components if requested
    story_state = None
    knowledge_layers = None
    chapter_memory = None
    canon_db = None
    summarizer = None
    state_diff_applier = None
    contradiction_scanner = None
    canon_expert = None
    # Relay Stage 1g — presence_checker is a cheap Haiku agent; instantiate
    # eagerly so the save-blocker layer always has it available.
    from src.agents.presence_checker import PresenceChecker
    presence_checker = PresenceChecker(router)

    # Relay Stage 3 — LineWriter runs as the line-editing pass after the
    # drafter. Only instantiate when agent_routing.line_writer is configured
    # (bench configs and cheap-run configs can omit it to keep runs light).
    # In raw-draft mode the orchestrator also skips the call.
    line_writer = None
    if config.get("agent_routing", {}).get("line_writer"):
        from src.agents.line_writer import LineWriter
        line_writer = LineWriter(router)

    # Forward Relay v4 â€” bounded post-check repair stage. The runtime flag
    # decides whether it ever runs; routing presence decides whether the
    # agent can be instantiated for experiment configs.
    micro_repair = None
    if config.get("agent_routing", {}).get("micro_repair"):
        from src.agents.micro_repair import MicroRepair

        micro_repair = MicroRepair(router)

    if args.phase >= 2:
        print("Initializing Phase 2 components...")
        (
            story_state,
            knowledge_layers,
            chapter_memory,
            canon_db,
            _,
            _,
            _,
        ) = _init_phase2(args.concept_seed, config, manuscripts_dir, paths=paths)

        if story_state and knowledge_layers:
            from src.agents.summarizer import Summarizer
            from src.memory.contradiction_scanner import ContradictionScanner
            from src.memory.state_diff import StateDiffApplier

            ledger = RunLedger(db_path=ledger_path, run_id=run_id)
            summarizer = Summarizer(router)
            state_diff_applier = StateDiffApplier(story_state, knowledge_layers, ledger)
            contradiction_scanner = ContradictionScanner(story_state, knowledge_layers, ledger)

            # CanonExpert is the runtime save-blocker validator. CanonDB/RAG
            # evidence is optional; profile-only validation must still run for
            # projects that use static Canon Scout sidecars instead of a rigid
            # prebuilt canon database.
            try:
                from src.agents.canon_expert import CanonExpert

                ranker = None
                if canon_db:
                    try:
                        from src.rag.canon_evidence import CanonEvidenceRanker
                        from src.rag.hybrid_search import HybridSearch

                        hybrid = HybridSearch(canon_db)
                        ranker = CanonEvidenceRanker(hybrid)
                    except (ImportError, Exception) as e:
                        print(f"  Warning: CanonDB evidence disabled: {e}")
                canon_expert = CanonExpert(router, canon_evidence=ranker)
                if ranker is None:
                    print("  CanonExpert initialized in profile-only mode")
            except (ImportError, Exception) as e:
                print(f"  Warning: CanonExpert not available: {e}")

            print("  Phase 2 components initialized")
        else:
            print("  Phase 2 initialization incomplete — running in Phase 1 mode")

    # Initialize context assembler (lore_service wired later if --universe-id given)
    assembler = ContextAssembler(
        concept_seed_path=args.concept_seed,
        manuscripts_dir=manuscripts_dir,
        story_state=story_state,
        knowledge_layers=knowledge_layers,
        chapter_memory=chapter_memory,
        canon_db=canon_db,
    )

    # Ensure ledger exists — Phase 2 may have created it above, but if
    # Phase 2 init failed (e.g., chromadb missing), it won't exist yet.
    try:
        ledger
    except UnboundLocalError:
        ledger = RunLedger(db_path=ledger_path, run_id=run_id)

    # Initialize Phase 3 components if requested
    metrics_dashboard = None
    character_specialist = None
    milestone_gates = None

    if args.phase >= 3:
        print("Initializing Phase 3 components...")
        # Phase 3 requires Phase 2 to be initialized
        try:
            ef = None
            try:
                from src.rag.embedding import get_embedding_function
                embed_cfg = config.get("pipeline", {}).get("embeddings", {})
                ef = get_embedding_function(use_mock=embed_cfg.get("use_mock", True))
            except Exception:
                pass

            metrics_dashboard, character_specialist, milestone_gates = (
                _init_phase3(
                    router, ledger, config, ef,
                    no_milestones=args.no_milestones,
                )
            )
            components = []
            if metrics_dashboard:
                components.append("quality metrics")
            if character_specialist:
                components.append("character specialist")
            if milestone_gates:
                components.append("milestone gates")
            print(f"  Phase 3 components: {', '.join(components) or 'none'}")
        except Exception as e:
            print(f"  Phase 3 initialization error: {e}")

    # Phase 4 components
    physics_enforcer = None
    pipeline_session = None
    session_id = None
    scene_card_generator = None
    export_manager = None
    judge_evaluator = None

    if args.phase >= 4:
        print("Initializing Phase 4 components...")
        try:
            ef = None
            try:
                from src.rag.embedding import get_embedding_function
                embed_cfg = config.get("pipeline", {}).get("embeddings", {})
                ef = get_embedding_function(use_mock=embed_cfg.get("use_mock", True))
            except Exception:
                pass

            (
                physics_enforcer, metrics_dashboard,
                character_specialist, milestone_gates, pipeline_session,
                scene_card_generator, export_manager, judge_evaluator,
            ) = _init_phase4(
                router, ledger, config, concept_seed, ef,
                no_milestones=args.no_milestones,
                judge=args.judge,
            )

            components = []
            if physics_enforcer:
                components.append("physics enforcer")
            if pipeline_session:
                components.append("session persistence")
            if scene_card_generator:
                components.append("scene card generator")
            if export_manager:
                components.append("export manager")
            if judge_evaluator:
                components.append("LLM judge")
            print(f"  Phase 4 components: {', '.join(components) or 'none'}")
        except Exception as e:
            print(f"  Phase 4 initialization error: {e}")

    # Phase 5: Chapter Gate Critic — constructed below AFTER the
    # worldbuilding lore_service is built, so Phase 7.4 can pass
    # lore_service + universe_id into the critic for lore-consistency
    # checks.
    chapter_gate_critic = None

    # Worldbuilding service (optional, requires --universe-id)
    lore_service = None
    if franchise_slug:
        try:
            from src.worldbuilding.worldbuilding_db import WorldbuildingDB
            from src.worldbuilding.lore_vectorstore import LoreVectorStore
            from src.worldbuilding.lore_service import LoreService

            wb_config = config.get("worldbuilding", {})
            wb_db_path = wb_config.get("db_path", str(paths.worldbuilding_db))
            wb_vectors_dir = wb_config.get("vectors_dir", str(paths.worldbuilding_vectors_dir))

            ef_wb = None
            try:
                from src.rag.embedding import get_embedding_function
                ef_wb = get_embedding_function(use_mock=True)
            except Exception:
                pass

            wb_db = WorldbuildingDB(db_path=wb_db_path)
            wb_vs = LoreVectorStore(persist_directory=wb_vectors_dir, embedding_function=ef_wb)
            lore_service = LoreService(db=wb_db, vectorstore=wb_vs)

            # Ensure universe record exists for this franchise
            lore_service.ensure_universe(
                universe_id=franchise_slug,
                display_name=franchise_slug.replace("-", " ").title(),
                franchise=franchise_slug,
            )
            print(f"  Worldbuilding service initialized (universe={franchise_slug})")

            # Wire lore into context assembler
            assembler.lore_service = lore_service
            assembler.universe_id = franchise_slug
            assembler.project_id = book_id
        except (ImportError, Exception) as e:
            print(f"  Warning: Worldbuilding service not available: {e}")

    # Phase 5: instantiate ChapterGateCritic. Wired to lore_service +
    # universe_id when available so Phase 7.4 lore_consistency_check runs.
    if args.phase >= 5:
        print("Initializing Phase 5 components...")
        try:
            from src.agents.chapter_gate_critic import ChapterGateCritic
            chapter_gate_critic = ChapterGateCritic(
                router,
                lore_service=lore_service,
                universe_id=franchise_slug,
            )
            if lore_service and franchise_slug:
                print("  Phase 5 components: chapter gate critic (lore-aware)")
            else:
                print("  Phase 5 components: chapter gate critic")
        except ImportError as e:
            print(f"  Warning: ChapterGateCritic not available: {e}")

    # Phase 4: Generate scene cards from concept seed if requested
    if args.generate_outline and scene_card_generator:
        print("Generating scene cards from concept seed...")
        generated_cards = await scene_card_generator.generate(concept_seed)
        if generated_cards:
            output_dir = args.scene_cards_dir
            paths = scene_card_generator.save_scene_cards(generated_cards, output_dir)
            print(f"Generated {len(paths)} scene card(s) in {output_dir}")
            ledger.emit("outline_generated", payload={"count": len(paths)})

            # Phase 5.4: emit chapter blueprint drafts alongside the new scene
            # cards so the planning artifact is complete in one step.
            if (
                args.phase >= 5
                and not args.no_blueprints
                and franchise_slug
                and book_id
            ):
                await _ensure_chapter_blueprints(
                    router=router,
                    ledger=ledger,
                    concept_seed=concept_seed,
                    scene_cards=generated_cards,
                    franchise_slug=franchise_slug,
                    book_slug=book_id,
                    regenerate=args.regenerate_blueprints,
                )
        else:
            print("Warning: No scene cards generated")

    # Phase 4: Session handling
    if args.resume and pipeline_session:
        session_id = args.session_id
        if not session_id:
            sessions = pipeline_session.list_sessions()
            if sessions:
                session_id = sessions[-1]["session_id"]
                print(f"Resuming most recent session: {session_id}")
            else:
                print("No sessions found to resume")
    elif pipeline_session and args.phase >= 4:
        session_id = args.session_id or pipeline_session.generate_session_id()

    chapter_packet_compiler = build_chapter_packet_compiler(
        concept_seed=concept_seed,
        paths=paths,
        assembler=assembler,
        chapter=args.chapter,
        story_state=story_state,
    )

    orchestrator = Orchestrator(
        router=router,
        context_assembler=assembler,
        ledger=ledger,
        manuscripts_dir=manuscripts_dir,
        max_structural_retries=pipeline_cfg.get("max_structural_retries", 3),
        max_voice_retries=pipeline_cfg.get("max_voice_retries", 2),
        runtime_flags=runtime_flags,
        chapter_packet_compiler=chapter_packet_compiler,
        summarizer=summarizer,
        state_diff_applier=state_diff_applier,
        contradiction_scanner=contradiction_scanner,
        chapter_memory=chapter_memory,
        story_state=story_state,
        canon_expert=canon_expert,
        presence_checker=presence_checker,
        line_writer=line_writer,
        micro_repair=micro_repair,
        metrics_dashboard=metrics_dashboard,
        character_specialist=character_specialist,
        milestone_gates=milestone_gates,
        physics_enforcer=physics_enforcer,
        pipeline_session=pipeline_session,
        session_id=session_id,
        judge_evaluator=judge_evaluator,
        chapter_gate_critic=chapter_gate_critic,
        lore_service=lore_service,
        universe_id=franchise_slug,
        project_id=book_id,
        worldbuilding_auto_extract=bool(lore_service and franchise_slug),
        strict_lore=bool(getattr(args, "strict_lore", False)),
        raw_draft=args.raw_draft,
        skip_gate_loop=args.skip_gate_loop,
    )

    # Create session if Phase 4
    if pipeline_session and session_id and not args.resume:
        scene_cards_for_session = load_scene_cards(args.scene_cards_dir, args.chapter)
        pipeline_session.create_session(session_id, scene_cards_for_session)

    # Load scene cards
    scene_cards = load_scene_cards(args.scene_cards_dir, args.chapter)
    if args.resume and pipeline_session and session_id:
        original_count = len(scene_cards)
        scene_cards = pipeline_session.get_pending_cards(session_id, scene_cards)
        completed_count = original_count - len(scene_cards)
        print(
            f"Resume session {session_id}: "
            f"{completed_count} completed, {len(scene_cards)} pending"
        )
    print(f"Loaded {len(scene_cards)} scene card(s)")
    print(f"Deployment mode: {router.mode}")
    print(f"Pipeline phase: {args.phase}")
    print(f"Output directory: {manuscripts_dir}")

    # Phase 5: ensure chapter blueprints exist for every chapter being run.
    # Hand-authored blueprints take precedence (skip-if-exists). Requires
    # franchise_slug and book_id so blueprints land at the canonical path
    # ChapterGateCritic loads from.
    if (
        args.phase >= 5
        and not args.no_blueprints
        and franchise_slug
        and book_id
    ):
        await _ensure_chapter_blueprints(
            router=router,
            ledger=ledger,
            concept_seed=concept_seed,
            scene_cards=scene_cards,
            franchise_slug=franchise_slug,
            book_slug=book_id,
            regenerate=args.regenerate_blueprints,
        )

    try:
        results = await orchestrator.run_pipeline(scene_cards)

        # Summary
        print(f"\n{'='*60}")
        print("Pipeline Complete")
        print(f"{'='*60}")
        total_words = sum(r["word_count"] for r in results)
        print(f"Scenes saved: {len(results)}")
        print(f"Total word count: {total_words:,}")

        # Relay v3 (Stage 1i): three-count summary reflecting the new status
        # vocabulary. Scenes whose saved prose survived all gates are
        # 'saved_clean'; any advisory signal (compression, final-gate,
        # continuity/pov advisory) degrades to 'saved_with_advisory'. The
        # 'quarantined' count comes from save_blocked ledger events, not the
        # results list — quarantined scenes never reach the results array
        # because run_pipeline aborts on the first blocker.
        scenes_saved_clean = 0
        scenes_saved_with_advisory = 0
        for r in results:
            if _scene_had_advisory(r):
                scenes_saved_with_advisory += 1
            else:
                scenes_saved_clean += 1
        scenes_quarantined = _count_quarantined_scenes(ledger)
        print(f"  saved_clean:          {scenes_saved_clean}")
        print(f"  saved_with_advisory:  {scenes_saved_with_advisory}")
        print(f"  quarantined:          {scenes_quarantined}")

        for r in results:
            status = "saved_with_advisory" if _scene_had_advisory(r) else "saved_clean"
            flags = len(r.get("contradiction_flags", []))
            flag_str = f", flags={flags}" if flags else ""
            quality_str = ""
            if "quality_metrics" in r:
                qs = r["quality_metrics"]["overall_score"]
                quality_str = f", quality={qs:.2f}"
            char_str = ""
            if "character_analysis" in r:
                char_str = f", chars={r['character_analysis']['verdict']}"
            judge_str = ""
            if "judge_evaluation" in r:
                js = r["judge_evaluation"]["overall_score"]
                judge_str = f", judge={js:.1f}/10"
            print(
                f"  Chapter {r['chapter_number']}.{r['scene_number']}: "
                f"{r['word_count']:,} words, status={status}"
                f"{flag_str}{quality_str}{char_str}{judge_str}"
            )

        # Architecture upgrade Slice 1: surface open gap notes from the
        # state firewall. Runs regardless of whether the firewall flag was
        # on — an open gap from an earlier run still deserves attention.
        if story_state is not None:
            try:
                open_gaps = story_state.list_open_gaps()
            except Exception:  # noqa: BLE001 -- pre-migration DBs gracefully skip
                open_gaps = []
            if open_gaps:
                print(f"\nOpen state-firewall gaps: {len(open_gaps)}")
                for g in open_gaps:
                    cats = ", ".join(g.get("blocker_categories", [])) or "unspecified"
                    affected = g.get("affected_scenes", [])
                    affected_str = (
                        f" affects={len(affected)} scene(s)" if affected else ""
                    )
                    print(
                        f"  {g['gap_id']}  isolated={g['isolated_scene']}  "
                        f"categories=[{cats}]{affected_str}"
                    )
                print(
                    "  Resolve via scripts/patch_workflow.py "
                    "(landing in Slice 6) or hand-fix the quarantined scene."
                )

        # Phase 4: Export after pipeline
        if args.export and export_manager:
            print(f"\nExporting manuscript...")
            formats = [f.strip() for f in args.export_formats.split(",")]
            export_results = export_manager.export_all(output_dir=export_dir, formats=formats)
            for fmt, path in export_results.items():
                if path:
                    print(f"  {fmt}: {path}")
                else:
                    print(f"  {fmt}: skipped")
            ledger.emit("export_complete", payload={"formats": formats})

    except KeyboardInterrupt:
        print("\nPipeline interrupted.")
    finally:
        # Sync-safe cleanup — ledger and story_state are synchronous
        try:
            ledger.close()
        except Exception:
            pass
        try:
            if story_state:
                story_state.close()
        except Exception:
            pass
        # Async client cleanup — skip on interrupt to avoid event loop teardown errors
        if not isinstance(sys.exc_info()[1], KeyboardInterrupt):
            try:
                await router.close()
            except Exception:
                pass


def cli():
    """Entry point for the CLI."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
