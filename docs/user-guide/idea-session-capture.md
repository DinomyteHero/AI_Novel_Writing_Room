# Idea Session Capture

Idea Session Capture is the front door for author-led planning. It lets you have a loose, exploratory chat first, then preserve the useful parts as structured notes before the six workflow-kit surfaces are authored.

It does not replace `compile_bundle.py` and it does not generate the final `concept_seed.json` directly. It creates a planning workspace under the book's `workflows/idea_session/` folder.

For the full start-to-finish path, see [New Manuscript Workflow](new-manuscript-workflow.md).

## When To Use It

Use it at the start of a new manuscript when the book is still becoming itself:

- You have a premise, image, character, or setting but not a full outline.
- You want a guided chat before committing to scene cards.
- You want to separate settled author decisions from open questions.
- You want later planning sessions to inherit the same intent.

## Create A Capture Workspace

```bash
python scripts/idea_session_capture.py init \
  --title "Working Title" \
  --franchise "Franchise Or Original Universe"
```

For relationship-heavy projects, add metadata up front:

```bash
python scripts/idea_session_capture.py init \
  --title "Spinoff Title" \
  --franchise "Shared Franchise" \
  --project-scope spinoff \
  --series-id "mainline-series" \
  --book-number 2 \
  --parent-project "Parent Book" \
  --source-franchise "Shared Franchise" \
  --source-work "Original Source"
```

Shared-universe and same-base-source planning can use:

```bash
python scripts/idea_session_capture.py init \
  --title "Parallel Book" \
  --franchise "Second Universe" \
  --project-scope shared_universe_entry \
  --cosmology-id "shared-cosmology" \
  --base-source "same root myth / source continuity"
```

This writes:

```text
data/franchises/<franchise>/books/<book>/workflows/idea_session/
  capture.json
  session.md
  README.md
  surface_handoffs/
    universe.md
    canon.md
    voice.md
    characters.md
    outline.md
    scene_cards.md
```

If you already have a transcript, copy it into the workspace:

```bash
python scripts/idea_session_capture.py init \
  --title "Working Title" \
  --franchise "Franchise Or Original Universe" \
  --from-transcript path/to/transcript.md
```

Use `--force` only when you intentionally want to overwrite an existing capture workspace.

## Check Status

```bash
python scripts/idea_session_capture.py status \
  --title "Working Title" \
  --franchise "Franchise Or Original Universe"
```

The status command reports decision counts, open-question counts, and the readiness of each surface handoff.

## Conversation Ladder

Run the planning chat in four passes:

1. **Spark** - first image, dilemma, relationship, question, or setting pressure.
2. **Foundation** - universe, canon status, era, tone, premise, conflict, theme, target length, reader promise.
3. **Deepening** - character wounds, contradictions, moral cost, setting rules, voice, genre texture.
4. **Production handoff** - settled inputs and unresolved questions for each workflow surface.

The key discipline is not to make everything final in the first pass. The capture packet should preserve both excitement and uncertainty.

## Relationship Cases

The capture packet has first-class fields for:

- Standalone books
- Planned series entries
- Continuations
- Spinoffs from a parent project
- Shared-universe entries linked by `cosmology_id`
- Alternate universes with a `branch_point`
- Different universes that draw from the same `base_source`

## Expand To Surface Drafts

When the capture has a settled north star and at least one decision, run:

```bash
python scripts/idea_session_capture.py expand \
  --title "Working Title" \
  --franchise "Franchise Or Original Universe"
```

This pre-seeds the five JSON workflow-kit surfaces (`universe`, `canon`, `voice`, `characters`, `outline`) and writes a `scene_cards/_intent.md` brief. Each JSON skeleton is **schema-valid on write** — required fields land with `<EDIT_ME ...>` placeholders that satisfy schema constraints (minLength, minItems, enum). The downstream surface session reads the skeleton and replaces those placeholders with real content; the surface api re-validates on write.

Re-running `expand` is idempotent — existing artifacts are skipped unless you pass `--force`.

## How It Connects To The Existing System

The capture workspace feeds the six workflow-kit surfaces:

```text
idea_session
  -> expand_to_surface_drafts (skeletons)
  -> author each surface (replace EDIT_ME with real content)
  -> compile_bundle.py
  -> lean production
```

Once the six surfaces are authored, run:

```bash
python scripts/compile_bundle.py --franchise <slug> --book <slug>
```

Then continue through the production lifecycle: lean drafting, full manuscript review, targeted revision, targeted cleanup, final validation.
