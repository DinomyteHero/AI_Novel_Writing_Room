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

#### Scene-count discipline (less is more)

The schema does **not** force a minimum scene count per chapter. A
chapter with one load-bearing scene is healthier than a chapter padded
with three scenes that share one turning point. Do not invent extra
scenes to "fill" a chapter.

Only split a chapter when each resulting scene carries its own:

- distinct turning point (trigger / shift / cost)
- distinct mission for the POV character
- distinct emotional arc (start / shift / end)

If two candidate scenes share a turning point, fold them into one. The
scene-card-authoring surface enforces this same discipline at the per-card
level — but planner-level intent (which chapters are dense, which are
single-scene) belongs in the synopsis here.

When you set `estimated_word_count`, calibrate to what the dramatic load
actually needs, not to a uniform-cadence ideal. A 1,500-word single-scene
chapter and a 4,500-word three-scene chapter can sit beside each other
without an alarm bell.

#### Multi-POV chapter braiding (optional, recommended for tension)

Single-POV chapters are the safe default. They keep one character's
emotional thread continuous and let the drafter sink fully into a single
voice per chapter.

But Zahn / Allston / Stackpole-tier commercial Star Wars tie-ins (and
most ensemble thrillers) routinely braid 2–4 POVs *within a single chapter*
when the dramatic shape calls for it. The Scoundrels chapter 1 model is the
canonical example: three POVs (Imperial captain → Intelligence agent →
Black Sun sector chief) advance three threads in 3,500 words, each scene
cutting at a question that the next scene's POV makes more urgent.

Use `pov_sequence` to signal multi-POV intent on a chapter:

```json
{
  "chapter_number": 7,
  "synopsis": "Ben tracks Korda through the Foundation archive; Tess, off-stage, orders Korda's elimination.",
  "pov_character": "Ben",
  "pov_sequence": ["Ben", "Tess", "Ben"],
  "structural_phase": "first_pinch"
}
```

`pov_character` remains the dominant / framing POV. `pov_sequence` is the
ordered list of POVs across the chapter's scenes. The example above asks
scene-card-authoring to generate three cards — Ben, Tess, Ben — for an
A-B-A weave that lets the antagonist's calm appear mid-chapter and
escalate the protagonist's chase on return.

When to braid:

- A protagonist scene whose tension depends on antagonist offstage action
  the reader needs to *see* now, not hear about later.
- A chapter whose climax is an ensemble convergence (Glasswell-style).
- Pinch-point or midpoint chapters where the antagonist's calm functions
  as a tonal counterweight.

When NOT to braid:

- Quiet character scenes that need uninterrupted interiority.
- Chapters with a single load-bearing turning point already fully owned by
  one POV character.
- Early-act setup chapters where adding POVs would scatter the reader.

Use `scene_briefs` to seed per-scene shape at outline time:

```json
{
  "chapter_number": 7,
  "pov_sequence": ["Ben", "Tess", "Ben"],
  "scene_briefs": [
    {"scene_number": 1, "pov": "Ben", "thread": "Ben archive chase",
     "structural_role": "escalation", "turning_point_hint": "Korda routes through Cinderline cutout"},
    {"scene_number": 2, "pov": "Tess", "thread": "Tess board-clearing",
     "structural_role": "reveal", "turning_point_hint": "Tess orders Korda eliminated"},
    {"scene_number": 3, "pov": "Ben", "thread": "Ben archive chase",
     "structural_role": "aftermath", "turning_point_hint": "Ben finds Korda dead, trail cold"}
  ]
}
```

The `thread` field is load-bearing for braided chapters: it tells
scene-card-authoring which plot line each scene advances, so the cards
don't drift into rehashing the same beat from different angles. Distinct
threads per scene is the test for whether the braid is dramatically
justified.

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
