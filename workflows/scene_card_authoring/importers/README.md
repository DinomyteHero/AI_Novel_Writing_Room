# scene-card-authoring — plain_markdown importer

```markdown
# Scene Cards

## Chapter 1 Scene 1
chapter_number: 1
scene_number: 1
pov_character: Kael
structural_phase: setup
scene_type: action
mission: Reach the Council chamber before the deployment vote.
why_now: The vote happens at dawn.
conflict: A Sith spy in the corridors.
conflict_type: external
turning_point: Kael chooses to alert the Council, betraying his cover.
setting: Coruscant Jedi Temple, pre-dawn.
emotional_trajectory: dread -> grim resolve

## Chapter 1 Scene 2
chapter_number: 1
scene_number: 2
pov_character: Aria
structural_phase: setup
mission: ...
why_now: ...
conflict: ...
turning_point: ...
```

Each `## Chapter N Scene M` (or `## chapter_N_scene_M_anything`) section
produces one scene card. Required fields per card: `chapter_number`,
`scene_number`, `pov_character`. The bundle compiler runs each card
through `workflows/_shared/scene_card_translator` before validating
against `schemas/scene_card.json`, so workshop fields (`scene_goal`,
`scene_conflict`, `location`) and canonical fields (`mission`,
`conflict`, `setting`) are both accepted.
