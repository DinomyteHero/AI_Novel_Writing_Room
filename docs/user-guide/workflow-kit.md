# Workflow Kit (Phase 4)

The **workflow kit** is the front end to the AI Novel Writing Room
pipeline. It splits concept authoring into six independent **surfaces**,
each with three orthogonal **ingress modes**: an interactive chat SKILL,
a programmatic API, and importers for external formats.

The single bundle compiler at [`scripts/compile_bundle.py`](../../scripts/compile_bundle.py)
merges all six surface outputs into the canonical `concept_seed.json` +
`scene_cards/` tree the pipeline already consumes. Nothing in the
pipeline changed in Phase 4; what changed is how you produce its input.

For the full operator sequence, see [New Manuscript Workflow](new-manuscript-workflow.md).
For a looser author-led start, use [Idea Session Capture](idea-session-capture.md)
before authoring the six surfaces. It creates `workflows/idea_session/`
with chat notes, open questions, and per-surface handoff files.

## Why six surfaces

The legacy `workshop_runner.py` (now removed — see [Legacy `workshop_runner` has been removed](#legacy-workshop_runner-has-been-removed)
below) walked an 11-step protocol in one long monolithic chat session.
That works when one author knows every step, but it doesn't compose.
The workflow kit splits authoring along its natural seams so:

- A non-Claude-Code frontend can drive any surface independently (Phase 8).
- An author with existing material can use an importer instead of
  re-authoring through chat.
- Programmatic automations (CI scaffolds, data pipelines, ports of
  legacy seeds) call the api.py modules directly.

## The six surfaces

| Surface | What it owns | Ingress |
|---|---|---|
| **universe-builder** | meta + universe_meta + premise + conflict + theme | SKILL ✓ • API ✓ • importers (legacy_seed, plain_markdown) |
| **canon-drafter** | canon_profile + canon_constraints + force_mechanics + terminology_registry | SKILL ✓ • API ✓ • importers |
| **voice-discovery** | voice_definition (POV, register, anti-slop, character voices, etc.) | SKILL ✓ • API ✓ • importers |
| **character-forge** | ensemble_cast + relationship_arcs + referenced_characters | SKILL ✓ • API ✓ • importers |
| **outline-planner** | structural_notes + outline + subplots + hooks + revelations + promises | SKILL ✓ • API ✓ • importers |
| **scene-card-authoring** | per-scene cards | SKILL stub (P2) • API ✓ • importers |

Each surface module lives at `workflows/<surface>/`:

```
workflows/<surface>/
  schema.json                 # canonical output contract
  SKILL.md                    # ingress 1: interactive chat session
  api.py                      # ingress 2: programmatic / headless
  validate.py                 # schema + semantic checks
  importers/
    legacy_seed.py            # ingress 3a: extract from a concept_seed.json
    plain_markdown.py         # ingress 3b: parse a hand-written markdown file
    README.md                 # plain_markdown format spec
```

The shared preamble at [`workflows/_shared/SKILL_preamble.md`](../../workflows/_shared/SKILL_preamble.md)
describes the protocol every surface follows.

## End-to-end usage

### Fresh project (empty directory → compiled bundle)

```bash
# 0. Optional: create an idea-session workspace for the planning chat.
python scripts/idea_session_capture.py init --title "My Novel" --franchise "My Franchise"

# 1. Scaffold the project tree (canon_profile + voice templates).
python scripts/init_project.py --title "My Novel" --franchise "My Franchise" --depth original_light

# 2. Author each surface — pick any ingress mode per surface:
#
#    Interactive chat (Claude Code auto-discovers skills under .claude/skills/):
#      /universe-builder
#      /canon-drafter
#      /voice-discovery
#      /character-forge
#      /outline-planner
#      /scene-card-authoring
#
#    Programmatic — see workflows/<surface>/api.py
#
#    Hand-written markdown — write a .md file then call the surface's
#    plain_markdown importer (see workflows/<surface>/importers/README.md).

# 3. Compile the bundle.
python scripts/compile_bundle.py --franchise my-franchise --book my-novel

# 4. Run the pipeline.
python -m src.main --franchise my-franchise --book my-novel --chapter 1 --raw-draft
```

### Migrate an existing project (concept_seed.json → workflow surfaces)

There is no dedicated migration script. Run each surface's `legacy_seed`
importer directly against the existing `concept_seed.json` (and, when
present, the extracted `scene_cards/` tree) to write the per-surface
artifacts into `workflows/`, then compile:

```bash
# Run each surface's legacy_seed importer against the existing seed.
# See workflows/<surface>/importers/legacy_seed.py for the per-surface API.
python scripts/compile_bundle.py --franchise <slug> --book <slug>
```

## What the bundle compiler does

[`scripts/compile_bundle.py`](../../scripts/compile_bundle.py):

1. Reads `workflows/{universe,canon,voice,characters,outline}.json` and
   `workflows/scene_cards.json` (or `workflows/scene_cards/*.json` per-card files).
2. Applies the same fixed transform sequence as
   [`scripts/install_seed.py::_apply_workshop_patch`](../../scripts/install_seed.py)
   so validation semantics match the legacy installer exactly.
3. Validates structurally against `schemas/concept_seed.json` and
   `schemas/scene_card.json`.
4. Validates semantically via
   [`compliance_validator.validate_concept_seed`](../../src/concept_workshop/compliance_validator.py).
5. Writes `concept_seed.json`, `scene_cards/chapter_NN_scene_NN.json`,
   and `compile_report.json` (machine-readable gap report).

The compiler is **idempotent**: re-running on unchanged surface inputs
produces byte-identical seed and per-card files.

### Required vs optional surfaces

The compiler treats `universe`, `canon`, `voice`, `characters`, and
`outline` as **required**. Missing any of them fails the compile (exit 1).

`scene_cards.json` is **optional**: when missing the compiler emits a
warning and writes a seed with empty extracted scene cards. The pipeline
auto-generates cards via `SceneCardGenerator` at run time. Use
`--strict` to make this a failure instead.

## Legacy `workshop_runner` has been removed

The interactive `src.concept_workshop.workshop_runner` CLI has been
removed entirely — see [concept-workshop.md](concept-workshop.md) for
the rationale. New projects must use the workflow kit surfaces described
above. There is no migration script; compile fresh per-surface artifacts
under `workflows/<surface>/` and run `scripts/compile_bundle.py`.

The `seed_transforms`, `scene_card_translator`, and `voice_discovery`
re-export shims that previously lived under `src/concept_workshop/` have
been removed. Import directly from the canonical locations:

- `workflows/_shared/seed_transforms.py`
- `workflows/_shared/scene_card_translator.py`
- `workflows/voice_discovery/api.py`

The remaining modules in `src/concept_workshop/` (`compliance_validator.py`,
`series_manager.py`, `stress_test.py`) are canonical, not shims, and keep
their existing import paths.

## Out of scope (Phase 5+)

Phase 4 deliberately does not touch:

- **Chapter blueprint generation** and `ChapterGateCritic` instantiation
  (Phase 5).
- **Series transitions** — `spawn_next_book.py`, `branch_point`
  enforcement (Phase 6).
- **Closed-loop lore** — `lore_extractor` post-scene loop,
  `promote_lore.py` (Phase 7).
- **Frontend decoupling** — extracting prompts to
  `prompts/workflow_kit/` and shipping a reference web UI (Phase 8).
- **`notion_export.py`, `world_anvil.py`, `author_corpus.py`** importers
  (Phase 8 or later).
