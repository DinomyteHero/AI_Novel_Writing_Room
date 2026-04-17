# outline-planner — plain_markdown importer

```markdown
# Outline

## Brooks Alignment
part_1_setup: Establish the world and Kael's lie.
inciting_incident: The mission to Ruusan is announced.
first_plot_point: Kael volunteers, locking himself in.
midpoint: ...
second_plot_point: ...
part_4_resolution: The Brotherhood is broken; Kael walks away from the Order.

## Chapter 1
chapter_title: The Summons
synopsis: Kael receives the order to deploy.
pov_character: Kael
structural_phase: setup
estimated_word_count: 4500

## Chapter 2
chapter_title: First Blood
synopsis: ...
pov_character: Kael

## Subplots
- SUB_01: Royal politics
  function: secondary_pressure
- SUB_02: Family debt

## Hooks
- HK_01: The strange medallion
  hook_type: hard
  planted_in: 1
  resolved_in: 12
- HK_02: Vex's missing apprentice
  hook_type: soft

## Revelation Schedule
- R_01: Kael's father was Sith
  what: His father's identity
  significance: major
  revealed_in: 18
```

Each `## Chapter N` (or `## Chapter N: Title`) section produces an
outline entry. Subplots/hooks/revelations/promises follow a flat
bullet-and-indent shape; for richer content, hand-author the JSON or
import from a legacy seed.
