# AGENTS.md — Codex orientation for the AI Writers' Room

This file is the entry point for Codex (and any other CLI agent that
reads `AGENTS.md`). It orients you to the project and points at the
authoritative documents. **Read `CLAUDE.md` after this file** — it
contains the full project guide and applies to every agent here, not
just Claude Code.

## What this project is

A multi-agent fiction generation system. Humans plan a novel through a
**workflow kit** (six per-surface skills that produce
`workflows/*.json`); `scripts/compile_bundle.py` merges those into a
`concept_seed.json` + `scene_cards/`; then the autonomous pipeline
drafts, line-edits, and saves each scene in a single lean forward pass.

## The two-tier model

The user does the **creative tier** (idea-session, taste calls,
non-negotiables). The agent (you, or Claude Code) does the **structural
tier** (fleshing out the six surfaces, validating, compiling, drafting).
Match your behavior to that split: when the user is in idea-session,
listen and capture — don't pre-decide structure. When the user hands off,
make decisive structural moves.

## Running an idea session in Codex

The idea-session-capture surface is **portable** — it runs identically
in Claude Code and Codex. The conversation contract is at:

- `workflows/idea_session_capture/SKILL.md` — read this first; it tells
  you the four-pass conversation ladder and the capture rules.
- `workflows/_shared/SKILL_preamble.md` — your role and the surface
  protocol.

State mutation goes through the headless api, not hand-edited JSON.
Each call validates against `schema.json`. Required keyword arguments
are explicit — `add_decision` takes `surface`/`topic`/`decision`,
`add_open_question` takes `surface`/`question`, etc.

```python
from workflows.idea_session_capture import IdeaSessionCapture

capture = IdeaSessionCapture(title="Working Title", franchise="My World")
capture.init_workspace()                     # scaffold workflows/idea_session/
capture.set_north_star(
    one_sentence_pitch="...",
    reader_promise="...",
    emotional_core="...",
)
capture.add_decision(
    surface="voice", topic="POV", decision="...", confidence="settled",
)
capture.add_open_question(
    surface="characters", question="...", why_it_matters="...",
)
capture.update_handoff(
    "characters",
    status="seeded",
    settled_inputs=[...],
    questions_to_resolve=[...],
)
capture.expand_to_surface_drafts()           # pre-seed the six surfaces
```

`expand_to_surface_drafts` writes **schema-valid skeletons** for each
of `universe.json`, `canon.json`, `voice.json`, `characters.json`, and
`outline.json` (plus a `scene_cards/_intent.md` brief). Each skeleton
passes its surface validator on write — required fields land with
`<EDIT_ME ...>` placeholders satisfying schema constraints. The
downstream surface session reads the skeleton and replaces those
placeholders with real content.

CLI equivalents (when you'd rather shell out):

```bash
python scripts/idea_session_capture.py init   --title "..." --franchise "..."
python scripts/idea_session_capture.py status --title "..." --franchise "..."
python scripts/idea_session_capture.py expand --title "..." --franchise "..."
```

## The six downstream surfaces

After idea-session, the six structural surfaces deepen each artifact.
Each lives at `workflows/<surface>/SKILL.md` (the conversation contract)
and `workflows/<surface>/api.py` (the headless surface). Codex can read
the SKILL.md and call the api directly.

| Order | Surface              | SKILL                                          | Produces                        |
|-------|----------------------|------------------------------------------------|----------------------------------|
| 1     | universe-builder     | `workflows/universe_builder/SKILL.md`          | `workflows/universe.json`        |
| 2     | canon-drafter        | `workflows/canon_drafter/SKILL.md`             | `workflows/canon.json`           |
| 3     | voice-discovery      | `workflows/voice_discovery/SKILL.md`           | `workflows/voice.json`           |
| 4     | character-forge      | `workflows/character_forge/SKILL.md`           | `workflows/characters.json`      |
| 5     | outline-planner      | `workflows/outline_planner/SKILL.md`           | `workflows/outline.json`         |
| 6     | scene-card-authoring | `workflows/scene_card_authoring/SKILL.md`      | `workflows/scene_cards/*.json`   |

Then `scripts/compile_bundle.py` merges them into `concept_seed.json`.

## Structural framework (load-bearing)

Two named frameworks govern the structural tier. **Honor them.**

- **Brooks Story Engineering** — the outline-planner produces a four-part
  beat map (setup, response, attack, resolution) with explicit
  inciting incident, first plot point, midpoint, second plot point,
  climax. Every scene card carries a `structural_phase` from the same
  enum.
- **K. M. Weiland's character arcs** — every main character carries
  `lie_believed`, `ghost`, `want`, `need`, `arc_type` (positive change /
  flat / negative change / disillusionment / corruption), and
  `arc_phase_map` keyed by chapter or scene id. Scene cards may declare
  `pov_arc_phase` (the current phase for the POV character) and
  `arc_phase_transition` (when this scene flips the phase).

The drafter sees both frameworks at runtime. Don't write outline or
character artifacts that ignore them.

## Less is more — variable scene counts

A chapter has **as many or as few scenes as the dramatic need calls for.**
A chapter with one load-bearing scene is healthier than a chapter padded
with three scenes that share one turning point.

Only split a chapter when each resulting scene carries its own:

- distinct turning point (trigger / shift / cost)
- distinct mission for the POV character
- distinct emotional arc (start / shift / end)

If two candidate scenes share a turning point, fold them into one. The
schema does not enforce a minimum scene count per chapter; do not invent
one.

## Conventions

- Always route I/O through `src.project_paths.ProjectPaths`. Don't
  hand-construct paths under `data/` or `output/`.
- Don't mutate `workflows/<surface>.json` by hand — call the surface's
  api. Validation is enforced at write time.
- Never raise `runtime.*` flags on shipping books (Ruusan, Betrayal)
  without a passing per-book parity test. The guard tests at
  `tests/test_runtime_flags.py` block accidental flips.
- Don't add backwards-compat shims unless a concrete external caller
  would break. The repo has been pruned and we don't reintroduce the
  cruft.

## When in doubt

Read `CLAUDE.md` — it has the full pipeline contract, the runtime-flag
table, the agent catalog, and the testing surface. Anything stated
there governs every agent, including you.
