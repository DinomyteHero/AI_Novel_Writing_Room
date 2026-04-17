# universe-builder — plain_markdown importer

Lowest-common-denominator entry point: hand-write a markdown file and run
`import_from_markdown(path)` to produce a universe-builder artifact dict.

## Expected sections

```markdown
# My Project

## Project
title: The Ruusan Atonement
franchise: Star Wars (Legends EU)
canon_status: AU
era: Old Republic, ~1000 BBY
tone: heroic_with_weight
target_word_count: 100000
target_chapters: 28
pov_structure: rotating limited
project_scope: standalone

## Universe
name: Star Wars (Legends EU)
franchise: Star Wars (Legends EU)
canon_status: AU
commercial_intent: fanfiction_noncommercial

## Premise
what_if: What if the Jedi Order had to choose between annihilating the Sith and breaking their own code?
central_dramatic_question: Can the Jedi survive what they must become to win?
logline: After centuries of war, two Jedi Masters race to end the Sith — and themselves.

## Conflict
type: institutional + personal
identity: Sith Brotherhood of Darkness
motivation: ...minimum 50 chars...
escalation: ...minimum 100 chars...
lock_in_mechanism: Once the Brotherhood gathers at Ruusan, neither side can disengage without...

## Secondary Pressures
- Republic political collapse
- Civilian terror and refugee waves
- Internal Jedi schism over the Code

## Theme
thematic_premise: ...
thematic_argument: ...minimum 100 chars...

## Notes
Free-form prose. Becomes universe_meta.notes.
```

All sections are optional. The importer maps each `key: value` line into
the artifact via the surface schema. Use `legacy_seed.py` instead when
you already have a `concept_seed.json`.
