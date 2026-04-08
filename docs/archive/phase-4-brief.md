# Claude Code Project Brief: AI Writers' Room — Phase 4 (Export Pipeline, Story Physics Integration, Adaptive Revision, and Scene Card Generation)

## Context

Phases 1–3 of the AI Writers' Room are complete. All 265 tests pass. The existing codebase contains:

### Phase 1 (Complete)
- **`src/model_router.py`** — Routes agent calls to llama-server (local) or OpenRouter (cloud) based on `config/settings.yaml`
- **`src/agents/base_agent.py`** — Abstract agent class with system prompt loading, `run()` and `run_structured()` methods
- **`src/agents/plot_architect.py`** — Scene card → generation brief
- **`src/agents/prose_stylist.py`** — Generation brief + context → prose
- **`src/agents/gate_critic.py`** — Prose → structured CriticFailure JSON with 14 failure codes and automatic routing
- **`src/agents/craft_editor.py`** — Non-blocking voice/polish improvements
- **`src/memory/context_assembler.py`** — Four-tier memory system with backward compat fallback
- **`src/orchestrator.py`** — Event-driven loop: PlotArchitect → ProseStylist → GateCritic (retry) → CraftEditor → [RevisionPipeline] → save → [QualityMetrics] → [Phase 2 post-save] → [CharacterSpecialist] → [MilestoneGate]. All Phase 2/3 deps are optional with `None` defaults.
- **`src/run_ledger.py`** — SQLite append-only event log (event types: `pipeline_start`, `chapter_start`, `agent_start`, `agent_complete`, `gate_pass`, `gate_fail`, `craft_edit_complete`, `state_diff_proposed`, `state_diff_committed`, `revision_band_start`, `revision_band_complete`, `milestone_reached`, `milestone_gate_paused`, `pipeline_complete`, `contradiction_scan`, `summarizer_complete`)
- **`src/main.py`** — CLI entry point with `--phase` flag (1, 2, or 3), `--no-revision`, `--no-milestones`

### Phase 2 (Complete)
- **`src/planning/story_physics.py`** — `CausalityChainValidator`, `RevelationMap`, `PromisePayoffLedger`, `StoryPhysicsValidator` (standalone validators, **NOT yet integrated into the orchestrator pipeline**)
- **`src/planning/pressure_matrix.py`** — `PressureMatrix` with escalation validation (standalone, **NOT yet integrated**)
- **`src/planning/scene_economics.py`** — `SceneEconomics` "why now?" validation (standalone, **NOT yet integrated**)
- **`src/memory/story_state.py`** — SQLite with 7 tables: characters, character_knowledge, character_relationships, plot_threads, timeline, chekhov_guns, chapter_log. Includes `init_from_concept_seed()`, `get_state_hash()`, CRUD for all tables.
- **`src/memory/knowledge_layers.py`** — Three-layer system (truth/belief/narrative_exposure) with `get_beliefs_for_characters()`, `check_belief_accuracy()`, `get_dramatic_irony()`
- **`src/memory/chapter_memory.py`** — ChromaDB-backed chapter summary storage
- **`src/agents/summarizer.py`** — Compresses chapters into summaries + state diffs (JSON)
- **`src/memory/state_diff.py`** — `StateDiffApplier`: validates and applies diffs with state hash tracking
- **`src/memory/contradiction_scanner.py`** — Post-chapter consistency scanner (5 scan types)
- **`src/rag/embedding.py`** — `MockEmbeddingFunction` + `SentenceTransformerEmbedding`
- **`src/rag/canon_db.py`** — ChromaDB vector DB for franchise canon
- **`src/rag/wiki_ingester.py`** — Entity-aware chunking, source authority classification
- **`src/rag/hybrid_search.py`** — Semantic + BM25, reciprocal rank fusion
- **`src/rag/canon_evidence.py`** — `CanonEvidenceRanker`: confidence = combined_score × source_authority_weight
- **`src/agents/canon_expert.py`** — RAG-powered lore validation agent

### Phase 3 (Complete)
- **`src/quality/repetition_detector.py`** — Word frequency, n-gram, opener, paragraph similarity analysis
- **`src/quality/pacing_analyzer.py`** — Sentence length variance, dialogue ratio, scene type classification, event density
- **`src/quality/voice_checker.py`** — Banned phrase detection, adverb density, metaphor cooldown, voice fidelity
- **`src/quality/slop_detector.py`** — AI-tell detection, burstiness scoring, show-don't-tell flagging, filler patterns
- **`src/quality/metrics_dashboard.py`** — Aggregator: runs all 4 checkers, weighted average (0.25 each), pass threshold >= 0.6. Methods: `analyze_chapter()`, `analyze_manuscript()`.
- **`src/quality/milestone_gates.py`** — Pauses at first_plot_point/midpoint/second_plot_point with CLI callback
- **`src/agents/character_specialist.py`** — OOC detection agent (supplementary, uses `run_structured()`)
- **`src/revision/structural_continuity.py`** — Band 1: plot holes, arc consistency, timeline
- **`src/revision/scene_emotion.py`** — Band 2: conflict quality, turning points, emotional arc
- **`src/revision/line_copy.py`** — Band 3: prose polish, AI-tell removal, rhythm
- **`src/revision/pipeline.py`** — Sequential 3-band orchestrator with ledger events

### Existing Config
- **`config/settings.yaml`** — deployment_mode (local/cloud/hybrid), models (local + cloud), agent_routing for all agents, pipeline settings
- **`config/failure_codes.yaml`** — 14 failure codes across structural/voice/polish categories
- **`config/negative_constraints.yaml`** — Banned phrases (4 categories) and structural_rules (adverb density, sentence variance, opener pct, metaphor cooldown)

### Existing Tests
- **265 tests passing** across 19 test files
- **`tests/conftest.py`** — Fixtures: sample_concept_seed, sample_scene_card, temp_dir, mock_router, settings_yaml, story_state, story_state_initialized, knowledge_layers, mock_embedding_function, chapter_memory, negative_constraints, metrics_dashboard, sample_prose, sloppy_prose

### Empty Stub Directories
- `src/export/` — `__init__.py` only (ready for Phase 4)

### Data Fixtures
- `data/story_bibles/beyond_the_veil/` — concept_seed.json + 5 scene cards (chapters 1-5)
- `data/eval_corpus/` — 3 reference chapters + eval_rubric.json
- `schemas/` — concept_seed.json, scene_card.json, story_physics.json, state_diff.json, canon_evidence.json, failure_code.json, character_sheet.json, story_bible.json

Read `AI_Writers_Room_Design_Document_v1.1.md` in the project root for the full technical specification.

---

## What to Build

Phase 4 completes the pipeline's autonomy: **export** final manuscripts to publishable formats, **integrate story physics** validators into the live generation loop, **auto-generate scene cards** from a concept seed, enable **adaptive revision** (5 bands when metrics warrant it), and add a **session persistence** layer so multi-hour runs can be paused and resumed. The goal is a pipeline that can take a concept seed, generate a full novel outline, produce all chapters with quality gates, and export the finished manuscript — end to end.

---

## Implementation Order

### Step 1: Export Pipeline — Markdown Assembler (`src/export/markdown_assembler.py`)

Assemble all generated chapter files into a single, clean manuscript markdown file:

1. **Chapter collection** — Scan `data/manuscripts/` (or configured output dir) for `chapter_*_scene_*.md` files. Sort by chapter/scene number. Handle multi-scene chapters (concatenate scenes within a chapter, separated by scene break markers `* * *`).

2. **Front matter generation** — From the concept seed, generate manuscript front matter:
   - Title page: project_title, "A [franchise] Novel"
   - Dedication placeholder (configurable)
   - Table of contents (auto-generated from chapter numbers)

3. **Chapter formatting** — Each chapter gets:
   - `# Chapter N` heading
   - Optional chapter title (if provided in scene card `notes` field)
   - Scene break markers between multi-scene chapters
   - Consistent paragraph spacing

4. **Manuscript statistics** — Append a colophon section with:
   - Total word count
   - Per-chapter word counts
   - Generation date
   - Pipeline phase used
   - Quality metrics summary (if available from chapter_log in story state)

**Class design:**
```python
class MarkdownAssembler:
    def __init__(self, manuscripts_dir: str = "data/manuscripts", concept_seed: dict = None):
        ...

    def assemble(self, include_stats: bool = True) -> str:
        """Assemble all chapters into a single markdown manuscript.
        Returns the complete manuscript as a string."""

    def save(self, output_path: str = "data/export/manuscript.md", include_stats: bool = True) -> Path:
        """Assemble and save to file."""
```

### Step 2: Export Pipeline — DOCX Exporter (`src/export/docx_exporter.py`)

Convert the assembled markdown manuscript to a properly formatted Word document:

1. **Document structure** — Use `python-docx` to create a `.docx` with:
   - Title page (centered, large font)
   - Table of contents (Word-native TOC field)
   - Chapter headings (Heading 1 style)
   - Body text (Normal style, 12pt, 1.5 line spacing)
   - Scene breaks (centered `* * *` with spacing)
   - Page breaks before each chapter

2. **Typography** — Follow mass-market fiction conventions:
   - Font: Times New Roman or Georgia, 12pt
   - First paragraph of each chapter/scene: no indent
   - Subsequent paragraphs: 0.5" first line indent
   - Chapter headings: centered, bold, 18pt
   - Margins: 1" all around

3. **Metadata** — Set Word document properties:
   - Title, author, subject from concept seed
   - Creation date
   - Keywords: genre, franchise

**Class design:**
```python
class DocxExporter:
    def __init__(self, concept_seed: dict = None):
        ...

    def export(self, manuscript_md: str, output_path: str = "data/export/manuscript.docx") -> Path:
        """Convert markdown manuscript to DOCX. Returns path to created file."""
```

### Step 3: Export Pipeline — EPUB Exporter (`src/export/epub_exporter.py`)

Convert the assembled markdown to a valid EPUB ebook:

1. **EPUB structure** — Use `ebooklib` to create an EPUB 3.0 file:
   - Cover page (text-based, styled with CSS)
   - Table of contents (EPUB NCX/nav)
   - One XHTML file per chapter
   - Embedded CSS for typography

2. **Chapter splitting** — Each `# Chapter N` heading becomes a separate EPUB section/file.

3. **Metadata** — EPUB metadata from concept seed:
   - Title, creator (author placeholder), language, identifier (UUID)
   - Publisher placeholder
   - Description from `premise.logline`

4. **Styling** — Embedded CSS for:
   - Body font: serif, readable size
   - Chapter headings: centered, large
   - Scene breaks: centered, with vertical spacing
   - First paragraph: no indent

**Class design:**
```python
class EpubExporter:
    def __init__(self, concept_seed: dict = None):
        ...

    def export(self, manuscript_md: str, output_path: str = "data/export/manuscript.epub") -> Path:
        """Convert markdown manuscript to EPUB. Returns path to created file."""
```

### Step 4: Export Pipeline — Unified Export Manager (`src/export/export_manager.py`)

Orchestrate all export formats from a single entry point:

```python
class ExportManager:
    def __init__(self, manuscripts_dir: str = "data/manuscripts", concept_seed: dict = None):
        ...

    def export_all(self, output_dir: str = "data/export", formats: list[str] = None) -> dict:
        """Export manuscript to all requested formats.
        formats: list of "md", "docx", "epub" (default: all three)
        Returns: {"md": Path, "docx": Path, "epub": Path}
        """

    def export_markdown(self, output_dir: str = "data/export") -> Path: ...
    def export_docx(self, output_dir: str = "data/export") -> Path: ...
    def export_epub(self, output_dir: str = "data/export") -> Path: ...
```

### Step 5: Story Physics Integration (`src/planning/physics_enforcer.py`)

The Phase 2 story physics validators (`CausalityChainValidator`, `RevelationMap`, `PromisePayoffLedger`, `PressureMatrix`, `SceneEconomics`) exist as standalone classes but are **not wired into the orchestrator**. Create an enforcer layer that runs these validators at key pipeline moments.

**Design:**
```python
class PhysicsEnforcer:
    def __init__(self, story_state: StoryState, concept_seed: dict, scene_cards: list[dict]):
        ...

    def validate_pre_chapter(self, scene_card: dict) -> dict:
        """Run before chapter generation. Checks:
        - SceneEconomics: does this scene card have a valid why_now?
        - PressureMatrix: is character pressure escalating appropriately?
        - PromisePayoffLedger: are overdue promises being addressed?
        Returns {valid: bool, issues: list[dict], recommendations: list[str]}
        """

    def validate_post_chapter(self, scene_card: dict, prose: str, chapter_num: int) -> dict:
        """Run after chapter generation. Checks:
        - CausalityChain: do this chapter's events have causes and consequences?
        - RevelationMap: are reveals ordered correctly (setup before reveal)?
        Returns {valid: bool, issues: list[dict]}
        """

    def validate_milestone(self, milestone_phase: str, chapter_results: list[dict]) -> dict:
        """Run at milestone gates. Checks phase-specific physics:
        - After First Plot Point: causal lock-in established?
        - After Midpoint: protagonist pressure shift verified?
        - After Second Plot Point: all revelations revealed?
        Returns {valid: bool, issues: list[dict], summary: str}
        """
```

**Orchestrator integration:** Add `physics_enforcer: Optional["PhysicsEnforcer"] = None` to the Orchestrator. Run `validate_pre_chapter` before PlotArchitect. Run `validate_post_chapter` after save. Feed validation issues into the generation context as guidance notes.

### Step 6: Scene Card Auto-Generator (`src/planning/scene_card_generator.py`)

Currently, scene cards must be manually written. Create an agent that generates scene cards from a concept seed + story physics plan:

1. **Outline generation** — New agent `OutlinePlanner` that takes a concept seed and produces a full chapter-by-chapter outline:
   - Assigns structural phases following Brooks's four-part structure
   - Distributes plot threads, promises, and revelations across chapters
   - Assigns POV characters using the `pov_structure` from concept seed
   - Sets emotional trajectories per chapter
   - Generates `why_now` justifications for each scene

2. **Scene card formatting** — Convert outline entries into valid scene card JSON matching `schemas/scene_card.json`:
   - All required fields populated
   - `characters_present` derived from plot thread assignments
   - `canon_elements_needed` derived from the outline's world-building requirements
   - `target_word_count` calculated from `meta.target_word_count / meta.target_chapters`

3. **Physics validation** — Run the `PhysicsEnforcer` on generated scene cards before accepting them:
   - SceneEconomics validation (no generic `why_now`)
   - PressureMatrix check (escalation trajectory)
   - PromisePayoff check (promises planted early, paid later)
   - Reject and regenerate cards that fail validation

**Agent design:**
```python
class OutlinePlanner(BaseAgent):
    def __init__(self, router, role="outline_planner"):
        super().__init__(router, role)

    async def run(self, context: dict) -> dict:
        """Generate a complete chapter outline from concept seed.
        context: {concept_seed, target_chapters, story_physics_plan (optional)}
        Returns: {outline: list[dict], scene_cards: list[dict]}
        """
```

Write the system prompt at `prompts/agent_system_prompts/outline_planner.md`.

**Scene Card Generator wrapper:**
```python
class SceneCardGenerator:
    def __init__(self, router, physics_enforcer=None):
        self.planner = OutlinePlanner(router)
        self.physics = physics_enforcer

    async def generate(self, concept_seed: dict, max_retries: int = 3) -> list[dict]:
        """Generate all scene cards for a novel.
        Runs outline planner, validates with physics enforcer, retries on failure.
        Returns: list of scene card dicts matching schemas/scene_card.json
        """

    def save_scene_cards(self, scene_cards: list[dict], output_dir: str) -> list[Path]:
        """Save scene cards as individual JSON files."""
```

### Step 7: Adaptive Revision — Five-Band Expansion (`src/revision/adaptive_revision.py`)

The design doc specifies: "Expand to five passes only if metrics show benefit." Add two conditional bands and logic to decide when to apply them.

**New bands:**

- **Band 4: Dialogue Polish** (`src/revision/dialogue_polish.py`) — Extends BaseAgent. Focuses exclusively on dialogue: tag variety, subtext, character voice differentiation, exposition-in-dialogue reduction. Only runs if `pacing_analyzer.dialogue_ratio > 0.25` (scene has significant dialogue) AND `quality_metrics.voice.voice_fidelity_score < 0.8`.

- **Band 5: Worldbuilding Coherence** (`src/revision/worldbuilding_coherence.py`) — Extends BaseAgent. Ensures world-building details are consistent: technology levels, geography, cultural references, franchise-specific terminology. Only runs if the scene card has `canon_elements_needed` entries AND `character_specialist.verdict != "pass"` or quality flags include canon-related issues.

**Adaptive logic:**
```python
class AdaptiveRevisionPipeline(RevisionPipeline):
    """Extends RevisionPipeline with conditional Band 4 and Band 5."""

    def __init__(self, router, ledger, metrics_dashboard=None):
        super().__init__(router, ledger)
        self.band4 = DialoguePolishEditor(router)
        self.band5 = WorldbuildingCoherenceReviewer(router)
        self.metrics = metrics_dashboard

    async def run(self, prose: str, context: dict) -> dict:
        """Run 3 mandatory bands, then conditionally run bands 4 and 5.
        Decision based on quality metrics from the 3-band output.
        """
```

Write system prompts at:
- `prompts/revision_prompts/dialogue_polish.md`
- `prompts/revision_prompts/worldbuilding_coherence.md`

### Step 8: Session Persistence (`src/pipeline_session.py`)

Multi-chapter pipeline runs can take hours. Add save/resume capability:

1. **Session state** — Serialize the pipeline's progress to a JSON file:
   - Which scene cards have been processed
   - Which are pending
   - Current quality metrics per chapter
   - Story state hash for continuity verification
   - Timestamp and configuration snapshot

2. **Save on interrupt** — Register a signal handler (SIGINT/SIGTERM) that saves session state before exit. Also save after each completed chapter.

3. **Resume from session** — Load session state and skip already-completed chapters. Verify story state hash matches to detect external modifications.

**Class design:**
```python
class PipelineSession:
    def __init__(self, session_dir: str = "data/sessions"):
        ...

    def save(self, session_id: str, state: dict) -> Path:
        """Save pipeline session state to JSON."""

    def load(self, session_id: str) -> dict | None:
        """Load session state. Returns None if not found."""

    def list_sessions(self) -> list[dict]:
        """List all saved sessions with metadata."""

    def mark_chapter_complete(self, session_id: str, chapter_num: int, result: dict):
        """Update session with completed chapter."""
```

**Orchestrator integration:** Add optional `session: Optional["PipelineSession"] = None` to Orchestrator. In `run_pipeline`, check for existing session and skip completed chapters.

### Step 9: LLM-as-Judge Evaluation (`src/quality/llm_judge.py`)

Add a cloud-model-powered evaluation that provides a holistic quality assessment beyond the heuristic metrics:

1. **Structured rubric** — Define a JSON rubric (`config/eval_rubric.yaml`) with scoring criteria:
   - Narrative engagement (1-10): Does the chapter compel the reader forward?
   - Character authenticity (1-10): Do characters feel real and distinct?
   - Prose craftsmanship (1-10): Is the writing itself good?
   - Thematic resonance (1-10): Does the scene serve the novel's thesis?
   - Structural contribution (1-10): Does this chapter earn its place?

2. **Evaluation agent** — New agent `JudgeEvaluator` that sends prose + rubric to a cloud model (Claude Sonnet via OpenRouter) for scoring. Uses `run_structured()` for JSON output.

3. **Manuscript-level evaluation** — After all chapters are generated, run the judge across the full manuscript for a holistic report.

**Agent design:**
```python
class JudgeEvaluator(BaseAgent):
    def __init__(self, router, role="judge_evaluator"):
        super().__init__(router, role)

    async def evaluate_chapter(self, context: dict) -> dict:
        """Returns {scores: dict, feedback: str, recommendation: str}"""

    async def evaluate_manuscript(self, chapters: list[dict]) -> dict:
        """Holistic manuscript evaluation. Returns {manuscript_score, chapter_scores, report}"""
```

Write system prompt at `prompts/agent_system_prompts/judge_evaluator.md`.
Write evaluation rubric at `config/eval_rubric.yaml`.

### Step 10: Update `main.py`

Update the CLI to support Phase 4 features:

1. **`--phase 4`** — Initializes all Phase 4 components (physics enforcer, adaptive revision, LLM judge)
2. **`--export`** flag — After pipeline completes, run export (md/docx/epub)
3. **`--export-only`** flag — Skip generation, just export existing manuscripts
4. **`--export-formats`** — Comma-separated: `md,docx,epub` (default: all)
5. **`--generate-outline`** — Generate scene cards from concept seed before running pipeline
6. **`--resume`** flag — Resume from saved session
7. **`--session-id`** — Specify session ID (default: auto-generated from concept seed title + timestamp)
8. **`--judge`** flag — Run LLM-as-judge evaluation after generation

### Step 11: Tests

Write tests covering all new Phase 4 components:

- **`tests/test_markdown_assembler.py`** — Test chapter collection, sorting, front matter, stats. Test with mock chapter files in temp dir.
- **`tests/test_docx_exporter.py`** — Test DOCX creation, verify document structure (headings, paragraphs, styles). Test with sample markdown.
- **`tests/test_epub_exporter.py`** — Test EPUB creation, verify metadata, chapter splitting. Test with sample markdown.
- **`tests/test_export_manager.py`** — Test unified export, all formats, selective formats.
- **`tests/test_physics_enforcer.py`** — Test pre/post chapter validation, milestone validation. Use story_state_initialized fixture with mock data.
- **`tests/test_scene_card_generator.py`** — Test with mock router. Verify generated cards match schema. Verify physics validation retry loop.
- **`tests/test_adaptive_revision.py`** — Test 3-band-only path, 4-band path, 5-band path. Verify conditional logic.
- **`tests/test_pipeline_session.py`** — Test save/load/resume. Test chapter completion tracking. Test hash verification.
- **`tests/test_llm_judge.py`** — Test with mock router. Verify rubric scoring structure. Test manuscript evaluation.

**Phase 4 milestone**: Run the full end-to-end pipeline: concept seed → auto-generated scene cards → chapter generation with physics enforcement → adaptive revision → quality metrics → export to all 3 formats. All 265+ existing tests must continue to pass.

---

## Dependencies to Add

Add to `requirements.txt`:
```
# Phase 4: Export
python-docx>=1.1.0
ebooklib>=0.18
```

Note: `python-docx` and `ebooklib` are already listed as commented-out entries in `requirements.txt`.

---

## Key Technical Decisions

- **Export is post-pipeline.** It reads from the manuscripts directory and does not interfere with generation. It can be run independently via `--export-only`.
- **Story physics enforcement is advisory.** `PhysicsEnforcer` produces warnings and recommendations but does not block generation. Issues are logged and fed into generation context as guidance.
- **Scene card generation is a pre-pipeline step.** It runs before the main generation loop. Generated cards are saved to disk and can be manually edited before running the pipeline.
- **Adaptive revision is opt-in via Phase 4.** The base 3-band pipeline (Phase 3) still runs in `--phase 3` mode. Phase 4 adds the conditional 4th and 5th bands.
- **Session persistence is automatic in Phase 4.** Sessions are saved after each chapter. Resume is manual via `--resume`.
- **LLM-as-judge requires cloud access.** It routes to cloud models (Claude Sonnet) and costs real API credits. It's opt-in via `--judge`.
- **Backward compatibility.** Phases 1, 2, and 3 continue to work unchanged. All 265 existing tests must pass. All new Phase 4 dependencies are optional kwargs with `None` defaults on the Orchestrator.
