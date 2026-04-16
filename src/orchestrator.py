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
from typing import Callable, Optional, TYPE_CHECKING

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
    from src.agents.summarizer import Summarizer
    from src.memory.chapter_memory import ChapterMemory
    from src.memory.contradiction_scanner import ContradictionScanner
    from src.memory.state_diff import StateDiffApplier
    from src.memory.story_state import StoryState
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
        raw_draft: bool = False,
    ):
        self.router = router
        self.assembler = context_assembler
        self.ledger = ledger
        self.manuscripts_dir = Path(manuscripts_dir)
        self.manuscripts_dir.mkdir(parents=True, exist_ok=True)
        self.max_structural_retries = max_structural_retries
        self.max_voice_retries = max_voice_retries
        self.raw_draft = raw_draft

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

    @staticmethod
    def _is_last_scene_in_chapter(current_index: int, sorted_cards: list[dict]) -> bool:
        """Check if the current card is the last scene in its chapter."""
        if current_index >= len(sorted_cards) - 1:
            return True  # Last card overall
        current_ch = sorted_cards[current_index]["chapter_number"]
        next_ch = sorted_cards[current_index + 1]["chapter_number"]
        return current_ch != next_ch

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

        try:
            for i, scene_card in enumerate(active_cards):
                chapter_num = scene_card["chapter_number"]
                scene_num = scene_card.get("scene_number", 1)
                print(f"\n{'='*60}")
                print(f"Chapter {chapter_num}, Scene {scene_num}")
                print(f"{'='*60}")

                result = await self.run_chapter(scene_card)
                results.append(result)

                # Phase 4: Save session progress after each chapter
                if self.pipeline_session and self.session_id:
                    self.pipeline_session.mark_chapter_complete(
                        self.session_id, chapter_num, scene_num, result
                    )

                # Chapter-level gate: run after last scene in chapter
                if self.chapter_gate_critic and self._is_last_scene_in_chapter(i, active_cards):
                    ch_cards = [c for c in active_cards if c["chapter_number"] == chapter_num]
                    ch_results = [r for r in results if r.get("chapter_number") == chapter_num]
                    ch_eval = await self._run_chapter_gate(chapter_num, ch_cards, ch_results)
                    results[-1]["chapter_gate"] = ch_eval
                    if not ch_eval["chapter_passed"]:
                        failures = len(ch_eval.get("chapter_level_failures", []))
                        print(f"  Chapter {chapter_num} failed chapter-level gate ({failures} issue(s))")

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

        # Phase 4: Pre-chapter physics validation
        physics_pre = None
        if self.physics_enforcer:
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

        # Step 2.5: Canon Expert validates prose (before Gate Critic)
        canon_notes = ""
        canon_result = None
        if self.canon_expert:
            print("  [Canon] Canon expert validating...")
            try:
                # Build a scene card with canon elements if not already populated
                run_card = dict(scene_card)
                if not run_card.get("canon_elements_needed"):
                    elements = []
                    if run_card.get("setting"):
                        elements.append({"type": "location", "name": run_card["setting"]})
                    for char in run_card.get("characters_present", []):
                        elements.append({"type": "character", "name": char})
                    elements.append({"type": "general", "name": "franchise_voice_and_terminology"})
                    run_card["canon_elements_needed"] = elements

                canon_result = await self.canon_expert.run({
                    "prose": prose,
                    "scene_card": run_card,
                    "concept_seed": getattr(self, "concept_seed", {}),
                })
                canon_notes = canon_result.get("canon_notes", "")
                # If canon expert returned corrected prose, use it
                if canon_result.get("verdict") == "fail" and canon_result.get("corrected_prose"):
                    prose = canon_result["corrected_prose"]
                    violations = canon_result.get("violations", [])
                    for v in violations:
                        print(f"    Canon fix: [{v.get('category', '?')}] \"{v.get('text', '')}\" → {v.get('suggestion', '')}")
                elif canon_result.get("violations"):
                    violation_lines = []
                    for v in canon_result["violations"]:
                        violation_lines.append(
                            f"- CANON: [{v.get('category', '?')}] \"{v.get('text', '')}\" → {v.get('suggestion', '')}"
                        )
                    canon_notes = "\n".join(violation_lines)
                self.ledger.emit(
                    "agent_complete",
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    agent_role="canon_expert",
                )
            except Exception as e:
                print(f"    Canon expert: error ({e.__class__.__name__}) — skipping")

        # Step 3: Gate Critic evaluates (with canon violations context)
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
            # Step 4: Quality Polish — single bounded expression-level pass
            print("  [4/5] Quality Polish running...")
            polish_result = await self.quality_polish.run({
                "prose": gate_passed_prose,
                "scene_card": scene_card,
                "quality_metrics": quality_metrics,
                "negative_constraints": self.assembler.get_negative_constraints(),
                "canon_notes": canon_notes,
            })
            polished_prose = polish_result["prose"]

            # Canon re-check on polished prose: re-apply any corrections the
            # polish may have reverted.
            if canon_result and canon_result.get("violations"):
                reintroduced = []
                for v in canon_result["violations"]:
                    offending = v.get("text", "")
                    if offending and offending.lower() in polished_prose.lower():
                        reintroduced.append(v)
                if reintroduced:
                    print(f"    Canon: {len(reintroduced)} violation(s) reintroduced in polish — applying fixes")
                    for v in reintroduced:
                        offending = v.get("text", "")
                        suggestion = v.get("suggestion", "")
                        if offending and suggestion:
                            polished_prose = polished_prose.replace(offending, suggestion)

            # Step D: Compression guard — cheap numeric floor check before Final Gate
            polished_wc = len(polished_prose.split())
            if gate_passed_wc and polished_wc < 0.8 * gate_passed_wc:
                pct = polished_wc / gate_passed_wc * 100
                print(
                    f"    Compression guard: polish cut {gate_passed_wc} -> {polished_wc} "
                    f"({pct:.0f}%) — reverting to gate-passed draft"
                )
                self.ledger.emit(
                    "compression_guard_fired",
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    payload={
                        "gate_word_count": gate_passed_wc,
                        "polish_word_count": polished_wc,
                    },
                )
                final_prose = gate_passed_prose
                polish_rejected = True
                rejection_reason = "compression_guard"
            else:
                # Step 5: Final Gate — contract check on actual polished text
                print("  [5/5] Final Gate evaluating polish output...")
                final_gate_result = await self.final_gate.run({
                    "prose": polished_prose,
                    "scene_card": scene_card,
                    "gate_passed_word_count": gate_passed_wc,
                })
                if final_gate_result["verdict"] != "pass":
                    failure_codes = [fc["code"] for fc in final_gate_result.get("failure_codes", [])]
                    print(
                        f"    Final Gate: polish rejected (verdict={final_gate_result['verdict']}, "
                        f"codes={failure_codes}) — reverting to gate-passed draft"
                    )
                    self.ledger.emit(
                        "final_gate_rejection",
                        chapter_number=chapter_num,
                        scene_number=scene_num,
                        payload={
                            "verdict": final_gate_result["verdict"],
                            "failure_codes": failure_codes,
                        },
                    )
                    final_prose = gate_passed_prose
                    polish_rejected = True
                    rejection_reason = "final_gate"
                else:
                    self.ledger.emit(
                        "final_gate_complete",
                        chapter_number=chapter_num,
                        scene_number=scene_num,
                        payload={"verdict": "pass"},
                    )
                    final_prose = polished_prose

        # Save the chapter
        output_path = self._save_chapter(chapter_num, scene_num, final_prose)
        print(f"  Saved: {output_path}")

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
            # Post-Phase-1 pipeline status derivation. The saved prose is:
            #   - 'approved' when it survived Quality Polish + Final Gate
            #   - 'final_gate_rejected' when polish was reverted (compression
            #     guard fired or Final Gate rejected the polish)
            #   - 'gate_passed' in --raw-draft mode (polish/final gate skipped)
            #   - 'gate_failed' if the scene-level verdict never reached pass
            #     (edge case: gate loop exited early)
            if polish_rejected:
                revision_status = "final_gate_rejected"
            elif self.raw_draft:
                revision_status = "gate_passed"
            elif evaluation.get("verdict") == "pass":
                revision_status = "approved"
            else:
                revision_status = "gate_failed"
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

        # Build negative constraints with dynamic cross-scene feedback
        neg_constraints = self.assembler.get_negative_constraints()
        if hasattr(self, "_chapter_overused_words") and self._chapter_overused_words:
            neg_constraints += (
                f"\n\nAvoid overusing these words (flagged in prior scenes): "
                f"{', '.join(sorted(self._chapter_overused_words))}"
            )
        if hasattr(self, "_scene_description_ratios") and self._scene_description_ratios:
            avg_desc = sum(self._scene_description_ratios) / len(self._scene_description_ratios)
            if avg_desc > 0.55:
                neg_constraints += (
                    f"\n\nPrior scenes averaged {int(avg_desc * 100)}% description/interiority. "
                    "Increase dialogue and action beats. Avoid long unbroken passages of interiority or observation."
                )

        result = await self.prose_stylist.run({
            "generation_brief": generation_brief,
            "assembled_context": assembled_context,
            "negative_constraints": neg_constraints,
            "failure_context": failure_context or "",
            "scene_card": scene_card,
        })

        duration_ms = int((time.time() - start) * 1000)
        self.ledger.emit(
            "agent_complete",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="prose_stylist",
            payload={"duration_ms": duration_ms, "word_count": len(result["prose"].split())},
        )

        return result["prose"]

    async def _gate_loop(
        self,
        scene_card: dict,
        prose: str,
        generation_brief: dict,
    ) -> tuple[dict, str]:
        """Run the Gate Critic loop with retries on failure.

        `generation_brief` is the typed dict from Plot Architect; rewrites reuse
        the same brief and only vary the failure_context passed to Prose Stylist.
        """
        structural_retries = 0
        voice_retries = 0
        best_prose = prose
        best_eval = None
        best_score = -1.0
        chapter_num = scene_card["chapter_number"]
        scene_num = scene_card.get("scene_number", 1)

        while True:
            # attempt_id scopes every event inside this rewrite loop so
            # consumers can distinguish retry iterations after the fact.
            attempt_number = structural_retries + voice_retries + 1
            attempt_id = f"ch{chapter_num}_scene{scene_num}_attempt_{attempt_number}"

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
                # JSON parse failure — treat as structural failure to trigger retry
                print(f"    Gate: JSON parse error ({e.__class__.__name__}) — treating as structural failure")
                evaluation = {
                    "verdict": "fail_structural",
                    "failure_codes": [{"code": "JSON_PARSE_ERROR", "location": "gate_critic", "description": str(e), "fix_hint": "Retry"}],
                    "severity": "blocking",
                    "route_to": "full_rewrite",
                    "structural_score": 0.0,
                    "voice_score": 0.0,
                    "polish_score": 0.0,
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

            verdict = evaluation["verdict"]
            s_score = evaluation.get("structural_score", 0)
            v_score = evaluation.get("voice_score", 0)
            p_score = evaluation.get("polish_score", 0)
            fc_codes = [fc["code"] for fc in evaluation.get("failure_codes", [])]

            # Track the best attempt across retries
            composite = (s_score * 0.5) + (v_score * 0.3) + (p_score * 0.2)
            if composite > best_score:
                best_score = composite
                best_prose = prose
                best_eval = evaluation

            print(f"    Gate: {verdict} | structural={s_score:.2f} voice={v_score:.2f} polish={p_score:.2f}")
            if fc_codes:
                print(f"    Gate failures: {', '.join(fc_codes)}")
            # Alert if any score is suspiciously perfect on first draft
            if s_score >= 0.95 and v_score >= 0.95 and structural_retries == 0:
                print(f"    [WARN] All gate scores >= 0.95 on first draft — critic may not be evaluating rigorously")

            if verdict == "pass" or verdict == "fail_polish":
                # Pass or polish-only failure — proceed to Quality Polish
                # (polish issues are caught by the compression guard + Final Gate,
                # not by looping back to a rewrite)
                event_type = "gate_pass" if verdict == "pass" else "gate_fail"
                self.ledger.emit(
                    event_type,
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    payload={
                        "verdict": verdict,
                        "scores": {
                            "structural": evaluation.get("structural_score", 0),
                            "voice": evaluation.get("voice_score", 0),
                            "polish": evaluation.get("polish_score", 0),
                        },
                        "failure_codes": [fc["code"] for fc in evaluation.get("failure_codes", [])],
                    },
                    attempt_id=attempt_id,
                )
                print(f"    Gate: {verdict} (structural={evaluation.get('structural_score', 0):.2f}, "
                      f"voice={evaluation.get('voice_score', 0):.2f}, "
                      f"polish={evaluation.get('polish_score', 0):.2f})")
                return evaluation, prose

            elif verdict == "fail_structural":
                structural_retries += 1
                self.ledger.emit(
                    "gate_fail",
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    payload={
                        "verdict": verdict,
                        "retry": structural_retries,
                        "failure_codes": [fc["code"] for fc in evaluation.get("failure_codes", [])],
                    },
                    attempt_id=attempt_id,
                )

                if structural_retries > self.max_structural_retries:
                    print(f"    Gate: {verdict} — max retries reached, using best attempt (score={best_score:.2f})")
                    return best_eval or evaluation, best_prose

                # Build failure context for rewrite
                failure_context = self._format_failure_context(evaluation)
                print(f"    Gate: {verdict} — full rewrite (attempt {structural_retries}/{self.max_structural_retries})")
                prose = await self._run_prose_stylist(scene_card, generation_brief, failure_context)

                # Re-validate canon on rewritten prose (fixes are lost on full rewrite)
                if self.canon_expert:
                    try:
                        rewrite_canon = await self.canon_expert.run({
                            "prose": prose,
                            "scene_card": scene_card,
                            "concept_seed": getattr(self, "concept_seed", {}),
                        })
                        if rewrite_canon.get("verdict") == "fail" and rewrite_canon.get("corrected_prose"):
                            prose = rewrite_canon["corrected_prose"]
                            print(f"    Canon: re-applied {len(rewrite_canon.get('violations', []))} fix(es) after rewrite")
                    except Exception as e:
                        print(f"    Canon re-check after rewrite: error ({e.__class__.__name__}) — skipping")

            elif verdict == "fail_voice":
                voice_retries += 1
                self.ledger.emit(
                    "gate_fail",
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    payload={
                        "verdict": verdict,
                        "retry": voice_retries,
                        "failure_codes": [fc["code"] for fc in evaluation.get("failure_codes", [])],
                    },
                    attempt_id=attempt_id,
                )

                if voice_retries > self.max_voice_retries:
                    print(f"    Gate: {verdict} — max retries reached, using best attempt (score={best_score:.2f})")
                    return best_eval or evaluation, best_prose

                # Build targeted voice revision notes
                failure_context = self._format_failure_context(evaluation)
                print(f"    Gate: {verdict} — targeted revision (attempt {voice_retries}/{self.max_voice_retries})")
                prose = await self._run_prose_stylist(scene_card, generation_brief, failure_context)

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
