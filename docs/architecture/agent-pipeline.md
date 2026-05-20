# Agent Pipeline

This document describes how the lean multi-agent generation loop works, from scene card input to saved chapter.

## The Lean Forward Pass

The pipeline drafts each scene in a **single forward pass**. There are no gates, no save-blocker layer, no quarantine, no retries:

```
PlotArchitect -> ProseStylist -> [LineWriter] -> [RhythmValidator -> RhythmEditor]
  -> save -> post-save memory
```

`[...]` steps are optional. `LineWriter` runs when `runtime.lean_prose_only.line_edit.enabled` is true and an `agent_routing.line_writer` entry exists (the shipping default). The rhythm stages are flag-gated and default-off.

The drafter is expected to land the scene contract on the first pass. The structural framework (Brooks beat map + Weiland arc map + scene contract) is enforced *upstream*, at planning and scene-card validation time; the chapter packet hands the drafter a single inspectable runtime contract. There is no save-time editorial gate to catch drift — quality is a planning-and-prompt problem, not a retry problem.

After a manuscript is drafted, manuscript-level editorial passes run separately — see [Manuscript Production Lifecycle](manuscript-production-lifecycle.md).

## BaseAgent Pattern

All agents extend `BaseAgent` (`src/agents/base_agent.py`):

```python
class BaseAgent(ABC):
    def __init__(self, router: ModelRouter, role: str):
        self.router = router
        self.role = role
        self.system_prompt = self._load_system_prompt()  # from prompts/agent_system_prompts/{role}.md

    async def run(self, context: dict) -> dict:               # Free-text response
    async def run_structured(self, context: dict) -> dict:    # JSON response

    @abstractmethod
    def _format_context(self, context: dict) -> str:          # Build user prompt
    @abstractmethod
    def _parse_response(self, response: str, context: dict) -> dict:  # Parse output
```

Each agent:
- Has a single responsibility (one cognitive task)
- Loads its system prompt from `prompts/agent_system_prompts/{role}.md`
- Communicates exclusively through the ModelRouter
- Returns structured output (dict)

## Agent Roles

### Scene-path agents

| Agent | File | Role Key | Task |
|-------|------|----------|------|
| PlotArchitect | `src/agents/plot_architect.py` | `plot_architect` | Scene card -> typed generation brief (JSON per `schemas/generation_brief.json`) |
| ProseStylist | `src/agents/prose_stylist.py` | `prose_stylist` | Primary drafter. Generation brief + chapter packet -> draft prose |
| LineWriter | `src/agents/line_writer.py` | `line_writer` | Optional single post-draft line-edit pass. Preserves beats, turning point, POV, `characters_present`, and canon while rewriting sentence-level rhythm, imagery, and voice texture. Takes an **explicitly wired** context dict — does not reach into the ambient `ContextAssembler`. |
| RhythmEditor | `src/agents/rhythm_editor.py` | `rhythm_editor` | Optional bounded literal-edit pass that fixes rhythm issues flagged by `RhythmValidator`. Exact-span replacements only; deterministic safety caps enforced by `apply_rhythm_edits()`. Default off (`runtime.rhythm_editor.enabled`). |
| Summarizer | `src/agents/summarizer.py` | `summarizer` | Post-save: scene summary + state diff that feed chapter memory, story state, and the contradiction scan |

`RhythmValidator` (`src/quality/rhythm_validator.py`) is a deterministic analyzer, not an LLM agent — it measures five prose-rhythm metrics and emits advisory revision-debt rows. It never blocks a save.

### Auxiliary agents (not in the per-scene path)

| Agent | File | Role Key | Task |
|-------|------|----------|------|
| SeedBuilder | `src/agents/seed_builder.py` | `seed_builder` | Converts a planning manuscript into a concept seed (`--import-summary`) |
| EditorialConsultant | `src/agents/editorial_consultant.py` | `editorial_consultant` | Compile-time qualitative editorial review used by `scripts/compile_bundle.py` |
| CanonScout | `src/agents/canon_scout.py` | `canon_scout` | Pre-run canon-guidance authoring (`scripts/canon_scout.py`) |
| LiteraryPolish | `src/agents/literary_polish.py` | `literary_polish` | Post-production literary-polish pass (final pre-publication sweep) |
| ManuscriptReviewer | `src/agents/manuscript_reviewer.py` | `manuscript_reviewer` | Full-manuscript developmental review; output lands in revision-debt rows |

See [`src/agents/README.md`](../../src/agents/README.md) for the scene-path / utility split.

## Per-Scene Flow (Orchestrator)

The Orchestrator (`src/orchestrator.py::run_chapter`) processes each scene card through this flow.

### 1. Context Assembly + Chapter Packet

`ContextAssembler` (`src/memory/context_assembler.py`) builds the flat prompt payload with a four-tier memory system: story bible, act-level summary, ChromaDB chapter summaries (semantic retrieval), recent prose, plus canon RAG, worldbuilding lore/terminology, character knowledge, and voice sheets when available.

When `runtime.chapter_packet.enabled` is true (the shipping default), `ChapterPacketCompiler` (`src/pipeline/chapter_packet.py`) builds the drafter's single inspectable runtime contract: a per-chapter **base** composed once, then a per-scene **overlay** that adds the current scene card and trusted state. The overlay renderer embeds the flat `ContextAssembler` output, so the packet is a strict token-superset of flat context. On a compile error a `packet_fallback_flat` warn event fires and the drafter falls back to flat context (`runtime.chapter_packet.fallback_on_error`).

### 2. Generation Brief

`PlotArchitect` reads the scene card and produces a typed generation brief (`schemas/generation_brief.json`) — a per-beat plan that translates the scene card's structural requirements into actionable writing instructions. The orchestrator injects a current character-state snapshot, hook agenda, and active subplots so the brief reflects accurate story state.

### 3. Prose Draft

`ProseStylist` takes the generation brief plus the chapter packet (or flat context on fallback) and drafts the scene prose. Dynamic cross-scene feedback — overused words flagged in prior scenes, description-ratio drift — is injected into the prompt so the drafter avoids manuscript-level repetition.

### 4. Line Editing (optional)

`LineWriter` runs a single line-edit pass after the drafter when `runtime.lean_prose_only.line_edit.enabled` is true and a `line_writer` routing entry exists. It receives an explicitly wired context dict (source prose, scene card, generation brief, `characters_present`, franchise profile, POV approach) so it cannot reach into ambient `ContextAssembler` state. It preserves the structural beats, turning point, POV, and canon while rewriting sentence-level rhythm, imagery, and voice texture.

If LineWriter crashes, the orchestrator keeps the drafter prose and emits a warn-level `line_writer_error` event. If its output collapses below 40% of the source word count, the orchestrator keeps the drafter prose and emits `line_writer_collapsed`. Neither degradation aborts the scene.

### 5. Rhythm Validation + Edit (optional, advisory)

When `runtime.rhythm_validator.enabled` is true, `RhythmValidator` measures five rhythm metrics (em-dash density, consecutive short-sentence runs, default-opener percentage, dialogue-bearing paragraph percentage, abstract-construction tic density) and emits revision-debt rows of category `prose.rhythm.*`. It only measures — it never blocks or mutates prose.

When `runtime.rhythm_editor.enabled` is also true and the validator finds at least one actionable issue, `RhythmEditor` proposes bounded literal substring edits. `apply_rhythm_edits()` enforces deterministic safety caps (per-call edit count, total changed-char budget, changed-ratio ceiling) regardless of model output. Both stages are default-off; neither can abort a save.

### 6. Save

The post-edit prose is written to `<run_dir>/chapters/chapter_NN_scene_MM.md` and a `lean_prose_only_saved` info event fires. The save status is `saved_clean` (the normal outcome) or `saved_with_advisory`. There is no failure path that prevents a scene from saving.

### 7. Post-Save Memory

After the scene is saved, the orchestrator runs the memory chain. Every stage is wrapped in a broad error guard — a crash emits a warn-level event (`post_save_error` with a `stage` tag) but never aborts the saved scene; next-scene state may be stale, so the warn is load-bearing.

1. **Summarizer** compresses the scene to a summary + state-diff JSON. The orchestrator injects a current state snapshot and arc-state guidance so the diff carries accurate `old_value` fields.
2. **ChapterMemory** stores the summary in ChromaDB.
3. **StateDiffApplier** sanitizes the diff (fuzzy-matching near-miss enum values, correcting `old_value` mismatches, stripping no-ops) then applies it to SQLite.
4. **Chapter/scene log** records word count, structural phase, POV, and revision status in story state.
5. **ContradictionScanner** checks the new state against prior state across five scan types (truth, belief, promises, timeline, relationships).
6. **Worldbuilding extraction** runs when a `lore_service` and franchise binding are present: `lore_extractor` writes `provisional` lore entries, and `LoreConflictDetector` scans them and emits advisory `lore_conflicts` events. Extraction and conflict detection are advisory — they never block a saved scene.

If `runtime.promise_ledger.enabled` is on, the orchestrator also records declared promise deltas (`promises_progressed`, `promises_paid`) from the scene card and surfaces newly overdue promises as warn-level `promise_overdue` telemetry.

## Post-Draft: Manuscript Production

The per-scene pipeline produces raw scene prose; manuscript-level editorial happens afterward and never rewrites prose in place during a drafting run. The default path: export the manuscript, run `manuscript_reviewer` on GPT-5.4 to produce an editorial docket, apply targeted revision and cleanup patches through `scripts/patch_workflow.py`, optionally run `literary_polish` as a donor/comparison branch, then run deterministic final validation. See [Manuscript Production Lifecycle](manuscript-production-lifecycle.md) and [Quality and Revision](quality-and-revision.md).

## Event Logging

Every step emits a typed event to the RunLedger. Events carry a `level` field (`info`, `warn`, `error`) in the payload. The canonical list lives in [`src/run_ledger.py`](../../src/run_ledger.py); current event types include:

- `pipeline_start`, `pipeline_complete`, `chapter_start`
- `agent_start`, `agent_complete`
- `lean_prose_only_saved` (carries line-edit and rhythm telemetry)
- `line_writer_error`, `line_writer_collapsed`, `lean_line_edit_unavailable`
- `rhythm_validation`, `rhythm_edit_fired`, `rhythm_edit_complete`, `rhythm_edit_skipped`
- `packet_base_compiled`, `packet_overlay_written`, `packet_fallback_flat`
- `revision_debt_added`, `revision_debt_updated`
- `promise_progressed`, `promise_paid`, `promise_overdue`
- `summarizer_complete`, `state_diff_proposed`, `state_diff_committed`, `contradiction_scan`
- `lore_conflicts`, `post_save_error`
- `chapter_blueprints_generated`, `session_resume`, `session_save`
