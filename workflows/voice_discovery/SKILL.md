# voice-discovery — SKILL

> Read first: `workflows/_shared/SKILL_preamble.md` (shared role + protocol).

## Surface in one sentence

Elicit the project's narrative voice — POV approach, prose register,
reference authors, character voices, anti-slop rules, and structural
anti-patterns — into a single `voice_definition` artifact the drafter
and revision pipeline use as a north star.

## Workshop step owned

**Step 5** — Voice Discovery, in full.

## Authoring sequence

### Step 1 — POV and register (HARD VALIDATION GATE)

Required by the schema:

1. `voice_definition.pov_approach` — single sentence describing the
   narrator's stance ("rotating limited", "single close third with
   occasional deep POV", "epistolary").
2. `voice_definition.prose_register` — single sentence on the prose
   level ("literary with clear-eyed action", "muscular plain style",
   "high-elevated archaic").

Don't advance until both are set. These are what the voice checker and
revision pipeline read first.

### Step 2 — Reference authors (recommended)

For each author whose prose this book emulates, add an entry:

```json
{
  "author": "Ursula K. Le Guin",
  "what_to_emulate": "Patience with silence; precision in metaphor.",
  "what_to_avoid": "Heavy-handed allegory."
}
```

Aim for **3-5** reference authors. More dilutes the signal. The
drafter reads `what_to_emulate` and `what_to_avoid` as voice anchors.

### Step 3 — Anti-slop rules

The voice checker enforces these. Each rule is a single string of the
form "Never use 'X'" or "Avoid Y construction". The default rule set
is augmented from `config/negative_constraints.yaml` automatically by
`VoiceDiscovery.merge_anti_slop_rules`.

Aim for **8-15** rules. Be specific:

- "Never use 'filed away in his mind'"
- "Never use 'didn't trust himself to speak'"
- "No more than two consecutive paragraphs starting with the same word"

### Step 4 — Anti-patterns

Structural patterns to avoid (above the line-level slop):

- "Every chapter opening with weather/environment description"
- "Every chapter ending with a reflective sigh or 'little did they
  know' hook"
- "Characters nodding/smiling/raising eyebrows as default body
  language"
- "Dialogue attribution using anything other than said/asked more
  than 20% of the time"

Defaults are auto-injected by `VoiceDiscovery.build_voice_definition`
when the caller doesn't supply any; you can override with
`anti_patterns=...`.

### Step 5 — Character voices (optional)

Map character names to per-character voice guidance:

```json
"character_voices": {
  "Kael": "clipped, military cadence; never elaborates",
  "Aria": "lyrical, drifts mid-sentence; uses archaic terms"
}
```

This populates `voice_definition.character_voices` and feeds the
character_specialist agent.

### Step 6 — Optional fields

- `voice_definition.force_description_guidelines` — phenomenological
  vs. technical magic prose, when applicable.
- `voice_definition.pacing_feel` — single sentence on cadence
  ("deliberate; quiet preceding bursts").
- `voice_definition.narrative_voice_notes` — free-form prose for
  anything the structured fields don't capture.

## Persisting

```python
from workflows.voice_discovery.api import VoiceDiscovery, write_voice

vd = VoiceDiscovery()
voice_def = vd.build_voice_definition(
    pov_approach="rotating limited",
    prose_register="literary with clear-eyed action",
    reference_authors=[...],
    character_voices={...},
    anti_slop_rules=[...],
    anti_patterns=[...],
)
write_voice(paths, voice_def)  # validates and writes workflows/voice.json
```

`build_voice_definition` auto-merges global anti-slop rules from
`config/negative_constraints.yaml`. You don't need to copy them by hand.

## Importers

- `legacy_seed.py` — extract from `concept_seed.json`.
- `plain_markdown.py` — parse a hand-written markdown file. See
  `importers/README.md`.

## Hand-off

After this surface validates, the next natural surface is
**character-forge** (`/character-forge`) — character voices set here
will be referenced there.
