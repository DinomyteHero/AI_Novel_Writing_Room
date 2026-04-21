"""Event-driven orchestrator for the chapter generation pipeline.

Phase 1 flow (per scene card):
  PlotArchitect -> ProseStylist -> GateCritic -> (retry loop)
  -> QualityMetrics -> QualityPolish -> compression guard -> FinalGate -> save
All steps emit typed events to the RunLedger.

The Final Gate validates the actual polished text against the scene-card contract
(character presence, closing-hook boundary, word-count floor, turning point). If
it rejects the polish, the Scene-Gate-passed draft is saved instead. This makes
the final saved prose the unit of truth — no post-gate stage can silently rewrite
a scene without validation.

Phase 2 additions (when dependencies provided):
  After save: Summarizer -> ChromaDB storage -> StateDiff -> ContradictionScanner

Phase 3 additions (when dependencies provided):
  After save: CharacterSpecialist -> MilestoneGate check

Phase 4 additions (when dependencies provided):
  Before PlotArchitect: PhysicsEnforcer pre-chapter validation
  After save: PhysicsEnforcer post-chapter validation
  After quality metrics: JudgeEvaluator LLM-as-judge scoring
  Session persistence: save/resume via PipelineSession
"""

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING

from src.agents.final_gate import FinalGate
from src.agents.gate_critic import GateCritic
from src.agents.plot_architect import PlotArchitect
from src.agents.prose_stylist import ProseStylist
from src.agents.quality_polish import QualityPolish
from src.memory.context_assembler import ContextAssembler
from src.model_router import ModelRouter
from src.run_ledger import RunLedger

if TYPE_CHECKING:
    from src.agents.canon_expert import CanonExpert
    from src.agents.chapter_gate_critic import ChapterGateCritic
    from src.agents.character_specialist import CharacterSpecialist
    from src.agents.line_writer import LineWriter
    from src.agents.presence_checker import PresenceChecker
    from src.agents.summarizer import Summarizer
    from src.memory.chapter_memory import ChapterMemory
    from src.memory.contradiction_scanner import ContradictionScanner
    from src.memory.state_diff import StateDiffApplier
    from src.memory.story_state import StoryState
    from src.agents.continuity_extractor import ContinuityExtractor
    from src.memory.continuity_log import ContinuityLog
    from src.memory.promise_ledger import PromiseLedger
    from src.memory.sociogram import Sociogram
    from src.pipeline.chapter_packet import ChapterPacketCompiler
    from src.pipeline.revision_debt import RevisionDebtStore
    from src.quality.metrics_dashboard import MetricsDashboard
    from src.quality.milestone_gates import MilestoneGates
    from src.planning.physics_enforcer import PhysicsEnforcer
    from src.pipeline_session import PipelineSession
    from src.quality.llm_judge import JudgeEvaluator
    from src.worldbuilding.lore_service import LoreService


class Orchestrator:
    """Event-driven pipeline orchestrator.

    Manages the per-chapter generation loop:
    PlotArchitect -> ProseStylist -> GateCritic -> (retry loop)
      -> QualityMetrics -> QualityPolish -> compression guard -> FinalGate -> save
    with failure-driven retry logic. Final Gate rejection reverts to the
    Scene-Gate-passed draft so the saved file is always a validated artifact.

    Phase 2 (optional): After save, runs Summarizer -> state diff -> contradiction scan.
    Phase 3 (optional): Quality metrics, character specialist, milestones.
    Phase 4 (optional): Physics enforcement, session persistence, LLM judge.
    """

    def __init__(
        self,
        router: ModelRouter,
        context_assembler: ContextAssembler,
        ledger: RunLedger,
        manuscripts_dir: str = "output/_fallback/manuscripts",
        max_structural_retries: int = 3,
        max_voice_retries: int = 2,
        # Phase 2 optional dependencies:
        summarizer: Optional["Summarizer"] = None,
        state_diff_applier: Optional["StateDiffApplier"] = None,
        contradiction_scanner: Optional["ContradictionScanner"] = None,
        chapter_memory: Optional["ChapterMemory"] = None,
        story_state: Optional["StoryState"] = None,
        canon_expert: Optional["CanonExpert"] = None,
        presence_checker: Optional["PresenceChecker"] = None,
        line_writer: Optional["LineWriter"] = None,
        # Phase 3 optional dependencies:
        metrics_dashboard: Optional["MetricsDashboard"] = None,
        character_specialist: Optional["CharacterSpecialist"] = None,
        milestone_gates: Optional["MilestoneGates"] = None,
        # Phase 4 optional dependencies:
        physics_enforcer: Optional["PhysicsEnforcer"] = None,
        pipeline_session: Optional["PipelineSession"] = None,
        session_id: Optional[str] = None,
        judge_evaluator: Optional["JudgeEvaluator"] = None,
        # Chapter-level evaluation:
        chapter_gate_critic: Optional["ChapterGateCritic"] = None,
        # Worldbuilding optional dependency:
        lore_service: Optional["LoreService"] = None,
        universe_id: Optional[str] = None,
        project_id: Optional[str] = None,
        worldbuilding_auto_extract: bool = False,
        strict_lore: bool = False,
        raw_draft: bool = False,
        skip_gate_loop: bool = False,
        # Architecture upgrade Slice 1: state-firewall runtime flags.
        # None defers to config/settings.yaml defaults (firewall off → run
        # aborts on blocker, preserving pre-Slice-1 behavior).
        runtime_flags: Optional[dict] = None,
        # Architecture upgrade Slice 2: chapter packet + revision debt.
        # Both default None → flag-off path (no packet compilation, advisories
        # stay ledger-only). When runtime.chapter_packet.enabled is true the
        # caller must supply chapter_packet_compiler; otherwise packet flag is
        # ignored (fallback to flat assembly). Same for revision_debt_store.
        chapter_packet_compiler: Optional["ChapterPacketCompiler"] = None,
        revision_debt_store: Optional["RevisionDebtStore"] = None,
        # Architecture upgrade Slice 3: promise ledger. When the flag is on,
        # scene-save-time calls record_progression / record_payoff for each
        # declared promise_id on the scene card. The chapter-packet compiler
        # pulls list_top_urgent into the overlay via its own reference; pass
        # the same PromiseLedger instance here and to the compiler.
        promise_ledger: Optional["PromiseLedger"] = None,
        # Architecture upgrade Slice 4: continuity event log + extractor.
        # Both stay dormant unless runtime.continuity_log.enabled is true AND
        # both collaborators are supplied. The extractor runs *after* save so
        # blocker-quarantined prose never produces trusted events.
        continuity_log: Optional["ContinuityLog"] = None,
        continuity_extractor: Optional["ContinuityExtractor"] = None,
        # Architecture upgrade Slice 5: sociogram. Scene-card
        # ``relationship_deltas`` flow into the store at save time. The
        # chapter-packet compiler queries the same instance for the
        # overlay's ``relationship_context`` field.
        sociogram: Optional["Sociogram"] = None,
    ):
        self.router = router
        self.assembler = context_assembler
        self.ledger = ledger
        self.runtime_flags = runtime_flags or {}
        self.manuscripts_dir = Path(manuscripts_dir)
        self.manuscripts_dir.mkdir(parents=True, exist_ok=True)
        # Quarantine directory sits beside manuscripts so the project layout
        # keeps saved chapters and save-blocker artifacts side-by-side:
        #   <run_output>/chapters/   — saved prose
        #   <run_output>/quarantine/ — scenes that tripped save-blockers
        self.quarantine_dir = self.manuscripts_dir.parent / "quarantine"
        self.max_structural_retries = max_structural_retries
        self.max_voice_retries = max_voice_retries
        self.raw_draft = raw_draft
        self.skip_gate_loop = skip_gate_loop

        # Initialize Phase 1 agents
        self.plot_architect = PlotArchitect(router)
        self.prose_stylist = ProseStylist(router)
        self.gate_critic = GateCritic(router)
        self.quality_polish = QualityPolish(router)
        self.final_gate = FinalGate(router)

        # Phase 2 optional components
        self.summarizer = summarizer
        self.state_diff_applier = state_diff_applier
        self.contradiction_scanner = contradiction_scanner
        self.chapter_memory = chapter_memory
        self.story_state = story_state
        self.canon_expert = canon_expert
        self.presence_checker = presence_checker
        self.line_writer = line_writer

        # Phase 3 optional components
        self.metrics_dashboard = metrics_dashboard
        self.character_specialist = character_specialist
        self.milestone_gates = milestone_gates

        # Phase 4 optional components
        self.physics_enforcer = physics_enforcer
        self.pipeline_session = pipeline_session
        self.session_id = session_id
        self.judge_evaluator = judge_evaluator

        # Chapter-level evaluation
        self.chapter_gate_critic = chapter_gate_critic

        # Worldbuilding optional components
        self.lore_service = lore_service
        self._universe_id = universe_id
        self._project_id = project_id
        self._worldbuilding_auto_extract = worldbuilding_auto_extract
        # Phase 7.2 — advisory by default (decision D3). Strict mode marks
        # high-severity lore_conflicts flags on the scene result so callers
        # can treat them as failures.
        self._strict_lore = strict_lore

        # Architecture upgrade Slice 2 — chapter packet + revision debt.
        # Both stay dormant unless runtime.chapter_packet.enabled /
        # runtime.revision_debt.enabled is true AND the caller supplies the
        # corresponding collaborator. Bases are cached per chapter_number so
        # overlay compilation per scene is cheap (base immutable).
        self.chapter_packet_compiler = chapter_packet_compiler
        self.revision_debt_store = revision_debt_store
        self._chapter_packet_bases: dict[int, Any] = {}
        packet_cfg = self.runtime_flags.get("runtime", {}).get("chapter_packet", {})
        self._chapter_packet_enabled = bool(
            packet_cfg.get("enabled", False) and self.chapter_packet_compiler is not None
        )
        self._chapter_packet_fallback_on_error = bool(
            packet_cfg.get("fallback_on_error", True)
        )
        self._revision_debt_enabled = bool(
            self.runtime_flags.get("runtime", {}).get("revision_debt", {}).get("enabled", False)
            and self.revision_debt_store is not None
        )
        # Active store reference used by producers — None when the flag is off
        # so wrappers short-circuit even when a store is attached for inspection.
        self._active_debt_store = (
            self.revision_debt_store if self._revision_debt_enabled else None
        )
        # Persistence path for compiled packets: <run_dir>/chapter_packets/.
        # <run_dir> = parent of manuscripts_dir (chapters/). Matches the
        # existing quarantine_dir placement convention.
        self._packets_dir = self.manuscripts_dir.parent / "chapter_packets"

        # Architecture upgrade Slice 3 \u2014 promise ledger. When the flag is on
        # and a ledger was passed, scene-save time calls record_progression /
        # record_payoff per declared promise_id, emits `promise_progressed` /
        # `promise_paid` events, and surfaces any `list_overdue` matches as
        # warn-level `promise_overdue` telemetry.
        self.promise_ledger = promise_ledger
        self._promise_ledger_enabled = bool(
            self.runtime_flags.get("runtime", {}).get("promise_ledger", {}).get("enabled", False)
            and self.promise_ledger is not None
        )

        # Architecture upgrade Slice 4 \u2014 continuity event log + extractor.
        # Both must be attached AND the flag on for trusted-event recording to
        # fire. Suppressed (sub-threshold) events go *nowhere* except a warn
        # count event (spec \u00a78.3.2).
        self.continuity_log = continuity_log
        self.continuity_extractor = continuity_extractor
        continuity_cfg = (
            self.runtime_flags.get("runtime", {}).get("continuity_log", {}) or {}
        )
        self._continuity_log_enabled = bool(
            continuity_cfg.get("enabled", False)
            and self.continuity_log is not None
            and self.continuity_extractor is not None
        )
        try:
            self._continuity_min_confidence = float(
                continuity_cfg.get("min_confidence", 0.85)
            )
        except (TypeError, ValueError):
            self._continuity_min_confidence = 0.85

        # Architecture upgrade Slice 5 \u2014 sociogram. Scene-card
        # ``relationship_deltas`` fire at save time when the flag is on.
        # Overlay rendering uses the same store via ChapterPacketCompiler.
        self.sociogram = sociogram
        self._sociogram_enabled = bool(
            self.runtime_flags.get("runtime", {}).get("sociogram", {}).get("enabled", False)
            and self.sociogram is not None
        )

        # Architecture upgrade Slice 1 — Phase 0 prompt capture.
        # When runtime.phase0_audit.enabled is on, instantiate a snapshot
        # writer and attach to every agent. Scenes get opened via
        # phase0_snapshot.start_scene() at the top of each scene loop.
        self.phase0_snapshot = None
        phase0_cfg = (
            self.runtime_flags.get("runtime", {}).get("phase0_audit", {})
        )
        if phase0_cfg.get("enabled", False):
            from src.pipeline.phase0_capture import Phase0PromptSnapshot
            # Conventional layout: manuscripts_dir is <run_dir>/chapters, so
            # its parent is <run_dir>. When callers pass a non-conventional
            # manuscripts_dir, this falls back to dumping beside the chapters
            # folder, which is fine for inspection.
            run_dir = self.manuscripts_dir.parent
            self.phase0_snapshot = Phase0PromptSnapshot(run_dir=run_dir)
            for agent in (
                self.plot_architect, self.prose_stylist, self.gate_critic,
                self.quality_polish, self.final_gate,
                self.line_writer, self.canon_expert, self.presence_checker,
                self.chapter_gate_critic, self.character_specialist,
                self.summarizer,
            ):
                if agent is not None:
                    agent.attach_phase0_snapshot(self.phase0_snapshot)

    @staticmethod
    def _is_last_scene_in_chapter(current_index: int, sorted_cards: list[dict]) -> bool:
        """Check if the current card is the last scene in its chapter."""
        if current_index >= len(sorted_cards) - 1:
            return True  # Last card overall
        current_ch = sorted_cards[current_index]["chapter_number"]
        next_ch = sorted_cards[current_index + 1]["chapter_number"]
        return current_ch != next_ch

    async def maybe_run_chapter_gate_after_scene(
        self,
        scene_index: int,
        active_cards: list[dict],
        results: list[dict],
    ) -> None:
        """Run chapter-close hooks after the last scene in a chapter.

        Shared between Orchestrator.run_pipeline and WebOrchestrator.run_pipeline
        so both surfaces honour the same semantics. No-op when the scene is not
        the last in its chapter. Two close-hooks run here:

        1. Chapter-level gate (if ``self.chapter_gate_critic`` is wired). Mutates
           the most recent result in-place with ``chapter_gate``.
        2. Word-count telemetry (Stage 1h). Always runs; never blocks.
        """
        if not self._is_last_scene_in_chapter(scene_index, active_cards):
            return

        chapter_num = active_cards[scene_index]["chapter_number"]
        ch_cards = [c for c in active_cards if c["chapter_number"] == chapter_num]
        ch_results = [r for r in results if r.get("chapter_number") == chapter_num]

        if self.chapter_gate_critic:
            ch_eval = await self._run_chapter_gate(chapter_num, ch_cards, ch_results)
            results[-1]["chapter_gate"] = ch_eval
            if not ch_eval["chapter_passed"]:
                failures = len(ch_eval.get("chapter_level_failures", []))
                print(
                    f"  Chapter {chapter_num} failed chapter-level gate "
                    f"({failures} issue(s))"
                )

        # Word-count telemetry — chapter-level drift only, never blocks.
        from src.pipeline.word_count_telemetry import (
            emit_chapter_word_count_telemetry,
        )
        try:
            telemetry_payload = emit_chapter_word_count_telemetry(
                self.ledger,
                chapter_number=chapter_num,
                chapter_results=ch_results,
                franchise_slug=self._universe_id,
                book_slug=self._project_id,
            )
            # Slice 2: debt row when drift exceeds the info band (|pct| > 15).
            # Noop when flag off.
            drift = telemetry_payload.get("drift_fraction")
            target = telemetry_payload.get("target_word_count")
            actual = telemetry_payload.get("actual_word_count")
            if drift is not None and target and abs(drift) > 0.15:
                from src.pipeline.revision_debt_producers import emit_wordcount_drift

                emit_wordcount_drift(
                    self._active_debt_store,
                    ledger=self.ledger,
                    scope={"level": "chapter", "chapter_number": chapter_num},
                    target=int(target),
                    actual=int(actual or 0),
                    pct_drift=float(drift) * 100.0,
                )
        except Exception as e:
            # Telemetry failure must never block chapter completion.
            print(
                f"  [WARN] word-count telemetry failed: {e.__class__.__name__}: {e}"
            )

    async def _run_chapter_gate(
        self,
        chapter_number: int,
        chapter_cards: list[dict],
        chapter_results: list[dict],
    ) -> dict:
        """Run the chapter-level gate critic after the last scene in a chapter.

        Passes franchise/book identifiers so ChapterGateCritic can locate the
        matching chapter_blueprint.json. Absent or unparseable blueprint
        falls back gracefully to composition-only checks.
        """
        scene_prose = []
        for result in chapter_results:
            path = Path(result["output_path"])
            if path.exists():
                scene_prose.append(path.read_text(encoding="utf-8"))

        context = {
            "scene_cards": chapter_cards,
            "scene_prose": scene_prose,
            "chapter_number": chapter_number,
        }
        if self._universe_id:
            context["franchise_slug"] = self._universe_id
        if self._project_id:
            context["book_slug"] = self._project_id

        evaluation = await self.chapter_gate_critic.run(context)

        self.ledger.emit(
            "chapter_gate_complete",
            chapter_number=chapter_number,
            payload={
                "passed": evaluation["chapter_passed"],
                "failure_count": len(evaluation.get("chapter_level_failures", [])),
                "blueprint_used": evaluation.get("blueprint_used", False),
            },
        )

        return evaluation

    async def run_pipeline(self, scene_cards: list[dict]) -> list[dict]:
        """Run the full pipeline for a list of scene cards."""
        # Phase 4: Filter out completed chapters if resuming a session
        active_cards = scene_cards
        if self.pipeline_session and self.session_id:
            active_cards = self.pipeline_session.get_pending_cards(
                self.session_id, scene_cards
            )
            if len(active_cards) < len(scene_cards):
                skipped = len(scene_cards) - len(active_cards)
                print(f"Resuming session '{self.session_id}' — skipping {skipped} completed chapter(s)")
                self.ledger.emit(
                    "session_resume",
                    payload={"session_id": self.session_id, "skipped": skipped},
                )

        # Sort scene cards by (chapter_number, scene_number) for correct ordering
        active_cards = sorted(
            active_cards,
            key=lambda c: (c["chapter_number"], c.get("scene_number", 1)),
        )

        self.ledger.emit("pipeline_start", payload={"total_scenes": len(active_cards)})
        results = []

        # Lazy import to avoid circular concerns and keep the pipeline package
        # optional for callers that don't exercise save-blockers.
        from src.pipeline.save_blockers import SaveBlockedError, should_abort_run

        try:
            for i, scene_card in enumerate(active_cards):
                chapter_num = scene_card["chapter_number"]
                scene_num = scene_card.get("scene_number", 1)
                print(f"\n{'='*60}")
                print(f"Chapter {chapter_num}, Scene {scene_num}")
                print(f"{'='*60}")

                # Phase 0 prompt capture: open a per-scene subdir. No-op when
                # runtime.phase0_audit.enabled is off (snapshot is None).
                if self.phase0_snapshot is not None:
                    self.phase0_snapshot.start_scene(
                        chapter=chapter_num, scene=scene_num,
                    )

                try:
                    result = await self.run_chapter(scene_card)
                except SaveBlockedError as e:
                    if should_abort_run(self.runtime_flags):
                        # Pre-Slice-1 behavior: abort the entire run on first
                        # blocker. No partial chapters, no silent skips.
                        print(f"\n{'=' * 60}")
                        print("PIPELINE ABORTED — save-blocker fired")
                        print(f"{'=' * 60}")
                        print(str(e))
                        break

                    decision = self._handle_firewall(
                        scene_card=scene_card,
                        error=e,
                        active_cards=active_cards,
                        current_index=i,
                    )
                    print(
                        f"\n[STATE-FIREWALL] isolated {scene_card['chapter_number']}.{scene_card.get('scene_number', 1)} "
                        f"→ gap_id={decision.gap_id}"
                    )
                    if decision.soft_halted_scenes:
                        print(
                            f"  soft_halt: {', '.join(decision.soft_halted_scenes)}"
                        )
                    if decision.continue_with_gap_note:
                        print(
                            f"  continue_with_note: {', '.join(decision.continue_with_gap_note)}"
                        )
                    if not decision.continue_run:
                        print("[STATE-FIREWALL] soft-halting run — open gaps require human review.")
                        break
                    # Skip the isolated scene and advance.
                    continue

                results.append(result)

                # Phase 4: Save session progress after each chapter
                if self.pipeline_session and self.session_id:
                    self.pipeline_session.mark_chapter_complete(
                        self.session_id, chapter_num, scene_num, result
                    )

                # Chapter-level gate: run after last scene in chapter
                await self.maybe_run_chapter_gate_after_scene(i, active_cards, results)

                # Check if milestone gate aborted the pipeline
                if result.get("milestone_abort"):
                    print(f"\nPipeline paused at milestone: {result['milestone']['milestone_name']}")
                    break
        except KeyboardInterrupt:
            print("\nPipeline interrupted — saving session...")
        finally:
            # Phase 4: Save session on exit
            if self.pipeline_session and self.session_id:
                self.pipeline_session.save(
                    self.session_id,
                    self.pipeline_session.load(self.session_id) or {},
                )
                self.ledger.emit(
                    "session_save",
                    payload={"session_id": self.session_id, "completed": len(results)},
                )

        self.ledger.emit(
            "pipeline_complete",
            payload={"chapters_generated": len(results)},
        )
        return results

    def _handle_firewall(
        self,
        *,
        scene_card: dict,
        error,
        active_cards: list[dict],
        current_index: int,
    ):
        """Route a save-blocker through :class:`StateFirewall`.

        Collects the subsequent scenes relevant to the classifier — the
        remaining scenes in the current chapter plus the first scene of the
        next chapter — and delegates the isolation + classification work.
        Returns the :class:`FirewallDecision` so ``run_pipeline`` can decide
        whether to break the scene loop.
        """
        from types import SimpleNamespace

        from src.pipeline.state_firewall import StateFirewall
        from src.pipeline.successor_classifier import SuccessorClassifier

        chapter_num = int(scene_card["chapter_number"])

        remaining = active_cards[current_index + 1:]
        same_chapter_remaining = [
            c for c in remaining
            if int(c["chapter_number"]) == chapter_num
        ]
        next_chapter_scenes = [
            c for c in remaining
            if int(c["chapter_number"]) == chapter_num + 1
        ]
        first_of_next: list[dict] = []
        if next_chapter_scenes:
            # Earliest by scene_number.
            first_of_next = [
                min(next_chapter_scenes, key=lambda c: int(c["scene_number"])),
            ]
        subsequent = [*same_chapter_remaining, *first_of_next]

        flags = self.runtime_flags or {}
        classifier_cfg = (
            flags.get("runtime", {})
            .get("firewall", {})
            .get("successor_classifier", {})
        )
        classifier = SuccessorClassifier(
            jaccard_threshold=float(classifier_cfg.get("jaccard_threshold", 0.5)),
            adjacency_max_for_continue=int(classifier_cfg.get("adjacency_max_for_continue", 1)),
        )

        project_paths_shim = SimpleNamespace(quarantine_dir=self.quarantine_dir)

        firewall = StateFirewall(
            project_paths=project_paths_shim,
            story_state=self.story_state,
            classifier=classifier,
            ledger=self.ledger,
            runtime_flags=flags,
        )

        blockers = getattr(error, "blockers", [])
        brief = None  # Pre-save state; the caller's brief is not currently
        # captured on the SaveBlockedError. Slice 6's patch workflow will
        # hydrate this by reading quarantine/brief.json.
        decision = firewall.handle_blocker(
            scene_card=scene_card,
            prose="",  # already persisted by write_quarantine before raise
            brief=brief,
            blockers=blockers,
            subsequent_scenes=subsequent,
        )
        # Slice 2: persist a high-severity blocker_record row. Noop when flag off.
        from src.pipeline.revision_debt_producers import emit_blocker_record
        emit_blocker_record(
            self._active_debt_store,
            ledger=self.ledger,
            scope={
                "level": "scene",
                "chapter_number": chapter_num,
                "scene_number": int(scene_card.get("scene_number", 1)),
            },
            blocker_categories=[getattr(b, "code", str(b)) for b in blockers],
            gap_id=getattr(decision, "gap_id", None),
        )
        return decision

    async def run_chapter(self, scene_card: dict) -> dict:
        """Run the full pipeline for a single scene card."""
        chapter_num = scene_card["chapter_number"]
        scene_num = scene_card.get("scene_number", 1)

        self.ledger.emit(
            "chapter_start",
            chapter_number=chapter_num,
            scene_number=scene_num,
            payload={"mission": scene_card.get("mission", "")},
        )

        # Phase 4: Pre-chapter physics validation.
        # Demoted to a sanity net: when the concept_seed carries
        # ``compile_metadata.physics_validated = True`` the compile-time
        # validator in ``scripts/compile_bundle.py`` has already covered the
        # full corpus, so re-running per-scene here would duplicate work and
        # catch nothing new. Skip with an info event in that case. When the
        # flag is absent or False, fall through to the advisory check so
        # hand-edited seeds or legacy projects still get coverage.
        physics_pre = None
        upstream_seed = getattr(self.assembler, "concept_seed", {}) or {}
        upstream_validated = (
            upstream_seed.get("compile_metadata", {}).get("physics_validated")
            is True
        )
        if self.physics_enforcer and upstream_validated:
            self.ledger.emit(
                "physics_pre_skipped_upstream_validated",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={"reason": "compile_metadata.physics_validated=True"},
            )
        elif self.physics_enforcer:
            print("  [P4] Physics pre-check...")
            physics_pre = self.physics_enforcer.validate_pre_chapter(scene_card)
            self.ledger.emit(
                "physics_validation_pre",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={"passed": physics_pre["passed"], "issue_count": len(physics_pre["issues"])},
            )
            if physics_pre["recommendations"]:
                for rec in physics_pre["recommendations"][:3]:
                    print(f"    Physics: {rec}")

        # Step 1: Plot Architect generates the brief
        print("  [1/5] Plot Architect generating brief...")
        generation_brief = await self._run_plot_architect(scene_card)

        # Step 2: Prose Stylist drafts the scene
        print("  [2/5] Prose Stylist drafting...")
        prose = await self._run_prose_stylist(scene_card, generation_brief)

        # Relay v3 (Stage 1f): Canon expert no longer runs mid-stream — it
        # moves to the LAST reader position (continuity_editor) just before
        # the save-blocker check. See below.

        # Relay v3 (Stage 3): optional LineWriter pass between drafter and
        # gate. Preserves structure/POV/canon/characters_present; rewrites
        # for sentence-level rhythm, imagery, and voice texture. Gate_critic
        # and downstream stages evaluate the line-edited prose.
        if self.line_writer and not self.raw_draft:
            prose = await self._run_line_writer(
                scene_card, generation_brief, prose
            )

        # Step 3: Gate Critic evaluates
        print("  [3/5] Gate Critic evaluating...")
        evaluation, prose = await self._gate_loop(scene_card, prose, generation_brief)
        gate_passed_prose = prose
        gate_passed_wc = len(gate_passed_prose.split())

        # Quality Metrics run on gate-passed prose so flags can feed Quality Polish
        # and the cross-scene overused-words accumulator stays consistent.
        quality_metrics = None
        if self.metrics_dashboard:
            print("  [3.5/5] Quality metrics running...")
            prior_chapters = self._load_prior_chapters(chapter_num)
            voice_notes = self._get_pov_voice_notes(scene_card)
            quality_metrics = self.metrics_dashboard.analyze_chapter(
                gate_passed_prose,
                scene_card,
                prior_chapters=prior_chapters,
                voice_notes=voice_notes,
            )
            status = "PASS" if quality_metrics["passed"] else "FAIL"
            print(f"    Quality: {quality_metrics['overall_score']:.2f} ({status})")
            if quality_metrics["flags"]:
                for flag in quality_metrics["flags"][:5]:
                    print(f"    - {flag}")
            # Slice 2: one debt row per quality flag. Noop when flag off.
            from src.pipeline.revision_debt_producers import emit_metric_advisory
            scope = {
                "level": "scene",
                "chapter_number": chapter_num,
                "scene_number": scene_num,
            }
            for flag in quality_metrics.get("flags", []) or []:
                emit_metric_advisory(
                    self._active_debt_store,
                    ledger=self.ledger,
                    scope=scope,
                    metric_name=str(flag)[:60],
                    value=float(quality_metrics.get("overall_score", 0.0)),
                    threshold=float(
                        quality_metrics.get("threshold", 0.0) or 0.0
                    ),
                    bands_over=0,
                    details={"flag": str(flag)},
                )
            # Accumulate overused words for dynamic Prose Stylist constraints
            if not hasattr(self, "_chapter_overused_words"):
                self._chapter_overused_words = set()
            for scene_result in quality_metrics.get("per_scene", []):
                rep = scene_result.get("repetition", {})
                for w in rep.get("flagged_words", []):
                    self._chapter_overused_words.add(w["word"])
            # Track description ratio for cross-scene feedback
            if not hasattr(self, "_scene_description_ratios"):
                self._scene_description_ratios = []
            for scene_result in quality_metrics.get("per_scene", []):
                pacing = scene_result.get("pacing", {})
                dist = pacing.get("scene_type_distribution", {})
                desc_ratio = dist.get("description", 0) + dist.get("introspection", 0)
                self._scene_description_ratios.append(desc_ratio)

        # Steps 4-5: Quality Polish + compression guard + Final Gate
        # (skipped in --raw-draft baseline mode — save gate-passed prose directly)
        final_gate_result: Optional[dict] = None
        polish_rejected = False
        rejection_reason: Optional[str] = None
        if self.raw_draft:
            print("  [4/5] Quality Polish skipped (--raw-draft baseline mode)")
            print("  [5/5] Final Gate skipped (--raw-draft baseline mode)")
            final_prose = gate_passed_prose
        else:
            # Step 4: Quality Polish — single bounded expression-level pass.
            # Relay v3 (Stage 1f): canon_notes is always empty here because
            # the canon expert now runs post-polish as the continuity editor.
            # Quality Polish remains a pure copy-editing pass.
            print("  [4/5] Quality Polish running...")
            polish_result = await self.quality_polish.run({
                "prose": gate_passed_prose,
                "scene_card": scene_card,
                "quality_metrics": quality_metrics,
                "negative_constraints": self.assembler.get_negative_constraints(),
                "canon_notes": "",
            })
            polished_prose = polish_result["prose"]

            # Compression telemetry — Stage 1b of the relay refactor.
            # Historically this block reverted polished_prose to gate_passed_prose
            # when polish cut below 80%. Under the relay, polish output is kept
            # unconditionally; a warn-level ledger event fires at <60% so humans
            # can spot aggressive compressions without auto-reverting.
            polished_wc = len(polished_prose.split())
            if gate_passed_wc and polished_wc < 0.6 * gate_passed_wc:
                pct = polished_wc / gate_passed_wc * 100
                print(
                    f"    Compression advisory: polish cut {gate_passed_wc} -> {polished_wc} "
                    f"({pct:.0f}%) — kept polished output; human review recommended"
                )
                self.ledger.emit(
                    "compression_guard_fired",
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    payload={
                        "gate_word_count": gate_passed_wc,
                        "polish_word_count": polished_wc,
                        "advisory_only": True,
                    },
                )
                # Slice 2: structured advisory row. Noop when flag off.
                from src.pipeline.revision_debt_producers import (
                    emit_compression_advisory,
                )
                emit_compression_advisory(
                    self._active_debt_store,
                    ledger=self.ledger,
                    scope={
                        "level": "scene",
                        "chapter_number": chapter_num,
                        "scene_number": scene_num,
                    },
                    pre_polish_words=gate_passed_wc,
                    post_polish_words=polished_wc,
                    ratio=polished_wc / gate_passed_wc if gate_passed_wc else 0.0,
                )

            # Final Gate — Stage 1c of the relay refactor.
            # Runs as telemetry. Its verdict is logged but does NOT control the
            # save path; polished_prose is always the saved prose unless a
            # save-blocker fires (Stage 1f) downstream.
            print("  [5/5] Final Gate evaluating polish output (advisory)...")
            final_gate_result = await self.final_gate.run({
                "prose": polished_prose,
                "scene_card": scene_card,
                "gate_passed_word_count": gate_passed_wc,
            })
            if final_gate_result["verdict"] != "pass":
                failure_codes = [fc["code"] for fc in final_gate_result.get("failure_codes", [])]
                print(
                    f"    Final Gate advisory: verdict={final_gate_result['verdict']}, "
                    f"codes={failure_codes} — kept polished output (forward-only)"
                )
                self.ledger.emit(
                    "final_gate_rejection",
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    payload={
                        "verdict": final_gate_result["verdict"],
                        "failure_codes": failure_codes,
                        "advisory_only": True,
                    },
                )
                # Slice 2: one debt row per failure code.
                from src.pipeline.revision_debt_producers import (
                    emit_final_gate_advisory,
                )
                scope = {
                    "level": "scene",
                    "chapter_number": chapter_num,
                    "scene_number": scene_num,
                }
                for fc in final_gate_result.get("failure_codes", []):
                    emit_final_gate_advisory(
                        self._active_debt_store,
                        ledger=self.ledger,
                        scope=scope,
                        failure=fc,
                    )
            else:
                print("    Final Gate: pass")
                self.ledger.emit(
                    "final_gate_complete",
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    payload={"verdict": "pass"},
                )
            final_prose = polished_prose

        # Relay v3 (Stage 1f): Continuity Editor runs on FINAL prose.
        # Canon expert is now the last reader before save-blockers — this is
        # the only position where its verdict can reflect the saved artifact.
        continuity_report: Optional[dict] = None
        if self.canon_expert:
            print("  [Continuity] Canon expert validating FINAL prose...")
            try:
                continuity_report = await self.canon_expert.run({
                    "prose": final_prose,
                    "scene_card": scene_card,
                    "concept_seed": getattr(self.assembler, "concept_seed", {}),
                })
                verdict_str = continuity_report.get("verdict", "pass")
                n_violations = len(continuity_report.get("violations", []) or [])
                print(f"    Continuity: {verdict_str} ({n_violations} finding(s))")
                self.ledger.emit(
                    "continuity_editor_complete",
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    payload={
                        "verdict": verdict_str,
                        "violation_count": n_violations,
                    },
                )
                # Slice 2: one debt row per canon advisory/violation. Noop when flag off.
                from src.pipeline.revision_debt_producers import emit_canon_advisory
                scope = {
                    "level": "scene",
                    "chapter_number": chapter_num,
                    "scene_number": scene_num,
                }
                for advisory in continuity_report.get("advisory_notes", []) or []:
                    emit_canon_advisory(
                        self._active_debt_store,
                        ledger=self.ledger,
                        scope=scope,
                        advisory=advisory,
                    )
                for violation in continuity_report.get("violations", []) or []:
                    emit_canon_advisory(
                        self._active_debt_store,
                        ledger=self.ledger,
                        scope=scope,
                        advisory=violation,
                    )
            except Exception as e:
                print(f"    Continuity editor: error ({e.__class__.__name__}) — skipping")
                continuity_report = None

        # Relay v3 (Stage 1f): Save-blocker check. Three categories —
        #   CHARACTER_PRESENCE_BLOCKER (PresenceChecker agent)
        #   CANON_BLOCKER             (continuity_report verdict + severity)
        #   POV_ADVISORY              (heuristic; logs but never blocks in v1)
        # Abort-on-first-blocker: quarantine the scene and raise
        # SaveBlockedError so run_pipeline halts the whole run.
        from src.pipeline.save_blockers import (
            SaveBlockedError,
            check_save_blockers,
            detect_pov_advisory,
            write_quarantine,
        )

        pov_hits = detect_pov_advisory(final_prose, scene_card)
        if pov_hits:
            self.ledger.emit(
                "pov_advisory",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={
                    "hit_count": len(pov_hits),
                    "hits": pov_hits[:10],
                    "advisory_only": True,
                },
            )
            print(f"  [POV] Advisory: {len(pov_hits)} suspect span(s) — no block in v1")

        blockers = await check_save_blockers(
            prose=final_prose,
            scene_card=scene_card,
            continuity_report=continuity_report,
            presence_checker=self.presence_checker,
        )

        if blockers:
            scene_dir = write_quarantine(
                quarantine_root=self.quarantine_dir,
                chapter_number=chapter_num,
                scene_number=scene_num,
                prose=final_prose,
                blockers=blockers,
                brief=generation_brief,
                scene_card=scene_card,
            )
            self.ledger.emit(
                "save_blocked",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={
                    "blocker_count": len(blockers),
                    "blocker_codes": [b.code for b in blockers],
                    "quarantine_path": str(scene_dir),
                },
            )
            print(
                f"  [SAVE-BLOCKED] {len(blockers)} blocker(s) — scene quarantined at {scene_dir}"
            )
            raise SaveBlockedError(
                blockers=blockers,
                quarantine_path=scene_dir,
                chapter_number=chapter_num,
                scene_number=scene_num,
            )

        # Save the chapter
        output_path = self._save_chapter(chapter_num, scene_num, final_prose)
        print(f"  Saved: {output_path}")

        # Architecture upgrade Slice 3 \u2014 record declared promise deltas.
        # Scene cards are the source of truth (spec \u00a77.1 declarative model);
        # SceneReviewer-suggested progressions are explicitly *not* written
        # here \u2014 those land as editorial.scene_reviewer revision-debt rows.
        self._maybe_record_promise_deltas(scene_card)

        # Architecture upgrade Slice 4 — extract narrow continuity events
        # from the saved prose. Threshold-filtered inside the helper; sub-
        # threshold rows are suppressed entirely (not logged, not stored) so
        # hallucinated facts can never reach the packet.
        await self._maybe_extract_continuity(scene_card, final_prose)

        # Architecture upgrade Slice 5 — apply declared relationship deltas.
        # Scene cards are the source of truth (spec §9.1 declarative model).
        self._maybe_apply_relationship_deltas(scene_card)

        # Phase 4: Post-chapter physics validation
        physics_post = None
        if self.physics_enforcer:
            physics_post = self.physics_enforcer.validate_post_chapter(
                scene_card, final_prose, chapter_num
            )
            self.ledger.emit(
                "physics_validation_post",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={"passed": physics_post["passed"], "issue_count": len(physics_post["issues"])},
            )
            if physics_post["issues"]:
                print(f"  [P4] Physics post-check: {len(physics_post['issues'])} issue(s)")

        # Phase 2: Post-save processing
        summary_text = None
        contradiction_flags = []
        if self.summarizer:
            summary_text, contradiction_flags = await self._run_post_save(
                scene_card, final_prose, evaluation,
                polish_rejected=polish_rejected,
            )

        # Phase 3: Character Specialist (supplementary, after Phase 2)
        character_analysis = None
        if self.character_specialist:
            print("  [P3-3] Character specialist running...")
            char_context = {
                "prose": final_prose,
                "scene_card": scene_card,
                "character_voices": self.assembler.get_character_voices(
                    scene_card.get("characters_present", [])
                ),
                "character_knowledge": "",
                "character_profiles": self._get_character_profiles(scene_card),
            }
            try:
                character_analysis = await self.character_specialist.run(char_context)
                print(f"    Character verdict: {character_analysis['verdict']}")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"    Character specialist: parse error ({e.__class__.__name__}) — skipping")
                character_analysis = None

        # Phase 4: LLM-as-Judge evaluation
        judge_evaluation = None
        if self.judge_evaluator:
            print("  [P4] LLM Judge evaluating...")
            judge_evaluation = await self.judge_evaluator.evaluate_chapter({
                "prose": final_prose,
                "scene_card": scene_card,
            })
            self.ledger.emit(
                "judge_evaluation",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={"overall_score": judge_evaluation.get("overall_score", 0)},
            )
            print(f"    Judge score: {judge_evaluation.get('overall_score', 0):.1f}/10")

        result = {
            "chapter_number": chapter_num,
            "scene_number": scene_num,
            "output_path": str(output_path),
            "evaluation": evaluation,
            "word_count": len(final_prose.split()),
        }

        if summary_text:
            result["summary"] = summary_text
        if contradiction_flags:
            result["contradiction_flags"] = contradiction_flags
        if final_gate_result is not None:
            result["final_gate"] = final_gate_result
        if continuity_report is not None:
            result["continuity_report"] = continuity_report
        if polish_rejected:
            result["polish_rejected"] = True
            result["polish_rejection_reason"] = rejection_reason
        if quality_metrics:
            result["quality_metrics"] = quality_metrics
        if character_analysis:
            result["character_analysis"] = character_analysis
        if physics_pre:
            result["physics_pre"] = physics_pre
        if physics_post:
            result["physics_post"] = physics_post
        if judge_evaluation:
            result["judge_evaluation"] = judge_evaluation

        # Phase 3: Milestone Gate check (at the very end)
        if self.milestone_gates:
            milestone_info = self.milestone_gates.check(scene_card)
            if milestone_info:
                result["milestone"] = milestone_info
                if not milestone_info.get("continue", True):
                    result["milestone_abort"] = True

        return result

    async def _run_post_save(
        self,
        scene_card: dict,
        prose: str,
        evaluation: dict,
        *,
        polish_rejected: bool = False,
    ) -> tuple[Optional[str], list[dict]]:
        """Phase 2 post-save processing: summarize, update state, scan."""
        chapter_num = scene_card["chapter_number"]
        scene_num = scene_card.get("scene_number", 1)
        summary_text = None
        contradiction_flags = []

        # Step 5: Summarizer produces summary + state diff
        print("  [P2-1] Summarizer running...")
        start = time.time()
        self.ledger.emit(
            "agent_start",
            chapter_number=chapter_num,
            scene_number=scene_num,
            agent_role="summarizer",
        )

        summarizer_context = {
            "prose": prose,
            "scene_card": scene_card,
        }
        # Inject current story state so the Summarizer can produce accurate old_value fields
        if self.story_state:
            summarizer_context["state_snapshot"] = self.story_state.get_state_snapshot()
            # Build arc state guidance so the Summarizer knows valid next phases
            arc_lines = []
            for arc in self.story_state.get_all_character_arcs():
                char_id = arc["character_id"]
                current = arc["current_phase"]
                valid = self.story_state.get_valid_next_phases(char_id)
                arc_lines.append(f"- {char_id}: currently '{current}', valid next: {valid}")
            if arc_lines:
                summarizer_context["arc_state_guidance"] = "\n".join(arc_lines)
        # Include any rejected transitions from prior scenes
        if hasattr(self, "_rejected_transitions") and self._rejected_transitions:
            summarizer_context["rejected_transitions"] = self._rejected_transitions
            self._rejected_transitions = []

        summary_result = await self.summarizer.run(summarizer_context)

        duration_ms = int((time.time() - start) * 1000)
        self.ledger.emit(
            "summarizer_complete",
            chapter_number=chapter_num,
            scene_number=scene_num,
            agent_role="summarizer",
            payload={"duration_ms": duration_ms},
        )

        summary_text = summary_result.get("summary", "")
        state_diff = summary_result.get("state_diff", {})
        established_concepts = summary_result.get("established_concepts", [])

        # Validate summarizer output completeness
        if not summary_text:
            print(f"  [WARN] Summarizer returned empty summary — downstream context will be degraded")
        if not state_diff or not state_diff.get("changes"):
            print(f"  [WARN] Summarizer returned empty state_diff — story state will not update")
        if not established_concepts:
            print(f"  [WARN] Summarizer returned no established_concepts — concept maturity tracking inactive for this scene")

        # Step 6: Store summary in ChromaDB
        if self.chapter_memory and summary_text:
            meta = {
                "structural_phase": scene_card.get("structural_phase", ""),
                "pov_character": scene_card.get("pov_character", ""),
            }
            # Store established concepts as JSON string in metadata
            if established_concepts:
                meta["established_concepts"] = json.dumps(established_concepts)
            self.chapter_memory.add_summary(
                chapter_num,
                summary_text,
                metadata=meta,
                scene_number=scene_num,
            )
            print(f"  [P2-2] Summary stored in ChromaDB")

        # Step 7: Apply state diff to SQLite
        if self.state_diff_applier and state_diff.get("changes"):
            self.state_diff_applier.apply_diff(state_diff, chapter_num, scene_num, scene_card=scene_card)
            # Capture rejected transitions for Summarizer feedback on next scene
            rejected = getattr(self.state_diff_applier, "last_rejected_transitions", [])
            if rejected:
                if not hasattr(self, "_rejected_transitions"):
                    self._rejected_transitions = []
                self._rejected_transitions.extend(rejected)
            print(f"  [P2-3] State diff applied")

        # Step 8: Update chapter log and scene log
        if self.story_state:
            scores = {
                "structural": evaluation.get("structural_score", 0),
                "voice": evaluation.get("voice_score", 0),
                "polish": evaluation.get("polish_score", 0),
            }
            failure_codes = [
                fc["code"] for fc in evaluation.get("failure_codes", [])
            ]
            word_count = len(prose.split())
            # Relay v3 (Stage 1i) — status vocabulary collapsed to three
            # saved-scene states:
            #   - 'saved_clean'          — all gates green
            #   - 'saved_with_advisory'  — any gate fired advisory-level signal
            #   - 'quarantined'          — scene blocked pre-save (not written
            #                              through this path; reserved for
            #                              manual quarantine flags)
            #
            # Scene-gate verdict drives the distinction: any non-pass verdict
            # (fail_*, skipped) plus any polish_rejected flag degrades the
            # save to 'saved_with_advisory'. --raw-draft saves as
            # 'saved_clean' because the user explicitly opted out of gates.
            advisory_fired = (
                polish_rejected
                or (not self.raw_draft and evaluation.get("verdict") != "pass")
            )
            if advisory_fired:
                revision_status = "saved_with_advisory"
            else:
                revision_status = "saved_clean"
            self.story_state.add_chapter_log(
                chapter_number=chapter_num,
                word_count=word_count,
                structural_phase=scene_card.get("structural_phase", ""),
                pov_character=scene_card.get("pov_character", ""),
                summary=summary_text,
                quality_scores=scores,
                failure_codes=failure_codes,
                revision_status=revision_status,
            )
            self.story_state.add_scene_log(
                chapter_number=chapter_num,
                scene_number=scene_num,
                word_count=word_count,
                structural_phase=scene_card.get("structural_phase", ""),
                pov_character=scene_card.get("pov_character", ""),
                summary=summary_text,
                quality_scores=scores,
                failure_codes=failure_codes,
                revision_status=revision_status,
            )
            print(f"  [P2-4] Chapter/scene log updated")

        # Step 9: Contradiction scanner
        if self.contradiction_scanner:
            contradiction_flags = self.contradiction_scanner.scan(
                chapter_num, prose, scene_card, scene_num
            )
            if contradiction_flags:
                print(
                    f"  [P2-5] Contradiction scanner: "
                    f"{len(contradiction_flags)} flag(s)"
                )
            else:
                print(f"  [P2-5] Contradiction scanner: clean")

        # Step 10: Worldbuilding extraction (if enabled)
        if (self.lore_service and self._worldbuilding_auto_extract
                and self._universe_id and self._project_id):
            import logging as _log
            _logger = _log.getLogger(__name__)
            try:
                new_entry_ids = await self.lore_service.extract_worldbuilding_from_chapter(
                    chapter_text=prose,
                    scene_card=scene_card,
                    universe_id=self._universe_id,
                    project_id=self._project_id,
                    router=self.router,
                )
                if new_entry_ids:
                    print(f"  [WB] Extracted {len(new_entry_ids)} provisional lore entries")
                else:
                    print(f"  [WARN] Worldbuilding extraction returned 0 entries — check lore_extractor JSON parsing or universe FK")
            except Exception as e:
                print(f"  [WARN] Worldbuilding extraction failed: {e.__class__.__name__}: {e}")
                _logger.warning("Worldbuilding extraction failed: %s", e)
                new_entry_ids = []

            # Step 10b (Phase 7.2): conflict detection on the new provisional
            # entries. Advisory-by-default — flags go to the run ledger under
            # event `lore_conflicts`; strict mode (`--strict-lore`) promotes
            # severity=high flags to blocking, which _run_post_save surfaces
            # via the `contradiction_flags` return value.
            if new_entry_ids:
                try:
                    from src.worldbuilding.lore_conflict_detector import (
                        LoreConflictDetector,
                    )
                    concept_seed = getattr(self.assembler, "concept_seed", {}) or {}
                    canon_profile = concept_seed.get("canon_profile")
                    detector = LoreConflictDetector(
                        self.lore_service, canon_profile=canon_profile,
                    )
                    scan = detector.scan_provisional_batch(
                        entry_ids=new_entry_ids,
                        universe_id=self._universe_id,
                    )
                    if scan.flags:
                        print(
                            f"  [WB] LoreConflictDetector: "
                            f"{len(scan.flags)} flag(s) "
                            f"({len(scan.high_severity_flags)} high)"
                        )
                    self.ledger.emit(
                        "lore_conflicts",
                        chapter_number=chapter_num,
                        scene_number=scene_num,
                        payload={
                            "flag_count": len(scan.flags),
                            "high_severity_count": len(scan.high_severity_flags),
                            "flags": scan.to_payload(),
                            "strict_mode": self._strict_lore,
                        },
                    )
                    if self._strict_lore and scan.high_severity_flags:
                        # In strict mode, promote high-severity lore flags to
                        # the scene's contradiction_flags list so the caller's
                        # gate-loop treats them as blocking.
                        for f in scan.high_severity_flags:
                            contradiction_flags.append({
                                "source": "lore_conflict_detector",
                                "entry_id": f.entry_id,
                                "conflict_type": f.conflict_type,
                                "severity": f.severity,
                                "rationale": f.rationale,
                            })
                except Exception as e:
                    print(
                        f"  [WARN] Lore conflict scan failed: "
                        f"{e.__class__.__name__}: {e}"
                    )
                    _logger.warning("Lore conflict scan failed: %s", e)

        return summary_text, contradiction_flags

    async def _run_plot_architect(self, scene_card: dict) -> dict:
        """Run the Plot Architect to generate a typed generation brief.

        Returns a dict matching schemas/generation_brief.json. The agent uses
        `complete_structured` for JSON output with one retry on parse failure.
        """
        start = time.time()
        self.ledger.emit(
            "agent_start",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="plot_architect",
        )

        pa_context = {
            "scene_card": scene_card,
            "bible_summary": self.assembler.get_bible_summary(),
        }

        # Previous chapter summary so the brief has narrative continuity
        if self.chapter_memory:
            prev_summary = self.chapter_memory.get_recent_summaries(n=2)
            if prev_summary and "No previous" not in prev_summary:
                pa_context["previous_chapter_summary"] = prev_summary

        # Inject current character state for more accurate scene briefs
        if self.story_state:
            snapshot = self.story_state.get_state_snapshot()
            # Format character states as context
            char_lines = []
            for c in snapshot.get("characters", []):
                arc_info = ""
                if c.get("arc"):
                    arc_info = f" | arc: {c['arc']['arc_type']} @ {c['arc']['current_phase']}"
                char_lines.append(
                    f"- {c['name']} ({c['id']}): "
                    f"location={c.get('current_location', 'unknown')}, "
                    f"emotional_state={c.get('emotional_state', 'unknown')}{arc_info}"
                )
            if char_lines:
                pa_context["arc_context"] = "## Current Character States\n" + "\n".join(char_lines)

        # Hook agenda — which hooks to plant, advance, or resolve in this scene
        chapter_num = scene_card.get("chapter_number", 1)
        hook_agenda = self.assembler._assemble_hook_agenda(chapter_num)
        if hook_agenda:
            pa_context["hook_agenda"] = hook_agenda

        # Active subplots relevant to this scene
        subplot_context = self.assembler._assemble_subplot_context(scene_card)
        if subplot_context:
            pa_context["subplot_context"] = subplot_context

        # Franchise profile (system-level register + canonical rules)
        pa_context["franchise_profile_text"] = self.assembler.get_franchise_profile_text()

        result = await self.plot_architect.run(pa_context)
        brief = result["generation_brief"]

        duration_ms = int((time.time() - start) * 1000)
        # Log observability fields — target word count + truncated scene objective.
        # Full brief is too large for the ledger; key fields surface drift.
        scene_objective = brief.get("scene_objective", "") if isinstance(brief, dict) else ""
        self.ledger.emit(
            "agent_complete",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="plot_architect",
            payload={
                "duration_ms": duration_ms,
                "target_word_count": brief.get("target_word_count") if isinstance(brief, dict) else None,
                "scene_objective": scene_objective[:160] if scene_objective else "",
            },
        )

        return brief

    # ------------------------------------------------------------------
    # Slice 2 chapter-packet helpers. When the flag is off these are no-ops
    # that return None and the drafter path falls back to flat assembly.
    # ------------------------------------------------------------------
    def _maybe_compile_base(self, chapter_number: int) -> None:
        """Build and persist the per-chapter packet base on first entry.

        Idempotent: subsequent scenes in the same chapter reuse the cached
        base. Safe to call unconditionally — guarded by the enabled flag.
        """
        if not self._chapter_packet_enabled:
            return
        if chapter_number in self._chapter_packet_bases:
            return
        try:
            base = self.chapter_packet_compiler.compile_base(chapter_number=chapter_number)
        except Exception as exc:  # noqa: BLE001
            self.ledger.emit_warn(
                "packet_fallback_flat",
                chapter_number=chapter_number,
                payload={"stage": "compile_base", "error": f"{type(exc).__name__}: {exc}"},
            )
            if not self._chapter_packet_fallback_on_error:
                raise
            return

        self._chapter_packet_bases[chapter_number] = base

        # Persist the base so debug/inspection has a single inspectable
        # contract per chapter (spec §6.1.1). Non-fatal on IO errors.
        try:
            self._packets_dir.mkdir(parents=True, exist_ok=True)
            path = self._packets_dir / f"chapter_{chapter_number:02d}.json"
            path.write_text(json.dumps(base.to_json(), indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        rendered = base.render_markdown()
        token_count = len(rendered.split())
        self.ledger.emit_info(
            "packet_base_compiled",
            chapter_number=chapter_number,
            payload={"chapter_number": chapter_number, "token_count": token_count},
        )

    def _maybe_compile_overlay(self, scene_card: dict) -> Optional[dict]:
        """Compile the per-scene overlay packet. Returns a dict (packet.to_json
        plus rendered_markdown) or None when the flag is off or fallback fired.
        """
        if not self._chapter_packet_enabled:
            return None
        chapter_number = scene_card.get("chapter_number")
        if chapter_number is None:
            return None
        self._maybe_compile_base(chapter_number)
        base = self._chapter_packet_bases.get(chapter_number)
        if base is None:
            # compile_base fell back; overlay cannot proceed.
            return None
        scene_number = scene_card.get("scene_number", 1)
        try:
            overlay = self.chapter_packet_compiler.compile_overlay(
                base=base,
                scene_card=scene_card,
                trusted_state_snapshot={
                    "chapter_number": chapter_number,
                    "scene_number": scene_number,
                },
            )
        except Exception as exc:  # noqa: BLE001
            self.ledger.emit_warn(
                "packet_fallback_flat",
                chapter_number=chapter_number,
                scene_number=scene_number,
                payload={
                    "stage": "compile_overlay",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            if not self._chapter_packet_fallback_on_error:
                raise
            return None

        try:
            self._packets_dir.mkdir(parents=True, exist_ok=True)
            path = (
                self._packets_dir
                / f"chapter_{chapter_number:02d}_sc_{scene_number:02d}_overlay.json"
            )
            path.write_text(json.dumps(overlay.to_json(), indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        rendered = overlay.rendered_markdown or overlay.render_markdown()
        token_count = len(rendered.split())
        self.ledger.emit_info(
            "packet_overlay_written",
            chapter_number=chapter_number,
            scene_number=scene_number,
            payload={
                "chapter_number": chapter_number,
                "scene_number": scene_number,
                "overlay_version": overlay.overlay_version,
                "token_count": token_count,
            },
        )
        payload = overlay.to_json()
        payload["rendered_markdown"] = rendered
        return payload

    # ------------------------------------------------------------------
    # Slice 3 promise-ledger hook. Called from save path *after* _save_chapter
    # so a blocker-quarantined scene never writes to the ledger. No-op when
    # the flag is off or no ledger was attached.
    # ------------------------------------------------------------------
    def _maybe_record_promise_deltas(self, scene_card: dict) -> None:
        if not self._promise_ledger_enabled:
            return
        chapter_number = scene_card.get("chapter_number")
        scene_number = scene_card.get("scene_number", 1)
        if chapter_number is None:
            return
        scene_id = f"ch{int(chapter_number):02d}_sc{int(scene_number):02d}"

        for pid in scene_card.get("promises_progressed") or []:
            try:
                self.promise_ledger.record_progression(
                    promise_id=pid, scene_id=scene_id, source="scene_card",
                )
            except KeyError:
                # Unknown promise_id \u2014 planning drift. Warn but don't abort.
                self.ledger.emit_warn(
                    "promise_progressed",
                    chapter_number=chapter_number, scene_number=scene_number,
                    payload={"promise_id": pid, "status": "unknown_promise_id"},
                )
                continue
            self.ledger.emit_info(
                "promise_progressed",
                chapter_number=chapter_number, scene_number=scene_number,
                payload={"promise_id": pid, "scene_id": scene_id},
            )

        for pid in scene_card.get("promises_paid") or []:
            try:
                self.promise_ledger.record_payoff(
                    promise_id=pid, scene_id=scene_id,
                )
            except KeyError:
                self.ledger.emit_warn(
                    "promise_paid",
                    chapter_number=chapter_number, scene_number=scene_number,
                    payload={"promise_id": pid, "status": "unknown_promise_id"},
                )
                continue
            self.ledger.emit_info(
                "promise_paid",
                chapter_number=chapter_number, scene_number=scene_number,
                payload={"promise_id": pid, "scene_id": scene_id},
            )

        # After the scene lands, surface any *newly* overdue promises as
        # advisory warnings so the human operator sees the slipping promise
        # without the drafter being forced into payoff (spec \u00a77.3).
        try:
            overdue = self.promise_ledger.list_overdue(at_scene=scene_id)
        except Exception:  # noqa: BLE001
            overdue = []
        for entry in overdue:
            self.ledger.emit_warn(
                "promise_overdue",
                chapter_number=chapter_number, scene_number=scene_number,
                payload={
                    "promise_id": entry.get("promise_id"),
                    "due_by_scene": entry.get("due_by_scene"),
                    "overdue_by_scenes": entry.get("overdue_by_scenes"),
                },
            )

    # ------------------------------------------------------------------
    # Slice 4 continuity-extractor hook. Called post-save so quarantined
    # scenes never produce trusted events. Suppressed rows go nowhere
    # except a warn-count telemetry event.
    # ------------------------------------------------------------------
    async def _maybe_extract_continuity(self, scene_card: dict, prose: str) -> None:
        if not self._continuity_log_enabled:
            return
        chapter_number = scene_card.get("chapter_number")
        scene_number = scene_card.get("scene_number", 1)
        if chapter_number is None or not prose:
            return
        try:
            concept_seed = getattr(self.assembler, "concept_seed", {}) or {}
        except Exception:  # noqa: BLE001
            concept_seed = {}
        try:
            events = await self.continuity_extractor.extract(
                prose=prose, scene_card=scene_card, concept_seed=concept_seed,
            )
        except Exception as exc:  # noqa: BLE001
            self.ledger.emit_warn(
                "continuity_extractor_error",
                chapter_number=chapter_number, scene_number=scene_number,
                payload={"error": f"{type(exc).__name__}: {exc}"},
            )
            return

        threshold = float(self._continuity_min_confidence)
        trusted: list[dict] = []
        suppressed: list[dict] = []
        for ev in events or []:
            conf = float(ev.get("confidence", 0.0))
            if conf >= threshold:
                trusted.append(ev)
            else:
                suppressed.append(ev)

        for ev in trusted:
            try:
                event_id = self.continuity_log.append(ev)
            except Exception as exc:  # noqa: BLE001
                # Store-rejected row \u2014 log as warn-count but do not raise.
                self.ledger.emit_warn(
                    "continuity_extractor_error",
                    chapter_number=chapter_number, scene_number=scene_number,
                    payload={
                        "error": f"append-rejected: {type(exc).__name__}: {exc}",
                        "event_type": ev.get("event_type"),
                    },
                )
                continue
            self.ledger.emit_info(
                "continuity_event_recorded",
                chapter_number=chapter_number, scene_number=scene_number,
                payload={
                    "event_id": event_id,
                    "event_type": ev.get("event_type"),
                    "subject": ev.get("subject"),
                    "confidence": ev.get("confidence"),
                },
            )

        if suppressed:
            # Spec \u00a78.3.2: only a count lands \u2014 no event content, no
            # per-row payload. Hallucinations stay invisible downstream.
            self.ledger.emit_warn(
                "continuity_events_suppressed",
                chapter_number=chapter_number, scene_number=scene_number,
                payload={
                    "count": len(suppressed),
                    "threshold": threshold,
                    "extractor_version": events[0].get("extractor_version")
                    if events else None,
                },
            )

    # ------------------------------------------------------------------
    # Slice 5 sociogram hook. Called post-save so quarantined scenes never
    # shift relationship state. No-op when flag off or no store attached.
    # ------------------------------------------------------------------
    def _maybe_apply_relationship_deltas(self, scene_card: dict) -> None:
        if not self._sociogram_enabled:
            return
        try:
            updates = self.sociogram.apply_scene_deltas(scene_card=scene_card)
        except Exception as exc:  # noqa: BLE001
            # Sociogram failure is advisory \u2014 do not abort the scene save.
            self.ledger.emit_warn(
                "sociogram_delta_applied",
                chapter_number=scene_card.get("chapter_number"),
                scene_number=scene_card.get("scene_number", 1),
                payload={"error": f"{type(exc).__name__}: {exc}"},
            )
            return
        chapter_number = scene_card.get("chapter_number")
        scene_number = scene_card.get("scene_number", 1)
        for update in updates:
            self.ledger.emit_info(
                "sociogram_delta_applied",
                chapter_number=chapter_number, scene_number=scene_number,
                payload={
                    "edge_id": update.get("edge_id"),
                    "trust": update.get("trust"),
                    "warmth": update.get("warmth"),
                    "power_balance": update.get("power_balance"),
                },
            )

    async def _run_prose_stylist(
        self,
        scene_card: dict,
        generation_brief: dict,
        failure_context: Optional[str] = None,
    ) -> str:
        """Run the Prose Stylist to draft prose.

        `generation_brief` is a dict matching schemas/generation_brief.json.
        """
        start = time.time()
        self.ledger.emit(
            "agent_start",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="prose_stylist",
        )

        assembled_context = self.assembler.assemble(scene_card)

        # Slice 2: build the chapter packet overlay for this scene when the
        # flag is on. The packet renderer embeds a flat-context snapshot so
        # the drafter prompt remains a token-superset of the legacy flat path.
        # On any failure, emit packet_fallback_flat and fall back to
        # assembled_context — runtime.chapter_packet.fallback_on_error gates
        # whether a raise bubbles up when fallback is not wanted.
        chapter_packet = self._maybe_compile_overlay(scene_card)

        # Build dynamic cross-scene feedback. The base banned-phrase list
        # from config/negative_constraints.yaml is already baked into
        # assembled_context — we only build the *dynamic* addendum here.
        dynamic_parts = []
        if hasattr(self, "_chapter_overused_words") and self._chapter_overused_words:
            dynamic_parts.append(
                f"Avoid overusing these words (flagged in prior scenes): "
                f"{', '.join(sorted(self._chapter_overused_words))}."
            )
        if hasattr(self, "_scene_description_ratios") and self._scene_description_ratios:
            avg_desc = sum(self._scene_description_ratios) / len(self._scene_description_ratios)
            if avg_desc > 0.55:
                dynamic_parts.append(
                    f"Prior scenes averaged {int(avg_desc * 100)}% description/interiority. "
                    "Increase dialogue and action beats. Avoid long unbroken passages of interiority or observation."
                )
        dynamic_feedback = "\n\n".join(dynamic_parts)

        prose_context = {
            "generation_brief": generation_brief,
            "assembled_context": assembled_context,
            "dynamic_feedback": dynamic_feedback,
            "failure_context": failure_context or "",
            "scene_card": scene_card,
            "pov_approach": self.assembler.get_pov_approach(),
            "franchise_profile_text": self.assembler.get_franchise_profile_text(),
        }
        if chapter_packet is not None:
            # Only attach when the overlay compiled cleanly. The absence of
            # this key is the signal to ProseStylist._format_context to use
            # the flat assembled_context path (spec §6.1.4 precedence rule).
            prose_context["chapter_packet"] = chapter_packet
        result = await self.prose_stylist.run(prose_context)

        duration_ms = int((time.time() - start) * 1000)
        self.ledger.emit(
            "agent_complete",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="prose_stylist",
            payload={"duration_ms": duration_ms, "word_count": len(result["prose"].split())},
        )

        return result["prose"]

    async def _run_line_writer(
        self,
        scene_card: dict,
        generation_brief: dict,
        source_prose: str,
    ) -> str:
        """Run the LineWriter pass between drafter and gate_critic.

        Preservation-critical context (scene_card, generation_brief,
        characters_present, franchise_profile_text, pov_approach) is passed
        EXPLICITLY — the agent does not reach back into the ambient assembler
        for those. Failures degrade to the source prose with a warn-level
        ledger event; they never block the pipeline.
        """
        chapter_num = scene_card["chapter_number"]
        scene_num = scene_card.get("scene_number", 1)
        start = time.time()
        print("  [2.5/5] Line Writer editing...")
        self.ledger.emit(
            "agent_start",
            chapter_number=chapter_num,
            scene_number=scene_num,
            agent_role="line_writer",
        )

        try:
            result = await self.line_writer.run({
                "source_prose": source_prose,
                "scene_card": scene_card,
                "generation_brief": generation_brief,
                "characters_present": scene_card.get("characters_present", []),
                "pov_approach": self.assembler.get_pov_approach(),
                "franchise_profile_text": self.assembler.get_franchise_profile_text(),
            })
            revised = result.get("prose", "") or ""
        except Exception as e:
            print(
                f"    Line Writer: error ({e.__class__.__name__}) — "
                f"keeping drafter output"
            )
            self.ledger.emit_warn(
                "line_writer_error",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={"error_class": e.__class__.__name__, "error": str(e)},
            )
            return source_prose

        # Guardrail: if the edit collapsed below a sane floor, keep the
        # drafter prose rather than saving a degraded scene. 40% is a wide
        # lower bound — most edits land in the 70-110% range of source word
        # count. Below 40% is almost certainly a model failure (partial
        # output, refusal, or collapsed-to-summary).
        source_wc = len(source_prose.split())
        revised_wc = len(revised.split())
        if source_wc and revised_wc < 0.40 * source_wc:
            pct = (revised_wc / source_wc * 100) if source_wc else 0
            print(
                f"    Line Writer: output at {pct:.0f}% of source "
                f"({revised_wc}/{source_wc} words) — falling back to drafter"
            )
            self.ledger.emit_warn(
                "line_writer_collapsed",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={
                    "source_word_count": source_wc,
                    "revised_word_count": revised_wc,
                    "ratio": revised_wc / source_wc if source_wc else 0,
                },
            )
            return source_prose

        duration_ms = int((time.time() - start) * 1000)
        self.ledger.emit(
            "agent_complete",
            chapter_number=chapter_num,
            scene_number=scene_num,
            agent_role="line_writer",
            payload={
                "duration_ms": duration_ms,
                "source_word_count": source_wc,
                "revised_word_count": revised_wc,
            },
        )
        return revised

    async def _gate_loop(
        self,
        scene_card: dict,
        prose: str,
        generation_brief: dict,
    ) -> tuple[dict, str]:
        """Run the Gate Critic once as telemetry; return the original prose.

        Method name is historical. Under the forward-only relay there is no
        loop and no retries — Gate Critic evaluates the draft exactly once and
        its verdict is logged to the ledger. The prose is returned unchanged;
        downstream stages (metrics, polish, final gate, canon expert) always
        proceed. `generation_brief` is the typed dict from Plot Architect,
        kept in the signature for future reuse but currently unused in the
        forward-only path.
        """
        if self.skip_gate_loop:
            # Accept the first draft without running gate_critic at all.
            # Synthesize a "skipped" evaluation compatible with downstream
            # consumers (all score accesses use .get() with defaults).
            chapter_num = scene_card["chapter_number"]
            scene_num = scene_card.get("scene_number", 1)
            print(f"  [3/5] Gate Critic skipped (--skip-gate-loop)")
            self.ledger.emit(
                "gate_critic_skipped",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={"reason": "skip_gate_loop flag"},
            )
            evaluation = {
                "verdict": "skipped",
                "structural_score": None,
                "voice_score": None,
                "polish_score": None,
                "failure_codes": [],
                "severity": None,
                "route_to": None,
            }
            return evaluation, prose

        # Relay v1 (Stage 1a): Gate Critic runs ONCE as telemetry.
        # No retries — the pipeline is forward-only. Gate findings are logged
        # to the ledger so humans can review; they do not control save flow.
        # Failed verdicts get advisory logs; the original prose is always
        # returned and the pipeline proceeds to copy editor / save-blocker.
        chapter_num = scene_card["chapter_number"]
        scene_num = scene_card.get("scene_number", 1)
        attempt_id = f"ch{chapter_num}_scene{scene_num}_gate"

        start = time.time()
        self.ledger.emit(
            "agent_start",
            chapter_number=chapter_num,
            scene_number=scene_num,
            agent_role="gate_critic",
            attempt_id=attempt_id,
        )

        try:
            evaluation = await self.gate_critic.run({
                "prose": prose,
                "scene_card": scene_card,
                "bible_summary": self.assembler.get_bible_summary(),
            })
        except (json.JSONDecodeError, KeyError) as e:
            # JSON parse failure — emit an advisory and synthesize a neutral evaluation.
            # Under the relay we do not retry; downstream stages handle the prose as-is.
            print(f"    Gate: JSON parse error ({e.__class__.__name__}) — continuing without verdict (advisory)")
            evaluation = {
                "verdict": "skipped",
                "failure_codes": [{"code": "JSON_PARSE_ERROR", "location": "gate_critic", "description": str(e), "fix_hint": "N/A under forward-only relay"}],
                "severity": None,
                "route_to": None,
                "structural_score": None,
                "voice_score": None,
                "polish_score": None,
            }

        duration_ms = int((time.time() - start) * 1000)
        self.ledger.emit(
            "agent_complete",
            chapter_number=chapter_num,
            scene_number=scene_num,
            agent_role="gate_critic",
            payload={"duration_ms": duration_ms},
            attempt_id=attempt_id,
        )

        verdict = evaluation.get("verdict", "unknown")
        s_score = evaluation.get("structural_score") or 0
        v_score = evaluation.get("voice_score") or 0
        p_score = evaluation.get("polish_score") or 0
        fc_codes = [fc["code"] for fc in evaluation.get("failure_codes", [])]

        # Single telemetry event. Event-type names are left as-is in Stage 1a;
        # vocabulary migration lands in Stage 1i.
        event_type = "gate_pass" if verdict == "pass" else "gate_fail"
        self.ledger.emit(
            event_type,
            chapter_number=chapter_num,
            scene_number=scene_num,
            payload={
                "verdict": verdict,
                "scores": {
                    "structural": s_score,
                    "voice": v_score,
                    "polish": p_score,
                },
                "failure_codes": fc_codes,
                "forward_only": True,
            },
            attempt_id=attempt_id,
        )
        if fc_codes:
            print(f"    Gate: {verdict} | structural={s_score:.2f} voice={v_score:.2f} polish={p_score:.2f} | {', '.join(fc_codes)} (advisory — no retry)")
        else:
            print(f"    Gate: {verdict} | structural={s_score:.2f} voice={v_score:.2f} polish={p_score:.2f}")

        # Slice 2: one debt row per non_blocking failure code. Noop when flag off.
        from src.pipeline.revision_debt_producers import emit_gate_critic_advisory
        scope = {
            "level": "scene",
            "chapter_number": chapter_num,
            "scene_number": scene_num,
        }
        for fc in evaluation.get("failure_codes", []) or []:
            # Gate critic emits three severities {blocker, non_blocking, advisory}.
            # Only non-pass verdicts with structured codes need rows; severity
            # mapping happens in the producer wrapper.
            emit_gate_critic_advisory(
                self._active_debt_store,
                ledger=self.ledger,
                scope=scope,
                failure=fc,
            )

        # Forward-only: always return the original prose regardless of verdict.
        return evaluation, prose

    def _format_failure_context(self, evaluation: dict) -> str:
        """Format failure codes into revision notes for the Prose Stylist."""
        lines = ["The previous draft was rejected for the following reasons:\n"]
        for fc in evaluation.get("failure_codes", []):
            lines.append(f"**{fc['code']}** at {fc.get('location', 'unspecified')}:")
            lines.append(f"  {fc['description']}")
            if fc.get("fix_hint"):
                lines.append(f"  Fix: {fc['fix_hint']}")
            lines.append("")
        return "\n".join(lines)

    def _save_chapter(self, chapter_num: int, scene_num: int, prose: str) -> Path:
        """Save the final prose to a markdown file."""
        filename = f"chapter_{chapter_num:02d}_scene_{scene_num:02d}.md"
        output_path = self.manuscripts_dir / filename
        output_path.write_text(prose, encoding="utf-8")
        return output_path

    def _load_prior_chapters(self, current_chapter: int) -> list[str]:
        """Load prose from prior chapters for cross-chapter analysis."""
        prior = []
        for ch in range(max(1, current_chapter - 3), current_chapter):
            # Load all scenes of each prior chapter
            pattern = f"chapter_{ch:02d}_scene_*.md"
            scene_files = sorted(self.manuscripts_dir.glob(pattern))
            for sf in scene_files:
                prior.append(sf.read_text(encoding="utf-8"))
        return prior

    def _get_prior_summary(self, scene_card: dict) -> str:
        """Get a summary of recent chapters for revision context."""
        chapter_num = scene_card.get("chapter_number", 1)
        if self.chapter_memory:
            recent = self.chapter_memory.get_recent_summaries(n=2)
            if recent and "No previous" not in recent:
                return recent
        # Fallback: truncated tail of previous chapter prose
        prev = self.assembler.get_previous_scene(chapter_num, 1)
        if prev:
            return prev[-1500:] if len(prev) > 1500 else prev
        return ""

    def _get_pov_voice_notes(self, scene_card: dict) -> str:
        """Extract POV character's voice notes from the concept seed."""
        pov = scene_card.get("pov_character", "")
        if not pov:
            return ""
        # Try to get voice notes via context assembler
        voices = self.assembler.get_character_voices([pov])
        return voices

    def _get_character_profiles(self, scene_card: dict) -> list[dict]:
        """Get character profiles for present characters from concept seed."""
        characters_present = scene_card.get("characters_present", [])
        if not characters_present or not hasattr(self.assembler, 'concept_seed'):
            return []

        profiles = []
        cast = self.assembler.concept_seed.get("ensemble_cast", [])
        for char in cast:
            if char.get("name") in characters_present:
                profiles.append(char)
        return profiles
