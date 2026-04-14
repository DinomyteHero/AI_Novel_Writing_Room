"""Resolve a scene's dialogue_expectation: explicit field wins, else derive.

Background: the pipeline previously used `len(characters_present) >= 2` as
its proxy for "this is a dialogue-led scene." That proxy misfires on scenes
where the second listed character is explicitly a background presence
(e.g. ch01 scene 01 lists a sparring partner whose scene-card notes say
"minimal characterization, exists to provide the physical context"). The
bad proxy was hard-wired into prose_stylist.md, plot_architect.md,
scene_emotion.md, and pacing_analyzer, forcing a 40-55% dialogue target
onto isolation scenes.

This module replaces that proxy with a scene-card field
`dialogue_expectation` taking one of three values:
  - dialogue_led  — target 40-55% dialogue, back-and-forth exchange
  - balanced      — no hard dialogue floor, both modes share weight
  - interior      — POV-isolation, interior monologue dominates

Scene cards can set the field explicitly (preferred). When absent, `derive`
infers a safe default from other card fields.
"""

from typing import Literal

DialogueExpectation = Literal["dialogue_led", "balanced", "interior"]

VALID_VALUES: tuple[DialogueExpectation, ...] = ("dialogue_led", "balanced", "interior")


def derive(scene_card: dict) -> DialogueExpectation:
    """Return the scene's dialogue_expectation.

    Order of resolution:
      1. Explicit `dialogue_expectation` field on the scene card (if valid).
      2. Derivation table below (first match wins).

    Derivation table:
      | Condition                                                          | Result         |
      |--------------------------------------------------------------------|----------------|
      | conflict_type == "interpersonal" AND 2+ characters_present         | dialogue_led   |
      | scene_role == "decision" AND 2+ characters_present                 | dialogue_led   |
      | conflict_type == "internal" AND scene_type == "sequel"             | interior       |
      | len(characters_present) <= 1                                       | interior       |
      | default                                                            | balanced       |

    Defaults to "balanced" when the card is empty or fields are missing,
    because balanced has no hard dialogue floor and therefore cannot trigger
    the false-positive behavior the field was introduced to prevent.
    """
    explicit = scene_card.get("dialogue_expectation")
    if explicit in VALID_VALUES:
        return explicit

    conflict_type = scene_card.get("conflict_type")
    scene_role = scene_card.get("scene_role")
    scene_type = scene_card.get("scene_type")
    characters_present = scene_card.get("characters_present") or []
    char_count = len(characters_present)

    if conflict_type == "interpersonal" and char_count >= 2:
        return "dialogue_led"
    if scene_role == "decision" and char_count >= 2:
        return "dialogue_led"
    if conflict_type == "internal" and scene_type == "sequel":
        return "interior"
    if char_count <= 1:
        return "interior"
    return "balanced"


def is_dialogue_led(scene_card: dict) -> bool:
    """Convenience: True if derive() resolves to 'dialogue_led'.

    Use this instead of `len(characters_present) >= 2` in any code path
    that previously gated on the bad proxy.
    """
    return derive(scene_card) == "dialogue_led"
