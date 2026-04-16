# Agent Pipeline

This document describes how the multi-agent generation loop works, from scene card input to saved chapter.

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
| GateCritic | `src/agents/gate_critic.py` | `gate_critic` | Prose -> structured pass/fail evaluation (Scene Gate) |
| QualityPolish | `src/agents/quality_polish.py` | `quality_polish` | Single bounded expression-level polish pass (replaces Craft Editor + 3 revision bands) |
| FinalGate | `src/agents/final_gate.py` | `final_gate` | Contract check on the polished text (unit of truth) |
| ChapterGateCritic | `src/agents/chapter_gate_critic.py` | `chapter_gate_critic` | Whole-chapter evaluation against the blueprint + composition heuristics |
| CanonExpert | `src/agents/canon_expert.py` | `canon_expert` | Franchise-agnostic, template-driven lore validation (reads canon_profile from concept seed) |
| CharacterSpecialist | `src/agents/character_specialist.py` | `character_specialist` | Out-of-character detection (supplementary) |
| Summarizer | `src/agents/summarizer.py` | `summarizer` | Chapter compression to summary + state diff |
| OutlinePlanner | `src/planning/scene_card_generator.py` | `outline_planner` | Concept seed -> structured outline |
| JudgeEvaluator | `src/quality/llm_judge.py` | `judge_evaluator` | LLM-as-judge 5-dimension evaluation |
| ManuscriptReviewer | `src/agents/manuscript_reviewer.py` | `manuscript_reviewer` | Dual-persona full-manuscript evaluation |

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

### 5. Canon Validation

CanonExpert runs before the Gate Critic to validate franchise lore compliance. The canon expert has been rewritten as a franchise-agnostic, template-driven agent: it reads the `canon_profile` section from the concept seed (franchise name, continuity rules, cross-continuity violations, anachronistic terms) and uses those to drive validation. There are zero franchise-specific strings hardcoded in the agent -- all franchise knowledge comes from the concept seed and RAG retrieval.

### 6. Scene Gate Evaluation

GateCritic evaluates the draft against a structural rubric and returns a structured `CriticFailure` JSON with:
- Overall verdict: `pass`, `fail_structural`, `fail_voice`, or `fail_polish`
- Failure codes from `config/failure_codes.yaml` (includes the programmatic `WORD_COUNT_VIOLATION` injected at the agent boundary when the draft is outside ±20% of target)
- **Calibration anchors**: scores use a 0.60-1.00 scale with defined anchor points
- **Chain-of-thought reasoning**: the critic includes a `reasoning` field explaining its evaluation logic
- Routing decision:
  - `fail_structural` -> full rewrite (back to ProseStylist with failure context)
  - `fail_voice` -> targeted revision (ProseStylist with specific notes)
  - `fail_polish` -> no rewrite; proceeds to Quality Polish where any remaining issues are handled or rejected by the Final Gate

Note: `CANON_VIOLATION` has been promoted from `POLISH_CODES` to `STRUCTURAL_CODES`, meaning canon violations now trigger full rewrites rather than non-blocking edits.

The orchestrator retries structural failures up to `max_structural_retries` (default: 3) and voice failures up to `max_voice_retries` (default: 2).

### 7. Quality Polish

QualityPolish runs a single bounded expression-level pass on the gate-passed prose. It **can** fix show-don't-tell violations, word choice, AI-tells, sentence rhythm, and dialogue tags. It **cannot** add/remove beats or characters, change the turning point, or extend past the closing hook. Quality Polish replaces the previous Craft Editor + 3 revision bands — see `docs/architecture/pipeline-redesign.md` for the rationale.

### 8. Compression Guard + Final Gate

Two guards catch polish drift before the prose is saved:

1. **Compression guard** (deterministic): if polished word count < 80% of gate-passed word count, the orchestrator rejects the polish and keeps the gate-passed draft. Emits `compression_guard_fired`.
2. **Final Gate** (LLM + deterministic): runs a contract check on the polished text — characters present, closing hook boundary, word-count floor. If it fails, the polish is rejected and the gate-passed draft is saved instead. Emits `final_gate_complete` or `final_gate_rejection`.

The Final Gate is the pipeline's unit-of-truth check: the only quality evaluation that runs on the exact text that gets saved.

### 9. Post-Save Pipeline (Phase 2+)

After the chapter is saved:
1. **Summarizer** compresses the chapter to a summary + state diff JSON. The orchestrator injects a current state snapshot (characters, subplots, hooks with their exact current values) so the Summarizer can produce accurate `old_value` fields. The Summarizer prompt includes all valid enum values and arc-type-specific phase progressions.
2. **ChapterMemory** stores the summary in ChromaDB
3. **StateDiffApplier** sanitizes the diff (fuzzy-matching near-miss enum values, correcting `old_value` mismatches, stripping no-ops) then applies it to SQLite
4. **ContradictionScanner** checks the new state against prior state for inconsistencies (5 scan types: truth, belief, promises, timeline, relationships)

### 10. Quality Metrics and Milestones (Phase 3+)

1. **MetricsDashboard** runs pure-Python checkers (no LLM calls) and feeds results into Quality Polish:
   - RepetitionDetector, PacingAnalyzer, VoiceChecker, SlopDetector
   - Weighted average score, pass threshold >= 0.6
   - Metrics advise; they do not block. Contract checks (Scene Gate, Final Gate, Chapter Gate) do the blocking.
2. **CharacterSpecialist** detects out-of-character behavior (supplementary, non-blocking)
3. **MilestoneGates** pause the pipeline at structural checkpoints (first plot point, midpoint, second plot point) for user approval

### 11. Chapter Gate (after all scenes pass)

ChapterGateCritic evaluates the assembled chapter after every scene has cleared its Scene Gate. When a `chapter_blueprint.json` exists at `data/franchises/{franchise}/books/{book}/chapter_blueprints/chapter_{NN}.json`, the critic's prompt includes blueprint-aware checks (chapter mission, chapter turn, reveal payload, subplot obligations, pacing curve, exit vector) alongside the existing composition heuristics. Blueprint checks are advisory — failures surface in `chapter_level_failures` for diagnostics rather than blocking the save.

### 12. LLM Judge (Phase 4, optional)

JudgeEvaluator uses a cloud model to score the chapter across 5 dimensions defined in `config/eval_rubric.yaml`.

## Event Logging

Every step emits a typed event to the RunLedger. Event types include:
- `pipeline_start`, `pipeline_complete`
- `chapter_start`, `agent_start`, `agent_complete`
- `gate_pass`, `gate_fail`
- `final_gate_complete`, `final_gate_rejection`
- `compression_guard_fired`
- `state_diff_proposed`, `state_diff_committed`
- `contradiction_scan`, `summarizer_complete`
- `milestone_reached`, `milestone_gate_paused`
- `judge_evaluation`, `export_complete`
