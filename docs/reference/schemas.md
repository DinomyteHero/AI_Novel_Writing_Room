# JSON Schemas

The `schemas/` directory contains JSON Schema definitions for the system's core data structures. These are used for validation and serve as the canonical reference for data formats.

## Available Schemas

| Schema | File | Description |
|--------|------|-------------|
| Concept Seed | `schemas/concept_seed.json` | The complete story plan emitted by `scripts/compile_bundle.py` from the workflow-kit surfaces. Contains metadata, characters, structural outline, story physics, and scene cards, plus `voice_definition`, `subplots`, `hooks`, `revelation_schedule`, `terminology_registry`, `stress_test_scores`, `canon_profile`, `referenced_characters`, `quality_overrides`, per-character Weiland arc beats, and `series_id`. |
| Scene Card | `schemas/scene_card.json` | Per-chapter/scene planning contract. Load-bearing required fields: `chapter_number`, `scene_number`, `pov_character`, `characters_present`, `mission`, `turning_point`. Optional additive enrichment consumed by the drafter and rhythm validator: `turning_point_detail`, `emotional_arc`, `key_beats`, `opening_mode`, `dialogue_density_target`, `interiority_budget`, `promises_progressed`, `promises_paid`, top-level `anti_patterns`. Legacy cards still validate. |
| Story Physics | `schemas/story_physics.json` | Causality chains, revelation maps, promise/payoff ledger, and character pressure matrices. |
| Story Bible | `schemas/story_bible.json` | The combined planning document linking concept seed, structural outline, and scene cards. |
| Character Sheet | `schemas/character_sheet.json` | Detailed character profile with physical description, personality dimensions, speech patterns, relationships, arc, and motivation. |
| State Diff | `schemas/state_diff.json` | Post-scene state mutation document. Describes changes to characters, knowledge, plot threads, timeline, Chekhov guns, subplots, hooks, arc phases, and terminology. Before application, `sanitize_diff()` auto-corrects LLM vocabulary errors (fuzzy enum matching, concept-seed label mapping, `old_value` correction). |
| Universe Meta | `schemas/universe_meta.json` | Per-universe metadata (name, franchise, canon status). Created automatically on first pipeline run when universe scoping is active. |
| Canon Evidence | `schemas/canon_evidence.json` | RAG retrieval result with confidence score, source authority class, continuity tag, and divergence safety flag. |
| Canon Guidance | `schemas/canon_guidance.json` | Franchise-level canon tips (terminology, mechanics, period detail) authored by `canon_scout`. Surfaced to the drafter through the chapter packet's `canon_guidance` field. Persisted at `data/franchises/<franchise>/canon_guidance.json`. |
| Series Seed | `schemas/series_seed.json` | Series-level planning document for multi-book projects. Contains series arc, per-book outlines, cross-book promises, and shared characters. |
| Chapter Blueprint | `schemas/chapter_blueprint.json` | Per-chapter planning document synthesised from the seed + scene cards. Feeds the chapter-packet base. Lives at `data/franchises/<fr>/books/<bk>/chapter_blueprints/chapter_NN.json`. |
| Generation Brief | `schemas/generation_brief.json` | `PlotArchitect` output handed to `ProseStylist`: a per-beat plan (beat sequence, turning point, POV, structural phase) derived from the scene card. |
| Chapter Packet | `schemas/chapter_packet.json` | The drafter's single inspectable runtime contract. Base compiled once per chapter; overlay composed per scene. Produced by `src/pipeline/chapter_packet.py`. Shipping default on, with flat-context fallback. |
| Revision Debt | `schemas/revision_debt.json` | Store for structured advisories (rhythm, continuity, word-count drift, etc.). Closed `category` enum. Persisted to `output/<franchise>/<book>/state/revision_debt.db`. Off by default on shipping books. |
| Promise Ledger Entry | `schemas/promise_ledger_entry.json` | Declaration-driven promise-ledger row. Seeded from planning (`story_physics.promise_payoff_ledger` + scene-card `promises_planted` / `promises_paid`); progression / payoff / broken transitions are the only mutating writes. Persisted to `promise_ledger.db`. Off by default on shipping books. |
| Manuscript Patch | `schemas/manuscript_patch.json` | Patch batch for `scripts/patch_workflow.py apply-manuscript-patch`. Closed action enum; scene-id pattern enforcement; `source_pass` tag. |
| Chapter Memo | `schemas/chapter_memo.json` | Per-chapter / milestone close memo synthesised by `ChapterCloseMemoGenerator` / `MilestoneMemoGenerator` from revision debt + pending promises. Human-review artifact under `<run_dir>/memos/`. |
| Cosmology Meta | `schemas/cosmology_meta.json` | Optional meta-universe registry (shared rules / cross-franchise lore). Referenced by `concept_seed.meta.cosmology_id`; resolves to `data/cosmologies/<slug>/cosmology_meta.json`. |
| Failure Code | `schemas/failure_code.json` | Legacy gate-evaluation output schema. Retained in-tree for migration compatibility but no longer consumed — the lean pipeline has no gate. |

## Notable Schema Sections

### canon_profile (Concept Seed)

The `canon_profile` section in the concept seed provides franchise-specific validation data:

| Field | Type | Description |
|-------|------|-------------|
| franchise | string | Franchise name (e.g., "Star Wars", "Marvel") |
| continuity | string | Continuity label (e.g., "Legends", "Canon", "MCU") |
| cross_continuity_violations | array | Terms/concepts from other continuities that must not appear |
| anachronistic_terms | array | Terms that are out-of-era for the story's timeline setting |

It is read at runtime by the canon-guidance store and the post-save lore-conflict detector. No franchise-specific logic is hardcoded.

### initial_phase (ensemble_cast weiland_arc)

The `initial_phase` field in each character's `weiland_arc` definition allows specifying a starting arc phase other than the default `lie_established` — useful for sequel books where characters begin mid-arc.

### series_id (meta)

The `series_id` field in the concept seed's `meta` section links a book to a series. Books sharing a `series_id` share state at `output/<franchise>/<series>/state/`, enabling cross-book continuity.

## Data Flow

```
Workflow kit (workflows/<surface>/*.json) -> compile_bundle.py
    -> concept_seed.json (Concept Seed schema)
    -> scene_cards/ (Scene Card schema per file)
    -> series_seed.json (Series Seed schema, series mode only)

Pipeline (per scene — lean forward pass):
    Scene Card + chapter blueprint + seed -> ChapterPacketCompiler
        -> chapter_packet.json (base compiled once per chapter; overlay per scene)
    Scene Card -> PlotArchitect -> generation_brief.json (Generation Brief schema)
    generation_brief + chapter packet -> ProseStylist -> prose (drafted)
    prose -> LineWriter -> prose (line-edited, optional)
    prose -> [RhythmValidator -> RhythmEditor] -> prose (optional, advisory)
    prose -> save

Post-save (Phase 2+):
    saved prose -> Summarizer -> state_diff.json (State Diff schema)
    State Diff -> StateDiffApplier (sanitizes + applies to SQLite)
    saved prose -> ChapterMemory (ChromaDB)
    ContradictionScanner runs on updated state
    worldbuilding extraction -> provisional lore entries

Advisory stores (flag-gated, default off):
    revision-debt rows -> revision_debt.json -> revision_debt.db
    promise ledger    -> promise_ledger_entry.json -> promise_ledger.db

RAG queries:
    Query -> CanonDB -> canon_evidence.json
    Query -> LoreService -> worldbuilding lore entries
```

## Using Schemas

The schema files are standard JSON Schema and can be used with any JSON Schema validator. They define the expected structure of input and output data throughout the pipeline.

Schema files are located at:

```
schemas/
├── canon_evidence.json
├── canon_guidance.json
├── chapter_blueprint.json
├── chapter_memo.json
├── chapter_packet.json
├── character_sheet.json
├── concept_seed.json
├── cosmology_meta.json
├── failure_code.json
├── generation_brief.json
├── manuscript_patch.json
├── promise_ledger_entry.json
├── revision_debt.json
├── scene_card.json
├── series_seed.json
├── state_diff.json
├── story_bible.json
├── story_physics.json
└── universe_meta.json
```

Keep this list in sync with `git ls-files schemas/*.json`.
