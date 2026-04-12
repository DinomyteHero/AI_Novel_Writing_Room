# JSON Schemas

The `schemas/` directory contains JSON Schema definitions for the system's core data structures. These are used for validation and serve as the canonical reference for data formats.

## Available Schemas

| Schema | File | Description |
|--------|------|-------------|
| Concept Seed | `schemas/concept_seed.json` | The complete story plan output from the Concept Workshop. Contains metadata, characters, structural outline, story physics, and scene cards. Phase 5 added optional fields: `voice_definition`, `subplots`, `hooks`, `revelation_schedule`, `terminology_registry`, `stress_test_scores`, series metadata, and Weiland arc beats per character. Post-Phase 5 additions: `referenced_characters` (non-ensemble characters appearing in scene cards), `quality_overrides` (per-project quality metric thresholds and allowlists). |
| Scene Card | `schemas/scene_card.json` | Per-chapter/scene planning document. Contains chapter number, scene number, scene type (action/sequel), mission objectives, characters present, location, and structural constraints. Phase 5 added optional fields: `active_subplots`, `hook_actions`, `revelations`, `pov_arc_phase`, `arc_phase_transition`. |
| Story Physics | `schemas/story_physics.json` | Causality chains, revelation maps, promise/payoff ledger, and character pressure matrices. |
| Story Bible | `schemas/story_bible.json` | The combined planning document linking concept seed, structural outline, and scene cards. |
| Character Sheet | `schemas/character_sheet.json` | Detailed character profile with physical description, personality dimensions, speech patterns, relationships, arc, and motivation. |
| State Diff | `schemas/state_diff.json` | Post-chapter state mutation document. Describes changes to characters, knowledge, plot threads, timeline, and Chekhov guns after each chapter. Phase 5 added change types: `subplot_updates`, `hook_updates`, `arc_phase_updates`, `terminology_updates`. Before application, `sanitize_diff()` auto-corrects LLM vocabulary errors (fuzzy enum matching, concept-seed label mapping, old_value correction). |
| Universe Meta | `schemas/universe_meta.json` | Per-universe metadata (name, franchise, canon status). Created automatically on first pipeline run when universe scoping is active. |
| Failure Code | `schemas/failure_code.json` | GateCritic evaluation output. Contains verdict, failure codes, and routing decision. Phase 5 added 5 codes: `CHARACTER_ARC_STALL`, `HOOK_VIOLATION`, `SUBPLOT_DRIFT`, `TERMINOLOGY_DRIFT`, `VOICE_DEFINITION_VIOLATION`. |
| Canon Evidence | `schemas/canon_evidence.json` | RAG retrieval result with confidence score, source authority class, continuity tag, and divergence safety flag. |
| Series Seed | `schemas/series_seed.json` | Series-level planning document for multi-book projects. Contains series arc, per-book outlines, cross-book promises, and shared characters. Added in Phase 5. |

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
    Prose -> GateCritic -> Failure Code schema
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
