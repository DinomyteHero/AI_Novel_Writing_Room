# JSON Schemas

The `schemas/` directory contains JSON Schema definitions for the system's core data structures. These are used for validation and serve as the canonical reference for data formats.

## Available Schemas

| Schema | File | Description |
|--------|------|-------------|
| Concept Seed | `schemas/concept_seed.json` | The complete story plan emitted by `scripts/compile_bundle.py` from the workflow-kit surfaces. Contains metadata, characters, structural outline, story physics, and scene cards. Phase 5 added optional fields: `voice_definition`, `subplots`, `hooks`, `revelation_schedule`, `terminology_registry`, `stress_test_scores`, series metadata, and Weiland arc beats per character. Post-Phase 5 additions: `referenced_characters`, `quality_overrides`, `canon_profile` (franchise canon validation data), `initial_phase` (per-character starting arc phase), `series_id` (series linkage for shared state). |
| Scene Card | `schemas/scene_card.json` | Per-chapter/scene planning document. Contains chapter number, scene number, scene type (action/sequel), mission objectives, characters present, location, and structural constraints. Phase 5 added optional fields: `active_subplots`, `hook_actions`, `revelations`, `pov_arc_phase`, `arc_phase_transition`. |
| Story Physics | `schemas/story_physics.json` | Causality chains, revelation maps, promise/payoff ledger, and character pressure matrices. |
| Story Bible | `schemas/story_bible.json` | The combined planning document linking concept seed, structural outline, and scene cards. |
| Character Sheet | `schemas/character_sheet.json` | Detailed character profile with physical description, personality dimensions, speech patterns, relationships, arc, and motivation. |
| State Diff | `schemas/state_diff.json` | Post-chapter state mutation document. Describes changes to characters, knowledge, plot threads, timeline, and Chekhov guns after each chapter. Phase 5 added change types: `subplot_updates`, `hook_updates`, `arc_phase_updates`, `terminology_updates`. Before application, `sanitize_diff()` auto-corrects LLM vocabulary errors (fuzzy enum matching, concept-seed label mapping, old_value correction). |
| Universe Meta | `schemas/universe_meta.json` | Per-universe metadata (name, franchise, canon status). Created automatically on first pipeline run when universe scoping is active. |
| Failure Code | `schemas/failure_code.json` | GateCritic evaluation output. Contains verdict, failure codes, routing decision, calibrated score (0.60-1.00 scale with anchors), and chain-of-thought `reasoning` field. Phase 5 added 5 codes: `CHARACTER_ARC_STALL`, `HOOK_VIOLATION`, `SUBPLOT_DRIFT`, `TERMINOLOGY_DRIFT`, `VOICE_DEFINITION_VIOLATION`. `CANON_VIOLATION` promoted from polish to structural codes. |
| Canon Evidence | `schemas/canon_evidence.json` | RAG retrieval result with confidence score, source authority class, continuity tag, and divergence safety flag. |
| Series Seed | `schemas/series_seed.json` | Series-level planning document for multi-book projects. Contains series arc, per-book outlines, cross-book promises, and shared characters. Added in Phase 5. |
| Chapter Blueprint | `schemas/chapter_blueprint.json` | Per-chapter planning document synthesised from the seed + scene cards. Consumed by `ChapterGateCritic`. Lives at `data/franchises/<fr>/books/<bk>/chapter_blueprints/chapter_NN.json`. |
| Generation Brief | `schemas/generation_brief.json` | PlotArchitect output handed to ProseStylist: per-beat plan (beat sequence, turning point, POV, characters_present, structural phase) derived from the scene card. |
| Phase 0 Audit | `schemas/phase0_audit.json` | Output of `scripts/audit_phase0.py`. Records six-criterion audit of rendered prompts (voice rules → drafter, scene contract → drafter, constraints survive assembly, cross-scene feedback, register single-source, audit report exists). |
| Chapter Packet | `schemas/chapter_packet.json` | Slice 2 contract: the drafter's single inspectable runtime input. Base compiled once per chapter; overlay composed per scene. Produced by `src/pipeline/chapter_packet.py`. Off by default on shipping books. |
| Revision Debt | `schemas/revision_debt.json` | Slice 2 store for structured advisories (canon drift, gate findings, presence near-misses, compression, etc.). Closed `category` enum. Persisted to `output/<franchise>/<book>/state/revision_debt.db`. Off by default on shipping books. |
| Promise Ledger Entry | `schemas/promise_ledger_entry.json` | Slice 3 declaration-driven promise ledger row. Seeded from planning (`story_physics.promise_payoff_ledger` + scene-card `promises_planted` / `promises_paid`); progression / payoff / broken transitions are the only mutating writes. Persisted to `promise_ledger.db`. Off by default on shipping books. |
| Continuity Event | `schemas/continuity_event.json` | Slice 4 narrow LLM-extracted event log. `oneOf` restricts to five event types (`location_change`, `injury_state`, `possession`, `revelation`, `status_change`). Threshold-gated by `runtime.continuity_log.min_confidence`. Persisted to `continuity_log.db`. Off by default on shipping books. |
| Sociogram Edge | `schemas/sociogram_edge.json` | Slice 5 directional relationship edge. Three-axis scalar encoding (`trust`, `warmth`, `power_balance` in `[-1, 1]`) plus closed `arc_type` enum. Seeded from planning; scene-card `relationship_deltas` are the only auto-trusted write path. Persisted to `sociogram.db`. Off by default on shipping books. |
| Manuscript Patch | `schemas/manuscript_patch.json` | Slice 6 patch batch for `scripts/patch_workflow.py apply-manuscript-patch`. Closed action enum (`accept-isolated`, `replace`, `overrule`); scene-id pattern enforcement. |
| Chapter Memo | `schemas/chapter_memo.json` | Slice 2 per-chapter / milestone close memo synthesised by `ChapterCloseMemoGenerator` / `MilestoneMemoGenerator` from revision debt + gap notes + pending promises. Human-review artifact under `<run_dir>/memos/`. |
| Cosmology Meta | `schemas/cosmology_meta.json` | Optional meta-universe registry (shared rules / cross-franchise lore). Referenced by `concept_seed.meta.cosmology_id`; resolves to `data/cosmologies/<slug>/cosmology_meta.json`. |

## Notable Schema Additions

### canon_profile (Concept Seed)

The `canon_profile` section in the concept seed provides franchise-specific validation data for the Canon Expert agent. Fields:

| Field | Type | Description |
|-------|------|-------------|
| franchise | string | Franchise name (e.g., "Star Wars", "Marvel") |
| continuity | string | Continuity label (e.g., "Legends", "Canon", "MCU") |
| cross_continuity_violations | array | Terms/concepts from other continuities that must not appear |
| anachronistic_terms | array | Terms that are out-of-era for the story's timeline setting |

The Canon Expert reads this section at runtime and uses it to drive template-based validation. No franchise-specific logic is hardcoded in the agent itself.

### initial_phase (ensemble_cast weiland_arc)

The `initial_phase` field in each character's `weiland_arc` definition (within `ensemble_cast`) allows specifying a starting arc phase other than the default `lie_established`. This is useful for sequel books where characters begin mid-arc.

### series_id (meta)

The `series_id` field in the concept seed's `meta` section links a book to a series. Books sharing the same `series_id` share state at `output/<franchise>/<series>/state/`, enabling cross-book continuity for character arcs, plot threads, and knowledge.

## Data Flow

```
Workflow kit (workflows/<surface>/*.json) -> compile_bundle.py
    -> concept_seed.json (Concept Seed schema)
    -> scene_cards/ (Scene Card schema per file)
    -> series_seed.json (Series Seed schema, series mode only)

Pipeline (per chapter):
    Scene Card -> ContextAssembler -> prompt payload
        Context tiers: story bible, act summary, chapter summaries, recent prose
        Phase 5 tiers: voice_rules, hook_agenda, arc_context, subplot_context, terminology
    Prompt payload -> PlotArchitect -> generation_brief (Generation Brief schema)
    generation_brief + context -> ProseStylist -> prose (drafted)
    prose -> LineWriter -> prose (line-edited, optional; explicit context wiring)
    prose -> GateCritic -> Failure Code schema (advisory under forward-only relay)
    prose -> MetricsDashboard -> per-scene metrics (repetition, pacing, voice, slop)
    prose + metrics -> QualityPolish -> polished prose (expression-only)
    polished prose -> compression advisory (warn at <60%; never reverts)
    polished prose -> FinalGate -> Failure Code schema (advisory_only=True)
    polished prose -> CanonExpert -> continuity report (reads canon_profile from seed)
    polished prose + continuity report -> save-blocker layer
        CHARACTER_PRESENCE_BLOCKER | CANON_BLOCKER | POV advisory (non-blocking v1)
        -> save or quarantine (+ abort run on blocker)

Post-save (Phase 2+):
    Saved prose -> Summarizer -> State Diff schema
        Phase 5 deltas: subplot_updates, hook_updates, arc_phase_updates, terminology_updates
    State Diff -> StateDiffApplier (sanitizes + applies to SQLite)
    Saved prose -> ChapterMemory (ChromaDB)
    ContradictionScanner runs on updated state

Chapter close:
    All scenes saved -> word_count_telemetry (advisory: ±15% / 15-30% / >30%)
    All scenes saved -> ChapterGateCritic (blueprint-aware when present)

RAG queries:
    Query -> CanonDB -> Canon Evidence schema
    Query -> LoreService -> worldbuilding lore entries
```

## Using Schemas

The schema files are standard JSON Schema and can be used with any JSON Schema validator. They define the expected structure of input and output data throughout the pipeline.

Schema files are located at:
```
schemas/
├── canon_evidence.json
├── chapter_blueprint.json
├── chapter_memo.json
├── chapter_packet.json
├── character_sheet.json
├── concept_seed.json
├── continuity_event.json
├── cosmology_meta.json
├── failure_code.json
├── generation_brief.json
├── manuscript_patch.json
├── phase0_audit.json
├── promise_ledger_entry.json
├── revision_debt.json
├── scene_card.json
├── series_seed.json
├── sociogram_edge.json
├── state_diff.json
├── story_bible.json
├── story_physics.json
└── universe_meta.json
```

The actual schema inventory lives in the `schemas/` directory at the repo root; keep this list in sync with `git ls-files schemas/*.json`.
