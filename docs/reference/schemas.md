# JSON Schemas

The `schemas/` directory contains JSON Schema definitions for the system's core data structures. These are used for validation and serve as the canonical reference for data formats.

## Available Schemas

| Schema | File | Description |
|--------|------|-------------|
| Concept Seed | `schemas/concept_seed.json` | The complete story plan output from the Concept Workshop. Contains metadata, characters, structural outline, story physics, and scene cards. Phase 5 added optional fields: `voice_definition`, `subplots`, `hooks`, `revelation_schedule`, `terminology_registry`, `stress_test_scores`, series metadata, and Weiland arc beats per character. Post-Phase 5 additions: `referenced_characters`, `quality_overrides`, `canon_profile` (franchise canon validation data), `initial_phase` (per-character starting arc phase), `series_id` (series linkage for shared state). |
| Scene Card | `schemas/scene_card.json` | Per-chapter/scene planning document. Contains chapter number, scene number, scene type (action/sequel), mission objectives, characters present, location, and structural constraints. Phase 5 added optional fields: `active_subplots`, `hook_actions`, `revelations`, `pov_arc_phase`, `arc_phase_transition`. |
| Story Physics | `schemas/story_physics.json` | Causality chains, revelation maps, promise/payoff ledger, and character pressure matrices. |
| Story Bible | `schemas/story_bible.json` | The combined planning document linking concept seed, structural outline, and scene cards. |
| Character Sheet | `schemas/character_sheet.json` | Detailed character profile with physical description, personality dimensions, speech patterns, relationships, arc, and motivation. |
| State Diff | `schemas/state_diff.json` | Post-chapter state mutation document. Describes changes to characters, knowledge, plot threads, timeline, and Chekhov guns after each chapter. Phase 5 added change types: `subplot_updates`, `hook_updates`, `arc_phase_updates`, `terminology_updates`. Before application, `sanitize_diff()` auto-corrects LLM vocabulary errors (fuzzy enum matching, concept-seed label mapping, old_value correction). |
| Universe Meta | `schemas/universe_meta.json` | Per-universe metadata (name, franchise, canon status). Created automatically on first pipeline run when universe scoping is active. |
| Failure Code | `schemas/failure_code.json` | GateCritic evaluation output. Contains verdict, failure codes, routing decision, calibrated score (0.60-1.00 scale with anchors), and chain-of-thought `reasoning` field. Phase 5 added 5 codes: `CHARACTER_ARC_STALL`, `HOOK_VIOLATION`, `SUBPLOT_DRIFT`, `TERMINOLOGY_DRIFT`, `VOICE_DEFINITION_VIOLATION`. `CANON_VIOLATION` promoted from polish to structural codes. |
| Canon Evidence | `schemas/canon_evidence.json` | RAG retrieval result with confidence score, source authority class, continuity tag, and divergence safety flag. |
| Series Seed | `schemas/series_seed.json` | Series-level planning document for multi-book projects. Contains series arc, per-book outlines, cross-book promises, and shared characters. Added in Phase 5. |

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
Concept Workshop
    -> concept_seed.json (Concept Seed schema)
    -> scene_cards/ (Scene Card schema per file)
    -> series_seed.json (Series Seed schema, series mode only)

Pipeline (per chapter):
    Scene Card -> ContextAssembler -> prompt payload
        Context tiers: story bible, act summary, chapter summaries, recent prose
        Phase 5 tiers: voice_rules, hook_agenda, arc_context, subplot_context, terminology
    Prompt payload -> PlotArchitect -> generation brief
    Generation brief -> ProseStylist -> prose
    Prose -> CanonExpert -> canon violations (reads canon_profile from seed)
    Prose -> GateCritic -> Failure Code schema (receives canon violation context)
    Prose -> Summarizer -> State Diff schema
        Phase 5 deltas: subplot_updates, hook_updates, arc_phase_updates, terminology_updates

RAG queries:
    Query -> CanonDB -> Canon Evidence schema
```

## Using Schemas

The schema files are standard JSON Schema and can be used with any JSON Schema validator. They define the expected structure of input and output data throughout the pipeline.

Schema files are located at:
```
schemas/
├── canon_evidence.json
├── character_sheet.json
├── concept_seed.json
├── failure_code.json
├── scene_card.json
├── state_diff.json
├── series_seed.json
├── story_bible.json
└── story_physics.json
```
