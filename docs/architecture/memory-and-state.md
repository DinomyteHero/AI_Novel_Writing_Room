# Memory and State

The system uses a multi-layered memory architecture to maintain story continuity across chapters. No state is stored in the LLM's context window -- all persistence is external.

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

Tracks K.M. Weiland character arc beats per character per book. PK: `(character_id, book_number)`. Fields: `lie_believed`, `ghost`, `want`, `need`, `arc_type` (positive_change/flat/negative/disillusionment), `current_phase` (lie_reinforced through truth_accepted/truth_rejected), `phase_chapter`, `phase_evidence`, `arc_phase_targets` (JSON mapping phases to Brooks structure).

### subplot_board (Phase 5)

Tracks subplot lifecycle. PK: `subplot_id`. Fields: `subplot_name`, `line_type` (A/B/C/D), `characters_involved` (JSON), `start_chapter`, `resolution_chapter`, `structural_purpose`, `interweave_points` (JSON), `current_status`, `book_number`.

### hook_ledger (Phase 5)

Promise/hook governance with admission control. PK: `hook_id`. Fields: `description`, `hook_type`, `planted_chapter`, `payoff_chapter`, `advancement_chapters` (JSON), `priority` (hard/soft/series), `current_status`, `last_advanced_chapter`, `mention_only_count`. Hook budget: `target_chapters / 3` hard hooks max.

### terminology_registry (Phase 5)

Canonical terms for consistency. PK: `term`. Fields: `aliases` (JSON), `definition`, `category`, `first_appearance_chapter`, `book_number`.

### propagation_debts (Phase 5)

Tracks state changes needing propagation to previously-written chapters. Fields: `source_layer`, `change_description`, `affected_chapters` (JSON), `resolved_at`, `resolution_method`.

### style_fingerprint (Phase 5)

Per-source style metrics for voice enforcement. Fields: `source`, `metric_name`, `metric_value` (JSON).

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
2. The StateDiffApplier validates and applies the diff to SQLite
3. Phase 5: old_value verification — before applying a `modify` operation, the applier checks that the expected old value matches the current DB value. On mismatch, a `state_diff_conflict` event is logged (optimistic strategy: apply anyway, flag for review)
4. A state hash is computed before and after to detect unexpected mutations
5. All diffs are logged to the RunLedger with before/after hashes

## Contradiction Scanner

`src/memory/contradiction_scanner.py` runs post-chapter consistency checks across 5 scan types:

| Scan Type | What It Checks |
|-----------|---------------|
| truth | Facts contradicting established truth-layer entries |
| belief | Characters knowing things they shouldn't or forgetting things they should know |
| promises | Promise/payoff consistency (planted items that should have fired by now) |
| timeline | Temporal inconsistencies (events out of order, impossible timelines) |
| relationships | Relationship status contradictions |
