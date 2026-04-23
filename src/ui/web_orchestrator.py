"""Web-aware orchestrator that adds pause gates and async milestone approval.

Thin subclass of Orchestrator. Overrides only run_pipeline() to insert:
- Pause gate between chapters (asyncio.Event)
- Async milestone approval (asyncio.Future via PipelineManager)

run_chapter() and all agent logic is inherited unchanged.
"""

from src.orchestrator import Orchestrator
from src.ui.pipeline_manager import PipelineManager, PipelineState


class WebOrchestrator(Orchestrator):
    """Orchestrator with web-aware pause and milestone support."""

    def __init__(self, *args, pipeline_manager: PipelineManager, **kwargs):
        super().__init__(*args, **kwargs)
        self.pipeline_manager = pipeline_manager

    async def run_pipeline(self, scene_cards: list[dict]) -> list[dict]:
        """Run the pipeline with pause gates and async milestone approval.

        Mirrors the parent implementation but adds:
        1. await pause_event.wait() between chapters
        2. Async milestone approval after chapters with milestone gates
        3. Progress tracking on pipeline_manager
        """
        pm = self.pipeline_manager

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

        pm.total_chapters = len(active_cards)
        self.ledger.emit("pipeline_start", payload={"total_scenes": len(active_cards)})
        results = []

        # Lazy import to match Orchestrator.run_pipeline; the pipeline package is
        # optional for callers that don't exercise save-blockers.
        from src.pipeline.save_blockers import SaveBlockedError, should_abort_run

        try:
            for i, scene_card in enumerate(active_cards):
                # Pause gate: blocks here if paused
                await pm.pause_event.wait()

                chapter_num = scene_card["chapter_number"]
                scene_num = scene_card.get("scene_number", 1)
                pm.current_chapter = chapter_num

                print(f"\n{'='*60}")
                print(f"Chapter {chapter_num}, Scene {scene_num}")
                print(f"{'='*60}")

                try:
                    result = await self.run_chapter(scene_card)
                except SaveBlockedError as e:
                    if not should_abort_run(self.runtime_flags):
                        decision = self._handle_firewall(
                            scene_card=scene_card,
                            error=e,
                            active_cards=active_cards,
                            current_index=i,
                        )
                        print(
                            f"\n[STATE-FIREWALL] isolated "
                            f"{scene_card['chapter_number']}.{scene_card.get('scene_number', 1)} "
                            f"-> gap_id={decision.gap_id}"
                        )
                        if decision.soft_halted_scenes:
                            print(
                                f"  soft_halt: {', '.join(decision.soft_halted_scenes)}"
                            )
                        if decision.continue_with_gap_note:
                            print(
                                "  continue_with_note: "
                                f"{', '.join(decision.continue_with_gap_note)}"
                            )
                        if not decision.continue_run:
                            print(
                                "[STATE-FIREWALL] soft-halting run -- "
                                "open gaps require human review."
                            )
                            break
                        continue
                    # Relay v1 quarantine policy: abort the entire run on the
                    # first blocker. Web UI surfaces the abort through the
                    # pipeline_manager state the same way a KeyboardInterrupt
                    # would — downstream UI telemetry reads the save_blocked
                    # ledger event.
                    print(f"\n{'=' * 60}")
                    print("PIPELINE ABORTED — save-blocker fired")
                    print(f"{'=' * 60}")
                    print(str(e))
                    break

                results.append(result)
                pm.results = results

                # Phase 4: Save session progress after each chapter
                if self.pipeline_session and self.session_id:
                    self.pipeline_session.mark_chapter_complete(
                        self.session_id, chapter_num, scene_num, result
                    )

                # Phase 5: chapter-level gate after last scene in chapter
                await self.maybe_run_chapter_gate_after_scene(i, active_cards, results)

                # Async milestone approval
                if result.get("milestone") and pm._milestone_pending:
                    should_continue = await pm.await_milestone_approval()
                    if not should_continue:
                        result["milestone_abort"] = True
                        print(f"\nPipeline aborted at milestone: {result['milestone']['milestone_name']}")
                        break
                elif result.get("milestone_abort"):
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
