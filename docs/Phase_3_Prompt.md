> **Historical document.** This was the project brief used to build Phase 3. It describes the codebase as it existed after Phase 2. For current architecture, see `AI_Writers_Room_Design_Document_v1.1.md` and `Phase_5_Changelog.md`.

# Claude Code Project Brief: AI Writers' Room — Phase 3 (Quality Metrics, Character Specialist, and Revision Pipeline)

## Context

Phases 1 and 2 of the AI Writers' Room are complete. All 184 tests pass. The existing codebase contains:

### Phase 1 (Complete)
- **`src/model_router.py`** — Routes agent calls to llama-server (local) or OpenRouter (cloud) based on `config/settings.yaml`
- **`src/agents/base_agent.py`** — Abstract agent class with system prompt loading, `run()` and `run_structured()` methods
- **`src/agents/plot_architect.py`** — Scene card → generation brief
- **`src/agents/prose_stylist.py`** — Generation brief + context → prose
- **`src/agents/gate_critic.py`** — Prose → structured CriticFailure JSON with 14 failure codes and automatic routing
- **`src/agents/craft_editor.py`** — Non-blocking voice/polish improvements
- **`src/memory/context_assembler.py`** — Four-tier memory system: story bible + act summary + ChromaDB summaries + recent prose + canon RAG + character knowledge + voice sheets. Falls back to Phase 1 concatenation when Phase 2 deps are None.
- **`src/orchestrator.py`** — Event-driven loop with Phase 2 post-save pipeline: Summarizer → ChromaDB → StateDiff → ContradictionScanner. All Phase 2 deps are optional with backward compat.
- **`src/run_ledger.py`** — SQLite append-only event log (event types include `contradiction_scan`, `summarizer_complete`, `state_diff_proposed`, `state_diff_committed`, `revision_band_start`, `revision_band_complete`, `milestone_reached`, `milestone_gate_paused`)
- **`src/main.py`** — CLI entry point with `--phase` flag (1 or 2)

### Phase 2 (Complete)
- **`src/planning/story_physics.py`** — CausalityChainValidator, RevelationMap, PromisePayoffLedger, StoryPhysicsValidator
- **`src/planning/pressure_matrix.py`** — PressureMatrix with escalation validation
- **`src/planning/scene_economics.py`** — SceneEconomics "why now?" validation
- **`src/memory/story_state.py`** — SQLite with 7 tables: characters, character_knowledge, character_relationships, plot_threads, timeline, chekhov_guns, chapter_log. Includes `init_from_concept_seed()`, `get_state_hash()`, CRUD for all tables.
- **`src/memory/knowledge_layers.py`** — Three-layer system (truth/belief/narrative_exposure) with `get_beliefs_for_characters()`, `check_belief_accuracy()`, `get_dramatic_irony()`
- **`src/memory/chapter_memory.py`** — ChromaDB-backed chapter summary storage
- **`src/agents/summarizer.py`** — Compresses chapters into summaries + state diffs (JSON)
- **`src/memory/state_diff.py`** — StateDiffApplier: validates and applies diffs with state hash tracking
- **`src/memory/contradiction_scanner.py`** — Post-chapter consistency scanner (5 scan types: truth, belief, promises, timeline, relationships)
- **`src/rag/embedding.py`** — MockEmbeddingFunction + SentenceTransformerEmbedding
- **`src/rag/canon_db.py`** — ChromaDB vector DB for franchise canon
- **`src/rag/wiki_ingester.py`** — Entity-aware chunking, source authority classification
- **`src/rag/hybrid_search.py`** — Semantic + BM25, reciprocal rank fusion
- **`src/rag/canon_evidence.py`** — CanonEvidenceRanker: confidence = combined_score × source_authority_weight
- **`src/agents/canon_expert.py`** — RAG-powered lore validation agent

### Existing Config
- **`config/settings.yaml`** — Has Phase 3 model entries commented out: `reasoning_upgrade` (Qwen3.5-35B-A3B), `prose` (Magidonia-24B), `prose_alt` (Qwen3.5-27B-Writer). Agent routing for `character_specialist` and `voice_checker` already defined.
- **`config/failure_codes.yaml`** — 14 failure codes across structural/voice/polish categories
- **`config/negative_constraints.yaml`** — Banned phrases (faux_profundity, sensory_cliches, magic_adverbs, ai_tells) and structural_rules (adverb density, sentence length variance, opener diversity, metaphor cooldown)

### Existing Tests
- **184 tests passing** across 11 test files
- **`tests/conftest.py`** — Fixtures: sample_concept_seed, sample_scene_card, temp_dir, mock_router, settings_yaml, story_state, story_state_initialized, knowledge_layers, mock_embedding_function, chapter_memory

### Empty Stub Directories (ready for Phase 3)
- `src/quality/` — `__init__.py` only
- `src/revision/` — `__init__.py` only
- `src/export/` — `__init__.py` only
- `prompts/revision_prompts/` — does not exist yet

### Data Fixtures
- `data/story_bibles/beyond_the_veil/` — concept_seed.json + 5 scene cards (chapters 1-5)
- `schemas/` — concept_seed.json, scene_card.json, story_physics.json, state_diff.json, canon_evidence.json, failure_code.json, character_sheet.json, story_bible.json

Read `AI_Writers_Room_Design_Document_v1.1.md` in the project root — it contains the full technical specification for the quality metrics, revision pipeline, and character specialist agent described below.

---

## What to Build

Phase 3 adds three major subsystems: **automated quality metrics** for measuring prose quality, the **Character Specialist agent** for OOC detection, and the **three-band revision pipeline** for post-draft improvement. The goal is to measurably reduce AI-typical patterns, catch out-of-character dialogue/actions, and produce revision-quality prose through multi-pass editing.

---

## Implementation Order

### Step 1: Repetition Detector (`src/quality/repetition_detector.py`)

Detect repetitive patterns at multiple levels:

1. **Word frequency analysis** — Count word frequencies per chapter. Flag words appearing >3 standard deviations above the expected frequency for their word class. Exclude stop words and character names.

2. **N-gram repetition** — Track 3-gram and 4-gram frequencies within a chapter and across the last 3 chapters. Flag any n-gram appearing more than twice in the same chapter or more than 3 times across a 3-chapter window.

3. **Sentence opener analysis** — Extract the first 3 words of each sentence. Flag when >15% of sentences share the same opener pattern (matching `config/negative_constraints.yaml` `max_same_opener_pct`).

4. **Paragraph semantic similarity** — Compute cosine similarity between paragraph embeddings (using the existing `MockEmbeddingFunction` or `SentenceTransformerEmbedding` from `src/rag/embedding.py`). Flag paragraph pairs with similarity >0.85 within the same chapter.

**Class design:**
```python
class RepetitionDetector:
    def __init__(self, embedding_function=None):
        ...

    def analyze(self, prose: str, previous_chapters: list[str] = None) -> dict:
        """Run all repetition analyses. Returns:
        {
            "flagged_words": [{"word": str, "count": int, "expected": float, "zscore": float}],
            "repeated_ngrams": [{"ngram": str, "count": int, "scope": "chapter"|"cross_chapter"}],
            "opener_violations": [{"opener": str, "percentage": float}],
            "similar_paragraphs": [{"para_a": int, "para_b": int, "similarity": float}],
            "repetition_score": float  # 0.0 (no issues) to 1.0 (severe repetition)
        }
        """
```

### Step 2: Pacing Analyzer (`src/quality/pacing_analyzer.py`)

Measure narrative pacing characteristics:

1. **Sentence length variance** — Compute the coefficient of variation (std/mean) of sentence lengths. Flag if below `min_sentence_length_variance` (0.3) from `config/negative_constraints.yaml`. Low variance = flat, AI-typical pacing.

2. **Dialogue-to-narrative ratio** — Measure the percentage of text that is dialogue (inside quotes). Compare against genre benchmarks (fiction target: 30-50% for dialogue-heavy scenes, 15-30% for introspective scenes).

3. **Scene type classification** — Classify paragraphs as action, dialogue, introspection, or description. Compute the distribution and flag chapters that are >60% any single type.

4. **Event density** — Count discrete events (actions, dialogue exchanges, revelations) per 1000 words. Compare against the expected pacing curve for the chapter's `structural_phase` from the scene card (setup = lower density, climax = higher density).

**Class design:**
```python
class PacingAnalyzer:
    def __init__(self):
        ...

    def analyze(self, prose: str, scene_card: dict) -> dict:
        """Returns:
        {
            "sentence_length_variance": float,
            "variance_flag": bool,  # True if below threshold
            "dialogue_ratio": float,
            "scene_type_distribution": {"action": float, "dialogue": float, "introspection": float, "description": float},
            "event_density_per_1k": float,
            "expected_density_range": [float, float],  # based on structural_phase
            "pacing_score": float  # 0.0 (poor pacing) to 1.0 (excellent pacing)
        }
        """
```

### Step 3: Voice Consistency Checker (`src/quality/voice_checker.py`)

Check prose against character voice profiles and anti-slop constraints:

1. **Character voice fidelity** — For each POV character, score how well the dialogue and internal monologue match their `voice_notes` from the concept seed. This is a heuristic check:
   - Sentence length consistency (short-sentence characters shouldn't have long dialogue)
   - Vocabulary register (academic characters vs casual characters)
   - Forbidden patterns per character (e.g., Ben shouldn't use "Jedi platitudes")

2. **Banned phrase detection** — Scan prose against all banned phrases from `config/negative_constraints.yaml` (faux_profundity, sensory_cliches, magic_adverbs, ai_tells). Return exact matches with locations.

3. **Adverb density** — Count adverbs (words ending in "-ly" as a rough heuristic, excluding known false positives like "only", "really", "family"). Flag if above `max_adverb_density` (0.02 per word).

4. **Metaphor cooldown** — Track metaphor/simile occurrences (heuristic: sentences containing "like a" or "as if" or "as though"). Flag when two metaphors appear within `metaphor_cooldown_paragraphs` (8) paragraphs.

**Class design:**
```python
class VoiceChecker:
    def __init__(self, negative_constraints_path: str = "config/negative_constraints.yaml"):
        ...

    def analyze(self, prose: str, pov_character: str, concept_seed: dict) -> dict:
        """Returns:
        {
            "banned_phrases_found": [{"phrase": str, "category": str, "location": str}],
            "adverb_density": float,
            "adverb_flag": bool,
            "metaphor_violations": [{"location_a": int, "location_b": int, "distance_paragraphs": int}],
            "voice_fidelity_score": float,  # 0.0 to 1.0
            "voice_notes": str  # Specific feedback
        }
        """
```

### Step 4: Slop Detector (`src/quality/slop_detector.py`)

Dedicated AI-tell detection focusing on LLM-typical writing artifacts:

1. **AI-tell word frequency** — Check frequency of known AI-tell words: "delve", "tapestry", "testament", "nuanced", "landscape", "multifaceted", "straightforward", "it's important to note", "it's worth noting", "a testament to", "in the realm of", "crucial", "vital", "pivotal". Flag any appearance.

2. **Burstiness analysis** — Measure the distribution of word/phrase repetition across the chapter. LLM text tends to have "bursty" repetition (same word appears in clusters). Compute burstiness score using the standard formula: `(variance - mean) / (variance + mean)` for inter-occurrence distances.

3. **Show-don't-tell detection** — Flag "telling" emotion words appearing outside dialogue: "felt", "knew", "realized", "noticed", "wondered", "seemed", "appeared", "was aware", "could tell", "could sense". Each occurrence is a potential tell-not-show violation.

4. **Filler pattern detection** — Flag generic transitional phrases: "In that moment", "Without hesitation", "For a long moment", "Despite everything", "Something shifted". These are LLM-typical space-fillers.

**Class design:**
```python
class SlopDetector:
    def __init__(self, negative_constraints_path: str = "config/negative_constraints.yaml"):
        ...

    def analyze(self, prose: str) -> dict:
        """Returns:
        {
            "ai_tells_found": [{"word": str, "count": int, "locations": list[str]}],
            "burstiness_score": float,  # 0.0 (uniform) to 1.0 (highly bursty)
            "tell_not_show": [{"phrase": str, "location": str, "suggestion": str}],
            "filler_patterns": [{"phrase": str, "location": str}],
            "slop_score": float  # 0.0 (clean) to 1.0 (AI-tell saturated)
        }
        """
```

### Step 5: Quality Metrics Dashboard (`src/quality/metrics_dashboard.py`)

Aggregator that runs all quality checkers and produces a unified per-chapter report:

```python
class MetricsDashboard:
    def __init__(self, concept_seed: dict, negative_constraints_path: str = "config/negative_constraints.yaml", embedding_function=None):
        ...

    def analyze_chapter(self, prose: str, scene_card: dict, previous_chapters: list[str] = None) -> dict:
        """Run all quality metrics on a chapter. Returns:
        {
            "chapter_number": int,
            "word_count": int,
            "repetition": {...},  # from RepetitionDetector
            "pacing": {...},       # from PacingAnalyzer
            "voice": {...},        # from VoiceChecker
            "slop": {...},         # from SlopDetector
            "overall_score": float,  # weighted average: repetition 0.25, pacing 0.25, voice 0.25, slop 0.25
            "flags": list[str],     # human-readable summary of all issues
            "pass": bool            # True if overall_score >= 0.6
        }
        """

    def analyze_manuscript(self, chapters: list[dict]) -> dict:
        """Aggregate metrics across all chapters. Returns trends and cross-chapter analysis."""
```

### Step 6: Character Specialist Agent (`src/agents/character_specialist.py`)

New agent for voice profiles and OOC detection:

- Extends `BaseAgent` with role `"character_specialist"`
- Uses primary_moe model (temperature 0.4) per settings.yaml routing (already configured)
- Input: prose + scene_card + concept_seed (character profiles)
- Output: structured OOC analysis with per-character scores

**Key responsibilities:**
1. **Voice fidelity check** — Does each character's dialogue sound like them? Reference their `voice_notes` and `three_dimensions` from the concept seed.
2. **OOC action detection** — Do character actions align with their `action_under_pressure` dimension? Flag behavior that contradicts established characterization.
3. **Knowledge consistency** — Does any character act on knowledge they shouldn't have? Cross-reference the knowledge layers.
4. **Emotional arc validation** — Does the POV character's emotional trajectory match the scene card's `emotional_trajectory`?

**Output format:**
```json
{
    "verdict": "pass" | "fail_voice" | "fail_action",
    "characters": [
        {
            "name": "Ben Skywalker",
            "voice_fidelity": 0.85,
            "ooc_flags": [],
            "knowledge_violations": [],
            "emotional_arc_match": true
        }
    ],
    "overall_voice_score": 0.82,
    "notes": "..."
}
```

Write the system prompt at `prompts/agent_system_prompts/character_specialist.md`.

### Step 7: Three-Band Revision Pipeline

Implement the revision pipeline that runs after the initial draft is approved by the Gate Critic. Each band is a separate revision pass with a specialized agent.

#### Band 1: Structural/Continuity (`src/revision/structural_continuity.py`)

New agent extending `BaseAgent` with role `"structural_continuity_reviewer"`.

**Checks:**
- Plot holes — are there logical gaps in the scene's events?
- Arc consistency — does the POV character's arc progress match the structural phase?
- Timeline coherence — do temporal references match the timeline table?
- Knowledge state — does the prose respect what characters know/don't know?
- Promise tracking — are planted promises referenced appropriately? Are paid promises set up?

**Input:** prose + scene_card + story_state (character locations, plot threads, timeline)
**Output:** annotated prose with inline revision markers OR a revision brief for the Prose Stylist

Write the system prompt at `prompts/revision_prompts/structural_continuity.md`.

#### Band 2: Scene/Emotion (`src/revision/scene_emotion.py`)

New agent extending `BaseAgent` with role `"scene_emotion_reviewer"`.

**Checks:**
- Conflict quality — is the scene's conflict tangible and escalating?
- Turning point validation — does the scene end differently than it began?
- Show-don't-tell — flag emotion-naming vs emotion-showing
- Emotional arc — does the POV character's emotional journey match the scene card's `emotional_trajectory`?
- Dialogue quality — does dialogue reveal character and advance conflict, or is it expository?

**Input:** prose + scene_card + character voice profiles
**Output:** revision brief with specific improvement suggestions

Write the system prompt at `prompts/revision_prompts/scene_emotion.md`.

#### Band 3: Line/Copy (`src/revision/line_copy.py`)

New agent extending `BaseAgent` with role `"line_copy_editor"`.

**Checks:**
- Prose quality — sentence variety, word choice precision, unnecessary modifiers
- Grammar and style — consistency with the franchise style guide (e.g., capitalize "Human", decapitalize "galaxy")
- Readability — Flesch-Kincaid grade level targeting 7-9 (mass-market fiction benchmark)
- AI-tell removal — apply fixes for any remaining banned phrases or slop patterns
- Rhythm — paragraph length variety, dialogue tag variety

**Input:** prose + negative_constraints + style_constraints from concept_seed
**Output:** directly revised prose (not suggestions — actual edits)

Write the system prompt at `prompts/revision_prompts/line_copy.md`.

#### Revision Orchestration

Add a `RevisionPipeline` class in `src/revision/pipeline.py`:

```python
class RevisionPipeline:
    def __init__(self, router, story_state, knowledge_layers, concept_seed):
        self.band1 = StructuralContinuityReviewer(router)
        self.band2 = SceneEmotionReviewer(router)
        self.band3 = LineCopyEditor(router)
        ...

    async def revise(self, prose: str, scene_card: dict, ledger: RunLedger) -> dict:
        """Run all three revision bands sequentially.
        Emits revision_band_start/revision_band_complete events to ledger.
        Returns:
        {
            "revised_prose": str,
            "band1_notes": str,
            "band2_notes": str,
            "band3_changes": int,  # number of edits made
            "quality_before": dict,  # MetricsDashboard result before revision
            "quality_after": dict,   # MetricsDashboard result after revision
        }
        """
```

### Step 8: Orchestrator Integration

Update `src/orchestrator.py` to integrate Phase 3 components:

1. **After Craft Editor, before save** (when revision pipeline is provided):
   - Run the three-band revision pipeline
   - Emit `revision_band_start`/`revision_band_complete` events for each band
   - Use the revised prose as the final output

2. **After save** (when quality dashboard is provided):
   - Run quality metrics on the final prose
   - Log quality scores to the chapter_log in story state
   - Emit quality metrics as part of the pipeline result

3. **Character Specialist integration** (when character specialist is provided):
   - Run the Character Specialist as a supplementary check alongside or after the Gate Critic
   - If the Character Specialist flags OOC issues, append them to the failure context for revision

**Backward compatibility:** All new dependencies are optional keyword-only parameters with `None` defaults. When `None`, the orchestrator behaves exactly as Phase 2.

### Step 9: Milestone Gates

Add milestone gate support to the orchestrator. At structural milestones (First Plot Point ~chapter 6, Midpoint ~chapter 12, Second Plot Point ~chapter 19 for a 25-chapter novel), the pipeline should:

1. Check if the current chapter's `structural_phase` is a milestone phase (`first_plot_point`, `midpoint`, `second_plot_point`)
2. Emit a `milestone_reached` event with the milestone name and current state
3. Emit a `milestone_gate_paused` event
4. In CLI mode: print a summary and prompt for human approval (y/n to continue)
5. Validate structural constraints:
   - After First Plot Point: narrative quest must be locked (no more setup exposition)
   - After Midpoint: protagonist must shift from reactive to proactive
   - After Second Plot Point: no new world-building data from RAG

Implement in `src/orchestrator.py` as part of `run_chapter()`.

### Step 10: Update `main.py`

Update the CLI to support `--phase 3`:
- Initialize quality metrics (RepetitionDetector, PacingAnalyzer, VoiceChecker, SlopDetector, MetricsDashboard)
- Initialize Character Specialist agent
- Initialize Revision Pipeline (3 bands)
- Pass all to the Orchestrator
- Add `--no-revision` flag to skip the revision pipeline (useful for fast iteration)
- Add `--no-milestones` flag to skip milestone gate pausing

### Step 11: Gold Evaluation Corpus

Create a small evaluation dataset for measuring quality improvements:

1. Create `data/eval_corpus/` directory
2. Create 3 reference chapters (manually curated "target quality" prose) as markdown files:
   - `data/eval_corpus/reference_chapter_01.md` — A well-written setup chapter (~3000 words) with varied sentence structure, strong show-don't-tell, authentic dialogue, and zero AI-tells
   - `data/eval_corpus/reference_chapter_02.md` — An action/discovery chapter (~3000 words) with strong pacing, varied event density, and clear emotional arc
   - `data/eval_corpus/reference_chapter_03.md` — A dialogue-heavy character chapter (~3000 words) with distinct voice per character and thematic depth

3. Create `data/eval_corpus/eval_rubric.json`:
```json
{
    "metrics": {
        "repetition_score_target": {"min": 0.0, "max": 0.2},
        "pacing_score_target": {"min": 0.7, "max": 1.0},
        "voice_score_target": {"min": 0.7, "max": 1.0},
        "slop_score_target": {"min": 0.0, "max": 0.15},
        "overall_score_target": {"min": 0.7, "max": 1.0}
    },
    "zero_tolerance": ["ai_tells_found", "banned_phrases_found"]
}
```

4. Create `tests/test_eval_corpus.py` — Run MetricsDashboard against the reference chapters and verify they meet the rubric targets. This serves as a baseline that the quality metrics system considers good writing to be good.

### Step 12: Tests

Write tests covering all new Phase 3 components:

- **`tests/test_repetition_detector.py`** — Test word frequency flagging (known over-used word), n-gram detection, opener analysis (>15% same opener), paragraph similarity flagging. Test with clean prose (should score low) and deliberately repetitive prose (should score high).
- **`tests/test_pacing_analyzer.py`** — Test sentence length variance calculation, dialogue ratio measurement, scene type classification, event density. Test with varied prose (good score) and monotonous prose (bad score).
- **`tests/test_voice_checker.py`** — Test banned phrase detection against known AI-tells, adverb density calculation, metaphor cooldown enforcement. Test with clean prose and slop-filled prose.
- **`tests/test_slop_detector.py`** — Test AI-tell word detection, burstiness scoring, show-don't-tell flagging, filler pattern detection.
- **`tests/test_metrics_dashboard.py`** — Test the aggregator produces correct structure, overall_score calculation, pass/fail threshold.
- **`tests/test_character_specialist.py`** — Test with mock router. Verify the agent formats context correctly and parses OOC analysis output.
- **`tests/test_revision_pipeline.py`** — Test three-band pipeline runs sequentially with mock router. Verify revision_band_start/complete events emitted. Verify quality_before/quality_after structure.
- **`tests/test_eval_corpus.py`** — Test reference chapters meet the rubric. (Depends on Step 11.)

**Phase 3 milestone**: Run the full 5-chapter pipeline with revision, achieve overall quality score >= 0.7 on the MetricsDashboard, with zero AI-tell detections and zero banned phrase occurrences in the final revised prose.

---

## Dependencies to Add

Add to `requirements.txt`:
```
nltk>=3.8
scikit-learn
```

NLTK is needed for:
- Sentence tokenization (`nltk.tokenize.sent_tokenize`)
- Readability scores (Flesch-Kincaid via `nltk` or manual formula)

scikit-learn is needed for:
- TF-IDF vectorization for cross-chapter repetition
- Cosine similarity for paragraph comparison

Note: `numpy` is already in requirements.txt from Phase 2.

---

## Key Technical Decisions

- **Quality metrics are non-blocking.** They produce scores and flags but do not reject chapters. The revision pipeline acts on the flags.
- **Revision bands run sequentially.** Band 1 (structural) must complete before Band 2 (scene/emotion) because structural changes can invalidate emotional arc analysis. Band 3 (line/copy) runs last because word-level edits should not be made until higher-level issues are resolved.
- **The Character Specialist is a supplementary check**, not a gate. It runs alongside the Gate Critic and its flags are informational. In Phase 4, it may become a gate.
- **Revision output replaces the Craft Editor output** when the revision pipeline is active. The Craft Editor still runs (for quick polish), but the revision pipeline does the deeper work.
- **Gold corpus is manually curated.** The reference chapters should be written (or selected) to represent target quality, not generated by the pipeline. They serve as the calibration standard.
- **Milestone gates are opt-in.** They require `--phase 3` and can be disabled with `--no-milestones`. In CLI mode they use a simple y/n prompt; in Phase 5 (UI) they'll use the web interface.
- **Backward compatibility.** Phase 1 and Phase 2 modes continue to work. `--phase 1` and `--phase 2` behave exactly as before. All 184 existing tests must continue to pass.
