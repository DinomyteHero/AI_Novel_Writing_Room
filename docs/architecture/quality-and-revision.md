# Quality and Revision

The system uses pure-Python quality metrics (no LLM calls) to score scenes, then runs a bounded LLM refinement pass (QualityPolish) whose output must pass a compression guard and a Final Gate before it is saved. If polish is rejected, the Scene-Gate-passed draft is saved instead — so the saved file is always a validated artifact.

> **Note — pipeline redesign.** Earlier builds ran a multi-band revision pipeline (StructuralContinuity → SceneEmotion → LineCopy → optional DialoguePolish / WorldbuildingCoherence) after the Gate. That pipeline has been removed. Polish is now a single pass bounded by the compression guard and the Final Gate. Prompts under `prompts/revision_prompts/` and code under `src/revision/` are legacy and are not invoked by the current orchestrator.

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

## Refinement Path: QualityPolish → Compression Guard → Final Gate

After a draft passes the Scene Gate, the orchestrator runs a single bounded refinement pass and validates its output before saving.

### QualityPolish (`src/agents/quality_polish.py`)

A single LLM pass that receives the Gate-passed draft plus the structured quality flags (flagged_words, description_ratio, etc.) and produces a refined version. Unlike the old multi-band pipeline, QualityPolish does not recursively re-edit — it makes one pass and hands off.

### Compression Guard

The orchestrator rejects polish output that significantly drops or compresses material relative to the Gate-passed draft. This is one of two mechanisms that keep QualityPolish bounded: if it tries to over-edit, the output is discarded.

### Final Gate (`src/agents/final_gate.py`)

Validates the polished prose against the scene card contract:

- Character presence (all required characters are on-page)
- Closing-hook boundary (the scene ends where the card says it should)
- Opening-hook alignment (the scene opens where the card says it should)
- Word-count floor
- Turning point is identifiable in the final prose

Final Gate emits structural failure codes (`CLOSING_HOOK_VIOLATION`, `CHARACTER_PRESENCE_VIOLATION`, `OPENING_HOOK_MISMATCH`) — see [`config/failure_codes.yaml`](../../config/failure_codes.yaml). If it rejects the polish, the orchestrator reverts to the Scene-Gate-passed draft and saves that instead. No stage can silently rewrite a saved scene.

### Rewrite Retry Loop (Scene Gate only)

The Scene Gate runs before QualityPolish and drives a bounded retry loop back to the ProseStylist when structural or voice failures occur. Failure routing (see [`config/failure_codes.yaml`](../../config/failure_codes.yaml)):

- `fail_structural` → full rewrite (ProseStylist with corrective brief)
- `fail_voice` → targeted revision (ProseStylist with voice notes)
- `fail_polish` → revert to Gate-passed draft (caught at compression guard / Final Gate, not routed back to a polish retry)

Max retries: `max_structural_retries` (default 3) and `max_voice_retries` (default 2), configurable via `config/settings.yaml`.

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

## Style Fingerprinter (Phase 5)

`src/quality/style_fingerprint.py` extracts quantitative prose metrics (sentence length distribution, dialogue ratio, adverb density, em-dash usage) and compares them against reference fingerprints stored in the `style_fingerprint` SQLite table. This enables voice drift detection across chapters and against reference material.

## Manuscript Reviewer (Phase 5)

`src/agents/manuscript_reviewer.py` performs full-manuscript-level review using dual personas (Literary Critic and Structural Editor). Unlike the per-chapter LLM Judge, the Manuscript Reviewer evaluates the complete work and outputs categorized issues with severity levels (critical/major/minor/suggestion) and an overall recommendation (approve/revise_specific_chapters/major_revision_needed).

## Gold Evaluation Corpus

`data/eval_corpus/` contains 3 reference chapters used for calibrating quality metrics. These provide ground-truth baselines for the quality scoring system.
