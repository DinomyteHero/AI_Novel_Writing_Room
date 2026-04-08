"""Event-driven orchestrator for the chapter generation pipeline.

Phase 1 flow (per scene card):
  PlotArchitect -> ProseStylist -> GateCritic -> (retry loop) -> CraftEditor -> save
All steps emit typed events to the RunLedger.

Phase 2 additions (when dependencies provided):
  After save: Summarizer -> ChromaDB storage -> StateDiff -> ContradictionScanner

Phase 3 additions (when dependencies provided):
  After CraftEditor: RevisionPipeline (3 bands) -> replaces CraftEditor output
  After save: QualityMetrics -> CharacterSpecialist -> MilestoneGate check

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

from src.agents.craft_editor import CraftEditor
from src.agents.gate_critic import GateCritic
from src.agents.plot_architect import PlotArchitect
from src.agents.prose_stylist import ProseStylist
from src.memory.context_assembler import ContextAssembler
from src.model_router import ModelRouter
from src.run_ledger import RunLedger

if TYPE_CHECKING:
    from src.agents.canon_expert import CanonExpert
    from src.agents.character_specialist import CharacterSpecialist
    from src.agents.summarizer import Summarizer
    from src.memory.chapter_memory import ChapterMemory
    from src.memory.contradiction_scanner import ContradictionScanner
    from src.memory.state_diff import StateDiffApplier
    from src.memory.story_state import StoryState
    from src.quality.metrics_dashboard import MetricsDashboard
    from src.quality.milestone_gates import MilestoneGates
    from src.revision.pipeline import RevisionPipeline
    from src.planning.physics_enforcer import PhysicsEnforcer
    from src.pipeline_session import PipelineSession
    from src.quality.llm_judge import JudgeEvaluator


class Orchestrator:
    """Event-driven pipeline orchestrator.

    Manages the per-chapter generation loop:
    PlotArchitect -> ProseStylist -> GateCritic -> CraftEditor -> save
    with failure-driven retry logic.

    Phase 2 (optional): After save, runs Summarizer -> state diff -> contradiction scan.
    Phase 3 (optional): Revision pipeline, quality metrics, character specialist, milestones.
    Phase 4 (optional): Physics enforcement, session persistence, LLM judge.
    """

    def __init__(
        self,
        router: ModelRouter,
        context_assembler: ContextAssembler,
        ledger: RunLedger,
        manuscripts_dir: str = "data/manuscripts",
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
        revision_pipeline: Optional["RevisionPipeline"] = None,
        metrics_dashboard: Optional["MetricsDashboard"] = None,
        character_specialist: Optional["CharacterSpecialist"] = None,
        milestone_gates: Optional["MilestoneGates"] = None,
        # Phase 4 optional dependencies:
        physics_enforcer: Optional["PhysicsEnforcer"] = None,
        pipeline_session: Optional["PipelineSession"] = None,
        session_id: Optional[str] = None,
        judge_evaluator: Optional["JudgeEvaluator"] = None,
    ):
        self.router = router
        self.assembler = context_assembler
        self.ledger = ledger
        self.manuscripts_dir = Path(manuscripts_dir)
        self.manuscripts_dir.mkdir(parents=True, exist_ok=True)
        self.max_structural_retries = max_structural_retries
        self.max_voice_retries = max_voice_retries

        # Initialize Phase 1 agents
        self.plot_architect = PlotArchitect(router)
        self.prose_stylist = ProseStylist(router)
        self.gate_critic = GateCritic(router)
        self.craft_editor = CraftEditor(router)

        # Phase 2 optional components
        self.summarizer = summarizer
        self.state_diff_applier = state_diff_applier
        self.contradiction_scanner = contradiction_scanner
        self.chapter_memory = chapter_memory
        self.story_state = story_state
        self.canon_expert = canon_expert

        # Phase 3 optional components
        self.revision_pipeline = revision_pipeline
        self.metrics_dashboard = metrics_dashboard
        self.character_specialist = character_specialist
        self.milestone_gates = milestone_gates

        # Phase 4 optional components
        self.physics_enforcer = physics_enforcer
        self.pipeline_session = pipeline_session
        self.session_id = session_id
        self.judge_evaluator = judge_evaluator

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

        self.ledger.emit("pipeline_start", payload={"total_scenes": len(active_cards)})
        results = []

        try:
            for scene_card in active_cards:
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
        print("  [1/4] Plot Architect generating brief...")
        generation_brief = await self._run_plot_architect(scene_card)

        # Step 2: Prose Stylist drafts the scene
        print("  [2/4] Prose Stylist drafting...")
        prose = await self._run_prose_stylist(scene_card, generation_brief)

        # Step 3: Gate Critic evaluates
        print("  [3/4] Gate Critic evaluating...")
        evaluation, prose = await self._gate_loop(scene_card, prose, generation_brief)

        # Step 4: Craft Editor polishes
        print("  [4/4] Craft Editor polishing...")
        final_prose = await self._run_craft_editor(scene_card, prose, evaluation)

        # Phase 3: Revision Pipeline (after CraftEditor, before save)
        revision_result = None
        if self.revision_pipeline:
            print("  [P3-1] Revision pipeline running (3 bands)...")
            revision_context = {
                "scene_card": scene_card,
                "story_state_summary": "",
                "prior_chapter_summary": "",
                "character_voices": self.assembler.get_character_voices(
                    scene_card.get("characters_present", [])
                ),
                "negative_constraints": self.assembler.get_negative_constraints(),
                "quality_flags": [],
            }
            revision_result = await self.revision_pipeline.run(final_prose, revision_context)
            final_prose = revision_result["prose"]
            bands = ", ".join(revision_result["bands_applied"])
            print(f"    Revision complete: {bands}")

        # Save the chapter
        output_path = self._save_chapter(chapter_num, scene_num, final_prose)
        print(f"  Saved: {output_path}")

        # Phase 3: Quality Metrics (after save)
        quality_metrics = None
        if self.metrics_dashboard:
            print("  [P3-2] Quality metrics running...")
            prior_chapters = self._load_prior_chapters(chapter_num)
            voice_notes = self._get_pov_voice_notes(scene_card)
            quality_metrics = self.metrics_dashboard.analyze_chapter(
                final_prose,
                scene_card,
                prior_chapters=prior_chapters,
                voice_notes=voice_notes,
            )
            status = "PASS" if quality_metrics["passed"] else "FAIL"
            print(f"    Quality: {quality_metrics['overall_score']:.2f} ({status})")
            if quality_metrics["flags"]:
                for flag in quality_metrics["flags"][:5]:
                    print(f"    - {flag}")

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
                scene_card, final_prose, evaluation
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
            character_analysis = await self.character_specialist.run(char_context)
            print(f"    Character verdict: {character_analysis['verdict']}")

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
        if revision_result:
            result["revision"] = {
                "bands_applied": revision_result["bands_applied"],
                "band_results": revision_result["band_results"],
            }
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

        summary_result = await self.summarizer.run({
            "prose": prose,
            "scene_card": scene_card,
        })

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

        # Step 6: Store summary in ChromaDB
        if self.chapter_memory and summary_text:
            self.chapter_memory.add_summary(
                chapter_num,
                summary_text,
                metadata={
                    "structural_phase": scene_card.get("structural_phase", ""),
                    "pov_character": scene_card.get("pov_character", ""),
                },
            )
            print(f"  [P2-2] Summary stored in ChromaDB")

        # Step 7: Apply state diff to SQLite
        if self.state_diff_applier and state_diff.get("changes"):
            self.state_diff_applier.apply_diff(state_diff, chapter_num, scene_num)
            print(f"  [P2-3] State diff applied")

        # Step 8: Update chapter log
        if self.story_state:
            scores = {
                "structural": evaluation.get("structural_score", 0),
                "voice": evaluation.get("voice_score", 0),
                "polish": evaluation.get("polish_score", 0),
            }
            failure_codes = [
                fc["code"] for fc in evaluation.get("failure_codes", [])
            ]
            self.story_state.add_chapter_log(
                chapter_number=chapter_num,
                word_count=len(prose.split()),
                structural_phase=scene_card.get("structural_phase", ""),
                pov_character=scene_card.get("pov_character", ""),
                summary=summary_text,
                quality_scores=scores,
                failure_codes=failure_codes,
                revision_status="craft_edited" if evaluation.get("verdict") != "pass" else "approved",
            )
            print(f"  [P2-4] Chapter log updated")

        # Step 9: Contradiction scanner
        if self.contradiction_scanner:
            contradiction_flags = self.contradiction_scanner.scan(
                chapter_num, prose, scene_card
            )
            if contradiction_flags:
                print(
                    f"  [P2-5] Contradiction scanner: "
                    f"{len(contradiction_flags)} flag(s)"
                )
            else:
                print(f"  [P2-5] Contradiction scanner: clean")

        return summary_text, contradiction_flags

    async def _run_plot_architect(self, scene_card: dict) -> str:
        """Run the Plot Architect to generate a brief."""
        start = time.time()
        self.ledger.emit(
            "agent_start",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="plot_architect",
        )

        result = await self.plot_architect.run({
            "scene_card": scene_card,
            "bible_summary": self.assembler.get_bible_summary(),
        })

        duration_ms = int((time.time() - start) * 1000)
        self.ledger.emit(
            "agent_complete",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="plot_architect",
            payload={"duration_ms": duration_ms},
        )

        return result["generation_brief"]

    async def _run_prose_stylist(
        self,
        scene_card: dict,
        generation_brief: str,
        failure_context: Optional[str] = None,
    ) -> str:
        """Run the Prose Stylist to draft prose."""
        start = time.time()
        self.ledger.emit(
            "agent_start",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="prose_stylist",
        )

        assembled_context = self.assembler.assemble(scene_card)

        result = await self.prose_stylist.run({
            "generation_brief": generation_brief,
            "assembled_context": assembled_context,
            "negative_constraints": self.assembler.get_negative_constraints(),
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
        generation_brief: str,
    ) -> tuple[dict, str]:
        """Run the Gate Critic loop with retries on failure."""
        structural_retries = 0
        voice_retries = 0

        while True:
            start = time.time()
            self.ledger.emit(
                "agent_start",
                chapter_number=scene_card["chapter_number"],
                scene_number=scene_card.get("scene_number", 1),
                agent_role="gate_critic",
            )

            evaluation = await self.gate_critic.run({
                "prose": prose,
                "scene_card": scene_card,
                "bible_summary": self.assembler.get_bible_summary(),
            })

            duration_ms = int((time.time() - start) * 1000)
            self.ledger.emit(
                "agent_complete",
                chapter_number=scene_card["chapter_number"],
                scene_number=scene_card.get("scene_number", 1),
                agent_role="gate_critic",
                payload={"duration_ms": duration_ms},
            )

            verdict = evaluation["verdict"]

            if verdict == "pass" or verdict == "fail_polish":
                # Pass or polish-only failure — proceed to craft editor
                event_type = "gate_pass" if verdict == "pass" else "gate_fail"
                self.ledger.emit(
                    event_type,
                    chapter_number=scene_card["chapter_number"],
                    scene_number=scene_card.get("scene_number", 1),
                    payload={
                        "verdict": verdict,
                        "scores": {
                            "structural": evaluation.get("structural_score", 0),
                            "voice": evaluation.get("voice_score", 0),
                            "polish": evaluation.get("polish_score", 0),
                        },
                        "failure_codes": [fc["code"] for fc in evaluation.get("failure_codes", [])],
                    },
                )
                print(f"    Gate: {verdict} (structural={evaluation.get('structural_score', 0):.2f}, "
                      f"voice={evaluation.get('voice_score', 0):.2f}, "
                      f"polish={evaluation.get('polish_score', 0):.2f})")
                return evaluation, prose

            elif verdict == "fail_structural":
                structural_retries += 1
                self.ledger.emit(
                    "gate_fail",
                    chapter_number=scene_card["chapter_number"],
                    scene_number=scene_card.get("scene_number", 1),
                    payload={
                        "verdict": verdict,
                        "retry": structural_retries,
                        "failure_codes": [fc["code"] for fc in evaluation.get("failure_codes", [])],
                    },
                )

                if structural_retries > self.max_structural_retries:
                    print(f"    Gate: {verdict} — max retries reached, proceeding anyway")
                    return evaluation, prose

                # Build failure context for rewrite
                failure_context = self._format_failure_context(evaluation)
                print(f"    Gate: {verdict} — full rewrite (attempt {structural_retries}/{self.max_structural_retries})")
                prose = await self._run_prose_stylist(scene_card, generation_brief, failure_context)

            elif verdict == "fail_voice":
                voice_retries += 1
                self.ledger.emit(
                    "gate_fail",
                    chapter_number=scene_card["chapter_number"],
                    scene_number=scene_card.get("scene_number", 1),
                    payload={
                        "verdict": verdict,
                        "retry": voice_retries,
                        "failure_codes": [fc["code"] for fc in evaluation.get("failure_codes", [])],
                    },
                )

                if voice_retries > self.max_voice_retries:
                    print(f"    Gate: {verdict} — max retries reached, proceeding anyway")
                    return evaluation, prose

                # Build targeted voice revision notes
                failure_context = self._format_failure_context(evaluation)
                print(f"    Gate: {verdict} — targeted revision (attempt {voice_retries}/{self.max_voice_retries})")
                prose = await self._run_prose_stylist(scene_card, generation_brief, failure_context)

    async def _run_craft_editor(
        self,
        scene_card: dict,
        prose: str,
        evaluation: dict,
    ) -> str:
        """Run the Craft Editor for non-blocking improvements."""
        start = time.time()
        self.ledger.emit(
            "agent_start",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="craft_editor",
        )

        # Build craft notes from any polish failures
        craft_notes = ""
        for fc in evaluation.get("failure_codes", []):
            if fc["code"] in {"EXPOSITION_LEAK", "PACING_FLATLINE", "PROSE_CLICHE_BURST"}:
                craft_notes += f"- {fc['code']}: {fc['description']}\n"
                if fc.get("fix_hint"):
                    craft_notes += f"  Suggestion: {fc['fix_hint']}\n"

        result = await self.craft_editor.run({
            "prose": prose,
            "scene_card": scene_card,
            "negative_constraints": self.assembler.get_negative_constraints(),
            "craft_notes": craft_notes,
        })

        duration_ms = int((time.time() - start) * 1000)
        self.ledger.emit(
            "craft_edit_complete",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="craft_editor",
            payload={"duration_ms": duration_ms},
        )

        return result["prose"]

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
            # Try scene 1 of each prior chapter
            path = self.manuscripts_dir / f"chapter_{ch:02d}_scene_01.md"
            if path.exists():
                prior.append(path.read_text(encoding="utf-8"))
        return prior

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
