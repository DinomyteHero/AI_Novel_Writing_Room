# character-forge — SKILL

> Read first: `workflows/_shared/SKILL_preamble.md` (shared role + protocol).

## Surface in one sentence

Build the **ensemble cast** — 2 to 6 characters with three-dimensional
profiles and Weiland arc structure (lie/ghost/want/need + arc_type +
arc_phase_map) — plus optional referenced characters and dyad-level
relationship arcs.

## Workshop step owned

**Step 4** — Character architecture, in full.

## Authoring sequence

### Step 1 — cast roster (HARD VALIDATION GATE)

The schema requires **2 to 6** entries in `ensemble_cast`. Per character:

1. `name` — the character's name as it appears in prose.
2. `role` — protagonist, antagonist, mentor, foil, deuteragonist, etc.
3. Optional: `age` (string), `force_status` (franchise-specific).

### Step 2 — three dimensions (HARD VALIDATION GATE per character)

For each character, all three required, **minimum 50 characters each**:

1. `three_dimensions.surface` — what other characters perceive (job,
   reputation, public face).
2. `three_dimensions.backstory_inner_demons` — the wound, the secret,
   the formative event that shaped the character.
3. `three_dimensions.action_under_pressure` — what the character DOES
   when pushed past their normal coping. Not what they think — what
   they do.

The minimum-length rule is structural: it forces specificity over
abstraction.

### Step 3 — Weiland arc (HARD VALIDATION GATE for any character with an arc)

For each main-cast character, build the Weiland Lie/Truth structure:

1. `weiland_arc.lie_believed` — **min 30 chars**. The Lie the
   character believes about the world or themselves at story open.
2. `weiland_arc.ghost` — **min 30 chars**. The past wound that
   produced the Lie.
3. `weiland_arc.want` — **min 20 chars**. What the character pursues
   on the surface.
4. `weiland_arc.need` — **min 20 chars**. What the character actually
   requires (usually contradicts the Want).
5. `weiland_arc.arc_type` — one of:
   - `positive_change` — Lie → Truth, growth.
   - `flat` — already knows the Truth, drags others to it.
   - `negative` — bleak parent category. Use a variant when the shape
     is clearer.
   - `disillusionment` — Lie → bleaker Truth.
   - `corruption` — glimpses Truth, consciously rejects it for Lie.
   - `fall` — never sees Truth, buried deeper in Lie.
6. `weiland_arc.arc_summary` — optional descriptive sentence
   complementing the strict enum.
7. `weiland_arc.arc_phase_map` — chapter-level map from phase name to
   chapter reference. Vocabulary depends on `arc_type`:

   - `positive_change` / `flat`: `lie_established`, `lie_reinforced`,
     `lie_challenged`, `moment_of_truth`, `new_truth_demonstrated`,
     `arc_resolved`.
   - `corruption` / `fall`: `lie_established`, `lie_reinforced`,
     `lie_deepened`, `point_of_no_return`, `lie_acted_upon`,
     `lie_consequence`, `arc_resolved_tragic`.
   - `disillusionment`: `lie_established`, `lie_reinforced`,
     `lie_challenged`, `truth_glimpsed`, `bleaker_truth_accepted`,
     `arc_resolved_bleak`.
   - `negative` (static villain): `lie_established`, `lie_reinforced`,
     `lie_tested`, `lie_unchanged`.

   The character-forge validator cross-checks `arc_phase_map` keys
   against the vocabulary. Use `validate_arc_coverage(cast,
   target_chapters)` to catch under-mapped arcs (warnings, not
   errors).

### Step 4 — voice_notes (deprecated; prefer voice-discovery)

Pre-Phase-5 seeds may carry per-character voice guidance under
`voice_notes`. New seeds should put this content under
`voice_definition.character_voices` (voice-discovery surface).

### Step 5 — referenced_characters (optional)

Characters who appear in scene cards but are not in the ensemble:

```json
{ "name": "Captain Maren", "role": "ship's captain", "initial_location": "bridge" }
```

This prevents `compliance_validator` from flagging "unknown
character" warnings.

### Step 6 — relationship_arcs (optional)

For relationships whose evolution is load-bearing (not every dyad):

```json
{
  "dyad": "Kael/Aria",
  "arc_type": "deepening",
  "arc_summary": "...",
  "ghost": "...", "lie": "...", "want": "...", "need": "...",
  "arc_phase_map": { "initial_state": "1", "first_strain": "8", ... },
  "payoff_chapter": 24
}
```

`arc_type` enum: `deepening`, `rupturing`, `reconciling`,
`transactional`, `static`.

## Persisting

```python
from workflows.character_forge.api import CharacterForge

cf = CharacterForge(paths)
artifact = CharacterForge.envelope(cast, relationship_arcs=arcs)
cf.write(artifact)
# Or incrementally:
cf.add_character(new_char)
```

## Importers

- `legacy_seed.py` — extract `ensemble_cast` from `concept_seed.json`.
- `plain_markdown.py` — parse a hand-written markdown file. Each
  `## Character: <Name>` section produces one cast entry. See
  `importers/README.md`.
- `notion_export.py`, `world_anvil.py` — deferred to a follow-up
  phase per the Phase 4 scope decision.

## Hand-off

After cast validates, the next natural surface is **outline-planner**
(`/outline-planner`) — the chapter outline references characters and
their arc_phase_maps.
