# Data Restructure Proposal: Multi-Franchise, Multi-Run Support

**Status: IMPLEMENTED** — All structural changes have been applied. See `src/project_paths.py` for the new path resolver, `scripts/migrate_to_franchise_layout.py` for the migration tool, and the concept seed's `series_id` field for series linkage.

**Addition: Series Linkage** — Books with the same `series_id` (in `meta.series_id` or `meta.series.series_id`) share accumulated story state (characters, arcs, plot threads, Chekhov's guns). State directory resolves to `output/<franchise>/<series>/state/` when series_slug is set. This enables multi-book series within a franchise to share characters and dropped plot points.

## 1. Current Layout (Pre-Migration)

```
data/
  eval_corpus/
    chapter_01_reference.md
    eval_rubric.json
  projects/
    the-ruusan-atonement/           # Flat project (no universe scoping)
      concept_seed.json             # Master concept document
      scene_cards/                  # Input scene planning documents
        chapter_01_scene_01.json
        ...                         # 75+ scene card files
      state/
        story_state.db              # SQLite: character arcs, chapter/scene logs
        run_ledger.db               # SQLite: immutable event log
        chapter_memory/             # ChromaDB: chapter summary embeddings
        sessions/                   # Pipeline session checkpoints (JSON)

config/
  settings.yaml                     # Global model routing, pipeline settings
  negative_constraints.yaml         # Anti-slop rules
  failure_codes.yaml                # Gate critic failure taxonomy
  eval_rubric.yaml                  # Quality metric rubric

output/
  the-ruusan-atonement/
    chapters/                       # Generated scene prose (.md files)
      chapter_01_scene_01.md
      ...
    export/                         # Assembled manuscripts (.docx, .epub, .md)

schemas/
  concept_seed.json                 # JSON Schema for concept seeds
  scene_card.json                   # JSON Schema for scene cards
```

**Key observations:**
- `ProjectPaths` (`src/project_paths.py`) already supports optional `universe_slug` for universe-scoped layout
- When `universe_slug` is provided, data lives under `data/projects/<universe>/<book>/`
- Shared universe resources (canon DB, worldbuilding) live under `data/universes/<universe>/`
- Currently, the-ruusan-atonement uses flat layout (no universe scoping active)
- No run-level isolation: re-running the pipeline with same config overwrites output
- Session files provide resume capability but not run comparison
- Inputs (concept seed, scene cards) live alongside state (DBs, sessions) under `data/projects/`

## 2. Proposed Layout

```
data/
  franchises/                               # NEW: top-level organizational unit
    star-wars-legends/                      # Franchise slug
      canon_db/                             # ChromaDB: franchise-wide canon/lore
      worldbuilding.db                      # SQLite: shared worldbuilding
      worldbuilding_vectors/                # ChromaDB: lore embeddings
      negative_constraints.yaml             # Franchise-specific anti-slop rules (optional override)
      books/
        the-ruusan-atonement/               # Book within franchise
          concept_seed.json                 # Book-level concept document
          scene_cards/                      # Book-level scene planning
            chapter_01_scene_01.json
          config_overrides.yaml             # Book-level config overrides (optional)
        ruusan-aftermath/                   # Another book in same franchise
          concept_seed.json
          scene_cards/
    game-of-thrones-book/                   # Different franchise
      canon_db/
      books/
        the-iron-price/
          concept_seed.json
          scene_cards/
    original/                               # Original fiction (no external franchise)
      books/
        my-novel/
          concept_seed.json
          scene_cards/

  eval_corpus/                              # UNCHANGED: reference evaluation data
    chapter_01_reference.md
    eval_rubric.json

output/
  star-wars-legends/
    the-ruusan-atonement/
      runs/                                 # NEW: per-run isolation
        2026-04-12_claude-sonnet_t085/      # Timestamped + model + temp
          config_snapshot.yaml              # Fully resolved config for this run
          chapters/                         # Generated scene prose
            chapter_01_scene_01.md
          metrics/                          # Quality metrics logs
          session.json                      # Session checkpoint
          run_summary.json                  # Run metadata and aggregate stats
        2026-04-13_gemini-pro_t070/         # A/B test with different model
          config_snapshot.yaml
          chapters/
          metrics/
      state/                                # Book-level accumulated state
        story_state.db                      # Character arcs, chapter logs
        run_ledger.db                       # Event history across all runs
        chapter_memory/                     # ChromaDB summaries
      export/                               # Assembled manuscripts
        manuscript_run-2026-04-12.md
  game-of-thrones-book/
    the-iron-price/
      runs/
      state/
      export/

config/
  settings.yaml                             # Global defaults (unchanged)
  negative_constraints.yaml                 # Global defaults (unchanged)
  failure_codes.yaml                        # Unchanged
  eval_rubric.yaml                          # Unchanged
```

**Annotations:**

- **Franchise level** (`data/franchises/<slug>/`): Owns canon DB, worldbuilding DB, and franchise-specific constraints. Multiple books share these resources. Replaces the current `data/universes/` concept.

- **Book level** (`data/franchises/<slug>/books/<book-slug>/`): Contains concept seed, scene cards, and optional config overrides. This is the unit of authorship.

- **Run level** (`output/<franchise>/<book>/runs/<run-id>/`): Each pipeline execution creates a new run directory. Run ID format: `YYYY-MM-DD_model_tXXX` (or user-provided name). The run directory contains: chapters output, config snapshot (fully resolved), quality metrics, session checkpoint. Re-running the pipeline creates a new run, never overwrites.

- **State level** (`output/<franchise>/<book>/state/`): Accumulated state across runs. Story state DB and chapter memory persist across runs. The run ledger records events from all runs with run-id tagging.

- **Config layering**: Global defaults (`config/settings.yaml`) -> franchise overrides (`data/franchises/<slug>/negative_constraints.yaml`) -> book overrides (`<book>/config_overrides.yaml`) -> CLI overrides (`--temperature 0.7`). Run directory captures the fully resolved config.

## 3. Migration Plan

### Step 1: Create franchise directory structure
```bash
mkdir -p data/franchises/star-wars-legends/books
mv data/projects/the-ruusan-atonement data/franchises/star-wars-legends/books/
```

### Step 2: Move shared universe resources
```bash
# If data/universes/ exists, move its contents
mv data/universes/star-wars-legends-eu/* data/franchises/star-wars-legends/
```

### Step 3: Separate state from inputs
```bash
# Move state out of the book directory into output
mkdir -p output/star-wars-legends/the-ruusan-atonement/state
mv data/franchises/star-wars-legends/books/the-ruusan-atonement/state/* \
   output/star-wars-legends/the-ruusan-atonement/state/
```

### Step 4: Retroactively create run directories for existing output
```bash
# Wrap existing chapters in a run directory
mkdir -p output/star-wars-legends/the-ruusan-atonement/runs/legacy-run
mv output/the-ruusan-atonement/chapters \
   output/star-wars-legends/the-ruusan-atonement/runs/legacy-run/
```

### Step 5: Update .gitignore
```
# Generated output (don't commit chapters or run artifacts)
output/*/runs/
output/*/state/
```

## 4. Code Changes Required

| File | Change |
|------|--------|
| `src/project_paths.py` | Rename `universe_slug` to `franchise_slug`. Add `run_id` parameter. Add properties: `franchise_dir`, `book_dir`, `run_dir`, `config_snapshot_path`. Change `project_root` from `data/projects/` to `data/franchises/<franchise>/books/`. Change state paths to `output/<franchise>/<book>/state/`. |
| `src/main.py` | Update CLI args: `--franchise` replaces `--universe-id`. Add `--run-name` for custom run IDs. Auto-generate timestamped run ID if not provided. Save config snapshot at run start. |
| `src/pipeline_session.py` | Update session paths to live inside run directories. |
| `src/run_ledger.py` | Add `run_id` column to events table for multi-run tracking. |
| `src/memory/context_assembler.py` | Update canon DB path resolution to use franchise directory. |
| `src/rag/canon_db.py` | Update persist_directory to franchise-level canon_db path. |
| `src/worldbuilding/` | Update all worldbuilding paths to franchise directory. |
| `src/export/export_manager.py` | Output to `output/<franchise>/<book>/export/`. |

## 5. CLI Argument Changes

| Current | Proposed | Notes |
|---------|----------|-------|
| `--universe-id` | `--franchise` | Rename for clarity |
| `--project-id` | `--book` | Rename for clarity |
| (none) | `--run-name` | Optional custom run name (default: auto-timestamped) |
| (none) | `--compare-runs` | Compare two run directories side by side |
| Positional `concept_seed_path` | Kept, but also derive from `--franchise --book` | `--franchise star-wars-legends --book the-ruusan-atonement` resolves concept seed automatically |

## 6. Backward Compatibility

- **Flat projects still work**: `ProjectPaths("the-ruusan-atonement")` without franchise slug continues to resolve to `data/projects/the-ruusan-atonement/`. Existing tests and workflows are unaffected.
- **Positional args preserved**: `python src/main.py path/to/seed.json path/to/cards/` continues to work. The franchise/book flags are optional sugar.
- **Migration script**: A `scripts/migrate_to_franchise_layout.py` script handles the directory moves. It's idempotent (safe to run twice).
- **State DB schema unchanged**: SQLite tables and ChromaDB collections don't change. Only their on-disk locations move.
- **Config layering is additive**: If no franchise or book override exists, global defaults apply. The system degrades gracefully to the current single-config behavior.
