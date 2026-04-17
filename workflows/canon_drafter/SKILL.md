# canon-drafter — SKILL

> Read first: `workflows/_shared/SKILL_preamble.md` (shared role + protocol).

## Surface in one sentence

Author the canon constraints, canon profile, force/magic mechanics, and
canonical-terminology registry that govern what `canon_expert` flags,
what the drafter respects, and how franchise-specific terms are used
consistently throughout the book.

## Workshop steps owned

The canon portion of **Step 1** plus **Step 9** (terminology registry).

## Authoring sequence

### Step 1 — canon constraints (HARD VALIDATION GATE)

Required by the schema:

1. `canon_constraints.continuity` — which continuity / canon tier
   ("Star Wars Legends EU", "Tolkien Middle-earth", "Original world").
2. `canon_constraints.canon_preserved` — array of strings. What's
   load-bearing to honor (philosophies, established events, magic
   rules). Don't pad — only list what an editor would call a violation
   if broken.
3. `canon_constraints.style_constraints` — array of strings. Voice
   rules at the canon level ("no 21st-century idioms", "no real-world
   brand names").
4. Optional: `canon_constraints.divergence_point` for AU work.
5. Optional: `canon_constraints.canon_overridden` — array. Things this
   project deliberately departs from.

### Step 2 — canon profile (drives canon_expert)

Optional but strongly recommended. The canon_profile is the agent
specialization data — every franchise-specific rule the canon_expert
applies comes from here.

1. `canon_profile.franchise` — the franchise/world.
2. `canon_profile.continuity` — which canon tier.
3. `canon_profile.continuity_description` — what counts as valid
   source material.
4. `canon_profile.era_description` — when within the franchise
   timeline; key context about the state of the world.
5. `canon_profile.narrative_register` — expected prose tone.
6. `canon_profile.cross_continuity_violations` — terms / characters /
   concepts from OTHER continuities that should be flagged
   ("midi-chlorians" in a Legends-only project).
7. `canon_profile.anachronistic_terms` — dict mapping real-world terms
   to in-universe replacements (`{"galaxy": ["the Galaxy"]}`).
8. `canon_profile.meta_reference_rules` — out-of-universe references
   forbidden in prose ("Wookieepedia tags", "fan terminology").
9. `canon_profile.franchise_terminology_notes` — additional
   franchise-specific voice or terminology guidance.

For a fast start, copy from a template:

```python
from workflows.canon_drafter.api import CanonDrafter
artifact = CanonDrafter.apply_template("fanfic_elseworlds")
# templates: fanfic_elseworlds, fanfic_compliant, original_deep,
# original_light, realistic
```

### Step 3 — force/magic mechanics (when applicable)

Skip for low-fantasy or contemporary realism.

1. `force_mechanics.primary_rule` — the foundational rule of the
   magic/Force system in one sentence.
2. `force_mechanics.implications` — array of strings. Logical
   consequences ("corruption is irreversible", "balance is a
   falsehood").
3. `force_mechanics.canon_grounding` — which sources you draw the
   mechanics from.

### Step 9 — terminology registry

For each franchise-specific term, place name, faction, organization,
artifact, technology, magic system element, etc. that appears (or will
appear) in prose:

```json
{
  "term": "Ashla",
  "definition": "Pre-Republic Sith term for the light-side current of the Force.",
  "category": "cultural_term",
  "first_appearance": 3,
  "aliases": ["Light"],
  "usage_notes": "Use only in dialogue between Sith characters."
}
```

Required per entry: `definition` AND `category` (enum:
`character_name`, `place_name`, `faction`, `organization`,
`artifact`, `concept`, `cultural_term`, `species`, `title`,
`title_rank`, `technology`, `magic_system`, `other`). Either `term`
or `canonical_form` must be set. Use `add_term()` to append:

```python
cd = CanonDrafter(paths)
cd.add_term({"term": "Ashla", "definition": "...", "category": "cultural_term"})
```

## Persisting

```python
from workflows.canon_drafter.api import CanonDrafter
cd = CanonDrafter(paths)
cd.write(artifact)  # validates and writes workflows/canon.json
```

## Importers

- `legacy_seed.py` — extract from `concept_seed.json`.
- `plain_markdown.py` — parse a hand-written markdown file. Each
  `### Term: <name>` subsection becomes one terminology entry. See
  `importers/README.md`.

## Hand-off

When this surface validates, recommend the human move on to
**voice-discovery** (`/voice-discovery`) and **character-forge**
(`/character-forge`).
