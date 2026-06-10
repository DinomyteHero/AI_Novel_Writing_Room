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
        canon_guidance_store=canon_guidance_store,
    )


def _init_phase2(concept_seed_path: str, config: dict, manuscripts_dir: str,
                  paths: "ProjectPaths | None" = None):
    """Initialize Phase 2 components. Returns (story_state, knowledge_layers,
    chapter_memory, canon_db, summarizer, state_diff_applier, contradiction_scanner)
    or all Nones if imports fail."""
    try:
        from src.memory.chapter_memory import ChapterMemory
        from src.memory.knowledge_layers import KnowledgeLayers
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


def _init_phase4(router, ledger, config, concept_seed):
    """Initialize Phase 4 components still used outside the Orchestrator.

    Returns (physics_enforcer, pipeline_session, scene_card_generator,
    export_manager). PhysicsEnforcer + SceneCardGenerator back
    ``--generate-outline``; PipelineSession backs ``--resume``;
    ExportManager backs ``--export``. None of these are passed to the
    lean Orchestrator.
    """
    physics_enforcer = None
    pipeline_session = None
    scene_card_generator = None
    export_manager = None

    # Physics enforcer (used by SceneCardGenerator for --generate-outline)
    try:
        from src.planning.physics_enforcer import PhysicsEnforcer
        physics_enforcer = PhysicsEnforcer(concept_seed)
    except ImportError as e:
        print(f"  Warning: PhysicsEnforcer not available: {e}")

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

    return physics_enforcer, pipeline_session, scene_card_generator, export_manager


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
        help="Pipeline phase: 1 = basic, 2 = memory/canon, 4 = sessions/export, 5 = chapter blueprints (default: 1)",
    )
    parser.add_argument(
        "--no-blueprints",
        action="store_true",
        help="Phase 5: skip chapter blueprint auto-generation. "
             "Hand-authored blueprints at data/franchises/<fr>/books/<bk>/chapter_blueprints/ "
             "are still loaded by the chapter-packet compiler if present.",
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
        "--runtime-flag",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help=(
            "Override a runtime flag. Use dotted keys, e.g. "
            "--runtime-flag runtime.rhythm_validator.enabled=true. May be "
            "repeated. Resolution precedence is documented in the runtime: "
            "block of config/settings.yaml."
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
            "removed; the flag is a no-op."
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
    # The pipeline is lean-only; the only variant axis left is whether the
    # lean line-edit pass runs.
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
        # The pipeline is lean-only now: PlotArchitect -> ProseStylist ->
        # [LineWriter] -> save. The variant records whether the lean
        # line-edit pass ran.
        _pipeline_variant = (
            "lean_prose_line_edit" if lean_line_edit else "lean_prose_only"
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

    # LineWriter runs as the lean line-editing pass after the drafter. Only
    # instantiate when agent_routing.line_writer is configured (bench configs
    # and cheap-run configs can omit it to keep runs light).
    line_writer = None
    if config.get("agent_routing", {}).get("line_writer"):
        from src.agents.line_writer import LineWriter
        line_writer = LineWriter(router)

    # Rhythm-editor literal-edit pass. Runtime flag decides whether it ever
    # runs; routing presence decides whether the agent can be instantiated.
    rhythm_editor = None
    if config.get("agent_routing", {}).get("rhythm_editor"):
        from src.agents.rhythm_editor import RhythmEditor

        rhythm_editor = RhythmEditor(router)

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

    # Phase 4 components — none are passed to the lean Orchestrator; these
    # back stand-alone CLI modes (--generate-outline, --resume, --export).
    physics_enforcer = None
    pipeline_session = None
    session_id = None
    scene_card_generator = None
    export_manager = None

    if args.phase >= 4:
        print("Initializing Phase 4 components...")
        try:
            (
                physics_enforcer, pipeline_session,
                scene_card_generator, export_manager,
            ) = _init_phase4(router, ledger, config, concept_seed)

            components = []
            if physics_enforcer:
                components.append("physics enforcer")
            if pipeline_session:
                components.append("session persistence")
            if scene_card_generator:
                components.append("scene card generator")
            if export_manager:
                components.append("export manager")
            print(f"  Phase 4 components: {', '.join(components) or 'none'}")
        except Exception as e:
            print(f"  Phase 4 initialization error: {e}")

    # Worldbuilding service (optional, requires --franchise)
    lore_service = None
    if franchise_slug:
        try:
            from src.worldbuilding.worldbuilding_db import WorldbuildingDB
            from src.worldbuilding.lore_vectorstore import LoreVectorStore
            from src.worldbuilding.lore_service import LoreService

            wb_config = config.get("worldbuilding", {})
            wb_db_path = wb_config.get("db_path") or str(paths.worldbuilding_db)
            wb_vectors_dir = (
                wb_config.get("vectors_dir") or str(paths.worldbuilding_vectors_dir)
            )

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
        except Exception as e:
            print(f"  Warning: Worldbuilding service not available: {e}")

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

    # Revision-debt store — structured advisories (rhythm validator, etc.)
    # persist to output/<franchise>/<book>/state/revision_debt.db. The
    # runtime.revision_debt.enabled flag gates whether the orchestrator
    # actually writes to it.
    from src.pipeline.revision_debt import RevisionDebtStore
    revision_debt_store = RevisionDebtStore(
        db_path=str(paths.state_dir / "revision_debt.db")
    )

    # Promise ledger (Slice 3) — declaration-driven setup/payoff tracking at
    # <state_dir>/promise_ledger.db (series-scoped when meta.series_id is
    # set). Constructed only when the flag resolves on: the packet compiler
    # populates active_promises from ledger presence, so packets must stay
    # promise-free for books that haven't signed off.
    promise_ledger = None
    if bool(
        (runtime_flags.get("runtime") or {})
        .get("promise_ledger", {})
        .get("enabled", False)
    ):
        from src.memory.promise_ledger import PromiseLedger
        promise_ledger = PromiseLedger(
            db_path=str(paths.state_dir / "promise_ledger.db")
        )

    chapter_packet_compiler = build_chapter_packet_compiler(
        concept_seed=concept_seed,
        paths=paths,
        assembler=assembler,
        chapter=args.chapter,
        story_state=story_state,
        promise_ledger=promise_ledger,
    )

    orchestrator = Orchestrator(
        router=router,
        context_assembler=assembler,
        ledger=ledger,
        manuscripts_dir=manuscripts_dir,
        summarizer=summarizer,
        state_diff_applier=state_diff_applier,
        contradiction_scanner=contradiction_scanner,
        chapter_memory=chapter_memory,
        story_state=story_state,
        line_writer=line_writer,
        rhythm_editor=rhythm_editor,
        pipeline_session=pipeline_session,
        session_id=session_id,
        lore_service=lore_service,
        universe_id=franchise_slug,
        project_id=book_id,
        worldbuilding_auto_extract=(
            bool(lore_service and franchise_slug)
            and bool(
                config.get("worldbuilding", {})
                .get("auto_extraction", {})
                .get("enabled", True)
            )
        ),
        runtime_flags=runtime_flags,
        chapter_packet_compiler=chapter_packet_compiler,
        revision_debt_store=revision_debt_store,
        promise_ledger=promise_ledger,
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
    # the chapter-packet compiler loads from.
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

        # The lean pipeline has no gate/polish/save-blocker layer, so every
        # saved scene is 'saved_clean' and no scene is quarantined mid-run.
        print(f"  saved_clean:          {len(results)}")

        for r in results:
            flags = len(r.get("contradiction_flags", []))
            flag_str = f", flags={flags}" if flags else ""
            print(
                f"  Chapter {r['chapter_number']}.{r['scene_number']}: "
                f"{r['word_count']:,} words, status=saved_clean{flag_str}"
            )

        # Surface open gap notes from story state. An open gap from an
        # earlier run still deserves attention.
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
            print("\nExporting manuscript...")
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
        try:
            revision_debt_store.close()
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
