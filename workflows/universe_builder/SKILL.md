# universe-builder — SKILL

> Read first: `workflows/_shared/SKILL_preamble.md` (shared role + protocol).

## Surface in one sentence

Pin down what universe / franchise / canon-status / era / tone / target
shape this project lives in, plus the project's foundational premise,
conflict, and theme — the fields that make every other surface coherent.

## Workshop steps owned

This surface absorbs **Step 0** (project scope) and **Step 1** (franchise,
era, tone, canon status, basic context). It also owns the foundational
**premise** (Step 2) and **conflict** (Step 3) and **theme** (Step 2/3)
sections, which are project-identity content rather than craft execution.

## Authoring sequence

### Step 0 — project scope

Ask:

> "Are we working on a **standalone** novel, the first book of a
> **planned series**, or a **continuation** of an existing book/series?"

Set `meta.project_scope` to one of `standalone`, `planned_series`,
`continuation`. For a continuation, also ask for `meta.series_id` and
`meta.book_number`.

### Step 1 — universe identity

Walk these one at a time:

1. `meta.project_title` — the working title.
2. `meta.franchise` — the franchise name. (Use the kebab-case
   `franchise_slug` for the directory; the human-friendly form lives
   here.) For original work, use `"Original"` or the imprint name.
3. `meta.canon_status` — one of `canon_compliant`, `AU`, `original`.
4. `meta.canon_status_description` — optional prose elaborating
   ("post-Lost Tribe AU", "Legends-only continuity").
5. `meta.era` — when in the franchise timeline this is set. For
   original work, the in-world period name.
6. `meta.tone` — one of `dark_gritty`, `adventurous_hopeful`,
   `political_intrigue`, `character_study`, `heroic_with_weight`.
7. `meta.tone_description` — optional descriptive blend.
8. `meta.target_word_count` — integer 40000-120000.
9. `meta.target_chapters` — integer 15-40.
10. `meta.pov_structure` — short string (e.g. `"single close third"`,
    `"rotating limited"`).
11. **Cosmology check**: does this universe share a meta-cosmology
    with other franchises? If yes, set `meta.cosmology_id` and
    `universe_meta.cosmology_id` (Sanderson-style shared lore).

`universe_meta` mirrors `meta`'s franchise/canon_status/cosmology_id and
adds:

- `universe_meta.universe_name` — usually equals franchise.
- `universe_meta.commercial_intent` — default `fanfiction_noncommercial`;
  options: `fanfiction_monetized`, `commercial_original`,
  `commercial_licensed`, `private`.
- `universe_meta.notes` — free-form prose.
- `universe_meta.branch_point` — for AU work, the divergence point
  metadata (`source_canon`, `divergence_point`,
  `divergence_description`). Phase 4 records this descriptively;
  enforcement comes in Phase 6.

### Step 2 — premise (HARD VALIDATION GATE)

Author all three fields:

1. `premise.what_if` — the speculative core, **minimum 50 characters**.
   "What if X — and what changes?"
2. `premise.central_dramatic_question` — the yes/no question the book
   answers. Must be answerable; specific to the book (not the series).
3. `premise.logline` — one-sentence pitch, **maximum 500 characters**.

Don't advance past this gate until all three are present and the
`what_if` minimum-length check passes.

### Step 3 — conflict (HARD VALIDATION GATE)

1. `conflict.primary_antagonistic_force.type` — short noun
   ("institutional", "personal", "cosmic").
2. `conflict.primary_antagonistic_force.identity` — who/what.
3. `conflict.primary_antagonistic_force.motivation` — **minimum 50
   characters**. Why does this force act?
4. `conflict.primary_antagonistic_force.escalation` — **minimum 100
   characters**. How does pressure mount across the book?
5. `conflict.secondary_pressures` — at least one bullet (array of
   strings).
6. `conflict.lock_in_mechanism` — **minimum 30 characters**. Why can't
   the protagonist walk away?

### Step 4 — theme

1. `theme.thematic_premise` — the single sentence the book argues.
2. `theme.thematic_argument` — **minimum 100 characters**. Elaborate
   the argument in dialectic form.
3. `theme.how_each_arc_tests_theme` — dict keyed by character name,
   value is a sentence on how that character's arc tests the theme.
   (You can defer this until character-forge runs and write a stub
   `{"_pending": "filled in after character-forge"}`.)

### Step 5 — protagonist arc type (optional)

`protagonist_arc_type` is one of `change`, `steadfast`, `fall`, `rise`.
This is a high-level signal; per-character structured arcs live in
character-forge under `ensemble_cast[].weiland_arc.arc_type`.

### Step 6 — quality and metadata (optional)

- `quality_overrides.word_frequency_allowlist` — franchise vocabulary
  that should not flag as overused (e.g. `["Force", "Sith", "Jedi"]`
  for Star Wars).
- `quality_overrides.semantic_similarity_threshold` — 0.5–1.0; default
  0.85.
- `extended_metadata` — any project-specific structured data that
  doesn't fit the canonical schema.

## Persisting

```python
from src.project_paths import ProjectPaths
from workflows.universe_builder.api import UniverseBuilder

paths = ProjectPaths(book_slug, franchise_slug=franchise_slug)
ub = UniverseBuilder(paths)
ub.write(artifact)  # validates and writes workflows/universe.json
```

Use `UniverseBuilder.init_from_template(title=..., franchise=..., depth=...)`
to bootstrap a baseline that you then refine through the steps above.

## Importers (skip the chat if you can)

- `workflows/universe_builder/importers/legacy_seed.py` — extract from an
  existing `concept_seed.json` (the Ruusan path).
- `workflows/universe_builder/importers/plain_markdown.py` — parse a
  hand-written markdown file. See `importers/README.md` for the format.

## Hand-off

After this surface validates, recommend the human run:

1. **canon-drafter** — `/canon-drafter` for canon profile + constraints
   + terminology + force/magic mechanics.
2. **voice-discovery** — `/voice-discovery` for voice definition.
3. **character-forge** — `/character-forge` for ensemble cast.
4. **outline-planner** — `/outline-planner` for structural notes +
   chapter outline + subplots.
5. **scene-card-authoring** — `/scene-card-authoring` (or
   `SceneCardAuthoring.generate(seed)` headless) for per-scene cards.
6. `python scripts/compile_bundle.py --franchise <slug> --book <slug>`
   to merge into the canonical bundle.
