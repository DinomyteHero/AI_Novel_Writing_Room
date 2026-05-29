"""Event-driven orchestrator for the chapter generation pipeline.

Lean per-scene flow (per scene card):
  PlotArchitect -> ProseStylist -> [LineWriter] -> [RhythmValidator/RhythmEditor]
  -> save -> post-save memory
All steps emit typed events to the RunLedger.

Post-save memory (when dependencies provided):
  Summarizer -> ChromaDB storage -> StateDiff -> ContradictionScanner
  -> worldbuilding extraction

The chapter packet is the drafter's runtime contract. Revision-debt rows and
rhythm telemetry are advisory and never block a save.
"""

import json
import time
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from src.agents.plot_architect import PlotArchitect
from src.agents.prose_stylist import ProseStylist
from src.agents.rhythm_editor import apply_rhythm_edits
from src.quality.rhythm_validator import validate_rhythm
from src.memory.context_assembler import ContextAssembler
from src.model_router import ModelRouter
from src.run_ledger import RunLedger

if TYPE_CHECKING:
    from src.agents.line_writer import LineWriter
    from src.agents.rhythm_editor import RhythmEditor
    from src.agents.summarizer import Summarizer
    from src.memory.chapter_memory import ChapterMemory
    from src.memory.contradiction_scanner import ContradictionScanner
    from src.memory.state_diff import StateDiffApplier
    from src.memory.story_state import StoryState
    from src.memory.promise_ledger import PromiseLedger
    from src.pipeline.chapter_packet import ChapterPacketCompiler
    from src.pipeline.revision_debt import RevisionDebtStore
    from src.pipeline_session import PipelineSession
    from src.worldbuilding.lore_service import LoreService


class Orchestrator:
    """Event-driven pipeline orchestrator.

    Manages the per-scene generation loop:
    PlotArchitect -> ProseStylist -> [LineWriter] -> [RhythmValidator/
    RhythmEditor] -> save.

    Post-save (optional, when dependencies provided): Summarizer -> state
    diff -> contradiction scan -> worldbuilding extraction.
    """

    def __init__(
        self,
        router: ModelRouter,
        context_assembler: ContextAssembler,
        ledger: RunLedger,
        manuscripts_dir: str = "output/_fallback/manuscripts",
        # Post-save memory dependencies:
        summarizer: Optional["Summarizer"] = None,
        state_diff_applier: Optional["StateDiffApplier"] = None,
        contradiction_scanner: Optional["ContradictionScanner"] = None,
        chapter_memory: Optional["ChapterMemory"] = None,
        story_state: Optional["StoryState"] = None,
        # Lean scene-path agents:
        line_writer: Optional["LineWriter"] = None,
        rhythm_editor: Optional["RhythmEditor"] = None,
        # Session persistence:
        pipeline_session: Optional["PipelineSession"] = None,
        session_id: Optional[str] = None,
        # Worldbuilding optional dependency:
        lore_service: Optional["LoreService"] = None,
        universe_id: Optional[str] = None,
        project_id: Optional[str] = None,
        worldbuilding_auto_extract: bool = False,
        # Runtime flags (resolved settings.yaml + per-book overrides).
        runtime_flags: Optional[dict] = None,
        # Chapter packet + revision debt. Both default None -> flag-off path.
        chapter_packet_compiler: Optional["ChapterPacketCompiler"] = None,
        revision_debt_store: Optional["RevisionDebtStore"] = None,
        # Promise ledger. When the flag is on, scene-save-time calls
        # record_progression / record_payoff for each declared promise_id.
        promise_ledger: Optional["PromiseLedger"] = None,
    ):
        self.router = router
        self.assembler = context_assembler
        self.ledger = ledger
        self.runtime_flags = runtime_flags or {}
        self.manuscripts_dir = Path(manuscripts_dir)
        self.manuscripts_dir.mkdir(parents=True, exist_ok=True)
        lean_cfg = (self.runtime_flags.get("runtime") or {}).get("lean_prose_only") or {}
        self._lean_prose_only = bool(lean_cfg.get("enabled", False))
        line_edit_cfg = lean_cfg.get("line_edit", {})
        if isinstance(line_edit_cfg, dict):
            self._lean_line_edit = bool(line_edit_cfg.get("enabled", False))
        else:
            self._lean_line_edit = bool(line_edit_cfg)

        # Lean scene-path agents
        self.plot_architect = PlotArchitect(router)
        self.prose_stylist = ProseStylist(router)

        # Post-save memory components
        self.summarizer = summarizer
        self.state_diff_applier = state_diff_applier
        self.contradiction_scanner = contradiction_scanner
        self.chapter_memory = chapter_memory
        self.story_state = story_state
        # Lean scene-path optional agents
        self.line_writer = line_writer
        self.rhythm_editor = rhythm_editor

        # Rhythm validator + editor runtime flags.
        rhythm_validator_cfg = (
            self.runtime_flags.get("runtime") or {}
        ).get("rhythm_validator") or {}
        self._rhythm_validator_enabled = bool(
            rhythm_validator_cfg.get("enabled", False)
        )
        self._rhythm_validator_thresholds = (
            rhythm_validator_cfg.get("thresholds") or {}
        )
        rhythm_editor_cfg = (
            self.runtime_flags.get("runtime") or {}
        ).get("rhythm_editor") or {}
        self._rhythm_editor_enabled = bool(
            rhythm_editor_cfg.get("enabled", False) and self.rhythm_editor is not None
        )
        self._rhythm_editor_trigger_codes = set(
            rhythm_editor_cfg.get("trigger_codes")
            or [
                "rhythm.em_dash_overuse",
                "rhythm.staccato_cluster",
                "rhythm.opener_monotone",
                "rhythm.abstract_tic",
            ]
        )
        self._rhythm_editor_max_trigger_codes = int(
            rhythm_editor_cfg.get("max_trigger_codes", 5)
        )
        self._rhythm_editor_max_edits = int(
            rhythm_editor_cfg.get("max_edits", 8)
        )
        self._rhythm_editor_max_total_changed_chars = int(
            rhythm_editor_cfg.get("max_total_changed_chars", 1500)
        )
        self._rhythm_editor_max_changed_ratio = float(
            rhythm_editor_cfg.get("max_changed_ratio", 0.15)
        )

        # Session persistence
        self.pipeline_session = pipeline_session
        self.session_id = session_id

        # Worldbuilding optional components
        self.lore_service = lore_service
        self._universe_id = universe_id
        self._project_id = project_id
        self._worldbuilding_auto_extract = worldbuilding_auto_extract
        # Lore-conflict strict mode is dormant — no CLI flag wires it on.
        self._strict_lore = False

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

    async def run_pipeline(self, scene_cards: list[dict]) -> list[dict]:
        """Run the full pipeline for a list of scene cards."""
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

                try:
                    result = await self.run_chapter(scene_card)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001
                    # One scene's failure must not abort the remaining chapters.
                    # Record it, emit an error event, and continue so a long
                    # multi-chapter run survives a single bad scene. The scene is
                    # NOT marked complete, so a resumed run will retry it.
                    self.ledger.emit_error(
                        "scene_error",
                        chapter_number=chapter_num,
                        scene_number=scene_num,
                        payload={"error": f"{type(exc).__name__}: {exc}"},
                    )
                    print(
                        f"  [ERROR] Chapter {chapter_num} scene {scene_num} failed: "
                        f"{type(exc).__name__}: {exc} — skipping, continuing run"
                    )
                    results.append({
                        "chapter_number": chapter_num,
                        "scene_number": scene_num,
                        "error": f"{type(exc).__name__}: {exc}",
                        "status": "failed",
                    })
                    continue
                results.append(result)

                if self.pipeline_session and self.session_id:
                    self.pipeline_session.mark_chapter_complete(
                        self.session_id, chapter_num, scene_num, result
                    )
        except KeyboardInterrupt:
            print("\nPipeline interrupted — saving session...")
        finally:
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

    @staticmethod
    def _lean_skipped_evaluation() -> dict:
        """Synthetic evaluation payload for the prose-only runtime path."""
        return {
            "verdict": "skipped",
            "failure_codes": [],
            "severity": "non_blocking",
            "route_to": None,
            "structural_score": 1.0,
            "voice_score": 1.0,
            "polish_score": 1.0,
            "skip_reason": "lean_prose_only",
        }

    async def run_chapter(self, scene_card: dict) -> dict:
        """Run the lean pipeline for a single scene card."""
        chapter_num = scene_card["chapter_number"]
        scene_num = scene_card.get("scene_number", 1)

        self.ledger.emit(
            "chapter_start",
            chapter_number=chapter_num,
            scene_number=scene_num,
            payload={"mission": scene_card.get("mission", "")},
        )

        # Step 1: Plot Architect generates the brief
        print("  [1/4] Plot Architect generating brief...")
        generation_brief = await self._run_plot_architect(scene_card)

        # Step 2: Prose Stylist drafts the scene
        print("  [2/4] Prose Stylist drafting...")
        prose = await self._run_prose_stylist(scene_card, generation_brief)

        # Step 3: optional LineWriter line-edit pass
        line_edit_attempted = False
        line_edit_applied = False
        if self._lean_line_edit and self.line_writer:
            source_before_line_edit = prose
            line_edit_attempted = True
            prose = await self._run_line_writer(
                scene_card, generation_brief, prose
            )
            line_edit_applied = prose != source_before_line_edit
        elif self._lean_line_edit and not self.line_writer:
            self.ledger.emit_warn(
                "lean_line_edit_unavailable",
                chapter_number=chapter_num,
                scene_number=scene_num,
                payload={"reason": "agent_routing.line_writer missing"},
            )

        # Step 4: rhythm validation + literal-edit pass (flag-gated, no-op when off)
        rhythm_telemetry: dict = {}
        rhythm_edit_applied = False
        prose_before_rhythm = prose
        if self._rhythm_validator_enabled or self._rhythm_editor_enabled:
            prose, rhythm_telemetry = await self._maybe_rhythm_validate_and_edit(
                prose=prose,
                scene_card=scene_card,
                chapter_number=chapter_num,
                scene_number=scene_num,
            )
            rhythm_edit_applied = prose != prose_before_rhythm

        output_path = self._save_chapter(chapter_num, scene_num, prose)
        word_count = len(prose.split())
        print(f"  Saved: {output_path}")

        # Post-save memory: summarizer -> state diff -> contradiction scan
        # -> worldbuilding extraction. Wrapped so a failure never aborts a
        # saved scene; next-scene state may be stale, so the warn is load-bearing.
        summary_text = None
        contradiction_flags: list[dict] = []
        if self.summarizer:
            try:
                summary_text, contradiction_flags = await self._run_post_save(
                    scene_card, prose, self._lean_skipped_evaluation(),
                )
            except Exception as exc:  # noqa: BLE001
                self.ledger.emit_warn(
                    "post_save_error",
                    chapter_number=chapter_num,
                    scene_number=scene_num,
                    payload={
                        "stage": "run_post_save",
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                print(
                    f"  [WARN] post-save processing crashed: "
                    f"{type(exc).__name__}: {exc} — scene saved, state may be stale"
                )

        # Slice 3 — record declared promise deltas (no-op when flag off).
        self._maybe_record_promise_deltas(scene_card)

        self.ledger.emit_info(
            "lean_prose_only_saved",
            chapter_number=chapter_num,
            scene_number=scene_num,
            payload={
                "word_count": word_count,
                "output_path": str(output_path),
                "line_edit_enabled": bool(self._lean_line_edit),
                "line_edit_attempted": line_edit_attempted,
                "line_edit_applied": line_edit_applied,
                "rhythm_validator_enabled": self._rhythm_validator_enabled,
                "rhythm_editor_enabled": self._rhythm_editor_enabled,
                "rhythm_edit_applied": rhythm_edit_applied,
            },
        )

        result = {
            "chapter_number": chapter_num,
            "scene_number": scene_num,
            "output_path": str(output_path),
            "evaluation": self._lean_skipped_evaluation(),
            "word_count": word_count,
            "lean_prose_only": True,
            "line_edit_attempted": line_edit_attempted,
            "line_edit_applied": line_edit_applied,
        }
        if summary_text:
            result["summary"] = summary_text
        if contradiction_flags:
            result["contradiction_flags"] = contradiction_flags
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
            print("  [WARN] Summarizer returned empty summary — downstream context will be degraded")
        if not state_diff or not state_diff.get("changes"):
            print("  [WARN] Summarizer returned empty state_diff — story state will not update")
        if not established_concepts:
            print("  [WARN] Summarizer returned no established_concepts — concept maturity tracking inactive for this scene")

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
            print("  [P2-2] Summary stored in ChromaDB")

        # Step 7: Apply state diff to SQLite
        if self.state_diff_applier and state_diff.get("changes"):
            self.state_diff_applier.apply_diff(state_diff, chapter_num, scene_num, scene_card=scene_card)
            # Capture rejected transitions for Summarizer feedback on next scene
            rejected = getattr(self.state_diff_applier, "last_rejected_transitions", [])
            if rejected:
                if not hasattr(self, "_rejected_transitions"):
                    self._rejected_transitions = []
                self._rejected_transitions.extend(rejected)
            print("  [P2-3] State diff applied")

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
            # Status vocabulary collapsed to three saved-scene states:
            #   - 'saved_clean'          — saved with no advisory
            #   - 'saved_with_advisory'  — an advisory-level signal fired
            #   - 'quarantined'          — scene blocked pre-save (not written
            #                              through this path)
            # The lean path runs no save-time gates, so a scene that reaches
            # this point saves clean unless an explicit polish_rejected flag
            # is threaded through.
            if polish_rejected:
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
            print("  [P2-4] Chapter/scene log updated")

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
                print("  [P2-5] Contradiction scanner: clean")

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
                    print("  [WARN] Worldbuilding extraction returned 0 entries — check lore_extractor JSON parsing or universe FK")
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
        # Slice 6 (spec \u00a710.3 step 4/5): patch_workflow.py writes a
        # ``*_overlay.STALE`` marker whenever gap resolution touches the
        # scene's downstream. Overlays already rebuild every scene, so the
        # marker is advisory \u2014 we emit an info event then clear it so the
        # audit trail lands exactly once per resolution.
        try:
            marker = self._packets_dir / (
                f"chapter_{chapter_number:02d}_sc_{scene_number:02d}_overlay.STALE"
            )
            if marker.exists():
                self.ledger.emit_info(
                    "packet_overlay_written",
                    chapter_number=chapter_number, scene_number=scene_number,
                    payload={
                        "chapter_number": chapter_number,
                        "scene_number": scene_number,
                        "stale_marker_cleared": True,
                        "marker_written_at": marker.read_text(encoding="utf-8").strip(),
                    },
                )
                marker.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001 -- marker errors must not block draft
            pass

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
            except Exception as exc:  # noqa: BLE001
                # Store-level failure (DB lock, serialization, schema) must
                # not abort a scene that already saved. Surface as warn.
                self.ledger.emit_warn(
                    "promise_progressed",
                    chapter_number=chapter_number, scene_number=scene_number,
                    payload={
                        "promise_id": pid,
                        "status": "store_error",
                        "error": f"{type(exc).__name__}: {exc}",
                    },
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
            except Exception as exc:  # noqa: BLE001
                self.ledger.emit_warn(
                    "promise_paid",
                    chapter_number=chapter_number, scene_number=scene_number,
                    payload={
                        "promise_id": pid,
                        "status": "store_error",
                        "error": f"{type(exc).__name__}: {exc}",
                    },
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

        # Slice 2: build the chapter packet overlay for this scene when the
        # flag is on. The packet renderer embeds its own flat-context snapshot,
        # so the legacy flat assembly is only needed for the fallback path.
        chapter_packet = self._maybe_compile_overlay(scene_card)

        # Only run the (canon-RAG + worldbuilding-retrieval) flat assembly when
        # it is actually used: the packet path is off, or its overlay failed to
        # compile. On the packet hot path the overlay already embedded the
        # assemble() output, so recomputing it here is pure waste (a redundant
        # retrieval per scene).
        if chapter_packet is None:
            assembled_context = self.assembler.assemble(scene_card)
        else:
            assembled_context = ""

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
        prose = result.get("prose", "") if isinstance(result, dict) else ""

        duration_ms = int((time.time() - start) * 1000)
        word_count = len(prose.split())
        if not prose.strip():
            self.ledger.emit_warn(
                "prose_empty",
                chapter_number=scene_card["chapter_number"],
                scene_number=scene_card.get("scene_number", 1),
                agent_role="prose_stylist",
                payload={"reason": "drafter returned empty prose"},
            )
        self.ledger.emit(
            "agent_complete",
            chapter_number=scene_card["chapter_number"],
            scene_number=scene_card.get("scene_number", 1),
            agent_role="prose_stylist",
            payload={"duration_ms": duration_ms, "word_count": word_count},
        )

        return prose

    async def _run_line_writer(
        self,
        scene_card: dict,
        generation_brief: dict,
        source_prose: str,
    ) -> str:
        """Run the LineWriter line-edit pass after the drafter.

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

    async def _maybe_rhythm_validate_and_edit(
        self,
        *,
        prose: str,
        scene_card: dict,
        chapter_number: int,
        scene_number: int,
    ) -> tuple[str, dict]:
        """Run RhythmValidator and optionally RhythmEditor on the prose.

        Two flag-gated stages:
        - ``runtime.rhythm_validator.enabled`` → measure rhythm, emit
          revision_debt rows for any issues. Never blocks; never mutates prose.
        - ``runtime.rhythm_editor.enabled`` → if the validator finds at least
          one *actionable* issue (em_dash_overuse / staccato_cluster /
          opener_monotone / abstract_tic), call the RhythmEditor LLM and apply
          its proposed edits under deterministic safety caps. The
          ``dialogue_starved`` code is *not* in the trigger set — adding
          dialogue is generative work that belongs in the drafter.

        Returns ``(prose, telemetry)`` where ``telemetry`` carries the pre-
        and post-edit metrics for the ledger payload. When both flags are
        off this is a noop and ``telemetry`` is empty.
        """
        telemetry: dict = {}
        if not (self._rhythm_validator_enabled or self._rhythm_editor_enabled):
            return prose, telemetry

        # Resolve dialogue requirement from the scene card.
        require_dialogue = not (
            scene_card.get("dialogue_density_target") == "low"
            or scene_card.get("dialogue_expectation") == "interior"
        )
        thresholds = self._rhythm_validator_thresholds or None
        try:
            pre_result = validate_rhythm(
                prose,
                scope="scene",
                scope_id=f"ch{chapter_number:02d}_sc{scene_number:02d}",
                thresholds=thresholds,
                require_dialogue=require_dialogue,
            )
        except Exception as exc:  # noqa: BLE001
            self.ledger.emit_warn(
                "rhythm_validation_error",
                chapter_number=chapter_number,
                scene_number=scene_number,
                agent_role="rhythm_validator",
                payload={"error": f"{exc.__class__.__name__}: {exc}"},
            )
            return prose, telemetry

        pre_payload = pre_result.to_dict()
        telemetry["pre_edit"] = pre_payload
        self.ledger.emit_info(
            "rhythm_validation",
            chapter_number=chapter_number,
            scene_number=scene_number,
            agent_role="rhythm_validator",
            payload={
                "passed": pre_result.passed,
                "issue_count": len(pre_result.issues),
                "metrics": pre_payload["metrics"],
            },
        )

        # Flow each validator issue into the revision_debt store.
        if self._active_debt_store is not None and pre_result.issues:
            try:
                from src.pipeline.revision_debt_producers import emit_rhythm_advisory
            except ImportError:
                emit_rhythm_advisory = None  # type: ignore[assignment]
            if emit_rhythm_advisory is not None:
                scope = {
                    "level": "scene",
                    "chapter_number": chapter_number,
                    "scene_number": scene_number,
                }
                for issue in pre_result.issues:
                    emit_rhythm_advisory(
                        self._active_debt_store,
                        ledger=self.ledger,
                        scope=scope,
                        issue={
                            "code": issue.code,
                            "severity": issue.severity,
                            "message": issue.message,
                            "metric_value": issue.metric_value,
                            "threshold": issue.threshold,
                        },
                        metrics=pre_payload["metrics"],
                    )

        if not self._rhythm_editor_enabled:
            return prose, telemetry

        actionable = [
            i for i in pre_result.issues
            if i.code in self._rhythm_editor_trigger_codes
        ]
        if not actionable:
            self.ledger.emit_info(
                "rhythm_edit_skipped",
                chapter_number=chapter_number,
                scene_number=scene_number,
                agent_role="rhythm_editor",
                payload={"reason": "no_actionable_issues"},
            )
            return prose, telemetry
        if len(pre_result.issues) > self._rhythm_editor_max_trigger_codes:
            self.ledger.emit_info(
                "rhythm_edit_skipped",
                chapter_number=chapter_number,
                scene_number=scene_number,
                agent_role="rhythm_editor",
                payload={
                    "reason": "confusion_threshold",
                    "issue_count": len(pre_result.issues),
                    "threshold": self._rhythm_editor_max_trigger_codes,
                },
            )
            return prose, telemetry

        self.ledger.emit_info(
            "rhythm_edit_fired",
            chapter_number=chapter_number,
            scene_number=scene_number,
            agent_role="rhythm_editor",
            payload={"actionable_count": len(actionable)},
        )

        try:
            editor_result = await self.rhythm_editor.run({
                "prose": prose,
                "scene_card": scene_card,
                "rhythm_issues": [
                    {
                        "code": i.code,
                        "severity": i.severity,
                        "message": i.message,
                        "metric_value": i.metric_value,
                        "threshold": i.threshold,
                    }
                    for i in actionable
                ],
            })
        except Exception as exc:  # noqa: BLE001
            self.ledger.emit_warn(
                "rhythm_edit_error",
                chapter_number=chapter_number,
                scene_number=scene_number,
                agent_role="rhythm_editor",
                payload={"error": f"{exc.__class__.__name__}: {exc}"},
            )
            return prose, telemetry

        edits = editor_result.get("edits", [])
        patched, audit = apply_rhythm_edits(
            prose,
            edits,
            max_edits=self._rhythm_editor_max_edits,
            max_total_changed_chars=self._rhythm_editor_max_total_changed_chars,
            max_changed_ratio=self._rhythm_editor_max_changed_ratio,
        )
        applied_count = sum(1 for a in audit if a["action"] == "applied")
        rejected_count = sum(1 for a in audit if a["action"] == "rejected")

        if applied_count == 0:
            self.ledger.emit_info(
                "rhythm_edit_complete",
                chapter_number=chapter_number,
                scene_number=scene_number,
                agent_role="rhythm_editor",
                payload={
                    "summary": editor_result.get("summary", ""),
                    "proposed": len(edits),
                    "applied": 0,
                    "rejected": rejected_count,
                    "rejection_reasons": [a.get("reason") for a in audit if a["action"] == "rejected"],
                },
            )
            return prose, telemetry

        try:
            post_result = validate_rhythm(
                patched,
                scope="scene",
                scope_id=f"ch{chapter_number:02d}_sc{scene_number:02d}__rhythm_edit",
                thresholds=thresholds,
                require_dialogue=require_dialogue,
            )
            telemetry["post_edit"] = post_result.to_dict()
        except Exception:  # noqa: BLE001 -- post-edit metrics are advisory
            telemetry["post_edit"] = None

        self.ledger.emit_info(
            "rhythm_edit_complete",
            chapter_number=chapter_number,
            scene_number=scene_number,
            agent_role="rhythm_editor",
            payload={
                "summary": editor_result.get("summary", ""),
                "proposed": len(edits),
                "applied": applied_count,
                "rejected": rejected_count,
                "pre_em_dash_per_1k": pre_payload["metrics"]["em_dashes_per_1k_words"],
                "post_em_dash_per_1k": telemetry.get("post_edit", {}).get("metrics", {}).get("em_dashes_per_1k_words") if telemetry.get("post_edit") else None,
            },
        )
        return patched, telemetry

    def _save_chapter(self, chapter_num: int, scene_num: int, prose: str) -> Path:
        """Save the final prose to a markdown file."""
        filename = f"chapter_{chapter_num:02d}_scene_{scene_num:02d}.md"
        output_path = self.manuscripts_dir / filename
        output_path.write_text(prose, encoding="utf-8")
        return output_path
