# AI Writers' Room -- Pipeline Diagnostic Report

**Project:** The Ruusan Atonement
**Run scope:** 8 chapters, 25 scenes, Phase 4, cloud mode (OpenRouter)
**Report date:** 2026-04-12

---

## 1. Canon Expert Agent -- Missing from Pipeline

### Root Cause

**The canon expert never fires because of a conditional guard on a field that does not exist in any scene card.**

In `src/orchestrator.py:296`, the canon expert is invoked inside a conditional:

```python
if self.canon_expert and scene_card.get("canon_elements_needed"):
```

A `grep` across all 25+ scene cards in `data/projects/the-ruusan-atonement/scene_cards/*.json` returns **zero matches** for `canon_elements_needed`. The field is defined in the schema (`schemas/scene_card.json:47`) and appears in the test fixture (`tests/fixtures/sample_scene_card.json:21`), but neither the `SceneCardGenerator` nor the manual scene cards for this project populate it.

### How the Canon Expert Works (When Triggered)

- **Agent class:** `src/agents/canon_expert.py:9` -- `CanonExpert(BaseAgent)`
- **Dependencies:** `CanonEvidenceRanker` (from `src/rag/canon_evidence.py`) which wraps `HybridSearch` (from `src/rag/hybrid_search.py`) over a `CanonDB` (ChromaDB collection at `data/canon_dbs/`)
- **Model:** `gemini_flash` per `config/settings.yaml:105`
- **Flow:** Retrieves top-3 evidence chunks per canon element from the ChromaDB canon database, formats them as context, sends to LLM for validation, returns `canon_notes` string
- **Integration point:** `src/orchestrator.py:294-311` -- runs *after* Gate Critic, *before* Craft Editor. Canon notes are injected into the Craft Editor context (`src/orchestrator.py:804-805`)

### Why the Failures Occurred

The "LIDAR", "40 ABY", and "High Republic" canon violations had **no validation checkpoint**. Even if the canon expert had fired, it operates as an advisory layer -- its output (`canon_notes`) is passed to the Craft Editor as optional context (`src/orchestrator.py:315`, `src/orchestrator.py:804`), not as a blocking gate.

### Recommended Fixes

1. **Populate `canon_elements_needed`** in scene cards during generation or as a post-processing step
2. **Remove the guard** or make it fallback -- the canon expert should run on *every* scene (even without explicit elements), performing a general franchise-accuracy scan
3. **Add canon validation to the Gate Critic** -- add `CANON_VIOLATION` as a blocking structural code (it's currently a polish-only code at `src/agents/gate_critic.py:43`)
4. **Ensure canon DB is populated** -- the wiki ingester (`src/rag/wiki_ingester.py`) needs to have been run against Legends EU sources

---

## 2. Gate Critic -- Uniform Scoring (Rubber-Stamping)

### Root Cause

**The Gate Critic prompt asks for general impressions on a 0.0-1.0 scale with no calibration anchors, no reference examples, and no instruction to use the full range.** Additionally, it uses `complete_structured` (`src/agents/gate_critic.py:141`), which prepends "Respond with valid JSON only" -- this further biases the model toward producing conservative, safe-looking numbers.

### Code Analysis

- **Prompt location:** `src/agents/gate_critic.py:80-134` -- the `_format_context` method builds the evaluation prompt
- **Scoring request:** Lines 108-112 ask for `structural_score: 0.0-1.0`, `voice_score: 0.0-1.0`, `polish_score: 0.0-1.0` with no guidance on what constitutes each score level
- **Rubric specificity:** The checklist (lines 123-133) lists 11 checks but provides no scoring weights, severity mapping, or examples of what a 0.6 vs 0.9 scene looks like
- **Pass/fail logic:** `src/agents/gate_critic.py:48-59` -- verdict is determined by which failure codes are present. Scores are informational only and **do not influence the pass/fail decision**
- **No calibration:** No reference scenes, no few-shot examples, no instruction like "a score of 0.7 means X specific deficiency"
- **Self-evaluation bias:** Claude Sonnet 4 evaluating Claude Sonnet 4 prose -- same model family tends to rate its own output favorably

### Impact

The gate critic effectively never fails a scene. The only way a scene fails is if the LLM generates explicit failure codes -- but the high scores indicate the model believes the prose is near-perfect, so it returns `verdict: "pass"` with no failure codes. The gate loop (`src/orchestrator.py:666-779`) is designed for retry logic that never activates.

### Recommended Fixes

1. **Add calibration anchors** to the prompt: "0.7 = acceptable first draft, 0.85 = publishable, 0.95 = exceptional; most AI-generated first drafts should score 0.65-0.80"
2. **Decouple scores from verdict** -- force the model to list issues *before* scoring (chain-of-thought), then derive scores from issue severity
3. **Add few-shot examples** with deliberately flawed scenes rated at 0.5-0.7 to anchor the scale
4. **Cross-model evaluation** -- use a different model family for the gate critic (e.g., Gemini Pro or DeepSeek) to break self-evaluation bias
5. **Inject quality metrics** into the gate critic context so it can see objective measurements (description ratio, event density, etc.)

---

## 3. Quality Metrics -> Revision Pipeline Disconnect

### Root Cause

**Quality flags ARE passed to the revision pipeline, but the base three bands do not consume them. Only Band 3 (LineCopyEditor) receives `quality_flags` in its context, and even then its prompt does not specifically target the flagged issues.**

### Data Flow

1. **Quality metrics run first** at `src/orchestrator.py:319-333`
2. **Flags are passed** to the revision pipeline context at `src/orchestrator.py:347-348`:
   ```python
   "quality_flags": quality_metrics.get("flags", []) if quality_metrics else [],
   "quality_metrics": quality_metrics,
   ```
3. **RevisionPipeline.run** at `src/revision/pipeline.py:34` receives this context and passes it through to each band via `band_context = {**context, "prose": prose}` at line 119
4. **Band 1 (StructuralContinuityReviewer)** at `src/revision/structural_continuity.py:26-55` -- uses `prose`, `scene_card`, `story_state_summary`, `prior_chapter_summary`. **Does NOT reference `quality_flags` or `quality_metrics`.**
5. **Band 2 (SceneEmotionReviewer)** at `src/revision/scene_emotion.py:26-51` -- uses `prose`, `scene_card`, `character_voices`. **Does NOT reference `quality_flags` or `quality_metrics`.**
6. **Band 3 (LineCopyEditor)** at `src/revision/line_copy.py:26-57` -- uses `prose`, `negative_constraints`, `quality_flags`. **DOES receive quality flags** (line 29) and includes them in the prompt (lines 37-40). However, the flags are generic strings like "Overused words: something, didn't, looked" with no specific fix instructions.

### The AdaptiveRevisionPipeline

Phase 4 uses `AdaptiveRevisionPipeline` (`src/revision/adaptive_revision.py:132`), which extends the base pipeline with Bands 4-5. These conditional bands DO consume quality metrics:
- **Band 4 (DialoguePolishEditor)** at line 207 -- checks `quality_metrics.voice.voice_fidelity_score < 0.8`
- **Band 5 (WorldbuildingCoherenceReviewer)** at line 243 -- checks for canon/character flags

But **no band targets** the most common quality flags:
- Description imbalance (>60%) -- no dedicated band
- Event density outside range -- no dedicated band
- Show-don't-tell violations -- only addressed generically by Band 2
- Overused words -- Band 3 receives the flag list but its prompt says "replace vague words" generically, not "eliminate these specific words: X, Y, Z"
- Repeated n-grams -- no band targets this

### Recommended Fixes

1. **Feed specific quality flags into Band 3's prompt** with actionable instructions: "Replace each instance of [overused word] with a contextually appropriate alternative"
2. **Add a description-rebalancing band** (or merge it into Band 1) that reads the `pacing.scene_type_flag` and adjusts the action/description/dialogue ratio
3. **Pass quality_metrics to ALL bands** -- Band 1 should know about event density issues; Band 2 should see show-don't-tell counts
4. **Make Band 3 prompt data-driven** -- instead of "fix AI-tells", say "Remove these 5 specific flagged instances: [list from slop_detector]"

---

## 4. Milestone Gate -- Fires Per-Scene Instead of Per-Chapter

### Root Cause

**The milestone gate check is called inside `run_chapter()` (the per-scene method), not at the chapter boundary in `run_pipeline()`.**

### Code Path

1. `src/orchestrator.py:447-453` -- milestone check is the final step of `run_chapter()`:
   ```python
   if self.milestone_gates:
       milestone_info = self.milestone_gates.check(scene_card)
       if milestone_info:
           result["milestone"] = milestone_info
   ```
2. `src/quality/milestone_gates.py:53-98` -- `check()` fires whenever `scene_card.structural_phase` matches a milestone phase. There is **no deduplication** -- no "already fired for this chapter" flag.
3. All scenes in a milestone chapter share the same `structural_phase` value in their scene card. So if Chapter 5 has 4 scenes all with `structural_phase: "first_plot_point"`, the milestone fires 4 times.

### Why `_is_last_scene_in_chapter` Doesn't Help

The chapter gate critic (`src/orchestrator.py:222-229`) correctly uses `_is_last_scene_in_chapter()` to fire only once per chapter. But the milestone gate was not given the same treatment.

### Recommended Fixes

1. **Move the milestone check** from `run_chapter()` to `run_pipeline()`, adjacent to the chapter gate logic at line 222, gated by `_is_last_scene_in_chapter()`
2. **Alternatively, add a `_fired_milestones` set** to `MilestoneGates` that tracks which phases have already been prompted:
   ```python
   if structural_phase in self._fired_milestones:
       return None
   self._fired_milestones.add(structural_phase)
   ```

---

## 5. Arc Phase Transition Rejections -- Ben Skywalker's Frozen State

### Root Cause

**The arc state machine enforces strictly sequential, single-step-forward-only transitions. The Summarizer LLM proposes transitions that don't match the strict progression rules.**

### The State Machine

Defined at `src/memory/story_state.py:101-133`:

**positive_change** (Ben's likely arc type):
```
lie_established -> lie_reinforced -> lie_questioned -> lie_cracking -> lie_confronted -> truth_accepted
```

**Validation rules** at `src/memory/story_state.py:1298-1309`:
- `new_idx <= current_idx` -> reject (no backward, no self-transition)
- `new_idx > current_idx + 1` -> reject (no skipping phases)

### Analysis of the Three Rejections

1. **Ch1.1: `lie_reinforced -> lie_established`** -- *backward movement*. The Summarizer proposed going backward. But wait -- if Ben's initial state was `lie_reinforced` (set by the concept seed), then proposing `lie_established` is a regression. The concept seed likely initialized Ben at `lie_reinforced` rather than `lie_established`, so the Summarizer generated a transition that goes backward from the seed's starting point.

2. **Ch1.3: `lie_reinforced -> lie_reinforced`** -- *self-transition*. The Summarizer recognized the arc should stay in the current phase but the state machine rejects `new_idx <= current_idx`. This is the most common case -- many scenes reinforce the current phase without advancing.

3. **Ch5.4: `lie_confronted -> lie_reinforced`** -- *backward movement*. By Ch5, the state should have progressed, but since transitions 1 and 2 were rejected, Ben's state remained frozen at the initial phase. The Summarizer, reading the actual prose, saw regression and reported it accurately.

### The Deeper Problem

The transition is proposed by the **Summarizer** agent (via state diff `arc_phase_updates`), applied by `StateDiffApplier._apply_arc_phase_updates()` at `src/memory/state_diff.py:447-488`. When a transition is rejected:
- A warning is logged (`state_diff.py:474-478`)
- A ledger event `arc_phase_transition_rejected` is emitted (`state_diff.py:479-488`)
- **The character's arc state remains unchanged** -- it stays at whatever it was

This means:
- If the initial state is wrong (e.g., `lie_reinforced` instead of `lie_established`), the character can never advance because `lie_established` is behind `lie_reinforced`
- **Self-transitions are never allowed**, but many scenes legitimately reinforce the current phase
- The Character Specialist (`src/agents/character_specialist.py`) is a separate agent that **does not read arc state from the database** -- it evaluates the prose independently, which is why its verdict always passes

### Recommended Fixes

1. **Allow self-transitions** -- modify `advance_arc_phase()` at `story_state.py:1305` to allow `new_idx == current_idx` (update evidence/chapter without changing phase)
2. **Verify initial arc phase** in the concept seed matches the state machine's starting phase. If arc_type is `positive_change`, initial phase must be `lie_established`
3. **Add a "hold" transition type** that updates evidence/chapter without requiring phase advancement
4. **Map concept seed planning labels** -- the `CONCEPT_SEED_PHASE_MAP` at `story_state.py:148` should be consulted when initializing character arc states, not just during diff application
5. **Feed rejected transitions back** to the Summarizer prompt so it learns the valid progression

---

## 6. Judge Evaluator Agent -- Configured but Never Triggered

### Root Cause

**The Judge Evaluator requires the `--judge` CLI flag, which was not passed during the pipeline run.**

### Code Path

1. `config/settings.yaml:66` -- `judge_evaluator` is defined with model `claude`, temperature 0.2
2. `src/main.py:220-225` -- in `_init_phase4()`, the judge is only initialized when `judge=True`:
   ```python
   if judge:
       from src.quality.llm_judge import JudgeEvaluator
       judge_evaluator = JudgeEvaluator(router)
   ```
3. `src/main.py:367-369` -- the `--judge` argument defaults to `False`:
   ```python
   parser.add_argument("--judge", action="store_true", ...)
   ```
4. `src/orchestrator.py:402-416` -- the judge runs in `run_chapter()` only if `self.judge_evaluator` is not None

This is **by design** -- the judge is an opt-in expensive evaluation step (Claude Sonnet 4 at temperature 0.2, running per-scene). It was not enabled for this run.

### manuscript_reviewer

Similarly, `manuscript_reviewer` (`src/agents/manuscript_reviewer.py:53`) is defined in settings.yaml but is **not wired into the CLI pipeline at all**. It has no instantiation in `main.py` and no call site in `orchestrator.py`. It is likely intended for the web UI API (`src/ui/`) or future manuscript-level evaluation.

### Recommended Fixes

1. **Document the `--judge` flag** more prominently -- it should be part of the Phase 4 standard run recommendation
2. **Consider auto-enabling** the judge at milestone boundaries (run once per milestone instead of per-scene to control cost)
3. **Wire `manuscript_reviewer`** into the pipeline as a post-run step, or document that it's API-only

---

## 7. Overused Word Detection Without Remediation

### Root Cause

**Overused words are detected by `RepetitionDetector` but the flagged word list is never passed to any agent prompt in a format that enables targeted replacement.**

### Detection Path

1. `src/quality/repetition_detector.py:117-153` -- `_check_word_frequency()` flags words >3 standard deviations above mean frequency, returning `{word, count, expected_max, zscore}`
2. `src/quality/metrics_dashboard.py:221-223` -- flags are summarized as human-readable strings: `"Overused words: something, didn't, looked"`
3. These flag strings flow to the revision pipeline context (`orchestrator.py:347`)

### Where Remediation Should Happen

- **Craft Editor** (`src/agents/craft_editor.py:21-53`): Prompt says "Prose cliche reduction -- eliminate AI-tell phrases and cliches from the constraints list." It does **not** mention overused words specifically. The overused word list is **not** in its context -- the Craft Editor receives `craft_notes` (from gate critic failure codes) and `negative_constraints`, neither of which contain the per-scene overused word data.
- **Line Copy Editor** (Band 3, `src/revision/line_copy.py:26-57`): Receives `quality_flags` but as generic strings. Its prompt says "Word choice -- replace vague words with precise ones" -- generic, not targeted.
- **Anti-slop mechanism** (`src/concept_workshop/voice_discovery.py:90-115`): Merges global banned phrases from `config/negative_constraints.yaml` into `anti_slop_rules`. These are static banned phrases (AI-tells), **not** dynamically detected overused words.
- **Prose Stylist**: No overused-word awareness. The `negative_constraints` it receives (`src/orchestrator.py:651`) are the static YAML constraints, not dynamic per-scene flags.

### No Cross-Scene Tracker

The `RepetitionDetector` runs per-scene. It does compare n-grams across prior chapters (`src/quality/repetition_detector.py:184-208`), but the overused word check at line 117 only analyzes the **current scene's tokens**. There is no running word frequency tracker across the full manuscript.

### Recommended Fixes

1. **Pass the `flagged_words` list** (not just the summary string) to Band 3's prompt with explicit instructions: "The following words appear excessively in this scene. Replace or eliminate each: [word (count)] ..."
2. **Add a cross-scene frequency tracker** in `MetricsDashboard` that accumulates word frequencies across all generated scenes and flags persistent offenders
3. **Inject overused words into the Craft Editor** context as part of `craft_notes`
4. **Add dynamic banned words** to the Prose Stylist's negative constraints for subsequent scenes

---

## 8. Semantically Similar Paragraph Pairs -- High Counts

### How Similarity Is Measured

`src/quality/repetition_detector.py:250-276` -- `_check_paragraph_similarity()`:

1. **Method:** Embedding cosine similarity using the configured embedding function
2. **Embedding function:** `src/rag/embedding.py` with `use_mock=True` (set at `src/main.py:89`, `src/main.py:626`, `src/main.py:666`)
3. **Threshold:** `semantic_similarity_threshold = 0.85` (default at line 52)
4. **Scope:** Within-scene only -- compares all paragraph pairs within a single scene. No cross-scene comparison.
5. **Adjacency window:** `None` by default (line 62) -- all pairs compared, including non-adjacent paragraphs

### Why Counts Are High

**The mock embedding function is the primary culprit.** With `use_mock=True`, embeddings are likely low-dimensional or random vectors that produce unreliable similarity scores. The 0.85 threshold may be too low for the mock embedding space, causing many false-positive matches.

Additionally, the O(n^2) comparison at lines 263-269 compares *every* paragraph pair. For a scene with 15 paragraphs, that's 105 pairs. The high counts (34-88) suggest the mock embeddings are producing similarity scores clustered above 0.85.

### Score Impact

`src/quality/repetition_detector.py:290`: similar paragraphs are capped at -0.15 penalty (`min(0.15, 0.05 * len(similar_paragraphs))`). So even 88 pairs only deduct 0.15 from the repetition score. The cap prevents this inflated count from tanking the overall quality score.

### Recommended Fixes

1. **Use real embeddings** -- set `use_mock=False` or configure a real embedding model (e.g., `all-MiniLM-L6-v2`) for production runs
2. **Set an adjacency window** -- `adjacency_window=5` would only compare paragraphs within 5 positions of each other, reducing both false positives and computation
3. **Raise the threshold** for mock embeddings to 0.95, or disable the check entirely when using mocks
4. **Add a minimum paragraph length** filter -- very short paragraphs (1-2 sentences) of dialogue will produce false similarity matches

---

## 9. Timeout and Crash Handling -- Chapter 9 Failure

### Retry Mechanism

`src/model_router.py:103-133` -- the `complete()` method handles retries:

```python
max_retries = 2  # Hardcoded, NOT from config
for attempt in range(max_retries + 1):  # 3 total attempts (0, 1, 2)
```

- **Total attempts:** 3 (initial + 2 retries)
- **Timeout:** `timeout_seconds: 300` from `config/settings.yaml:15` (cloud config)
- **Backoff:** Exponential (`2 ** attempt` seconds) for 502/503/connect/timeout errors. Fixed sleep for 429 rate limits (`retry-after` header, capped at 30s).
- **No jitter:** Backoff is deterministic, which can cause thundering herd in parallel runs
- **Config mismatch:** `config/settings.yaml:114` has `max_structural_retries: 3` but this controls *gate critic retry loops* in the Orchestrator (`src/orchestrator.py:750`), NOT HTTP retries. The HTTP retry count is hardcoded at 2 in ModelRouter.

### Why Only 2 Retries Appeared

The user saw 2 timeout retries before KeyboardInterrupt. This matches the code: `max_retries = 2` means attempts 0, 1, 2. After attempt 0 timed out, retries 1 and 2 fired. The user cancelled during retry 2 (or between retries).

### KeyboardInterrupt Handling

`src/orchestrator.py:235-247` -- the `run_pipeline` method:

```python
try:
    for i, scene_card in enumerate(active_cards):
        result = await self.run_chapter(scene_card)
        ...
except KeyboardInterrupt:
    print("\nPipeline interrupted -- saving session...")
finally:
    if self.pipeline_session and self.session_id:
        self.pipeline_session.save(...)
```

The session save in `finally` is synchronous (JSON file write via `src/pipeline_session.py:28-53` using atomic temp-file rename), so it should survive the interrupt.

**However**, `src/main.py:835-839` has the cleanup:

```python
finally:
    await router.close()
    ledger.close()
    if story_state:
        story_state.close()
```

`router.close()` at `src/model_router.py:290-295` calls `await client.aclose()`. When KeyboardInterrupt fires during an `await`, the event loop is in a torn-down state. The `AsyncLibraryNotFoundError` occurs because `httpx.AsyncClient.aclose()` tries to use an async backend that was already shut down.

### Session Resume

`src/pipeline_session.py:140-165` -- `get_pending_cards()` filters out completed chapters by `(chapter_number, scene_number)` tuple. **This works at scene granularity**, so a crash mid-chapter loses only the current scene, not the whole chapter. The session file is saved after each scene at `src/orchestrator.py:216-219`.

### Recommended Fixes

1. **Make HTTP retry count configurable** -- add `max_http_retries` to settings.yaml and read it in ModelRouter
2. **Add jitter** to exponential backoff: `await asyncio.sleep(2 ** attempt + random.uniform(0, 1))`
3. **Fix KeyboardInterrupt cleanup** -- wrap `router.close()` in a sync-safe handler:
   ```python
   except KeyboardInterrupt:
       # Sync cleanup only -- async clients will be GC'd
       ledger.close()
       if story_state:
           story_state.close()
   ```
4. **Add graceful shutdown signal handling** in `main.py` using `asyncio.get_event_loop().add_signal_handler()` to cancel pending tasks before teardown

---

## 10. Pipeline Architecture Overview

### Per-Scene Pipeline (as implemented in `src/orchestrator.py:run_chapter()`)

| Step | Function/Method | Agent(s) | Model | Inputs | Outputs | Consumed By |
|------|----------------|----------|-------|--------|---------|-------------|
| P4-Pre | `orchestrator.py:269-280` | `PhysicsEnforcer` | *local logic* | scene_card | `{passed, issues, recommendations}` | Logged only |
| 1 | `orchestrator.py:284` `_run_plot_architect()` L586 | `PlotArchitect` | gemini_flash | scene_card, bible_summary, arc_context | `generation_brief` (str) | Step 2 |
| 2 | `orchestrator.py:288` `_run_prose_stylist()` L630 | `ProseStylist` | claude (temp 0.85) | generation_brief, assembled_context, negative_constraints, scene_card | `prose` (str) | Step 3 |
| 3 | `orchestrator.py:292` `_gate_loop()` L666 | `GateCritic` | claude (temp 0.3) | prose, scene_card, bible_summary | `evaluation` dict + possibly revised prose | Step 4, Canon |
| Canon | `orchestrator.py:295-311` | `CanonExpert` | gemini_flash | prose, scene_card | `canon_notes` (str) | Step 4 (if fired) |
| 4 | `orchestrator.py:314-315` `_run_craft_editor()` L781 | `CraftEditor` | haiku (temp 0.4) | prose, scene_card, negative_constraints, craft_notes+canon_notes | `final_prose` (str) | P3-1 |
| P3-1 | `orchestrator.py:318-333` | `MetricsDashboard` | *local analysis* | final_prose, scene_card, prior_chapters | `quality_metrics` dict | P3-2, logged |
| P3-2 | `orchestrator.py:336-353` | `RevisionPipeline` (3-5 bands) | gemini_flash, haiku | final_prose, quality_flags, scene_card, state | revised `final_prose` | Save |
| | Band 1: `StructuralContinuityReviewer` | gemini_flash | prose, scene_card, state | revised prose | Band 2 |
| | Band 2: `SceneEmotionReviewer` | haiku | prose, scene_card, voices | revised prose | Band 3 |
| | Band 3: `LineCopyEditor` | gemini_flash | prose, constraints, quality_flags | revised prose | Band 4? |
| | Band 4*: `DialoguePolishEditor` | haiku | prose, voices, quality_flags | revised prose | Band 5? |
| | Band 5*: `WorldbuildingCoherenceReviewer` | gemini_flash | prose, canon_elements | revised prose | Save |
| Save | `orchestrator.py:356` `_save_chapter()` L836 | -- | -- | final_prose | markdown file | Post-save |
| P4-Post | `orchestrator.py:360-372` | `PhysicsEnforcer` | *local logic* | scene_card, final_prose | `{passed, issues}` | Logged only |
| P2-1 | `orchestrator.py:377-378` `_run_post_save()` L456 | `Summarizer` | gemini_flash (temp 0.2) | prose, scene_card, state_snapshot | summary + state_diff | P2-2 through P2-5 |
| P2-2 | `orchestrator.py:501-511` | `ChapterMemory` | *ChromaDB store* | summary, metadata | stored embedding | Context assembly |
| P2-3 | `orchestrator.py:514-515` | `StateDiffApplier` | *local logic* | state_diff | updated SQLite | Future scenes |
| P2-4 | `orchestrator.py:519-550` | `StoryState` | *SQLite write* | scores, summary | chapter_log + scene_log | Future context |
| P2-5 | `orchestrator.py:554-565` | `ContradictionScanner` | *local logic* | prose, scene_card | contradiction_flags | Logged |
| WB | `orchestrator.py:567-582` | `LoreService` | *extraction* | prose, scene_card | provisional lore entries | Worldbuilding DB |
| P3-3 | `orchestrator.py:385-400` | `CharacterSpecialist` | gemini_flash (temp 0.4) | prose, scene_card, voices, profiles | `{verdict, analysis}` | Logged |
| P4-Judge | `orchestrator.py:403-416` | `JudgeEvaluator` | claude (temp 0.2) | prose, scene_card | `{scores, overall_score, recommendation}` | Logged |
| Milestone | `orchestrator.py:447-453` | `MilestoneGates` | *local logic* | scene_card | milestone_info or None | Pipeline control |

\* Bands 4-5 are conditional, only in `AdaptiveRevisionPipeline`

### Per-Chapter Boundary (in `run_pipeline()`)

| Step | Location | Agent | Condition |
|------|----------|-------|-----------|
| Chapter Gate | `orchestrator.py:222-229` | `ChapterGateCritic` | Last scene in chapter |

### Agents Defined in settings.yaml but NOT Called in Active Pipeline

| Agent | settings.yaml | Status |
|-------|--------------|--------|
| `judge_evaluator` | Line 66 | **Opt-in via `--judge` flag** -- not a bug, but not auto-enabled |
| `manuscript_reviewer` | Line 67 | **Never wired** into CLI pipeline. Class exists at `src/agents/manuscript_reviewer.py` but no call site in orchestrator or main |
| `canon_expert` | Line 105 | **Conditional on missing field** -- effectively dead code (see Issue #1) |
| `outline_planner` | Line 75 | Workshop/planning agent, not part of generation pipeline |
| `concept_workshop` | Line 74 | Workshop agent, not part of generation pipeline |
| `seed_builder` | Line 76 | Import/build agent, not part of generation pipeline |
| `stress_test` | Line 95 | Workshop agent, not part of generation pipeline |
| `lore_extractor` | Line 108 | Used by LoreService internally, not directly by orchestrator |

---

## Prioritized Fix Recommendations

Ranked by impact on output quality:

### Critical (Immediate Impact)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| 1 | **Canon Expert dead code** (Issue #1) | Remove `canon_elements_needed` guard; run canon expert on every scene | Low |
| 2 | **Gate Critic rubber-stamping** (Issue #2) | Add calibration anchors, few-shot examples, chain-of-thought scoring | Medium |
| 3 | **Quality flags not actionable** (Issue #3) | Pass structured flag data (not summary strings) to revision band prompts | Medium |
| 4 | **Arc state frozen** (Issue #5) | Allow self-transitions; verify initial arc phases match concept seed | Low |

### High (Reliability)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| 5 | **Milestone per-scene** (Issue #4) | Move check to `run_pipeline()` after last scene in chapter | Low |
| 6 | **Crash cleanup** (Issue #9) | Fix async teardown; make HTTP retries configurable; add jitter | Medium |
| 7 | **Judge not auto-enabled** (Issue #6) | Auto-enable at milestones or make Phase 4 default | Low |

### Medium (Quality Improvement)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| 8 | **Overused words persist** (Issue #7) | Pass flagged word lists to Craft Editor and Band 3 with explicit replacement instructions | Medium |
| 9 | **False semantic similarity** (Issue #8) | Use real embeddings; add adjacency window; raise threshold for mocks | Medium |
| 10 | **manuscript_reviewer unwired** (Issue #6) | Wire as post-pipeline evaluation step or document as API-only | Low |
