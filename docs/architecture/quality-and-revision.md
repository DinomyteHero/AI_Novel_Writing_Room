# Quality and Revision

The system uses pure-Python quality metrics (no LLM calls) to score chapters, and a multi-band revision pipeline (LLM-powered) to improve them.

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

Quality metrics now produce structured flags that are passed downstream to revision bands, enabling targeted fixes:

- **flagged_words**: A dictionary of overused words with their counts (e.g., `{"whispered": 7, "nodded": 5}`). Passed to Band 3 (LineCopyEditor) so it can target specific word replacements with count context.
- **description_ratio**: The ratio of descriptive narration to total prose. When this exceeds 0.60 (60% description), it is passed to Band 2 (SceneEmotionReviewer) to trigger description rebalancing.

### Cross-Scene Overused Word Tracker

A manuscript-level tracker aggregates overused words across all generated scenes (not just per-chapter). After each chapter, newly flagged words are merged into the tracker. These accumulated overused words are dynamically injected into the Prose Stylist prompt for subsequent scenes, helping the drafting agent proactively avoid manuscript-level repetition patterns.

## Revision Pipeline

### Base Pipeline (Phase 3)

`src/revision/pipeline.py` runs 3 sequential editing bands:

| Band | Agent | Prompt | Focus |
|------|-------|--------|-------|
| 1 | StructuralContinuity | `prompts/revision_prompts/structural_continuity.md` | Plot holes, arc consistency, timeline validation, knowledge state |
| 2 | SceneEmotion | `prompts/revision_prompts/scene_emotion.md` | Conflict intensity, turning point impact, emotional arc, show-don't-tell. Also performs description rebalancing when the structured quality flag `description_ratio` exceeds 60%. |
| 3 | LineCopy | `prompts/revision_prompts/line_copy.md` | Prose quality, grammar, AI-tell removal, rhythm, style consistency. Receives overused word details with counts from structured quality flags for targeted replacement. |

Each band receives the current prose and returns revised prose. The output of one band becomes the input to the next.

### Adaptive Pipeline (Phase 4)

`src/revision/adaptive_revision.py` extends the base pipeline with 2 conditional bands:

| Band | Agent | Prompt | Condition |
|------|-------|--------|-----------|
| 4 | DialoguePolish | `prompts/revision_prompts/dialogue_polish.md` | Dialogue-heavy scene + low voice score |
| 5 | WorldbuildingCoherence | `prompts/revision_prompts/worldbuilding_coherence.md` | Canon elements present + consistency issues |

Bands 4 and 5 only run when quality metrics indicate they're needed, saving LLM calls on chapters that don't need them.

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
