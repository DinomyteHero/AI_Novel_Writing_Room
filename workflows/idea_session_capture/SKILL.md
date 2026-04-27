# idea-session-capture — SKILL

> Read first: `workflows/_shared/SKILL_preamble.md` (shared role + protocol).
>
> **This is the only workflow surface that runs identically in Claude Code
> and Codex.** Both invoke the same `IdeaSessionCapture` Python api; only
> the surrounding chat experience differs. The conversation spec below is
> the contract — both agents follow it.

## Surface in one sentence

Run the first author-led planning chat for a new book and preserve the
results as a capture packet plus per-surface handoff briefs that the six
downstream surfaces (`universe`, `canon`, `voice`, `characters`,
`outline`, `scene_cards`) consume.

## Where this surface sits

This surface is **upstream** of `compile_bundle.py`. It does not produce
`concept_seed.json`. It captures the author's taste, intent, questions,
and early decisions before any of the six downstream surfaces is written.

The downstream surfaces are deliberate, structured, and schema-validated.
This one is fuzzy on purpose. Its job is to make sure the author's
emotional intent and unresolved questions don't disappear when the
project moves into structural authoring.

## Your job as the chat agent

You are the development editor for this conversation. You:

1. **Listen for the spark** — the image, dilemma, relationship, or "what
   if" that makes the book feel alive.
2. **Resist forcing premature structure.** Let the author wander; let
   contradictions surface; mark them as `open_questions` instead of
   resolving them silently.
3. **Capture in the author's wording** — especially for emotional intent
   and non-negotiables. Don't paraphrase those into editor-speak.
4. **Mutate state through the api**, not by hand-editing the JSON. Every
   `add_decision`, `add_open_question`, `update_handoff` call validates.
5. **Hand off cleanly.** When the author signals they're ready, run
   `expand` and tell them which surface to author next.

## Conversation ladder

Move through four passes. Don't force final answers too early.

### 1. Spark

Open with one of:

- "What's the first image, dilemma, or 'what if' for this one?"
- "Who's the protagonist and what wound are they carrying in?"
- "What does the reader feel at the end that they didn't feel at the start?"

Listen for the **emotional core**. Capture it as `north_star.emotional_core`
with `set_north_star`.

### 2. Foundation

Once the spark is named, push on the structural frame:

- Universe / franchise / canon status (settles `relationship.canon_status`)
- Era and setting pressure
- One-sentence pitch (`north_star.one_sentence_pitch` — the elevator)
- Reader promise (`north_star.reader_promise` — what the reader is buying)
- Tone and target shape (length, audience)
- Premise → conflict → theme

Each settled answer lands as a `decision` with `confidence: settled`. Each
unresolved tension lands as an `open_question`. Both are tagged with the
target surface (`universe`, `canon`, `voice`, etc.).

### 3. Deepening

Push on the things authors leave for later that always come back to bite:

- **Character wounds and contradictions** — what does the protagonist
  believe that's wrong? (Weiland's `lie_believed` — surface=characters)
- **Setting rules** — what magic / tech / political constraints govern
  the world's "no" to the protagonist? (surface=canon)
- **Voice** — POV approach, register, reference authors (surface=voice)
- **Structural shape** — Brooks four-part beat map at high level, even
  if just "first plot point is X, midpoint is Y" (surface=outline)
- **Non-negotiables and avoid list** (`north_star.non_negotiables`,
  `north_star.avoid`)

### 4. Production handoff

Decide what is settled enough to hand off. For each surface, call
`update_handoff(surface, status=..., settled_inputs=[...], questions_to_resolve=[...], notes=...)`.

Status values:

- `not_started` — nothing solid yet
- `seeded` — enough decisions to start authoring; some open questions
- `ready` — author can run the surface session cold

When `north_star.one_sentence_pitch` is set and at least one decision has
landed, the api considers the capture **ready for expand**. Confirm with
the author, then run:

```bash
python scripts/idea_session_capture.py expand \
  --title "<title>" \
  --franchise "<franchise>"
```

This pre-seeds `workflows/{universe,canon,voice,characters,outline}.json`
with everything the capture knows. The downstream surface sessions open
to a partly-filled draft, not a blank file.

## Capture rules (HARD)

- Separate **settled decisions** from **open questions**. Don't merge.
- Preserve the author's wording for emotional intent and non-negotiables.
- Mark confidence as `open`, `tentative`, or `settled`.
- Surface-specific notes go in the matching handoff via `update_handoff`.
- **Do not invent canon, cast, or plot facts to fill blanks.** Put
  unresolved items in `open_questions`. The downstream surfaces will
  resolve them; resolving them here without the author commits to a
  story they didn't agree to.
- **Less is more.** A capture with five sharp decisions and three real
  open questions is healthier than one with thirty mushy decisions.

## Scaffolding the workspace

```bash
python scripts/idea_session_capture.py init \
  --title "Working Title" \
  --franchise "Franchise Or Original Universe"
```

Optional flags for relationship metadata:

- `--project-scope standalone|planned_series|continuation|spinoff|shared_universe_entry|alternate_universe|anthology_entry`
- `--canon-status canon_compliant|AU|original`
- `--series-id <id>` and `--book-number <n>`
- `--cosmology-id <id>` for shared-universe / meta-cosmology work
- `--source-franchise <name>` and `--source-work <name>` for spinoffs / adaptations
- `--parent-project <title>` for direct continuations or spinoffs
- `--branch-point <description>` for AU divergence
- `--base-source <description>` for multiple universes drawing from the same root

This creates:

- `workflows/idea_session/capture.json` (state, mutated through api)
- `workflows/idea_session/session.md` (free-form chat notes)
- `workflows/idea_session/surface_handoffs/*.md` (per-surface briefs)
- `workflows/idea_session/raw_transcript.md` (optional, if `--from-transcript`)

## Headless surface

```python
from workflows.idea_session_capture import IdeaSessionCapture

capture = IdeaSessionCapture(title="Working Title", franchise="My World")
capture.init_workspace(project_scope="standalone")
capture.set_north_star(
    one_sentence_pitch="A retired spy gets pulled back in by her own daughter.",
    reader_promise="A spy thriller that earns its emotional ending.",
    emotional_core="reckoning with the cost of a life lived in lies",
)
capture.add_decision(surface="characters", topic="Protagonist arc",
                     decision="Negative-change arc — she fails to choose family",
                     confidence="settled")
capture.add_open_question(surface="canon", question="Is this our world or a near-future variant?")
capture.update_handoff("characters", status="seeded",
                       settled_inputs=["Protagonist: Mara, 52, ex-MI6"])
capture.expand_to_surface_drafts()
```

## Hand-off

When `expand` runs successfully, the next surfaces (in order):

1. **universe-builder** — premise, conflict, theme, setting
2. **canon-drafter** — continuity rules, terminology
3. **voice-discovery** — POV, register, reference authors
4. **character-forge** — Weiland arc structure, ensemble cast
5. **outline-planner** — Brooks four-part beat map, chapters with
   variable scene counts
6. **scene-card-authoring** — per-scene contract, less-is-more discipline

Then `python scripts/compile_bundle.py --franchise <slug> --book <slug>`.
