"""CLI entry point for the AI Writers' Room pipeline."""

import argparse
import asyncio
import json
import sys
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
    ).get("story_state_path", "data/story_state.db")
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
    ).get("chapter_memory_dir", "data/chapter_memory")
    try:
        ef = get_embedding_function(use_mock=True)  # Use mock by default; set use_mock=False for real embeddings
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
    ).get("canon_db_dir", "data/canon_dbs")
    if Path(canon_db_dir).exists():
        try:
            from src.rag.canon_db import CanonDB
            canon_db = CanonDB(
                persist_directory=canon_db_dir,
                embedding_function=ef,
            )
        except Exception as e:
            print(f"Warning: CanonDB init failed: {e}")

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
                  no_revision=False, no_milestones=False, judge=False):
    """Initialize Phase 4 components.

    Returns (physics_enforcer, revision_pipeline, metrics_dashboard,
             character_specialist, milestone_gates, pipeline_session,
             scene_card_generator, export_manager, judge_evaluator)
    or Nones for unavailable components.
    """
    physics_enforcer = None
    revision_pipeline = None
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

    # Adaptive revision (replaces base RevisionPipeline)
    try:
        if not no_revision:
            from src.revision.adaptive_revision import AdaptiveRevisionPipeline
            revision_pipeline = AdaptiveRevisionPipeline(router, ledger)
    except ImportError:
        # Fall back to base RevisionPipeline
        try:
            from src.revision.pipeline import RevisionPipeline
            if not no_revision:
                revision_pipeline = RevisionPipeline(router, ledger)
        except ImportError:
            pass

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
        manuscripts_dir = config.get("pipeline", {}).get("chapter_output_dir", "data/manuscripts")
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
        physics_enforcer, revision_pipeline, metrics_dashboard,
        character_specialist, milestone_gates, pipeline_session,
        scene_card_generator, export_manager, judge_evaluator,
    )


def _init_phase3(router, ledger, config, embedding_function, no_revision=False, no_milestones=False):
    """Initialize Phase 3 components.

    Returns (metrics_dashboard, character_specialist, revision_pipeline, milestone_gates)
    or all Nones if imports fail.
    """
    try:
        from src.agents.character_specialist import CharacterSpecialist
        from src.quality.metrics_dashboard import MetricsDashboard
        from src.quality.milestone_gates import MilestoneGates
        from src.revision.pipeline import RevisionPipeline
    except ImportError as e:
        print(f"Warning: Phase 3 dependencies not available: {e}")
        return None, None, None, None

    metrics_dashboard = MetricsDashboard(
        negative_constraints_path=str(Path("config") / "negative_constraints.yaml"),
        embedding_function=embedding_function,
    )

    character_specialist = CharacterSpecialist(router)

    revision_pipeline = None
    if not no_revision:
        revision_pipeline = RevisionPipeline(router, ledger)

    milestone_gates = None
    if not no_milestones:
        milestone_gates = MilestoneGates(
            ledger=ledger,
            on_pause_callback=_cli_milestone_prompt,
        )

    return metrics_dashboard, character_specialist, revision_pipeline, milestone_gates


async def main():
    parser = argparse.ArgumentParser(
        description="AI Writers' Room — Multi-agent fiction generation pipeline"
    )
    parser.add_argument(
        "concept_seed",
        help="Path to the concept seed JSON file",
    )
    parser.add_argument(
        "scene_cards_dir",
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
        choices=[1, 2, 3, 4],
        help="Pipeline phase: 1 = basic, 2 = memory/canon, 3 = quality/revision, 4 = full (default: 1)",
    )
    parser.add_argument(
        "--no-revision",
        action="store_true",
        help="Skip the revision pipeline (Phase 3/4 only)",
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
        "--universe-id",
        default=None,
        help="Worldbuilding universe ID (enables lore context injection and extraction)",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Worldbuilding project ID (for spoiler-isolated reading order)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug (e.g., 'the-ruusan-atonement'). "
             "Auto-derived from concept seed project_title if not provided. "
             "Scopes all state data under data/projects/<slug>/.",
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

    # Validate inputs
    if not Path(args.concept_seed).exists():
        print(f"Error: Concept seed not found: {args.concept_seed}")
        sys.exit(1)

    if not Path(args.config).exists():
        print(f"Error: Config not found: {args.config}")
        sys.exit(1)

    # Load concept seed early (needed for Phase 4)
    with open(args.concept_seed, encoding="utf-8") as f:
        concept_seed = json.load(f)

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
    with open(args.config) as f:
        config = yaml.safe_load(f)

    pipeline_cfg = config.get("pipeline", {})

    # Resolve project paths (project-scoped data isolation)
    if args.project:
        paths = ProjectPaths(args.project)
    else:
        paths = ProjectPaths.from_concept_seed(concept_seed)
    paths.ensure_dirs()

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

            ledger = RunLedger(db_path=ledger_path)
            summarizer = Summarizer(router)
            state_diff_applier = StateDiffApplier(story_state, knowledge_layers, ledger)
            contradiction_scanner = ContradictionScanner(story_state, knowledge_layers, ledger)

            # Canon expert (requires canon_db + chromadb)
            if canon_db:
                try:
                    from src.agents.canon_expert import CanonExpert
                    from src.rag.canon_evidence import CanonEvidenceRanker
                    from src.rag.hybrid_search import HybridSearch

                    hybrid = HybridSearch(canon_db)
                    ranker = CanonEvidenceRanker(hybrid)
                    canon_expert = CanonExpert(router, canon_evidence=ranker)
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

    if args.phase < 2:
        ledger = RunLedger(db_path=ledger_path)

    # Initialize Phase 3 components if requested
    metrics_dashboard = None
    character_specialist = None
    revision_pipeline = None
    milestone_gates = None

    if args.phase >= 3:
        print("Initializing Phase 3 components...")
        # Phase 3 requires Phase 2 to be initialized
        try:
            ef = None
            try:
                from src.rag.embedding import get_embedding_function
                ef = get_embedding_function(use_mock=True)
            except Exception:
                pass

            metrics_dashboard, character_specialist, revision_pipeline, milestone_gates = (
                _init_phase3(
                    router, ledger, config, ef,
                    no_revision=args.no_revision,
                    no_milestones=args.no_milestones,
                )
            )
            components = []
            if metrics_dashboard:
                components.append("quality metrics")
            if character_specialist:
                components.append("character specialist")
            if revision_pipeline:
                components.append("revision pipeline")
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
                ef = get_embedding_function(use_mock=True)
            except Exception:
                pass

            (
                physics_enforcer, revision_pipeline, metrics_dashboard,
                character_specialist, milestone_gates, pipeline_session,
                scene_card_generator, export_manager, judge_evaluator,
            ) = _init_phase4(
                router, ledger, config, concept_seed, ef,
                no_revision=args.no_revision,
                no_milestones=args.no_milestones,
                judge=args.judge,
            )

            components = []
            if physics_enforcer:
                components.append("physics enforcer")
            if revision_pipeline:
                components.append("adaptive revision")
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

    # Worldbuilding service (optional, requires --universe-id)
    lore_service = None
    if args.universe_id:
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
            print(f"  Worldbuilding service initialized (universe={args.universe_id})")

            # Wire lore into context assembler
            assembler.lore_service = lore_service
            assembler.universe_id = args.universe_id
            assembler.project_id = args.project_id
        except (ImportError, Exception) as e:
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

    orchestrator = Orchestrator(
        router=router,
        context_assembler=assembler,
        ledger=ledger,
        manuscripts_dir=manuscripts_dir,
        max_structural_retries=pipeline_cfg.get("max_structural_retries", 3),
        max_voice_retries=pipeline_cfg.get("max_voice_retries", 2),
        summarizer=summarizer,
        state_diff_applier=state_diff_applier,
        contradiction_scanner=contradiction_scanner,
        chapter_memory=chapter_memory,
        story_state=story_state,
        canon_expert=canon_expert,
        revision_pipeline=revision_pipeline,
        metrics_dashboard=metrics_dashboard,
        character_specialist=character_specialist,
        milestone_gates=milestone_gates,
        physics_enforcer=physics_enforcer,
        pipeline_session=pipeline_session,
        session_id=session_id,
        judge_evaluator=judge_evaluator,
        lore_service=lore_service,
        universe_id=args.universe_id,
        project_id=args.project_id,
        worldbuilding_auto_extract=bool(lore_service and args.universe_id),
    )

    # Create session if Phase 4
    if pipeline_session and session_id and not args.resume:
        scene_cards_for_session = load_scene_cards(args.scene_cards_dir, args.chapter)
        pipeline_session.create_session(session_id, scene_cards_for_session)

    # Load scene cards
    scene_cards = load_scene_cards(args.scene_cards_dir, args.chapter)
    print(f"Loaded {len(scene_cards)} scene card(s)")
    print(f"Deployment mode: {router.mode}")
    print(f"Pipeline phase: {args.phase}")
    print(f"Output directory: {manuscripts_dir}")

    try:
        results = await orchestrator.run_pipeline(scene_cards)

        # Summary
        print(f"\n{'='*60}")
        print("Pipeline Complete")
        print(f"{'='*60}")
        total_words = sum(r["word_count"] for r in results)
        print(f"Chapters generated: {len(results)}")
        print(f"Total word count: {total_words:,}")
        for r in results:
            verdict = r["evaluation"]["verdict"]
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
                f"{r['word_count']:,} words, gate={verdict}{flag_str}{quality_str}{char_str}{judge_str}"
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

    finally:
        await router.close()
        ledger.close()
        if story_state:
            story_state.close()


def cli():
    """Entry point for the CLI."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
