"""Translate workshop-format scene cards into the ``schemas/scene_card.json``
shape.

The workshop-authored scene cards embedded in concept_seed.json carry
different field names than the canonical per-file scene card schema
introduced with the pipeline redesign. This module owns the translation
so both the Ruusan installer and any future franchise installer produce
consistent per-file cards.

Structural phase derivation uses three inputs, in order of precedence:
    1. Caller-supplied ``structural_overrides`` keyed by chapter_number.
    2. Uppercase markers in ``scene_goal`` (e.g. 'FIRST PLOT POINT').
    3. Arc-phase prefix in ``arc_phase`` (e.g. 'Setup: establish…').
    4. Fallback to 'setup'.

This module is intentionally pure — no IO, no schema validation — so it
can be reused by the generic install_seed.py, the Ruusan wrapper, and
future workshop-side tooling without coupling any of them to each other.
"""

from __future__ import annotations


UPPERCASE_MARKERS: dict[str, str] = {
    "FIRST PLOT POINT": "first_plot_point",
    "SECOND PLOT POINT": "second_plot_point",
    "MIDPOINT": "midpoint",
}

ARC_PHASE_PREFIX: dict[str, str] = {
    "Setup": "setup",
    "Response": "response",
    "Attack": "attack",
    "Resolution": "resolution",
    "First Plot Point": "first_plot_point",
    "Midpoint": "midpoint",
    "Second Plot Point": "second_plot_point",
}


def _coerce_override_keys(overrides: dict | None) -> dict[int, str]:
    """Allow structural_overrides to use int or str chapter keys.

    Workshop_patch.json (being JSON) must use string keys; in-code callers
    might pass int. Normalize to int.
    """
    if not overrides:
        return {}
    result: dict[int, str] = {}
    for key, value in overrides.items():
        try:
            result[int(key)] = value
        except (TypeError, ValueError):
            # Silently skip malformed keys rather than crashing on a
            # stray string chapter identifier in a patch file.
            continue
    return result


def derive_structural_phase(
    card: dict,
    structural_overrides: dict[int, str] | None = None,
) -> str:
    """Return the canonical structural_phase for a workshop-format card.

    Precedence:
        1. Override for this chapter_number, if provided.
        2. Uppercase marker in scene_goal (FIRST PLOT POINT, etc.).
        3. Arc-phase prefix (Setup, Response, Midpoint, …).
        4. Fallback: 'setup'.
    """
    overrides = _coerce_override_keys(structural_overrides)
    chapter = card.get("chapter_number")
    if chapter in overrides:
        return overrides[chapter]
    scene_goal = card.get("scene_goal", "")
    for marker, phase in UPPERCASE_MARKERS.items():
        if marker in scene_goal:
            return phase
    arc_phase = card.get("arc_phase", "")
    for prefix, phase in ARC_PHASE_PREFIX.items():
        if arc_phase.startswith(prefix):
            return phase
    return "setup"


def build_scene_card_notes(seed_card: dict) -> str:
    """Concatenate ``time``, ``thematic_beat`` and ``scene_outcome``.

    The resulting string feeds the ``notes`` field of the canonical scene
    card. Omits sections that are missing or empty; returns empty string
    when none of the three are present.
    """
    parts: list[str] = []
    if seed_card.get("time"):
        parts.append(f"Time: {seed_card['time']}")
    if seed_card.get("thematic_beat"):
        parts.append(f"Thematic beat: {seed_card['thematic_beat']}")
    if seed_card.get("scene_outcome"):
        parts.append(f"Original scene_outcome: {seed_card['scene_outcome']}")
    return "\n".join(parts)


def translate_scene_card(
    seed_card: dict,
    *,
    structural_overrides: dict[int, str] | None = None,
    default_conflict_type: str = "internal",
    default_target_word_count: int = 3500,
) -> dict:
    """Translate a workshop-format scene card to canonical scene_card.json shape.

    Defaults are intentionally conservative:
        - conflict_type defaults to 'internal' because the canonical
          scene_card schema requires a member of the conflict_type enum
          when present; 'internal' is the broadest fit for pre-authored
          scenes whose conflict type has not been explicitly categorised.
        - target_word_count defaults to 3500 — mid-range for commercial
          novel scenes. Override per-project via canon_profile or
          per-card in the workshop output.

    ``scene_type`` is passed through only when the workshop provided a
    valid enum value ('action' or 'sequel'); otherwise it is omitted so
    dialogue_expectation.py can derive a safe default.
    """
    chapter = seed_card["chapter_number"]
    scene = seed_card.get("scene_number", 1)

    card = {
        "chapter_number": chapter,
        "scene_number": scene,
        "structural_phase": derive_structural_phase(seed_card, structural_overrides),
        "pov_character": seed_card.get("pov_character", ""),
        "mission": seed_card.get("scene_goal", ""),
        "why_now": "",
        "opening_hook": "",
        "conflict": seed_card.get("scene_conflict", ""),
        "conflict_type": default_conflict_type,
        "turning_point": "",
        "closing_hook": "",
        "characters_present": [],
        "setting": seed_card.get("location", ""),
        "sensory_details": "",
        "emotional_trajectory": "",
        "plot_threads_advanced": [],
        "promises_planted": [],
        "promises_paid": [],
        "canon_elements_needed": [],
        "target_word_count": seed_card.get(
            "estimated_word_count", default_target_word_count
        ),
        "notes": build_scene_card_notes(seed_card),
        "active_subplots": seed_card.get("subplot_references", []),
        "hook_actions": seed_card.get("hook_references", []),
        "revelations": seed_card.get("revelation_references", []),
        "pov_arc_phase": seed_card.get("arc_phase", ""),
    }

    scene_type = seed_card.get("scene_type")
    if scene_type in ("action", "sequel"):
        card["scene_type"] = scene_type

    return card
