# Agent Pipeline

This document describes how the multi-agent generation loop works, from scene card input to saved chapter.

## Default Production Mode

The current production default is lean mode (`runtime.lean_prose_only.enabled: true`): `PlotArchitect -> ProseStylist -> LineWriter -> save`. In that path, broad scene gates, QualityPolish, FinalGate, CanonExpert, PresenceChecker, chapter gates, and post-save LLM analysis are skipped unless explicitly enabled for a diagnostic or benchmark run.

The fuller relay documented below remains real code and is still useful for experiments, telemetry, and non-lean runs. For final manuscript work after export, use the [Manuscript Production Lifecycle](manuscript-production-lifecycle.md): full manuscript review, targeted revision, targeted cleanup, optional literary donor pass, and deterministic validation.

## BaseAgent Pattern

All agents extend `BaseAgent` (`src/agents/base_agent.py`):

```python
class BaseAgent(ABC):
    def __init__(self, router: ModelRouter, role: str):
        self.router = router
        self.role = role
        self.system_prompt = self._load_system_prompt()  # from prompts/agent_system_prompts/{role}.md

    async def run(self, context: dict) -> dict:       # Free-text response
    async def run_structured(self, context: dict) -> dict:  # JSON response

    @abstractmethod
    def _format_context(self, context: dict) -> str:   # Build user prompt
    @abstractmethod
    def _parse_response(self, response: str, context: dict) -> dict:  # Parse output
```

Each agent:
- Has a single responsibility (one cognitive task)
- Loads its system prompt from `prompts/agent_system_prompts/{role}.md`
- Communicates exclusively through the ModelRouter
- Returns structured output (dict)

## Agent Roles

| Agent | File | Role Key | Task |
|-------|------|----------|------|
| PlotArchitect | `src/agents/plot_architect.py` | `plot_architect` | Scene card -> typed generation brief (JSON per `schemas/generation_brief.json`) |
| ProseStylist | `src/agents/prose_stylist.py` | `prose_stylist` | Typed generation brief + context -> draft prose |
| LineWriter | `src/agents/line_writer.py` | `line_writer` | Optional line-editing pass (GPT-5.4 Mini @ t=0.35 in the shipping config). Preserves beats, POV, characters_present, canon while rewriting sentence-level rhythm, imagery, and voice texture. In lean mode it runs when `runtime.lean_prose_only.line_edit.enabled: true`; in non-lean runs it is skipped in `--raw-draft` and when no `line_writer` routing entry is configured. |
| GateCritic | `src/agents/gate_critic.py` | `gate_critic` | Prose -> structured pass/fail evaluation (Scene Gate). Advisory only under the forward-only relay — verdicts are logged but do not block or retry. |
| QualityPolish | `src/agents/quality_polish.py` | `quality_polish` | Single bounded expression-level polish pass (replaces Craft Editor + 3 revision bands) |
| FinalGate | `src/agents/final_gate.py` | `final_gate` | Contract check on the current post-polish text. Advisory only — emits `final_gate_rejection` with `advisory_only=True`; prose still proceeds unless the compression guard has already reverted it or the save-blocker layer fires. |
| CanonExpert | `src/agents/canon_expert.py` | `canon_expert` | Continuity editor. Runs **after FinalGate** as the last reader on the current post-polish text; its verdict feeds the `CANON_BLOCKER` save-blocker. Franchise-agnostic, template-driven: reads `canon_profile` from the concept seed. |
| PresenceChecker | `src/agents/presence_checker.py` | `presence_checker` | Save-blocker agent. Detects named characters who speak or act in the prose despite being absent from the scene card's `characters_present` list; fires `CHARACTER_PRESENCE_BLOCKER`. |
| MicroRepair | `src/agents/micro_repair.py` | `micro_repair` | Optional bounded post-check repair agent. Converts presence findings into exact literal substitutions only; never rewrites paragraphs, adds beats, or introduces new names. Disabled by default. |
| ChapterGateCritic | `src/agents/chapter_gate_critic.py` | `chapter_gate_critic` | Whole-chapter evaluation against the blueprint + composition heuristics |
| CharacterSpecialist | `src/agents/character_specialist.py` | `character_specialist` | Out-of-character detection (supplementary) |
| Summarizer | `src/agents/summarizer.py` | `summarizer` | Chapter compression to summary + state diff |
| OutlinePlanner | `src/planning/scene_card_generator.py` | `outline_planner` | Concept seed -> structured outline |
| JudgeEvaluator | `src/quality/llm_judge.py` | `judge_evaluator` | LLM-as-judge 5-dimension evaluation |
| ManuscriptReviewer | `src/agents/manuscript_reviewer.py` | `manuscript_reviewer` | GPT-5.4 full-manuscript evaluation that produces the editorial docket for targeted revision |

## Per-Chapter Flow (Orchestrator)

The Orchestrator (`src/orchestrator.py`) processes each scene card through this flow:

### 1. Pre-Chapter Validation (Phase 4)

PhysicsEnforcer runs pre-chapter validation: causality chains, revelation timing, promise/payoff consistency.

### 2. Context Assembly

ContextAssembler (`src/memory/context_assembler.py`) builds the prompt payload with a four-tier memory system:
- Story bible + concept seed
- Act-level summary
- ChromaDB chapter summaries (semantic retrieval)
- Recent prose from prior chapters
- Canon RAG results (when available)
- Character knowledge and voice sheets

### 3. Generation Brief

PlotArchitect reads the scene card and produces a generation brief -- a structured document that translates the scene card's structural requirements into actionable writing instructions. The orchestrator injects a current character state snapshot (locations, emotional states, arc phases) so the brief reflects accurate story state.

### 4. Prose Draft

ProseStylist takes the generation brief + assembled context and drafts the chapter prose. Dynamic overused words from the cross-scene tracker (see [Quality and Revision](quality-and-revision.md#cross-scene-overused-word-tracker)) are injected into the Prose Stylist prompt for subsequent scenes, helping avoid manuscript-level repetition.

### 5. Line Editing (optional)

LineWriter runs an optional line-editing pass between ProseStylist and the next stage. It receives the source prose, scene card, generation brief, characters_present list, franchise profile, and POV approach as an explicitly wired context dict so it cannot reach into ambient ContextAssembler state. LineWriter preserves the structural beats, turning point, POV, and canon while rewriting sentence-level rhythm, imagery, and voice texture. In lean mode it runs when `runtime.lean_prose_only.line_edit.enabled` is true; in non-lean mode it is skipped in `--raw-draft` mode and when no `line_writer` routing entry is configured. If LineWriter infrastructure fails or its output collapses below 40% of the source word count, the orchestrator falls back to the drafter's prose and emits a warn-level `line_writer_error` or `line_writer_collapsed` event.

### 6. Scene Gate Evaluation (advisory)

GateCritic evaluates the draft against a structural rubric and returns a structured `CriticFailure` JSON with:
- Overall verdict: `pass`, `fail_structural`, `fail_voice`, or `fail_polish`
- Failure codes from `config/failure_codes.yaml`
- **Calibration anchors**: scores use a 0.60-1.00 scale with defined anchor points
- **Chain-of-thought reasoning**: the critic includes a `reasoning` field explaining its evaluation logic

Under the forward-only relay (Stage 1a+), the verdict is **advisory only**: the orchestrator logs the evaluation to the ledger and proceeds to QualityPolish regardless of outcome. The old routing logic (`fail_structural` → full rewrite, `fail_voice` → targeted revision) has been removed; `max_structural_retries` and `max_voice_retries` are pinned to `0` and have no runtime effect. Retaining Gate Critic as telemetry lets bench analyses and the run ledger surface craft concerns without blocking the pipeline.

### 7. Quality Polish

QualityPolish runs a single bounded expression-level pass on the gate-passed prose. It **can** fix show-don't-tell violations, word choice, AI-tells, sentence rhythm, and dialogue tags. It **cannot** add/remove beats or characters, change the turning point, or extend past the closing hook. Quality Polish replaces the previous Craft Editor + 3 revision bands — see `docs/architecture/pipeline-redesign.md` for the rationale.

In lean production mode, this step is skipped. LineWriter is the only post-draft scene-level edit before save; manuscript-level cleanup happens after export.

### 8. Compression Guard + Final Gate (advisory)

Two signals catch polish drift before the prose is saved:

1. **Compression guard** (deterministic): if polished word count < 60% of pre-polish word count, emits a `compression_guard_fired` event with `reverted: true` and keeps the gate-passed draft instead. Downstream FinalGate, CanonExpert, PresenceChecker, and save-blocker checks evaluate the reverted prose.
2. **Final Gate** (LLM + deterministic): runs a contract check on the current post-polish text — characters present, closing hook boundary, word-count floor. On rejection it emits `final_gate_rejection` with `advisory_only=True`; the prose still proceeds unless the compression guard has already reverted it or the save-blocker layer fires. Passing the gate emits `final_gate_complete`.

Under the old pipeline the Final Gate was the save-path's unit-of-truth. Post-Stage-1 it is telemetry; the save-blocker layer (step 10) is the new unit-of-truth for whether a scene writes to disk at all.

### 9. Continuity Editor (CanonExpert)

CanonExpert runs **after** FinalGate, as the last reader on the current post-polish prose. The canon expert is a franchise-agnostic, template-driven agent: it reads the `canon_profile` section from the concept seed (franchise name, continuity rules, cross-continuity violations, anachronistic terms) and uses those plus RAG retrieval to drive validation. There are zero franchise-specific strings hardcoded in the agent. Its verdict feeds the `CANON_BLOCKER` save-blocker in step 10: `verdict == "fail"` with any finding at `critical` or `moderate` severity fires the blocker; lower severities are advisory only.

When `runtime.canon_expert.apply_local_fixes=true`, whitelisted `local_fixes` can be applied as narrow literal substitutions before the save-blocker layer. If any such fix changes the prose, CanonExpert is rerun on the patched text so blocker decisions are based on the repaired artifact rather than the stale pre-fix report.

### 10. Save-Blocker Layer + Quarantine

The only hard stopping point in the relay. Three blocker categories run after the continuity editor (see [`src/pipeline/save_blockers.py`](../../src/pipeline/save_blockers.py)):

1. **`CHARACTER_PRESENCE_BLOCKER`** — dedicated PresenceChecker agent detects named characters who speak or act in the prose despite being absent from the scene card's `characters_present` list.
2. **`CANON_BLOCKER`** — CanonExpert (continuity editor) returned `verdict == "fail"` with at least one finding at `critical` or `moderate` severity.
3. **POV advisory** — regex heuristic flags non-POV interiority verbs. Advisory only in v1; will be promoted to a blocker after corpus validation.

When `runtime.micro_repair.enabled=true`, the orchestrator precomputes presence violations before blocker evaluation and gives them to MicroRepair. MicroRepair may propose only exact literal substitutions. Deterministic guardrails enforce: one literal match only, bounded diff size, bounded changed-text ratio, and no replacement containing the absent character's name. If a safe patch lands, PresenceChecker reruns on the patched prose before save; otherwise the original blocker path proceeds unchanged.

A non-empty blocker list causes the orchestrator to write the offending scene's prose + blockers.json + brief.json to `<project>/quarantine/chNN_scMM/` and raise `SaveBlockedError`, aborting the entire run. No partial chapters ship: quarantine-on-first-blocker policy.

### 11. Post-Save Pipeline (Phase 2+)

After the chapter is saved:
1. **Summarizer** compresses the chapter to a summary + state diff JSON. The orchestrator injects a current state snapshot (characters, subplots, hooks with their exact current values) so the Summarizer can produce accurate `old_value` fields. The Summarizer prompt includes all valid enum values and arc-type-specific phase progressions.
2. **ChapterMemory** stores the summary in ChromaDB
3. **StateDiffApplier** sanitizes the diff (fuzzy-matching near-miss enum values, correcting `old_value` mismatches, stripping no-ops) then applies it to SQLite
4. **ContradictionScanner** checks the new state against prior state for inconsistencies (5 scan types: truth, belief, promises, timeline, relationships)

### 12. Quality Metrics and Milestones (Phase 3+)

1. **MetricsDashboard** runs pure-Python checkers (no LLM calls) and feeds results into Quality Polish:
   - RepetitionDetector, PacingAnalyzer, VoiceChecker, SlopDetector
   - Weighted average score, pass threshold >= 0.6
   - Metrics advise; they do not block. Under the forward-only relay, blocking is exclusively the save-blocker layer's job.
2. **CharacterSpecialist** detects out-of-character behavior (supplementary, non-blocking)
3. **MilestoneGates** pause the pipeline at structural checkpoints (first plot point, midpoint, second plot point) for user approval

### 13. Chapter Gate (after all scenes in the chapter are saved)

ChapterGateCritic evaluates the assembled chapter after every scene has been saved. When a `chapter_blueprint.json` exists at `data/franchises/{franchise}/books/{book}/chapter_blueprints/chapter_{NN}.json`, the critic's prompt includes blueprint-aware checks (chapter mission, chapter turn, reveal payload, subplot obligations, pacing curve, exit vector) alongside the existing composition heuristics. Blueprint checks are advisory — failures surface in `chapter_level_failures` for diagnostics rather than blocking the save.

### 14. LLM Judge (Phase 4, optional)

JudgeEvaluator uses a cloud model to score the chapter across 5 dimensions defined in `config/eval_rubric.yaml`.

## Post-Manuscript Production

After a lean manuscript is exported, the default production path moves from per-scene agents to manuscript-level editorial control:

1. Run `manuscript_reviewer` on GPT-5.4 to create a full-book docket.
2. Apply targeted revision patches for major docket items.
3. Run targeted cleanup as the default polish branch.
4. Optionally run full literary polish as a comparison or donor branch, then cherry-pick only safe improvements.
5. Apply the final docket pass and run `scripts/manuscript_final_validation.py`.

The targeted cleanup branch is the production base unless manual comparison shows a concrete reason to choose otherwise. Full literary polish is not the default master because it can introduce visible prose style and tonal drift.

## Event Logging

Every step emits a typed event to the RunLedger. Events carry a `level` field (`info`, `warn`, `error`) in the payload. The canonical list lives in [`src/run_ledger.py`](../../src/run_ledger.py); current event types include:

- `pipeline_start`, `pipeline_complete`
- `chapter_start`, `agent_start`, `agent_complete`
- `gate_pass`, `gate_fail` (advisory under the forward-only relay)
- `line_writer_error`, `line_writer_collapsed` (Stage 3 — LineWriter fallback signals)
- `final_gate_complete`, `final_gate_rejection` (rejection carries `advisory_only=True`)
- `compression_guard_fired` (warn; `reverted=True` when the guard keeps the gate-passed draft)
- `save_blocked` (run aborted; scene quarantined)
- `continuity_editor_complete` (CanonExpert verdict used by the CANON_BLOCKER)
- `continuity_editor_recheck_complete` (CanonExpert rerun after applied local fixes)
- `micro_repair_fired`, `micro_repair_applied`, `micro_repair_rejected`, `micro_repair_complete`
- `chapter_word_count_telemetry` (chapter-close advisory at ±15% / ±15-30% / >30% thresholds)
- `state_diff_proposed`, `state_diff_committed`
- `contradiction_scan`, `summarizer_complete`
- `milestone_reached`, `milestone_gate_paused`
- `judge_evaluation`, `export_complete`
