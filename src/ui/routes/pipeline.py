"""Pipeline control API endpoints."""

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.ui.app import get_app_state
from src.ui.pipeline_manager import PipelineState

router = APIRouter(tags=["pipeline"])


class PipelineStartRequest(BaseModel):
    concept_seed_path: Optional[str] = None
    scene_cards_dir: Optional[str] = None
    phase: int = 4
    no_milestones: bool = False
    judge: bool = False
    chapter: Optional[int] = None
    # Canonical project scoping — mirrors the CLI --franchise / --book /
    # --run-name / --series flags so the web surface can request the same
    # franchise-scoped, run-isolated output layout as the CLI.
    franchise: Optional[str] = None
    book: Optional[str] = None
    run_name: Optional[str] = None
    series: Optional[str] = None
    # Deprecated aliases for franchise/book. Kept so existing frontend
    # clients keep working; new callers should use franchise/book.
    universe_id: Optional[str] = None
    project_id: Optional[str] = None
    raw_draft: bool = False
    # Phase 5: chapter blueprint controls. Auto-fill missing blueprints by
    # default when phase >= 5; set false to skip generation.
    generate_blueprints: bool = True
    regenerate_blueprints: bool = False
    # Phase 7.2: promote high-severity LoreConflictDetector flags to
    # blocking status. Advisory by default — flags land in the run ledger
    # but don't fail the scene. Mirrors the --strict-lore CLI flag.
    strict_lore: bool = False


class MilestoneApproveRequest(BaseModel):
    should_continue: bool = True


@router.post("/pipeline/start")
async def start_pipeline(body: PipelineStartRequest, request: Request):
    """Start a pipeline run as a background task."""
    state = get_app_state(request)
    pm = state.pipeline_manager

    if pm.state == PipelineState.RUNNING:
        raise HTTPException(409, "Pipeline is already running")

    # Resolve paths
    concept_seed_path = body.concept_seed_path or state.concept_seed_path
    scene_cards_dir = body.scene_cards_dir or state.scene_cards_dir

    if not concept_seed_path:
        raise HTTPException(400, "No concept_seed_path provided")
    if not scene_cards_dir:
        raise HTTPException(400, "No scene_cards_dir provided")
    if not Path(concept_seed_path).exists():
        raise HTTPException(400, f"Concept seed not found: {concept_seed_path}")
    if not Path(scene_cards_dir).exists():
        raise HTTPException(400, f"Scene cards directory not found: {scene_cards_dir}")

    # Load concept seed
    try:
        with open(concept_seed_path, encoding="utf-8") as f:
            concept_seed = json.load(f)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON in concept seed: {e}")

    # Load scene cards
    cards = _load_scene_cards(scene_cards_dir, body.chapter)
    if not cards:
        raise HTTPException(400, "No scene cards found")

    # Resolve canonical scoping — prefer the new fields; fall back to
    # deprecated universe_id/project_id for older clients.
    franchise_slug = body.franchise or body.universe_id
    book_slug = body.book or body.project_id

    # Apply run-level isolation when run_name is provided. Mirrors the CLI
    # ProjectPaths(..., run_id=run_name) flow so web runs land at
    # output/<franchise>/<book>/runs/<run_name>/chapters/ instead of the
    # book-level chapters/ default that app lifespan wires up.
    if body.run_name:
        from src.project_paths import ProjectPaths
        paths = ProjectPaths.from_concept_seed(concept_seed, run_id=body.run_name)
        if franchise_slug:
            paths.franchise_slug = franchise_slug
        if body.series:
            paths.series_slug = body.series
        paths.ensure_dirs()
        state.manuscripts_dir = str(paths.manuscripts_dir)

    # Phase 5: ensure chapter blueprints exist for every chapter being run.
    # Hand-authored blueprints take precedence (skip-if-exists). Requires
    # franchise and book slugs so blueprints land at the canonical path
    # ChapterGateCritic loads from.
    if (
        body.phase >= 5
        and body.generate_blueprints
        and franchise_slug
        and book_slug
    ):
        await _ensure_chapter_blueprints(
            router=state.router,
            ledger=state.ledger,
            concept_seed=concept_seed,
            scene_cards=cards,
            franchise_slug=franchise_slug,
            book_slug=book_slug,
            regenerate=body.regenerate_blueprints,
        )

    # Build the orchestrator and start pipeline
    orchestrator = _create_web_orchestrator(state, concept_seed_path, concept_seed, body)
    pm.total_chapters = len(cards)

    # Session handling
    session_id = None
    if state.pipeline_session:
        from src.pipeline_session import PipelineSession
        session_id = PipelineSession.generate_session_id()
        state.pipeline_session.create_session(session_id, cards)
        orchestrator.session_id = session_id
        orchestrator.pipeline_session = state.pipeline_session
    pm.session_id = session_id

    # Reset and start
    pm.state = PipelineState.IDLE
    pm.results = []
    pm.error = None
    await pm.start(orchestrator.run_pipeline(cards))

    return {"session_id": session_id, "status": "running", "total_chapters": len(cards)}


@router.get("/pipeline/status")
async def get_pipeline_status(request: Request):
    """Get current pipeline status."""
    state = get_app_state(request)
    return state.pipeline_manager.get_status()


@router.post("/pipeline/pause")
async def pause_pipeline(request: Request):
    """Pause the pipeline after the current chapter completes."""
    state = get_app_state(request)
    try:
        state.pipeline_manager.pause()
        return {"status": "paused"}
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.post("/pipeline/resume")
async def resume_pipeline(request: Request):
    """Resume a paused pipeline."""
    state = get_app_state(request)
    try:
        state.pipeline_manager.resume()
        return {"status": "running"}
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.get("/pipeline/results")
async def get_pipeline_results(request: Request):
    """Get all chapter results from the current or most recent run."""
    state = get_app_state(request)
    return {"results": state.pipeline_manager.results}


@router.post("/pipeline/milestone/approve")
async def approve_milestone(body: MilestoneApproveRequest, request: Request):
    """Approve or reject a milestone gate pause."""
    state = get_app_state(request)
    try:
        state.pipeline_manager.approve_milestone(body.should_continue)
        return {"status": "approved" if body.should_continue else "rejected"}
    except RuntimeError as e:
        raise HTTPException(409, str(e))


def _load_scene_cards(scene_cards_dir: str, chapter: Optional[int] = None) -> list[dict]:
    """Load scene cards from a directory."""
    cards_path = Path(scene_cards_dir)
    cards = []
    for card_file in sorted(cards_path.glob("*.json")):
        try:
            with open(card_file, encoding="utf-8") as f:
                card = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if chapter is None or card.get("chapter_number") == chapter:
            cards.append(card)
    return cards


def _load_chapter_blueprints(paths, chapter: Optional[int] = None) -> dict[int, dict]:
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
            blueprints[chapter_number] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return blueprints


async def _ensure_chapter_blueprints(
    router,
    ledger,
    concept_seed: dict,
    scene_cards: list[dict],
    franchise_slug: str,
    book_slug: str,
    regenerate: bool = False,
) -> None:
    """Phase 5: fill in missing chapter blueprints (UI route variant).

    Mirrors the CLI helper in src/main.py. Detects which chapters in
    ``scene_cards`` have no blueprint at the canonical path and generates
    them. Hand-authored blueprints are preserved unless ``regenerate=True``.
    Emits the ``chapter_blueprints_generated`` ledger event.
    """
    if not scene_cards:
        return

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
        return

    from src.planning.chapter_blueprint_generator import (
        ChapterBlueprintGenerator,
        save_blueprints,
    )

    target_cards = (
        scene_cards if regenerate
        else [c for c in scene_cards if c["chapter_number"] in needed_chapters]
    )
    generator = ChapterBlueprintGenerator(router)
    new_blueprints = await generator.generate(concept_seed, target_cards)
    saved = save_blueprints(
        new_blueprints, franchise_slug, book_slug, force=regenerate,
    )
    ledger.emit(
        "chapter_blueprints_generated",
        payload={"count": len(saved), "regenerated": regenerate},
    )


def _create_web_orchestrator(state, concept_seed_path, concept_seed, body):
    """Create a WebOrchestrator with all configured components."""
    from src.memory.context_assembler import ContextAssembler
    from src.pipeline.canon_guidance import CanonGuidanceStore
    from src.pipeline.chapter_packet import ChapterPacketCompiler
    from src.project_paths import ProjectPaths
    from src.runtime_flags import load_runtime_flags
    from src.ui.web_orchestrator import WebOrchestrator

    pipeline_cfg = state.config.get("pipeline", {})

    # Accept both the canonical franchise/book fields and the deprecated
    # universe_id/project_id aliases. ContextAssembler and ChapterGateCritic
    # keep the legacy parameter names internally for now.
    universe_id = body.franchise or body.universe_id
    project_id = body.book or body.project_id

    assembler = ContextAssembler(
        concept_seed_path=concept_seed_path,
        manuscripts_dir=state.manuscripts_dir,
        story_state=state.story_state,
        knowledge_layers=state.knowledge_layers,
        chapter_memory=state.chapter_memory,
        lore_service=state.lore_service,
        universe_id=universe_id,
        project_id=project_id,
    )
    paths = ProjectPaths.from_concept_seed_path(concept_seed_path)
    if universe_id:
        paths.franchise_slug = universe_id
    if project_id:
        paths.project_slug = project_id
    chapter_packet_compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints=_load_chapter_blueprints(paths, chapter=body.chapter),
        assembler=assembler,
        story_state=state.story_state,
        canon_guidance_store=CanonGuidanceStore(
            paths.canon_guidance_dir,
            canon_contract_path=paths.canon_contract_path,
        ),
    )
    runtime_flags = load_runtime_flags(concept_seed=concept_seed)

    # Save-blocker and post-check agents. Keep this aligned with the CLI path:
    # presence checking should always be available, while CanonExpert can run
    # in profile-only mode without a CanonDB/RAG evidence store.
    presence_checker = None
    canon_expert = None
    line_writer = None
    micro_repair = None
    try:
        from src.agents.presence_checker import PresenceChecker

        presence_checker = PresenceChecker(state.router)
    except ImportError:
        pass
    if body.phase >= 2:
        try:
            from src.agents.canon_expert import CanonExpert

            canon_expert = CanonExpert(state.router)
        except ImportError:
            pass
    if state.config.get("agent_routing", {}).get("line_writer"):
        try:
            from src.agents.line_writer import LineWriter

            line_writer = LineWriter(state.router)
        except ImportError:
            pass
    if state.config.get("agent_routing", {}).get("micro_repair"):
        try:
            from src.agents.micro_repair import MicroRepair

            micro_repair = MicroRepair(state.router)
        except ImportError:
            pass

    # Optional Phase 3/4 components
    metrics_dashboard = None
    character_specialist = None
    milestone_gates = None
    physics_enforcer = None
    judge_evaluator = None

    if body.phase >= 3:
        try:
            from src.quality.metrics_dashboard import MetricsDashboard
            from src.agents.character_specialist import CharacterSpecialist

            ef = state.embedding_function
            metrics_dashboard = MetricsDashboard(
                negative_constraints_path=str(Path("config") / "negative_constraints.yaml"),
                embedding_function=ef,
            )
            character_specialist = CharacterSpecialist(state.router)
        except ImportError:
            pass

        if not body.no_milestones:
            try:
                from src.quality.milestone_gates import MilestoneGates
                milestone_gates = MilestoneGates(
                    ledger=state.ledger,
                    on_pause_callback=state.pipeline_manager.milestone_callback,
                )
            except ImportError:
                pass

    if body.phase >= 4:
        try:
            from src.planning.physics_enforcer import PhysicsEnforcer
            physics_enforcer = PhysicsEnforcer(concept_seed)
        except ImportError:
            pass

        if body.judge:
            try:
                from src.quality.llm_judge import JudgeEvaluator
                judge_evaluator = JudgeEvaluator(state.router)
            except ImportError:
                pass

    # Phase 5: chapter-level gate critic. Always instantiate when phase >= 5;
    # the critic falls back to composition-only checks if no blueprint exists.
    # Phase 7.4: when lore_service + universe_id are available, the critic
    # retrieves canonical lore for a lore_consistency_check.
    chapter_gate_critic = None
    if body.phase >= 5:
        try:
            from src.agents.chapter_gate_critic import ChapterGateCritic
            chapter_gate_critic = ChapterGateCritic(
                state.router,
                lore_service=state.lore_service,
                universe_id=universe_id,
            )
        except ImportError:
            pass

    # Phase 2 components
    summarizer = None
    state_diff_applier = None
    contradiction_scanner = None

    if body.phase >= 2 and state.story_state:
        try:
            from src.agents.summarizer import Summarizer
            from src.memory.state_diff import StateDiffApplier
            from src.memory.contradiction_scanner import ContradictionScanner

            summarizer = Summarizer(state.router)
            state_diff_applier = StateDiffApplier(
                state.story_state, state.knowledge_layers, state.ledger
            )
            contradiction_scanner = ContradictionScanner(
                state.story_state, state.knowledge_layers, state.ledger
            )
        except ImportError:
            pass

    return WebOrchestrator(
        router=state.router,
        context_assembler=assembler,
        ledger=state.ledger,
        manuscripts_dir=state.manuscripts_dir,
        max_structural_retries=pipeline_cfg.get("max_structural_retries", 3),
        max_voice_retries=pipeline_cfg.get("max_voice_retries", 2),
        runtime_flags=runtime_flags,
        chapter_packet_compiler=chapter_packet_compiler,
        summarizer=summarizer,
        state_diff_applier=state_diff_applier,
        contradiction_scanner=contradiction_scanner,
        chapter_memory=state.chapter_memory,
        story_state=state.story_state,
        canon_expert=canon_expert,
        presence_checker=presence_checker,
        line_writer=line_writer,
        micro_repair=micro_repair,
        metrics_dashboard=metrics_dashboard,
        character_specialist=character_specialist,
        milestone_gates=milestone_gates,
        physics_enforcer=physics_enforcer,
        judge_evaluator=judge_evaluator,
        chapter_gate_critic=chapter_gate_critic,
        pipeline_manager=state.pipeline_manager,
        lore_service=state.lore_service,
        universe_id=universe_id,
        project_id=project_id,
        worldbuilding_auto_extract=(
            bool(state.lore_service and universe_id)
            and bool(
                state.config.get("worldbuilding", {})
                .get("auto_extraction", {})
                .get("enabled", True)
            )
        ),
        strict_lore=body.strict_lore,
        raw_draft=body.raw_draft,
    )
