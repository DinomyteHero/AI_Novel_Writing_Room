# The Ruusan Atonement Pre-Draft Planning Checklist

Date: 2026-04-21

## Purpose

This is the pre-draft gate for a fresh Ruusan manuscript run.

The repo is structurally ready to draft, but the planning layer still carries too much overt machinery into the prose path. The main risk is not missing pipeline capability. The main risk is drafting 60+ more scenes from planning artifacts that are already over-explicit about theme, arc, and design intent.

This checklist is intentionally bounded. It is not a call to rebuild the book from scratch. It is a call to revise the planning layer until it stops teaching the drafter to sound like the planning layer.

## Audit Summary

Verified current state:

- `concept_seed.json` exists and is fully populated.
- `scene_cards/` contains 87 committed scene cards.
- `chapter_blueprints/` contains 28 committed chapter blueprints.
- The book already has strong upstream anti-pattern handling in early scene cards, especially Chapters 1-4.
- The planning layer also contains a heavy concentration of internal design-spec shorthand and thesis-language.

The biggest issues are:

1. **Continuity framing is still too visibly AU-facing.**
   The seed opens with `canon_status: "AU"` and a continuity description that foregrounds divergence rather than hidden-history discovery.

2. **Top-level positioning language is over-curated and over-meta.**
   The seed is telling the model too much about comps, audience posture, architecture percentages, and what kind of book this is in abstract terms.

3. **Theme/arc language is too explicit in model-facing planning fields.**
   The seed often explains the argument of the book at an authorial level, even while warning not to do that on-page.

4. **Chapter blueprints are the worst offender.**
   They contain many internal labels and design references (`D2`, `PP26`, `R13`, `B3`, `W1`, etc.) that are useful as author notes but poor direct drafting fuel.

5. **Scene cards are mixed.**
   Early scene cards are strong and practical. Later scene cards increasingly accumulate internal planning shorthand, thesis labels, and explicit anti-slop architecture references that should be translated into scene-playable language.

## Priority Order

1. Revise top-level framing in `concept_seed.json`.
2. Rewrite chapter blueprints into scene-playable chapter guidance.
3. Rewrite scene-card notes where they still sound like design commentary instead of dramatic instruction.
4. Only after that, start a fresh drafting run.

## Revision Targets

### 1. `concept_seed.json`

Priority: highest

Key examples:

- `meta.canon_status` / `canon_status_description`
- `positioning_statement`
- `comp_block.target_audience`
- `theme.thematic_premise`
- `theme.thematic_argument`
- `theme.how_each_arc_tests_theme.*`
- `voice_definition.prose_register`
- `voice_definition.narrative_voice_notes`
- `voice_definition.prior_eu_onboarding`

What to change:

- Keep the story continuity facts, but stop foregrounding the book as "AU" in its descriptive voice.
- If schema or downstream tools require `canon_status: "AU"`, keep the enum but neutralize the surrounding prose.
- Reframe the book as a hidden-history Legends crisis rather than a divergence premise.
- Reduce comp-and-positioning rhetoric that sounds like pitch-deck language.
- Compress or rewrite fields that explain the thematic argument in abstract authorial prose.
- Keep the arc logic, but convert abstract labels into behavioral guidance where possible.
- Keep onboarding instructions, but remove any phrasing that teaches the drafter to assume reader fluency too aggressively.

What to preserve:

- Ben as single-POV anchor.
- The hidden Reformations history.
- The core conflict triangle: Ben / survivors / Veraine.
- The central solution shape: no single living prisoner, shared burden instead.
- The existing close-third discipline and anti-diagnostic-voice rules.

Success criteria:

- A reader of the seed should come away with the story, not the meta-argument about the story.
- The seed should stop sounding like it knows it is a designed artifact.
- Theme should read as story pressure, not as pre-written interpretive copy.

### 2. `chapter_blueprints/`

Priority: highest after seed

Observed issue:

- The blueprints are dense with internal design references and revision-history shorthand.
- They often read like implementation notes for a story system rather than chapter guidance for fiction.
- This is likely the single biggest planning artifact leaking machinery into future drafting.

What to change:

- Rewrite every chapter blueprint's `notes` block into chapter-facing dramatic guidance.
- Remove internal shorthand labels where they are not strictly needed:
  - `D*`
  - `R*`
  - `W*`
  - `B*`
  - `PP*`
  - `H*`
  - `SP*`
- Replace "this beat pays D2/PP26/R13" language with direct dramatic instruction.
- Replace "Lie cracks / thematic pivot / argument lands" language with visible behavior, decision, silence, cost, or change in relationship.
- Trim comp-author references (`Zahn`, `Bujold`, `Stover`, etc.) when they become repeated note-noise instead of high-value register guidance.
- Preserve structural intent, but express it as chapter motion, not architecture commentary.

Rewrite rule:

- Every blueprint should answer:
  - What changes in this chapter?
  - What does Ben want here?
  - What does the chapter reveal, withhold, or reframe?
  - What should the reader feel at the exit?

Instead of:

- which internal spec item is being paid
- which anti-slop bundle this beat belongs to
- which abstract argument this chapter is proving

Priority chapters for first-pass cleanup:

- `chapter_01.json`
- `chapter_05.json`
- `chapter_08.json`
- `chapter_21.json`
- `chapter_25.json`
- `chapter_26.json`
- `chapter_28.json`

Then revise the remaining 21 chapters for consistency.

Success criteria:

- A chapter blueprint should be understandable without prior knowledge of internal revision codes.
- A drafter should be able to use it to write fiction without inheriting design-language tics.
- The chapter should feel like a dramatic unit, not a spec document.

### 3. `scene_cards/`

Priority: medium-high

Observed issue:

- The early cards are often very good: concrete, embodied, anti-thesis, and alert to onboarding.
- Later cards increasingly pick up blueprint/spec language and explicit internal labels.
- The problem is not the existence of constraints; it is the phrasing of constraints as architecture commentary.

What to keep:

- concrete mission / conflict / turning point structure
- anti-diagnostic-voice warnings
- "show through action, not analysis" guidance
- light onboarding cues in Chapters 1-3 and Chapter 28
- lived-galaxy texture reminders

What to revise:

- Notes that explain scene purpose in abstract argument language.
- Notes that rely on internal codes or shorthand.
- Notes that explicitly narrate "this is the lie-breaking beat," "this is the thematic payload," etc.
- Notes that over-describe what the reader is supposed to conclude.
- Notes that repeatedly mention anti-slop architecture or design history rather than scene behavior.

Rewrite rule:

- Convert note language from:
  - "this is the book's thematic payload"
  - "per D2"
  - "per PP26 payoff"
  - "Ben's Lie cracks here"

Into:

- what Ben physically does
- what he avoids saying
- what someone else notices
- what the scene withholds
- what must remain subtext

Priority scene-card batches:

1. Chapters 1-3
   Reason: onboarding and tone gate
2. Chapters 5-8
   Reason: institutional reveal + survivor integration
3. Chapters 21, 25, 26, 28
   Reason: these are the most likely places for overt machinery to show on-page
4. Remaining middle-book cards

Success criteria:

- A scene card should feel like a playable dramatic contract.
- If a note could be mistaken for workshop commentary or architecture spec, rewrite it.
- The note should help the drafter stage the scene, not explain the novel.

## Specific Revision Themes

### A. Continuity-Native Framing

Target problem:

- The current seed still sells the book as a visible AU.

Desired replacement:

- Hidden-history Legends framing.
- "Untold crisis inside known continuity" tone.
- Divergence, where required, should feel like discovered truth rather than alternate-timeline branding.

### B. Onboarding Without Recap Drag

Target problem:

- Some seed-level framing is still too eager to assume a reader already knows every Ben/Jacen/Mara beat.

Desired replacement:

- Preserve Legends density.
- Do not flatten for casual readers.
- But make first-mention handling a rule of generosity rather than a defense of exclusivity.

### C. De-Thesis the Planning Layer

Target problem:

- The planning artifacts know the argument of the book too explicitly.

Desired replacement:

- Preserve the argument privately.
- Phrase the planning so the drafter stages pressure and behavior, not conclusions.

### D. Translate Design Language Into Story Language

Target problem:

- Internal codes and architecture notes are contaminating drafting inputs.

Desired replacement:

- Move any indispensable design shorthand into a separate author-only reference if needed.
- Keep runtime-facing artifacts readable as story instructions.

## Pre-Draft Acceptance Gate

Do not start the fresh full-book draft until these are true:

1. `concept_seed.json` no longer foregrounds AU framing in descriptive prose.
2. Top-level positioning and target-audience text no longer overteach the model how to classify the book.
3. Chapter blueprints have been rewritten to remove most internal code labels and implementation-history commentary.
4. High-risk scene cards (Ch 1-3, 5-8, 21, 25, 26, 28) have been translated into direct dramatic instructions.
5. A strongest-available Ch 1-8 reading draft has been assembled and used as a sanity check against the revised planning language.

## Fast Validation Pass

Before drafting, run these checks manually:

- Search for `canon_status_description` and confirm the descriptive framing is continuity-native.
- Search the seed, blueprints, and scene cards for internal code labels and remove or quarantine them where they are directly model-facing.
- Search for overt thesis-language:
  - `institutional lie`
  - `different path`
  - `thematic`
  - `Lie`
  - `argument`
- Review the opening three chapters and the final three chapters for onboarding clarity and callback subtlety.

## Recommended Working Method

1. Revise the seed first.
2. Revise blueprints second.
3. Revise scene cards third.
4. Reassemble the strongest Ch 1-8 reading draft against the new planning language.
5. Then begin a fresh named drafting run.

## Non-Goals

This checklist does **not** require:

- changing the premise
- changing the protagonist
- changing the structural arc
- inventing a new climax
- deleting the survivor cohort
- abandoning the Weave / wound / seal framework

This is a planning-language correction pass, not a story replacement pass.
