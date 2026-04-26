# idea-session-capture - SKILL

## Purpose

Run the first author-led planning conversation for a new book, then preserve the results as a capture packet and handoff notes for the six workflow-kit surfaces.

This surface is intentionally upstream of `compile_bundle.py`. It does not produce `concept_seed.json` directly. Its job is to make sure the author's taste, intent, questions, and early decisions do not disappear before deeper planning begins.

## Conversation Shape

Move through four passes. Do not force final answers too early.

1. **Spark** - find the initial image, dilemma, relationship, setting pressure, or "what if" that makes the book worth writing.
2. **Foundation** - settle franchise/universe, canon status, era, tone, premise, conflict, theme, target shape, and reader promise.
3. **Deepening** - push character wounds, contradictions, moral cost, setting rules, genre expectations, and voice.
4. **Production handoff** - decide what is settled enough to hand to `universe`, `canon`, `voice`, `characters`, `outline`, and `scene_cards`.

## Capture Rules

- Separate **settled decisions** from **open questions**.
- Preserve the author's wording for emotional intent and non-negotiables.
- Mark confidence as `open`, `tentative`, or `settled`.
- Keep surface-specific notes in the matching handoff file.
- Do not invent canon, cast, or plot facts just to fill blanks. Put unresolved items in open questions.

## Files

Use:

```bash
python scripts/idea_session_capture.py init \
  --title "Working Title" \
  --franchise "Franchise Or Original Universe"
```

Useful relationship flags:

- `--project-scope standalone|planned_series|continuation|spinoff|shared_universe_entry|alternate_universe|anthology_entry`
- `--canon-status canon_compliant|AU|original`
- `--series-id <id>` and `--book-number <n>`
- `--cosmology-id <id>` for shared-universe / meta-cosmology work
- `--source-franchise <name>` and `--source-work <name>` for spinoffs or adaptations
- `--parent-project <title>` for direct continuations or spinoffs
- `--branch-point <description>` for AU divergence
- `--base-source <description>` for multiple universes drawing from the same root source

The command creates:

- `workflows/idea_session/capture.json`
- `workflows/idea_session/session.md`
- `workflows/idea_session/surface_handoffs/*.md`

## Handoff

When the initial session feels ready, use the handoff notes to author the normal workflow-kit surfaces in this order:

1. `universe-builder`
2. `canon-drafter`
3. `voice-discovery`
4. `character-forge`
5. `outline-planner`
6. `scene-card-authoring`

Then run:

```bash
python scripts/compile_bundle.py --franchise <slug> --book <slug>
```
