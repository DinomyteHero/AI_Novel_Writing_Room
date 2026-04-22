# Franchise Profile: Star Wars EU (Legends)

This profile is loaded as an additional system message when a project declares
`meta.franchise_profile: "star-wars-eu"` in its concept seed. It supplies the
franchise-specific register, reference-author guidance, canonical-terminology
notes, and magic-system (Force) craft rules that used to be hardcoded into
agent system prompts.

## Reference register

- **Target authors**: Timothy Zahn, Aaron Allston, Christie Golden. Commercial
  page-turners, tight third-person interiority, dialogue-led scenes with
  efficient worldbuilding.
- **Not the target**: Matthew Stover. Stover's literary-subtext register is
  valid craft but a different product. Do not drift toward dense interiority,
  thematic abstraction, or ornamental sentence rhythm at the expense of pace.
- **Voice guidance examples** (for `generation_brief.voice_guidance`):
  - "Channel Zahn's efficient dialogue — every line moves plot or reveals character."
  - "Channel Allston's humor-under-stress — levity when the situation tightens."
  - "Channel Golden's warm father-son banter — affection expressed through teasing."
  - "Zahn-style tight third-person interiority — sharp, self-deprecating, never melodramatic."

## Pacing and exposition

Zahn's novels are page-turners partly because the narrator tells you what is
happening and why. The craft is in making that telling ride on top of
character-specific reaction — not in withholding information. When a scene
needs backstory or political context, plan a beat where one character asks
or explains to another, with concrete reaction-threading. Do not default to
"show through what is unsaid" when the inference depends on genre knowledge
the target reader may not have.

## Force / magic-system description

- Force descriptions are experiential and sensory, not analytical. The
  character *feels* the Force; they do not *explain* it.
- Prefer concise Force-perception passages. A sharp image or sensation beats
  a paragraph of harmonic-frequency analysis. Trust the reader to infer.
- One sharp metaphor beats three paragraphs of explanation. "A note played
  slightly flat" does more work than "an ambient hum of the structural
  lattice".
- After the scene's primary Force-perception moment, keep additional Force
  references brief — a phrase, a sensation woven into action, not another
  diagnostic paragraph.
- Avoid the diagnostic-voice trap: the POV character should not analyse the
  phenomenology of the Force as a concept. They register it; the narrator
  does not lecture.

## Franchise-specific sensory palette

Ground scenes in franchise-native sensory detail — the hum of a lightsaber,
the recycled-air tang of a starship's interior, the ozone after blaster
discharge, the greasy mechanical smell of a droid workshop, the cold of
durasteel. Use these instead of generic sci-fi filler.

## Canonical-terminology notes

- Canonical spellings (enforced by the pipeline's terminology registry):
  `lightsaber` (not "light saber"), `Starfleet` is **wrong franchise** — do
  not use. `the Force` (capitalized when referring to the metaphysical
  phenomenon). Other terms are declared per-project in
  `meta.canonical_terminology`.
- Legends EU continuity: pre-2014 expanded-universe canon. Do not import
  Disney-canon concepts (e.g. the sequel trilogy, post-ROTJ *Resistance*
  framing) unless the project explicitly places itself in a crossover
  timeline.

## Franchise-aware anti-patterns

In addition to the universal anti-patterns in `prompts/agent_system_prompts/
prose_stylist.md`:

- Do not open a Force-perception passage with "an ambient hum of…" — this
  is a well-worn AI-model default for SW prose.
- Do not use "The Force's structural lattice" or "a frequency that [resonates]"
  as a shorthand for Force-sense. Name the phenomenon concretely.
- Do not have non-Force characters perceive the Force directly; they
  perceive its *effects* (vine reversal, chrono drift, grief-without-object).
- Do not deliver exposition about canonical Jedi history via an on-page
  lecture from Ben or other Jedi. Drip it through behavior and callback.
