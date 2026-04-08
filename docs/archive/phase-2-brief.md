> **Historical document.** This was the project brief used to build Phase 2. It describes the codebase as it existed after Phase 1. For current architecture, see `AI_Writers_Room_Design_Document_v1.1.md` and `Phase_5_Changelog.md`.

# Claude Code Project Brief: AI Writers' Room — Phase 2 (Memory, Canon, and Story Physics)

## Context

Phase 1 of the AI Writers' Room is complete. The minimal viable pipeline is built and all 44 unit tests pass. The existing codebase contains:

- **`src/model_router.py`** — Routes agent calls to llama-server (local) or OpenRouter (cloud) based on `config/settings.yaml`
- **`src/agents/base_agent.py`** — Abstract agent class with system prompt loading and structured output
- **`src/agents/plot_architect.py`** — Scene card → generation brief
- **`src/agents/prose_stylist.py`** — Generation brief + context → prose
- **`src/agents/gate_critic.py`** — Prose → structured CriticFailure JSON with 14 failure codes across 3 categories (structural/voice/polish) and automatic routing (full_rewrite/targeted_revision/craft_edit)
- **`src/agents/craft_editor.py`** — Non-blocking voice/polish improvements
- **`src/memory/context_assembler.py`** — Phase 1 simplified version (concatenates story bible, scene card, previous chapter text)
- **`src/orchestrator.py`** — Event-driven loop: PlotArchitect → ProseStylist → GateCritic → retry loop → CraftEditor → save. All steps emit typed events to RunLedger.
- **`src/run_ledger.py`** — SQLite-backed append-only event log
- **`src/main.py`** — CLI entry point (`python -m src.main <concept_seed> <scene_cards_dir>`)
- **`config/settings.yaml`** — Deployment mode, model assignments, agent routing, pipeline settings
- **`config/failure_codes.yaml`** — Failure taxonomy with routing rules
- **`config/negative_constraints.yaml`** — Banned phrases and structural rules
- **`schemas/`** — JSON schemas for concept_seed, scene_card, failure_code, canon_evidence, state_diff, story_physics, story_bible, character_sheet
- **`prompts/agent_system_prompts/`** — System prompts for plot_architect, prose_stylist, gate_critic, craft_editor
- **`data/story_bibles/beyond_the_veil/`** — Test fixture: concept seed + Chapter 1 scene card
- **`tests/`** — 44 passing tests covering ModelRouter, failure codes, ContextAssembler, Orchestrator

Read `AI_Writers_Room_Design_Document_v1.1.md` in the project root — it contains the full technical specification for everything below.

## What to Build

Phase 2 adds three major subsystems to the existing pipeline: **Story Physics validation**, **persistent story state with knowledge layers**, and **canon knowledge retrieval (RAG)**. The goal is to generate 5 consecutive chapters with consistent continuity, tracked promise/payoff, and zero contradiction scanner failures.

## Implementation Order

### Step 1: Story Physics Pass (`src/planning/story_physics.py`)

Implement the Story Physics validation layer that runs between concept seed approval and scene card generation. It validates that the structural plan has causal and emotional infrastructure to sustain a novel.

**Components to implement:**

1. **Causality Chain Validator** — Build a directed graph of plot events. Every major event must have at least one traceable upstream cause and at least one downstream consequence. Flag events that are:
   - Causally orphaned (no upstream cause — things that "just happen")
   - Causally dead (no downstream effect — events that go nowhere)

2. **Revelation Map** — Track what information the reader learns and when. Validate:
   - No critical reveals happen too early (deflating tension) or too late (feeling arbitrary)
   - Information is released in an order that builds mystery, not confusion
   - Red herrings have both planting and subversion points

3. **Promise/Payoff Ledger** — Track every narrative promise with:
   - `planted_chapter`: where the promise appears
   - `payoff_chapter`: where it resolves (or subverts)
   - `type`: setup_payoff | foreshadow | chekhov | thematic
   - `status`: unfulfilled | fulfilled | subverted
   - At structural milestones, flag unfulfilled promises that should have resolved and promises lacking any planned payoff

4. **Character-Pressure Matrix** — For each chapter, track external and internal pressures on each POV character. Validate:
   - No POV character coasts through more than one consecutive chapter without meaningful pressure
   - Pressure escalates across acts (Part 1 < Part 2 < Part 3)
   - The climax concentrates maximum pressure on the protagonist

5. **Chapter-Level "Why Now?" Check** — Validate that every scene card answers: "Why does this scene happen at this point and not earlier or later?" Flag scenes where the answer is effectively "because the outline says so."

**Schema**: Use the StoryPhysics JSON schema already in `schemas/story_physics.json`. It defines causality_chains, revelation_map, promise_payoff_ledger, and pressure_matrix.

**Also implement** `src/planning/scene_economics.py` (the "why now?" checker) and `src/planning/pressure_matrix.py` (pressure tracking per chapter).

### Step 2: SQLite Story State Database (`src/memory/story_state.py`)

Implement the full SQLite story state tracker with these tables from the design doc:

```sql
CREATE TABLE characters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    current_location TEXT,
    emotional_state TEXT,
    arc_position TEXT,
    inventory TEXT,             -- JSON: items they carry
    last_appearance_chapter INTEGER,
    last_appearance_scene INTEGER
);

CREATE TABLE character_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id TEXT NOT NULL REFERENCES characters(id),
    fact_id TEXT NOT NULL,
    fact_description TEXT NOT NULL,
    layer TEXT CHECK(layer IN ('truth', 'belief', 'narrative_exposure')) NOT NULL,
    is_accurate BOOLEAN,       -- for belief layer: does it match truth?
    acquired_chapter INTEGER,
    source TEXT,                -- witnessed | told | inferred | false
    UNIQUE(character_id, fact_id, layer)
);

CREATE TABLE character_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_a TEXT NOT NULL REFERENCES characters(id),
    character_b TEXT NOT NULL REFERENCES characters(id),
    relationship_type TEXT,
    status TEXT,
    last_updated_chapter INTEGER,
    UNIQUE(character_a, character_b)
);

CREATE TABLE plot_threads (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT CHECK(status IN ('planted', 'active', 'escalating', 'resolving', 'resolved')),
    planted_chapter INTEGER,
    urgency TEXT CHECK(urgency IN ('background', 'rising', 'critical', 'climactic')),
    related_characters TEXT,   -- JSON array of character IDs
    resolution_notes TEXT
);

CREATE TABLE timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_number INTEGER,
    scene_number INTEGER,
    story_date TEXT,
    elapsed_time TEXT,
    key_events TEXT            -- JSON array
);

CREATE TABLE chekhov_guns (
    id TEXT PRIMARY KEY,
    item_description TEXT NOT NULL,
    planted_chapter INTEGER,
    planted_context TEXT,
    fired_chapter INTEGER DEFAULT NULL,
    fired_status TEXT CHECK(fired_status IN ('unfired', 'fired', 'subverted')) DEFAULT 'unfired'
);

CREATE TABLE chapter_log (
    chapter_number INTEGER PRIMARY KEY,
    word_count INTEGER,
    structural_phase TEXT,
    pov_character TEXT,
    summary TEXT,
    quality_scores TEXT,       -- JSON: {structural, voice, polish}
    failure_codes TEXT,        -- JSON array
    revision_status TEXT CHECK(revision_status IN ('draft', 'gate_failed', 'gate_passed', 'craft_edited', 'revised', 'approved')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revised_at TIMESTAMP
);
```

Provide Python methods for CRUD operations, querying character state at a given chapter, and bulk initialization from a concept seed's ensemble_cast.

### Step 3: Knowledge Layers (`src/memory/knowledge_layers.py`)

Implement the three-layer knowledge state system that operates on the `character_knowledge` table:

- **Truth layer**: What is objectively true in the story world. Agents check assertions against this.
- **Belief layer**: What each character believes. May differ from truth (e.g., the scholar believes their plan is justified). The `is_accurate` flag tracks whether each belief matches truth.
- **Narrative Exposure layer**: What the reader has been explicitly shown about each character's knowledge state. Drives dramatic irony — the reader may know things characters don't, and vice versa.

**Key methods:**
- `add_truth(fact_id, description, chapter)` — Add an objective fact
- `add_belief(character_id, fact_id, description, is_accurate, chapter, source)` — Add a character belief
- `add_exposure(character_id, fact_id, description, chapter)` — Record what the reader has been shown
- `get_beliefs_for_characters(character_ids) -> str` — Format all beliefs for the given characters into a context string for the prose stylist (this gets injected into the assembled context)
- `check_belief_accuracy(character_id, fact_id) -> bool` — Does this character's belief match truth?
- `get_dramatic_irony(chapter) -> list` — Facts where reader exposure differs from character beliefs

### Step 4: Chapter Memory with ChromaDB (`src/memory/chapter_memory.py`)

Implement vector-based chapter summary storage for Tier 3 context:

- Store chapter summaries as embedded vectors in ChromaDB
- `add_summary(chapter_number, summary_text)` — Embed and store
- `get_recent_summaries(n=3) -> str` — Retrieve last N summaries as formatted text
- `search_summaries(query, k=5) -> list` — Semantic search across all summaries

**Embedding model**: Use `nomic-embed-text` via Ollama (already in settings.yaml) or `sentence-transformers` as fallback. The embedding model is ~0.5GB and coexists with generation models.

**Add `chromadb` to `requirements.txt`** (uncomment the existing line).

### Step 5: Summarizer Agent (`src/agents/summarizer.py`)

New agent that compresses chapter prose into ~200-400 token summaries for ChromaDB storage.

- Extends `BaseAgent` with role `"summarizer"`
- Uses utility model (Qwen3.5-9B, temperature 0.2) per settings.yaml routing
- Input: full chapter prose + scene card
- Output: structured summary capturing key events, character state changes, plot thread advances, emotional arc
- Write the system prompt at `prompts/agent_system_prompts/summarizer.md`

### Step 6: State Diff System (`src/memory/state_diff.py`)

After each chapter generation, produce a state diff that updates the story state database:

- The Summarizer agent produces both a natural language summary AND a structured state diff (JSON conforming to `schemas/state_diff.json`)
- State diffs include: character location/emotional state updates, plot thread status changes, new knowledge entries, timeline events
- Before committing a diff, compute the state hash (SHA256 of current story state) and emit a `state_diff_proposed` event to the run ledger
- After committing, emit `state_diff_committed` with the new state hash
- Apply diffs to the SQLite story state database

### Step 7: Contradiction Scanner (`src/memory/contradiction_scanner.py`)

Post-chapter consistency check that runs after each approved chapter:

1. **Truth layer scan** — Extract factual assertions from the chapter prose and check against the truth layer in the story state DB. Flag contradictions.
2. **Belief layer scan** — Verify character actions are consistent with their belief state. Flag actions that contradict what a character should know/believe.
3. **Promise/payoff scan** — Cross-reference against the promise/payoff ledger. Flag broken promises without intentional subversion.
4. **Timeline scan** — Check event sequencing against the timeline table. Flag temporal inconsistencies.
5. **Relationship scan** — Flag unexplained shifts in character relationships.

Output: A list of contradiction flags with severity (blocking/warning) and location references. Contradiction flags should be logged to the run ledger.

### Step 8: Upgrade Context Assembler (`src/memory/context_assembler.py`)

Upgrade the Phase 1 simple concatenation to the full four-tier memory system. The new assembler takes these dependencies:

```python
class ContextAssembler:
    def __init__(self, story_state, knowledge_layers, chapter_memory, canon_db, story_bible_path):
        self.state = story_state          # SQLite (Step 2)
        self.knowledge = knowledge_layers # Knowledge layers (Step 3)
        self.memory = chapter_memory      # ChromaDB (Step 4)
        self.canon = canon_db             # Canon DB (Step 9)
        self.bible = self._load_bible(story_bible_path)
```

**Token budget per generation call:**

| Component | Budget | Source |
|-----------|--------|--------|
| System prompt | ~500 | Static file |
| Story bible essentials | ~1,000–2,000 | Tier 1 |
| Current act summary | ~500 | Tier 2 |
| Last 3 chapter summaries | ~600–1,200 | Tier 3 (ChromaDB) |
| Canon RAG results (evidence ranked) | ~500–1,000 | Canon DB |
| Character voice sheets | ~500–1,000 | Character sheets |
| Character knowledge state (belief layer) | ~200–500 | Knowledge layers |
| Recent prose context | ~2,000–4,000 | Tier 4 |
| Scene card + instructions | ~200–500 | Scene card |
| Negative constraints | ~200–400 | Static file |
| **Total** | **~6,200–11,600** | |

The assembler must respect these budgets. If a tier exceeds its budget, truncate from the least-recent content first.

**Important**: The Phase 1 ContextAssembler's existing interface (used by the Orchestrator) must remain compatible. Either keep backward compatibility or update the Orchestrator to pass the new dependencies.

### Step 9: Canon Database (`src/rag/canon_db.py`)

Implement the vector database for franchise canon knowledge:

- Use ChromaDB for <50K chunks (sufficient for Phase 2)
- Store chunks with metadata: source_article, source_section, entity_type, canon_era, continuity_status, source_class
- `add_chunks(chunks: list[dict])` — Batch insert with embedding
- `search(query, k=5) -> list[dict]` — Semantic search returning chunks with metadata

### Step 10: Wiki Ingester (`src/rag/wiki_ingester.py`)

Ingest franchise knowledge from MediaWiki API (Wookieepedia for the test fixture):

- Fetch articles via MediaWiki API
- Entity-aware chunking at 500-700 words with 100-150 word overlap
- Attach metadata per chunk: source article title, section heading, entity type, canon era, continuity tag
- **Source authority classification** per chunk:
  - `primary_canon` (weight 1.0): Films, TV series, official reference books
  - `secondary_canon` (weight 0.85): Novels, comics, games
  - `reference_book` (weight 0.7): Encyclopedias, visual dictionaries
  - `fan_maintained` (weight 0.4): Wiki-original content, synthesis, fan interpretations
  - `ambiguous` (weight 0.3): Contradicted across sources, retconned, disputed

For Phase 2, implement a basic ingester that can process a local JSON/markdown dump of wiki articles (don't require a live MediaWiki API connection for testing). Add live API support as an option.

### Step 11: Canon Evidence and Hybrid Search (`src/rag/canon_evidence.py`, `src/rag/hybrid_search.py`)

**Hybrid Search** (`src/rag/hybrid_search.py`):
- Semantic search via ChromaDB vector similarity
- BM25 keyword search for proper nouns and specific terms
- Merge results via reciprocal rank fusion
- Deduplicate

**Canon Evidence** (`src/rag/canon_evidence.py`):
Two-stage canon check:
1. Retrieve candidate chunks via hybrid search
2. Produce structured `CanonEvidence` objects (conforming to `schemas/canon_evidence.json`) with:
   - `claim`: the factual assertion
   - `source_class`: authority level
   - `confidence`: `semantic_score × source_authority_weight`
   - `continuity_tag`: canon | legends | both | disputed
   - `divergence_safe`: whether this claim is valid in the story's AU context

**Authority weights for confidence calculation:**
- primary_canon: 1.0
- secondary_canon: 0.85
- reference_book: 0.7
- fan_maintained: 0.4
- ambiguous: 0.3

**Confidence threshold**: 0.5 — results below this are excluded from context injection.

Also implement `src/rag/embedding.py` as a wrapper around the embedding model (nomic-embed-text or sentence-transformers).

### Step 12: Canon Expert Agent (`src/agents/canon_expert.py`)

New agent for RAG-powered lore validation:

- Extends `BaseAgent` with role `"canon_expert"`
- Uses fast_moe model (Gemma 4 26B-A4B, temperature 0.2) per settings.yaml routing
- Input: scene card + canon query
- Output: ranked canon evidence with confidence scores
- Write the system prompt at `prompts/agent_system_prompts/canon_expert.md`

### Step 13: Orchestrator Integration

Update `src/orchestrator.py` to integrate all Phase 2 components into the pipeline:

1. After each chapter passes the Gate Critic:
   - Run the **Summarizer** to produce a summary + state diff
   - Store the summary in **ChromaDB** (chapter memory)
   - Apply the state diff to the **SQLite story state**
   - Emit `state_diff_proposed` and `state_diff_committed` events to the run ledger
   - Run the **Contradiction Scanner** and log any flags
2. During context assembly, the upgraded **ContextAssembler** now pulls from all four tiers + canon RAG
3. Update the chapter_log table with summary, quality scores, and revision status

### Step 14: Additional Scene Cards for Testing

Create scene cards for Chapters 2-5 of Beyond the Veil in `data/story_bibles/beyond_the_veil/scene_cards/`:

- **Chapter 2** (Setup): The crew departs Coruscant. First hyperspace jump toward the Unknown Regions. Crew dynamics established. POV: Mandalorian.
- **Chapter 3** (Setup): First encounter with a wound region. The collective Force rule is discovered. Individual Force abilities fail. POV: Ben Skywalker.
- **Chapter 4** (Setup): The crew adapts (or fails to adapt) to the collective mechanic. The scholar volunteers to lead experiments. POV: Non-Force-Sensitive specialist.
- **Chapter 5** (Setup/First Plot Point transition): Discovery of the first Celestial marker. The scholar recognizes it too quickly. Ben notices but doesn't act. Mission scope transforms. POV: Ben Skywalker.

Each scene card must conform to `schemas/scene_card.json` and reference the concept seed's structural_notes.brooks_alignment.

### Step 15: Tests

Write tests covering all new Phase 2 components:

- **`tests/test_story_physics.py`** — Test causality chain validation (known good/bad graphs), promise/payoff tracking, pressure matrix escalation validation
- **`tests/test_story_state.py`** — Test SQLite CRUD, character state queries, bulk initialization from concept seed
- **`tests/test_knowledge_layers.py`** — Test truth/belief/exposure operations, belief accuracy checking, dramatic irony detection
- **`tests/test_chapter_memory.py`** — Test ChromaDB summary storage and retrieval (mock embedding for unit tests)
- **`tests/test_contradiction_scanner.py`** — Test contradiction detection against known good/bad chapter content
- **`tests/test_canon_evidence.py`** — Test confidence scoring, authority weighting, evidence filtering
- **`tests/test_context_assembler.py`** — Update existing tests + add tests for four-tier assembly with token budget compliance
- **`tests/test_pipeline_integration.py`** — Integration test: concept seed → 5 chapters with continuity tracking and promise/payoff validation

**Phase 2 milestone**: Generate 5 consecutive chapters with consistent continuity, tracked promise/payoff, and zero contradiction scanner failures.

## Dependencies to Add

Uncomment/add these in `requirements.txt`:
```
chromadb>=0.5.0
sentence-transformers
numpy
```

## Key Technical Decisions

- **SQLite for structured state, ChromaDB for vectors.** Both file-based, no server needed.
- **Three knowledge layers are separate rows, not separate tables.** The `layer` column in `character_knowledge` distinguishes truth/belief/exposure. This keeps queries simple.
- **Summarizer runs after Craft Editor, before state diff.** The summary feeds both ChromaDB (for future context) and the state diff (for story state updates).
- **Canon evidence is ranked, not just retrieved.** The confidence formula (`semantic_score × source_authority_weight`) ensures high-authority sources rank above fan-maintained content.
- **Contradiction scanner is non-blocking.** It logs warnings but does not reject chapters. Blocking contradictions should have been caught by the Gate Critic.
- **Backward compatibility with Phase 1.** The CLI, Orchestrator, and agent interfaces should extend, not break. Existing tests should continue to pass.
