# JSON Schemas

The `schemas/` directory contains JSON Schema definitions for the system's core data structures. These are used for validation and serve as the canonical reference for data formats.

## Available Schemas

| Schema | File | Description |
|--------|------|-------------|
| Concept Seed | `schemas/concept_seed.json` | The complete story plan output from the Concept Workshop. Contains metadata, characters, structural outline, story physics, and scene cards. |
| Scene Card | `schemas/scene_card.json` | Per-chapter/scene planning document. Contains chapter number, scene number, mission objectives, characters present, location, and structural constraints. |
| Story Physics | `schemas/story_physics.json` | Causality chains, revelation maps, promise/payoff ledger, and character pressure matrices. |
| Story Bible | `schemas/story_bible.json` | The combined planning document linking concept seed, structural outline, and scene cards. |
| Character Sheet | `schemas/character_sheet.json` | Detailed character profile with physical description, personality dimensions, speech patterns, relationships, arc, and motivation. |
| State Diff | `schemas/state_diff.json` | Post-chapter state mutation document. Describes changes to characters, knowledge, plot threads, timeline, and Chekhov guns after each chapter. |
| Failure Code | `schemas/failure_code.json` | GateCritic evaluation output. Contains verdict, failure codes, and routing decision. |
| Canon Evidence | `schemas/canon_evidence.json` | RAG retrieval result with confidence score, source authority class, continuity tag, and divergence safety flag. |
| Series Seed | `schemas/series_seed.json` | Series-level planning document for multi-book projects. Contains series arc, per-book outlines, cross-book promises, and shared characters. |

## Data Flow

```
Concept Workshop
    -> concept_seed.json (Concept Seed schema)
    -> scene_cards/ (Scene Card schema per file)

Pipeline (per chapter):
    Scene Card -> PlotArchitect -> generation brief
    Generation brief -> ProseStylist -> prose
    Prose -> GateCritic -> Failure Code schema
    Prose -> Summarizer -> State Diff schema

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
