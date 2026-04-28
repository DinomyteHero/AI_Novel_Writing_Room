# Quality and Revision

Current production defaults to lean mode, where the per-scene refinement stack is bypassed and LineWriter is the only post-draft scene edit. Quality and revision decisions then move to the full-manuscript lifecycle: GPT-5.4 review, targeted revision, targeted cleanup, final docket pass, and deterministic validation.

The system uses pure-Python quality metrics (no LLM calls) to score scenes, then runs a bounded LLM refinement pass (QualityPolish) whose output is checked by a compression guard and a Final Gate before it is saved. Under the forward-only relay, FinalGate verdicts are **advisory**: the polished prose is saved unless the compression guard reverts to the gate-passed draft or the save-blocker layer fires. The only hard-failure path is save-blockers (CHARACTER_PRESENCE_BLOCKER, CANON_BLOCKER critical/moderate, POV advisory), which quarantines the scene and aborts the run.

> **Note — pipeline redesign.** Earlier builds ran a multi-band revision pipeline (StructuralContinuity → SceneEmotion → LineCopy → optional DialoguePolish / WorldbuildingCoherence) after the Gate. That pipeline has been removed entirely. Polish is now a single pass followed by a Final Gate advisory and the save-blocker layer. The old `prompts/revision_prompts/` directory and `src/revision/` module that backed the revision bands have both been deleted; older docs that reference them describe a dead code path.

## Quality Metrics

`src/quality/metrics_dashboard.py` aggregates 4 independent checkers:

### RepetitionDetector (`src/quality/repetition_detector.py`)

Detects repetitive patterns:
- Word frequency analysis (over-used words)
- N-gram repetition (repeated phrases)
- Paragraph-opening similarity (varied opener diversity)
- Semantic similarity between paragraphs (via embeddings when available)

Configurable parameters (set via constructor or loaded from concept seed `quality_overrides`):
- `word_frequency_allowlist` — franchise-specific words excluded from overuse detection (e.g., "Force", "lightsaber" for Star Wars). Case-insensitive.
- `semantic_similarity_threshold` — cosine similarity above which paragraph pairs are flagged (default: 0.85). Raise for franchise-dense prose.
- `adjacency_window` — when set, only compares paragraphs within N positions of each other, reducing false positives from distant thematic echoes.

### PacingAnalyzer (`src/quality/pacing_analyzer.py`)

Measures prose rhythm:
- Sentence length variance (monotonous vs. varied)
- Dialogue ratio (balance of dialogue to narration)
- Scene type classification
- Event density (action pacing) -- thresholds recalibrated from (2-10)/1k words to (20-65)/1k words to better reflect the density of well-paced fiction

### VoiceChecker (`src/quality/voice_checker.py`)

Enforces style constraints from `config/negative_constraints.yaml`:
- Banned phrase detection (faux profundity, sensory cliches, magic adverbs, AI tells)
- Adverb density limits
- Metaphor cooldown (distance between figurative language)
- Voice fidelity scoring

In Phase 5, per-project voice definition rules from the concept seed's `voice_definition` field (defined during the Concept Workshop's Voice Discovery step) are merged with the static negative constraints, enabling project-specific anti-slop rules and anti-patterns.

### SlopDetector (`src/quality/slop_detector.py`)

Identifies AI-typical writing patterns:
- AI-tell word lists (from negative constraints)
- Burstiness scoring (unnatural pattern repetition)
- Show-don't-tell flagging
- Filler pattern detection

### Scoring

MetricsDashboard runs all 4 checkers and computes a weighted average:
- Each checker contributes 0.25 weight
- Pass threshold: overall score >= 0.6
- Results are stored in the chapter log

### Structured Quality Flags

Quality metrics produce structured flags that are passed to QualityPolish so the refinement pass can target specific issues instead of rewriting broadly:

- **flagged_words**: A dictionary of overused words with counts (e.g., `{"whispered": 7, "nodded": 5}`). Passed to QualityPolish for targeted replacement with count context.
- **description_ratio**: The ratio of descriptive narration to total prose. When this exceeds 0.60 (60% description), it is passed to QualityPolish to trigger description rebalancing.

### Cross-Scene Overused Word Tracker

A manuscript-level tracker aggregates overused words across all generated scenes (not just per-chapter). After each chapter, newly flagged words are merged into the tracker. These accumulated overused words are dynamically injected into the Prose Stylist prompt for subsequent scenes, helping the drafting agent proactively avoid manuscript-level repetition patterns.

## Full Relay Refinement Path: QualityPolish → Compression Guard → Final Gate

In non-lean runs, after a draft passes the Scene Gate, the orchestrator runs a single bounded refinement pass and validates its output before saving.

### QualityPolish (`src/agents/quality_polish.py`)

A single LLM pass that receives the Gate-passed draft plus the structured quality flags (flagged_words, description_ratio, etc.) and produces a refined version. Unlike the old multi-band pipeline, QualityPolish does not recursively re-edit — it makes one pass and hands off.

### Compression Guard

The orchestrator rejects polish output that significantly drops or compresses material relative to the Gate-passed draft. If the polished word count falls below 60% of the gate-passed draft, the saved candidate reverts to the gate-passed draft and `compression_guard_fired` is emitted with `reverted: true`.

### Final Gate (`src/agents/final_gate.py`)

Validates the polished prose against the scene card contract:

- Closing-hook boundary (the scene ends where the card says it should)
- Turning point is identifiable in the final prose (no polish-induced flattening)

Final Gate emits structural failure codes (`CLOSING_HOOK_VIOLATION`, `MISSING_TURNING_POINT`, `WEAK_TURNING_POINT`) — see [`config/failure_codes.yaml`](../../config/failure_codes.yaml). Under the forward-only relay, a rejection emits a `final_gate_rejection` event tagged `advisory_only` and does not block or retry. Severe compression has already been handled by the compression guard; remaining hard failures are handled by the save-blocker layer.

Forward Relay v4 narrowed FinalGate's scope: `CHARACTER_PRESENCE_VIOLATION` is no longer emitted (PresenceChecker at save time is the sole authority), and word-count enforcement moved to `src/pipeline/word_count_telemetry.py` at chapter-close. Only closing-hook and turning-point regression remain.

### Retry loops — removed (Stage 1a)

The old per-gate retry loops have been neutered. Scene Gate and Final Gate now run exactly once per scene and emit telemetry only; the orchestrator does not branch back to ProseStylist on failure. The `max_structural_retries` and `max_voice_retries` keys in `config/settings.yaml` are set to `0` and kept only for rollback; setting them higher has no effect in the current orchestrator. Structural/voice/polish failure codes are still useful as ledger signals and bench diagnostics, but they do not gate the save.

The single hard stopping point is the save-blocker layer (see [`src/pipeline/save_blockers.py`](../../src/pipeline/save_blockers.py)): when a CHARACTER_PRESENCE or CANON (critical/moderate) blocker fires, the run aborts and the offending scene is written to `<project>/quarantine/chNN_scMM/{prose.md, blockers.json, brief.json}`.

## Milestone Gates

`src/quality/milestone_gates.py` pauses the pipeline at structural checkpoints for user approval:

| Milestone | When |
|-----------|------|
| first_plot_point | ~25% through the story |
| midpoint | ~50% through the story |
| second_plot_point | ~75% through the story |

At each gate:
1. The pipeline pauses
2. New phase constraints are displayed
3. The user approves or rejects
4. Events are logged to the RunLedger

Milestone gates fire once per structural phase. A `_fired_milestones` set tracks which milestones have already been triggered, preventing duplicate gates when multiple chapters fall within the same structural window (dedup).

In CLI mode, this is an interactive `y/n` prompt. In web mode, a modal appears in the dashboard.

Can be disabled with `--no-milestones`.

## Character Specialist

`src/agents/character_specialist.py` runs out-of-character (OOC) detection on each chapter. It's a supplementary check -- it doesn't block the pipeline. It reports:
- Characters whose behavior diverges from their established profile
- Knowledge consistency issues (characters acting on knowledge they shouldn't have)
- Emotional arc continuity

## LLM Judge (Phase 4)

`src/quality/llm_judge.py` uses a cloud model to evaluate chapters across 5 dimensions defined in `config/eval_rubric.yaml`. This is an expensive evaluation (cloud API call) and is only run when `--judge` is passed.

## Manuscript Reviewer (Phase 5)

`src/agents/manuscript_reviewer.py` performs full-manuscript-level review using dual personas (Literary Critic and Structural Editor). Unlike the per-chapter LLM Judge, the Manuscript Reviewer evaluates the complete work and outputs categorized issues with severity levels (critical/major/minor/suggestion) and an overall recommendation (approve/revise_specific_chapters/major_revision_needed). The live route uses GPT-5.4 for this role.

## Current Manuscript-Level Revision Policy

The manuscript reviewer creates an editorial docket. It does not directly produce the final manuscript.

The current default sequence is:

1. Export the lean manuscript.
2. Review the full manuscript with GPT-5.4.
3. Apply targeted revision patches against the docket, including earlier chapters when a clean baseline is desired.
4. Run targeted cleanup as the default final polish branch.
5. Run full literary polish only as a donor/comparison branch.
6. Apply the final docket pass.
7. Validate the candidate with `scripts/manuscript_final_validation.py`.

The targeted cleanup branch is the production base because it has shown the best balance of readability, tonal fit, and line discipline. Full literary polish can be attractive, but it should be mined for isolated improvements rather than accepted wholesale.

## Gold Evaluation Corpus

`data/eval_corpus/` contains 3 reference chapters used for calibrating quality metrics. These provide ground-truth baselines for the quality scoring system.
