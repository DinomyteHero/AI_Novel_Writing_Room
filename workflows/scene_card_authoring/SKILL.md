# scene-card-authoring — SKILL (P2 stub)

> Read first: `workflows/_shared/SKILL_preamble.md` (shared role + protocol).

## Status: Phase 4 ships api.py + importers; chat-led authoring is P2

Per the Phase 4 scope decision, the **interactive chat-led**
scene-card-authoring SKILL is deferred to a follow-up phase. The
api.py and the two importers (legacy_seed, plain_markdown) are
shipped in Phase 4.

## What you can do today

### Headless generation (recommended)

```python
from src.model_router import ModelRouter
from workflows.scene_card_authoring.api import SceneCardAuthoring

router = ModelRouter()
sca = SceneCardAuthoring(paths, router=router)
cards = await sca.generate(concept_seed)
sca.write(SceneCardAuthoring.envelope(cards))
sca.write_per_card(cards)
```

`SceneCardAuthoring.generate` wraps `SceneCardGenerator` from
`src/planning/scene_card_generator.py` — the same generator the
pipeline uses at run time when scene cards are missing.

### Import from a legacy seed

```python
from workflows.scene_card_authoring.importers.legacy_seed import import_from_seed
artifact = import_from_seed(seed, extracted_scene_cards_dir=paths.scene_cards_dir)
sca.write(artifact)
sca.write_per_card(artifact["scene_cards"])
```

### Import from hand-written markdown

See `importers/README.md`. Each `## Chapter N Scene M` section
produces one card.

### Translate workshop-format cards to canonical shape

```python
canonical = sca.translate(workshop_cards, structural_overrides={"26": "climax"})
```

## Surface artifact contract

The envelope at `workflows/scene_cards.json` carries:

```json
{
  "surface": "scene-card-authoring",
  "schema_version": "1.0",
  "structural_overrides": { "26": "climax" },
  "scene_cards": [ ... ]
}
```

The per-card directory at `workflows/scene_cards/` carries one file
per `(chapter, scene)` pair, named `chapter_NN_scene_NN.json`. The
bundle compiler reads either; per-card files win when both exist.

## Card field reference (subset)

Required by `schemas/scene_card.json` (the strict schema the bundle
compiler validates against post-translation):

- `chapter_number`, `scene_number`, `structural_phase`,
  `pov_character`, `mission`, `conflict`, `turning_point`.

Workshop fields the translator accepts as fallbacks:

- `scene_goal` → `mission`
- `scene_conflict` → `conflict`
- `location` → `setting`
- `estimated_word_count` → `target_word_count`
- `arc_phase` → `pov_arc_phase`
- `subplot_references` → `active_subplots`
- `hook_references` → `hook_actions`
- `revelation_references` → `revelations`

See `workflows/_shared/scene_card_translator.py::translate_scene_card`
for the full mapping and structural-phase precedence rules.

## What's *not* in the chat-led SKILL yet

- Step 8 of the legacy concept_workshop walks the human through scene
  cards one at a time with prompts for stakes, action_beats,
  dialogue_expectation, etc. Phase 4 ships only the headless
  generation path; chat-led per-scene authoring lands in a follow-up
  phase.

## Hand-off

After scene cards are written (or omitted, in which case the pipeline
auto-generates), run:

```
python scripts/compile_bundle.py --franchise <slug> --book <slug>
```

to merge all six surfaces into the canonical `concept_seed.json` +
`scene_cards/` tree the pipeline consumes.
