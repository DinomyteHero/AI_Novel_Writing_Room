# outline-planner — SKILL

> Read first: `workflows/_shared/SKILL_preamble.md` (shared role + protocol).

## Surface in one sentence

Build the planner-level structural outline (Brooks four-part beat map
plus per-chapter synopsis + POV + structural phase) and the
subplot/hook/revelation/promise/arc-phase-map skeletons that orchestrate
the book.

## Workshop steps owned

**Step 6** (structural outline) and **Step 7** (subplots, hooks,
revelations, promises). Per-scene cards live in **scene-card-authoring**.

## Authoring sequence

### Step 1 — structural notes (Brooks four-part)

`structural_notes.brooks_alignment` keys (all optional but recommended):

- `part_1_setup` — opening world + protagonist's lie established.
- `inciting_incident` (~12%) — disturbance first touches protagonist.
- `first_plot_point` (~25%) — protagonist crosses the threshold;
  point of no return.
- `part_2_response` — protagonist reacts, mostly defensively.
- `first_pinch_point` (~37.5%) — antagonist threat re-asserted.
- `midpoint` (~50%) — revelation shifts the protagonist from response
  to attack.
- `part_3_attack` — protagonist drives the action.
- `second_pinch_point` (~62.5%) — antagonist escalates as protagonist
  attacks.
- `second_plot_point` (~75%) — last piece of information arrives;
  resolution path is clear.
- `part_4_resolution` — climax → denouement.
- `climax` (~85-95%) — final confrontation.

Don't pad. Each beat is a single sentence describing what happens at
that beat for *this* book.

### Step 2 — chapter outline (HARD VALIDATION GATE)

`outline` is an array of chapter entries. **At least 1 entry**, and
chapter_number values must be unique.

Per chapter:

1. `chapter_number` — integer ≥ 1.
2. `synopsis` — a sentence-or-three describing what happens.
3. Optional: `chapter_title`, `pov_character`, `structural_phase`
   (one of: `setup`, `first_plot_point`, `response`, `first_pinch`,
   `midpoint`, `attack`, `second_pinch`, `second_plot_point`,
   `resolution`, `climax`).
4. Optional: `arc_phases_active` — array of arc-phase names from the
   character-forge `arc_phase_map`.
5. Optional: `subplot_ids` — array of subplot IDs active in this
   chapter (must match `subplots[].subplot_id`; the validator
   cross-checks).
6. Optional: `estimated_word_count`.

Aim for one entry per `meta.target_chapters` from universe-builder.

### Step 3 — subplots

Each subplot:

```json
{
  "subplot_id": "SUB_01",
  "name": "Royal politics",
  "function": "secondary_pressure",
  "arc_summary": "Senate hearings escalate from procedural to existential.",
  "chapters_active": [3, 5, 8, 12, 18, 22]
}
```

Aim for **3-6** subplots in a 28-chapter book; fewer is fine for
shorter books.

### Step 4 — hooks

Each hook is a planted question or unresolved beat:

```json
{
  "hook_id": "HK_01",
  "hook_type": "hard",   // hard | soft | series
  "planted_in": 1,
  "resolved_in": 12,
  "description": "The strange medallion."
}
```

`hard` hooks must resolve in-book. `soft` hooks may carry. `series`
hooks resolve in a later book (`resolved_in: "next_book"`).

### Step 5 — revelation schedule

Each revelation:

```json
{
  "revelation_id": "R_01",
  "what": "Kael's father was Sith.",
  "known_by": ["Council"],
  "revealed_to": ["Kael"],
  "revealed_in": 18,
  "significance": "major"   // minor | moderate | major | climactic
}
```

### Step 6 — promise/payoff ledger

Higher-level reader contracts spanning multiple beats:

```json
{
  "promise_id": "P_01",
  "promise": "Kael will face his father's choice.",
  "type": "character",   // plot | character | thematic | atmospheric
  "planted_in": 1,
  "payoff_in": 25,
  "related_hook_id": "HK_03"
}
```

### Step 7 — arc_phase_maps

Chapter-level map of each character's Weiland arc, keyed by character
name. The bundle compiler injects these into
`ensemble_cast[].weiland_arc.arc_phase_map`. If the character-forge
artifact already carries arc_phase_maps, you can leave this section
out.

```json
"arc_phase_maps": {
  "Kael": {
    "lie_established": "1-3",
    "lie_reinforced": "5-8",
    "lie_challenged": "12-15",
    "moment_of_truth": "18",
    "new_truth_demonstrated": "22-25",
    "arc_resolved": "28"
  }
}
```

## Persisting

```python
from workflows.outline_planner.api import OutlinePlannerSurface

op = OutlinePlannerSurface(paths)
artifact = OutlinePlannerSurface.envelope(
    outline,
    structural_notes=structural_notes,
    subplots=subplots,
    hooks=hooks,
    revelation_schedule=revelations,
    promise_payoff_ledger=promises,
    arc_phase_maps=arc_phase_maps,
)
op.write(artifact)
# With router (LLM): await op.generate(concept_seed) projects an LLM-built
# outline; useful when you want a draft to refine rather than starting blank.
```

## Importers

- `legacy_seed.py` — derive outline from extracted scene cards via
  `OutlinePlannerSurface.project_to_outline`. Pulls subplots / hooks /
  revelations / promises verbatim from the legacy seed.
- `plain_markdown.py` — parse a hand-written markdown file. Each
  `## Chapter N` section produces an outline entry. See
  `importers/README.md`.

## Hand-off

After outline validates, the next natural surface is
**scene-card-authoring** (`/scene-card-authoring` or
`SceneCardAuthoring.generate(seed)` headless). The bundle compiler
treats missing scene_cards as a warning (the pipeline auto-generates
downstream); scene-card-authoring is the surface that lets you
hand-author or import them ahead of time.
