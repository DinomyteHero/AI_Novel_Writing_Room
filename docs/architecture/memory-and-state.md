# Memory and State

The system uses a multi-layered memory architecture to maintain story continuity across chapters. No state is stored in the LLM's context window -- all persistence is external.

## State File Locations

State databases have moved from project-level inputs to output-level paths:

| Resource | Old Location | New Location |
|----------|-------------|-------------|
| story_state.db | `data/projects/.../state/` | `output/<franchise>/<book>/state/` |
| chapter_memory/ | `data/projects/.../state/` | `output/<franchise>/<book>/state/` |
| run_ledger.db | `data/projects/.../state/` | `output/<franchise>/<book>/state/` |
| sessions/ | `data/projects/.../state/` | `output/<franchise>/<book>/state/` |

**Series-shared state**: When books share a `series_id`, their state is shared at `output/<franchise>/<series>/state/`. This enables cross-book continuity -- character arcs, plot threads, and knowledge carry over between books in the same series.

**Per-run isolation**: Each pipeline run writes chapters to `output/<franchise>/<book>/runs/<run_id>/chapters/` with a frozen config snapshot for reproducibility. State databases remain at the book (or series) level and accumulate across runs.

## Story State (SQLite)

`src/memory/story_state.py` manages a SQLite database with 13 tables (7 original + 6 added in Phase 5). Schema migrations are applied automatically on init via the `schema_migrations` table.

### characters

Tracks each character's current state.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | Slugified name (e.g., `ben_skywalker`) |
| name | TEXT | Display name |
| current_location | TEXT | Where the character is now |
| emotional_state | TEXT | Current emotional state |
| arc_position | TEXT | Position in character arc |
| inventory | TEXT | Notable items |
| last_appearance_chapter | INTEGER | Last chapter they appeared in |
| last_appearance_scene | INTEGER | Last scene they appeared in |

### character_knowledge

Three-layer knowledge system. Each row is a fact known by a character.

| Column | Type | Description |
|--------|------|-------------|
| character_id | TEXT FK | References characters.id |
| fact_id | TEXT | Unique fact identifier |
| fact_description | TEXT | What the fact is |
| layer | TEXT | `truth`, `belief`, or `narrative_exposure` |
| is_accurate | BOOLEAN | Whether a belief matches truth (belief layer only) |
| acquired_chapter | INTEGER | When this knowledge was gained |
| source | TEXT | How it was acquired |

### character_relationships

| Column | Type | Description |
|--------|------|-------------|
| character_a | TEXT FK | First character |
| character_b | TEXT FK | Second character |
| relationship_type | TEXT | Nature of relationship |
| status | TEXT | Current status |
| last_updated_chapter | INTEGER | Last chapter updated |

### plot_threads

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | Thread identifier |
| description | TEXT | What the thread is about |
| status | TEXT | `planted`, `active`, `escalating`, `resolving`, `resolved` |
| planted_chapter | INTEGER | Where it was introduced |
| urgency | TEXT | `background`, `rising`, `critical`, `climactic` |
| related_characters | TEXT | JSON list of character IDs |
| resolution_notes | TEXT | How it resolved |

### timeline

| Column | Type | Description |
|--------|------|-------------|
| chapter_number | INTEGER | Chapter |
| scene_number | INTEGER | Scene |
| story_date | TEXT | In-story date |
| elapsed_time | TEXT | Time since last entry |
| key_events | TEXT | What happened |

### chekhov_guns

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | Item identifier |
| item_description | TEXT | What the item/setup is |
| planted_chapter | INTEGER | Where it was planted |
| planted_context | TEXT | The context of the planting |
| fired_chapter | INTEGER | Where it fired (null if unfired) |
| fired_status | TEXT | `unfired`, `fired`, `subverted` |

### chapter_log

Records per-chapter generation metadata (word count, quality scores, etc.).

### character_arcs (Phase 5)

Tracks K.M. Weiland character arc beats per character per book. PK: `(character_id, book_number)`. Fields: `lie_believed`, `ghost`, `want`, `need`, `arc_type` (positive_change/flat/negative/disillusionment), `current_phase`, `phase_chapter`, `phase_evidence`, `arc_phase_targets` (JSON mapping phases to Brooks structure), `initial_phase` (optional starting phase from the concept seed's `ensemble_cast` Weiland arc definition -- allows characters to begin mid-arc, e.g., for sequels).

Arc phase progressions are type-specific (defined in `ARC_PHASE_PROGRESSIONS`):
- **positive_change**: lie_established → lie_reinforced → lie_questioned → lie_cracking → lie_confronted → truth_accepted
- **negative**: lie_established → lie_reinforced → lie_deepened → point_of_no_return → lie_acted_upon → lie_consequence → truth_rejected
- **flat**: lie_established → truth_tested → truth_pressured → truth_reaffirmed
- **disillusionment**: lie_established → lie_reinforced → lie_questioned → truth_glimpsed → truth_rejected → disillusionment_accepted

All arcs start at `lie_established` (the universal initial phase). `advance_arc_phase()` validates transitions against the character's specific arc type -- no skipping steps, no cross-type phases. `CONCEPT_SEED_PHASE_MAP` maps planning labels from the concept seed (e.g., `lie_challenged`, `moment_of_truth`) to their corresponding DB tracking phases.

**Arc self-transitions** are now allowed: a character can transition from a phase to the same phase (e.g., `lie_reinforced` -> `lie_reinforced`). This prevents false rejection of scenes that reinforce the current arc phase without advancing it. The state diff applier treats self-transitions as valid no-ops for the phase column while still recording updated evidence.

**Rejected transition feedback**: When an arc phase transition is rejected (e.g., attempting to skip a phase), the rejection reason is carried into the next scene's Summarizer context so the Summarizer proposes a valid state diff. The lean pipeline has no retries — the feedback flows forward to the next scene, never back into a re-draft of the current one.

### subplots (Phase 5)

Tracks subplot lifecycle. PK: `subplot_id`. Fields: `subplot_name`, `line_type` (A/B/C/D), `characters_involved` (JSON), `start_chapter`, `resolution_chapter`, `structural_purpose`, `interweave_points` (JSON), `current_status`, `book_number`.

### hook_ledger (Phase 5)

Promise/hook governance with admission control. PK: `hook_id`. Fields: `description`, `hook_type`, `planted_chapter`, `payoff_chapter`, `advancement_chapters` (JSON), `priority` (hard/soft/series), `current_status`, `last_advanced_chapter`, `mention_only_count`. Hook budget: `target_chapters / 3` hard hooks max.

### terminology_registry (Phase 5)

Canonical terms for consistency. PK: `term`. Fields: `aliases` (JSON), `definition`, `category`, `first_appearance_chapter`, `book_number`.

### propagation_debts (Phase 5)

Tracks state changes needing propagation to previously-written chapters. Fields: `source_layer`, `change_description`, `affected_chapters` (JSON), `resolved_at`, `resolution_method`.

## Worldbuilding Persistence Layer

`src/worldbuilding/` provides a cross-project worldbuilding persistence system in a separate database because universes span multiple projects. For franchise-scoped projects, the database lives at `data/franchises/<franchise>/worldbuilding.db`; for legacy flat projects, at `data/worldbuilding.db`.

### Architecture

| Component | File | Storage |
|-----------|------|---------|
| WorldbuildingDB | `worldbuilding_db.py` | SQLite (universes, lore entries, relations, affiliations) |
| LoreVectorStore | `lore_vectorstore.py` | ChromaDB (one collection per universe) |
| LoreService | `lore_service.py` | Orchestrates dual-write with write-ahead sync |
| LoreExtractor | `lore_extractor.py` | LLM prompt templates for extraction |

### universes

Shared worldbuilding namespaces with optional parent inheritance.

| Column | Type | Description |
|--------|------|-------------|
| universe_id | TEXT PK | Slug identifier |
| display_name | TEXT | Human-readable name |
| parent_universe_id | TEXT FK | Inheritance chain parent |
| franchise | TEXT | Base franchise (or "original") |
| timeline_system | TEXT | `forward`, `bby_aby`, `chapter_based`, `custom` |
| embedding_model | TEXT | Model used for ChromaDB collection |

### lore_entries

Individual worldbuilding knowledge units.

| Column | Type | Description |
|--------|------|-------------|
| entry_id | TEXT PK | UUID |
| universe_id | TEXT FK | Which universe |
| category | TEXT | faction, location, character_background, political_system, force_mechanic, technology, species_culture, historical_event, terminology, custom |
| title | TEXT | Entry name |
| content | TEXT | Full lore description (markdown) |
| status | TEXT | `canonical`, `provisional`, `deprecated` |
| visibility | TEXT | `public`, `faction_internal`, `secret` |
| valid_from / valid_until | TEXT | In-universe timeline bounds (display strings) |
| timeline_sort_start / timeline_sort_end | INTEGER | Numeric sort keys for comparison |
| thematic_notes | TEXT | How this should FEEL in prose |
| speech_patterns | TEXT | How characters from this group talk |
| canon_override | BOOLEAN | Intentionally contradicts parent/canon |
| extraction_source | TEXT | `author`, `concept_seed_import`, `prose_extraction`, `workshop` |
| introduced_in_project_id | TEXT | For spoiler isolation |

### lore_relations

Relationships between lore entries with dialogue implications.

| Column | Type | Description |
|--------|------|-------------|
| source_entry_id | TEXT FK | Source entry |
| target_entry_id | TEXT FK | Target entry |
| relation_type | TEXT | located_in, member_of, caused_by, allied_with, enemy_of, succeeded_by, part_of, references |
| dialogue_implications | TEXT | How this relation affects dialogue tone |

### character_lore_affiliations

Maps characters to factions/cultures for knowledge-gated dialogue.

| Column | Type | Description |
|--------|------|-------------|
| character_id | TEXT | Character slug (references story_state) |
| entry_id | TEXT FK | The faction/culture lore entry |
| affiliation_type | TEXT | `member`, `ally`, `aware` |

### project_universe_binding

Binds projects to universes with reading order for spoiler isolation.

| Column | Type | Description |
|--------|------|-------------|
| project_id | TEXT PK | Project identifier |
| universe_id | TEXT FK | Bound universe |
| reading_order | INTEGER | Position in reading sequence |
| timeline_start / timeline_end | TEXT | Project's in-universe time span |

### Write-Ahead Sync Pattern

ChromaDB does not support transactions. The LoreService uses a write-ahead pattern:

1. Begin SQLite transaction
2. Write to SQLite
3. Write to ChromaDB
4. If ChromaDB fails -> roll back SQLite (no orphans)
5. If SQLite commit fails after ChromaDB success -> orphan in ChromaDB

For case 5, `reconcile_chromadb_orphans()` periodically compares SQLite entry IDs against ChromaDB IDs and cleans up mismatches.

### Context Assembly Integration

The context assembler adds three worldbuilding tiers between canon RAG and character voices:

1. **Worldbuilding Lore** (800 tokens) -- Semantic retrieval from universe chain, filtered by timeline, spoiler isolation, and status
2. **Worldbuilding Terminology** (300 tokens) -- Always-include glossary, not top-K
3. **Worldbuilding Dialogue Context** (300 tokens) -- Knowledge-gated speech patterns for characters in the scene

### Knowledge-Gated Dialogue

Speech patterns are filtered by character knowledge:

- `public` entries: included for all characters
- `faction_internal` entries: only if the character is affiliated with that faction (via `character_lore_affiliations`)
- `secret` entries: only if the character has a belief-layer fact (`lore:{entry_id}`) in the knowledge layers

The `sync_lore_to_beliefs()` method bridges worldbuilding into the Truth/Belief system, creating truth-layer facts for canonical entries and belief-layer facts for affiliated characters.

### Timeline Sort Keys

Timeline filtering uses numeric sort keys (`timeline_sort_start`/`timeline_sort_end`) for correct comparison across all calendar systems. For backward-counting systems like BBY, the sort key inverts the sign (3600 BBY = -3600). The `timeline_system` field on the universe declares the calendar convention.

### Post-Chapter Extraction

After each chapter, the orchestrator optionally runs an LLM-assisted worldbuilding extraction pass. Extracted entries are created as `provisional` with `extraction_source = "prose_extraction"` and quarantined from the context assembler until the author promotes them to `canonical`.

## Knowledge Layers

`src/memory/knowledge_layers.py` provides a semantic API over the `character_knowledge` table:

- **Truth layer**: Objective facts about the story world. Stored with `character_id = "__world__"`.
- **Belief layer**: What each character believes. The `is_accurate` flag tracks whether the belief matches truth.
- **Narrative exposure layer**: What the reader has been shown.

Key methods:
- `add_truth(fact_id, description, chapter)` -- Add a world-level fact
- `add_belief(character_id, fact_id, description, is_accurate, chapter)` -- Add what a character believes
- `add_narrative_exposure(fact_id, description, chapter)` -- Record what the reader knows
- `get_dramatic_irony(chapter)` -- Find situations where the reader knows things characters don't
- `check_belief_accuracy(character_id)` -- Compare a character's beliefs against truth

This drives **dramatic irony** detection -- the pipeline can construct scenes where the reader's knowledge diverges from characters' beliefs.

## Chapter Memory (ChromaDB)

`src/memory/chapter_memory.py` stores chapter summaries as vector embeddings in ChromaDB:

- After each chapter, the Summarizer agent produces a compressed summary
- The summary is embedded and stored with chapter/scene metadata
- During context assembly, semantically relevant prior summaries are retrieved

This provides associative recall -- the system can pull in summaries from non-adjacent chapters if they're contextually relevant.

## Context Assembly

`src/memory/context_assembler.py` builds the prompt payload for each agent call using a four-tier memory system:

1. **Story bible** -- The concept seed (always included)
2. **Act summary** -- High-level structural context
3. **Chapter summaries** -- From ChromaDB (semantic retrieval of relevant prior chapters)
4. **Recent prose** -- Raw text from the most recent chapters

Additional context layers when available:
- Canon RAG results (franchise knowledge)
- Worldbuilding lore — semantic retrieval from universe chain with timeline/spoiler filtering
- Worldbuilding terminology — always-include glossary from universe chain
- Worldbuilding dialogue — knowledge-gated speech patterns and inter-faction dynamics
- Character knowledge state (beliefs and truth per character)
- Voice sheets (character speech patterns)
- Voice rules — anti-slop/anti-pattern injection from voice definition (Phase 5)
- Hook agenda — which hooks to plant/advance/resolve this chapter (Phase 5)
- Arc context — POV character's current Weiland arc phase and targets (Phase 5)
- Subplot context — active subplots for this scene (Phase 5)
- Terminology — canonical terms for consistency (Phase 5)

The assembler manages a token budget to fit everything within the model's context window. When Phase 2 dependencies aren't available, it falls back to Phase 1 behavior (simple concatenation of concept seed + scene card + previous chapter text).

## State Diffs

`src/memory/state_diff.py` manages state mutations:

1. After each chapter, the Summarizer produces a **state diff** (JSON) describing changes:
   - Character position/state updates (with old_value verification in Phase 5)
   - New knowledge acquired
   - Plot thread status changes
   - Timeline entries
   - Chekhov gun status changes
   - Subplot updates (Phase 5)
   - Hook updates with admission control (Phase 5)
   - Arc phase transitions with progression validation (Phase 5)
   - Terminology updates (Phase 5)
2. `sanitize_diff()` runs before application — auto-corrects common LLM errors:
   - Fuzzy-matches near-miss enum values (e.g., hook status `"active"` → `"advancing"`, subplot status `"escalating"` → `"climaxing"`)
   - Maps concept-seed planning labels to DB phases via `CONCEPT_SEED_PHASE_MAP`
   - Corrects `old_value` mismatches by replacing with the actual current DB value
   - Strips no-op entries where `old_value == new_value`
3. The StateDiffApplier validates and applies the sanitized diff to SQLite
4. Phase 5: old_value verification — before applying a `modify` operation, the applier checks that the expected old value matches the current DB value. On mismatch, a `state_diff_conflict` event is logged (optimistic strategy: apply anyway, flag for review)
5. Unknown characters referenced in `new_knowledge` entries are auto-registered with default state (`location: "unknown"`, `emotional_state: "unknown"`, `arc_position: "untracked"`) and a warning is logged
6. A state hash is computed before and after to detect unexpected mutations
7. All diffs are logged to the RunLedger with before/after hashes

## Contradiction Scanner

`src/memory/contradiction_scanner.py` runs post-chapter consistency checks across 5 scan types:

| Scan Type | What It Checks |
|-----------|---------------|
| truth | Facts contradicting established truth-layer entries |
| belief | Characters knowing things they shouldn't or forgetting things they should know |
| promises | Promise/payoff consistency (planted items that should have fired by now) |
| timeline | Temporal inconsistencies (events out of order, impossible timelines) |
| relationships | Relationship status contradictions |
