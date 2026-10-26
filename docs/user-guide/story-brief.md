# Story Brief

The Story Brief is the author-owned planning model between the idea-session
chat and the six structural surfaces. It stores **claims**, not a mutable
character blob: every fact carries an origin, confidence, status, and optional
source quote. Character, location, theme, plot, and voice sheets are
projections of the same file.

## The eight writer decisions

The writer is not asked to fill six forms. They make eight decisions; the
system projects them into character sheets, locations, plot, theme, and the
surface handoffs.

| Decision | Question |
|---|---|
| Promise | What experience is the reader buying? |
| Engine | Who wants what, why now, and what stands in the way? |
| Arc | What do they believe that is wrong, and what changes? |
| Pressure | What does the world forbid or make expensive? |
| People | Who matters, what do they want, and what can't be said? |
| Voice | Who tells it, from where, in what register? |
| Argument | What question should the reader sit with at the end? |
| Boundaries | What must this book never do? |

## Files

The idea-session workspace holds:

- `capture.json` — conversation state (north star, decisions, questions,
  handoffs).
- `story_brief.json` — canonical claim ledger and open questions.
- `sheets/characters/*.md` — reviewable character sheets.
- `sheets/locations/*.md` — reviewable location sheets.
- `sheets/themes/*.md` — reviewable theme sheets.
- `sheets/plot.md` — plot spine and open beats.
- `sheets/world.md` — world rule, cost, factions, and terminology.
- `sheets/review.md` — one-page coverage + gap + proposed-claim queue.

`story_brief.json` is the source of truth for the plan. Sheets can be edited
through the claim API, but regenerating them from confirmed claims never loses
the underlying decisions.

## Claim model

Each claim has:

- `entity_type` — `intent`, `character`, `location`, `theme`, `plot`,
  `world`, `voice`, `relationship`.
- `entity_id` — e.g. `mara`; `book` for intent/voice, `main` for plot/theme,
  `world` for world rules.
- `field` — e.g. `want`, `need`, `lie_believed`, `function`, `question`,
  `premise`, `pov`.
- `value` — string, list, or object.
- `origin` — `author`, `inferred`, `delegated`, or `import`.
- `confidence` — `explicit`, `inferred`, or `uncertain`.
- `status` — `proposed`, `confirmed`, `rejected`, or `superseded`.
- `impact` — `blocking`, `strong`, or `texture`.
- `source_quote` — optional evidence from the conversation.

A new confirmed claim supersedes the previous confirmed value for the same
entity/field. Old claims remain in the ledger as `superseded`, so the history
is auditable.

## Gap policy

The planner ranks gaps by downstream impact, uncertainty, and whether they
block drafting.

| Gap type | Action |
|---|---|
| Blocking and high-impact (protagonist lie, ending change, central rule) | `ask` — or propose 2–3 concrete options with consequences |
| Important but inferable | `propose` — mark `assumed`; confirm in review |
| Texture (names, taverns, minor lore) | `scaffold` — generate, mark `delegated`/`assumed`, batch-review |
| Intentionally mysterious | leave open as a deliberate mystery |

The model should fill gaps **at the point of use**, not all at once. A filled
value is a proposal unless the author explicitly delegates it. “Surprise me”
creates a `delegated` claim; it does not become an authorial decision.

## Commands

Initialize a capture and brief:

```bash
python scripts/story_brief.py init --title "My Novel" --franchise "Original"
```

See coverage and the highest-leverage gaps:

```bash
python scripts/story_brief.py status --title "My Novel" --franchise "Original"
python scripts/story_brief.py gaps   --title "My Novel" --franchise "Original"
```

Add an author-owned claim:

```bash
python scripts/story_brief.py claim add \
  --title "My Novel" --franchise "Original" \
  --type character --id mara --field want \
  --value "To get her daughter out of the country."
```

Add an inferred claim, then confirm or reject it:

```bash
python scripts/story_brief.py claim add \
  --title "My Novel" --franchise "Original" \
  --type character --id mara --field lie_believed \
  --value "That distance keeps people safe." --origin inferred
python scripts/story_brief.py claim confirm <claim_id> \
  --title "My Novel" --franchise "Original"
```

Fill a gap with a delegated option:

```bash
python scripts/story_brief.py fill \
  --title "My Novel" --franchise "Original" \
  --gap character:mara:want --mode delegate
```

Write the review sheets:

```bash
python scripts/story_brief.py sheets --title "My Novel" --franchise "Original"
```

## Chat extraction

The chat agent runs one extraction pass after an author turn and persists the
result as proposals:

```python
added = await capture.infer_claims(turn_text, router)
# every returned claim is origin=inferred, status=proposed
capture.confirm_claim(added[0]["claim_id"])
```

It can also ask the planning model for gap options:

```python
options = await capture.gap_options_with_model("character:mara:lie_believed", router)
claim = await capture.fill_gap_with_model("character:mara:lie_believed", router)
```

`fill_gap_with_model` records the chosen option as `origin=delegated`. Nothing
the extractor returns is confirmed automatically.

## Sheet statuses

- `approved` — no proposed claims and no open gaps for this entity.
- `draft` — at least one proposed claim or open gap.
- Proposed claims and open gaps appear in the sheet’s review sections, not
  silently in the body.

## Migrating legacy data

Books that predate the Story Brief may carry `character_sheets/*.json` and
`voice_profiles.json`. Import them once, then remove the old files:

```bash
python scripts/migrate_legacy_character_data.py \
  --book-dir data/franchises/<franchise>/books/<book> \
  --dry-run
python scripts/migrate_legacy_character_data.py \
  --book-dir data/franchises/<franchise>/books/<book> \
  --remove-legacy
```

The migration is additive: existing claims win unless `--force` is passed.
It imports the idea-session north star, seed premise/theme/voice/arc data, the
legacy character sheets, and the voice-profile fields, then writes the review
sheets. `--remove-legacy` only runs after the brief and sheets are written.

## How it feeds the surfaces

`IdeaSessionCapture.expand_to_surface_drafts()` reads confirmed Story Brief
claims and pre-seeds:

- `characters.json` cast names, roles, wants/needs, and Weiland fields.
- `universe.json` premise, logline, reader promise, and thematic question.
- `voice.json` POV and register.
- `outline.json` Brooks incident, midpoint, climax, and resolution.

Unconfirmed claims stay out of the surface drafts. Run `story_brief.py status`
before expanding; if essential gaps remain, the capture may not be ready.
