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
    no_revision: bool = False
    no_milestones: bool = False
    judge: bool = False
    chapter: Optional[int] = None


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


def _create_web_orchestrator(state, concept_seed_path, concept_seed, body):
    """Create a WebOrchestrator with all configured components."""
    from src.memory.context_assembler import ContextAssembler
    from src.ui.web_orchestrator import WebOrchestrator

    pipeline_cfg = state.config.get("pipeline", {})

    assembler = ContextAssembler(
        concept_seed_path=concept_seed_path,
        manuscripts_dir=state.manuscripts_dir,
        story_state=state.story_state,
        knowledge_layers=state.knowledge_layers,
        chapter_memory=state.chapter_memory,
    )

    # Optional Phase 3/4 components
    revision_pipeline = None
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

        if not body.no_revision:
            try:
                from src.revision.adaptive_revision import AdaptiveRevisionPipeline
                revision_pipeline = AdaptiveRevisionPipeline(state.router, state.ledger)
            except ImportError:
                try:
                    from src.revision.pipeline import RevisionPipeline
                    revision_pipeline = RevisionPipeline(state.router, state.ledger)
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
        summarizer=summarizer,
        state_diff_applier=state_diff_applier,
        contradiction_scanner=contradiction_scanner,
        chapter_memory=state.chapter_memory,
        story_state=state.story_state,
        revision_pipeline=revision_pipeline,
        metrics_dashboard=metrics_dashboard,
        character_specialist=character_specialist,
        milestone_gates=milestone_gates,
        physics_enforcer=physics_enforcer,
        judge_evaluator=judge_evaluator,
        pipeline_manager=state.pipeline_manager,
    )
