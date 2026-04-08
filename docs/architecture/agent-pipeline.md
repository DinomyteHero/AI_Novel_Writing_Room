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
| PlotArchitect | `src/agents/plot_architect.py` | `plot_architect` | Scene card -> generation brief |
| ProseStylist | `src/agents/prose_stylist.py` | `prose_stylist` | Generation brief + context -> draft prose |
| GateCritic | `src/agents/gate_critic.py` | `gate_critic` | Prose -> structured pass/fail evaluation |
| CraftEditor | `src/agents/craft_editor.py` | `craft_editor` | Non-blocking voice/polish improvements |
| CanonExpert | `src/agents/canon_expert.py` | `canon_expert` | RAG-powered franchise lore validation |
| CharacterSpecialist | `src/agents/character_specialist.py` | `character_specialist` | Out-of-character detection (supplementary) |
| Summarizer | `src/agents/summarizer.py` | `summarizer` | Chapter compression to summary + state diff |
| OutlinePlanner | `src/agents/outline_planner.py` | `outline_planner` | Concept seed -> structured outline |
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

PlotArchitect reads the scene card and produces a generation brief -- a structured document that translates the scene card's structural requirements into actionable writing instructions.

### 4. Prose Draft

ProseStylist takes the generation brief + assembled context and drafts the chapter prose.

### 5. Gate Evaluation

GateCritic evaluates the draft against a structural rubric and returns a structured `CriticFailure` JSON with:
- Overall verdict: `pass` or `fail`
- Failure codes from `config/failure_codes.yaml` (19 codes across 3 categories)
- Routing decision:
  - `fail_structural` -> full rewrite (back to ProseStylist with failure context)
  - `fail_voice` -> targeted revision (ProseStylist with specific notes)
  - `fail_polish` -> non-blocking (CraftEditor only)

The orchestrator retries structural failures up to `max_structural_retries` (default: 3) and voice failures up to `max_voice_retries` (default: 2).

### 6. Craft Editing

CraftEditor applies non-blocking improvements: voice consistency, prose polish, rhythm, and readability.

### 7. Revision Pipeline (Phase 3+)

The RevisionPipeline runs sequential editing passes. The base pipeline has 3 bands:

| Band | Agent | Focus |
|------|-------|-------|
| 1 | StructuralContinuity | Plot holes, arc consistency, timeline |
| 2 | SceneEmotion | Conflict intensity, turning points, show-don't-tell |
| 3 | LineCopy | Prose quality, grammar, AI-tell removal, rhythm |

Phase 4's AdaptiveRevisionPipeline (`src/revision/adaptive_revision.py`) extends this to 5 bands based on quality metrics:

| Band | Agent | Condition |
|------|-------|-----------|
| 4 | DialoguePolish | Dialogue-heavy scenes with low voice scores |
| 5 | WorldbuildingCoherence | Canon elements present with consistency issues |

Each band's revision prompt is in `prompts/revision_prompts/`.

### 8. Post-Save Pipeline (Phase 2+)

After the chapter is saved:
1. **Summarizer** compresses the chapter to a summary + state diff JSON
2. **ChapterMemory** stores the summary in ChromaDB
3. **StateDiffApplier** applies the state diff to SQLite (character positions, knowledge, plot threads, timeline)
4. **ContradictionScanner** checks the new state against prior state for inconsistencies (5 scan types: truth, belief, promises, timeline, relationships)

### 9. Quality and Milestones (Phase 3+)

1. **MetricsDashboard** runs 4 pure-Python checkers (no LLM calls):
   - RepetitionDetector, PacingAnalyzer, VoiceChecker, SlopDetector
   - Weighted average score (0.25 each), pass threshold >= 0.6
2. **CharacterSpecialist** detects out-of-character behavior (supplementary, non-blocking)
3. **MilestoneGates** pause the pipeline at structural checkpoints (first plot point, midpoint, second plot point) for user approval

### 10. LLM Judge (Phase 4, optional)

JudgeEvaluator uses a cloud model to score the chapter across 5 dimensions defined in `config/eval_rubric.yaml`.

## Event Logging

Every step emits a typed event to the RunLedger. Event types include:
- `pipeline_start`, `pipeline_complete`
- `chapter_start`, `agent_start`, `agent_complete`
- `gate_pass`, `gate_fail`
- `craft_edit_complete`
- `revision_band_start`, `revision_band_complete`
- `state_diff_proposed`, `state_diff_committed`
- `contradiction_scan`, `summarizer_complete`
- `milestone_reached`, `milestone_gate_paused`
- `judge_evaluation`, `export_complete`
