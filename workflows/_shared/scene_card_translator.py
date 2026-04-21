"""Translate workshop-format OR canonical-format scene cards into the
``schemas/scene_card.json`` shape.

The translator accepts a mixed shape because concept seeds can arrive in
two forms:

1. **Workshop-compressed** — legacy workshop output with field names
   like ``scene_goal``, ``scene_conflict``, ``location``, one card per
   chapter, minimal detail. Each field gets translated to its canonical
   counterpart (``mission``, ``conflict``, ``setting``).

2. **Canonical-detailed** — per-scene entries that already carry the
   ``schemas/scene_card.json`` field names with full hand-authored
   content (``mission``, ``turning_point``, ``opening_hook``,
   ``closing_hook``, ``action_beats``, ``stakes``, ``sensory_details``
   etc.). These pass through unchanged except for structural_phase
   override application.

The translator uses canonical-first / workshop-fallback merging: every
canonical field is read directly; if absent, its workshop counterpart is
substituted. Seeds can mix the two forms card-by-card.

Structural phase precedence (highest to lowest):
    1. Caller-supplied ``structural_overrides`` keyed by chapter_number.
    2. Canonical ``structural_phase`` already on the seed card.
    3. Uppercase markers in ``scene_goal`` (e.g. 'FIRST PLOT POINT').
    4. Arc-phase prefix in ``arc_phase`` (e.g. 'Setup: establish…').
    5. Fallback to 'setup'.

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
    """Return the canonical structural_phase for a scene card.

    Precedence:
        1. Override for this chapter_number, if provided.
        2. Canonical ``structural_phase`` already on the card.
        3. Uppercase marker in scene_goal (FIRST PLOT POINT, etc.).
        4. Arc-phase prefix (Setup, Response, Midpoint, …).
        5. Fallback: 'setup'.
    """
    overrides = _coerce_override_keys(structural_overrides)
    chapter = card.get("chapter_number")
    if chapter in overrides:
        return overrides[chapter]
    existing = card.get("structural_phase")
    if existing:
        return existing
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
    """Translate a scene card (workshop-format OR canonical) to the
    ``schemas/scene_card.json`` shape.

    Canonical fields win over workshop fields: ``mission`` beats
    ``scene_goal``, ``conflict`` beats ``scene_conflict``, ``setting``
    beats ``location``, ``target_word_count`` beats
    ``estimated_word_count``, ``active_subplots`` beats
    ``subplot_references``, ``hook_actions`` beats ``hook_references``,
    ``revelations`` beats ``revelation_references``, ``pov_arc_phase``
    beats ``arc_phase``. This lets a seed ship per-scene canonical cards
    and have them pass through essentially unchanged.

    Defaults are intentionally conservative and only apply when neither
    canonical nor workshop input is present:
        - conflict_type defaults to 'internal' (broadest fit for
          uncategorised scenes).
        - target_word_count defaults to 3500 (mid-range commercial).

    Optional canonical-only fields (``stakes``, ``action_beats``,
    ``scene_role``, ``dialogue_expectation``, ``arc_phase_transition``)
    are passed through when present and omitted otherwise — they have no
    workshop equivalent.

    ``scene_type`` is passed through only when a valid enum value
    ('action' or 'sequel') is supplied; otherwise it is omitted so
    dialogue_expectation.py can derive a safe default.
    """
    chapter = seed_card["chapter_number"]
    scene = seed_card.get("scene_number", 1)

    # Helper: prefer canonical key, fall back to workshop key, else default.
    def pick(canonical_key: str, workshop_key: str | None = None, default=""):
        if canonical_key in seed_card and seed_card[canonical_key] not in (None, ""):
            return seed_card[canonical_key]
        if workshop_key and workshop_key in seed_card and seed_card[workshop_key] not in (None, ""):
            return seed_card[workshop_key]
        return default

    def pick_list(canonical_key: str, workshop_key: str | None = None):
        if canonical_key in seed_card and seed_card[canonical_key]:
            return seed_card[canonical_key]
        if workshop_key and workshop_key in seed_card and seed_card[workshop_key]:
            return seed_card[workshop_key]
        return []

    card: dict = {}

    # Build in natural reading order. Required identifiers first,
    # then structural phase, optional scene_type/scene_role, then the
    # canonical body fields. Optional fields appear at their natural
    # position rather than appended, so diffs against hand-authored
    # cards stay order-stable.
    card["chapter_number"] = chapter
    card["scene_number"] = scene
    card["structural_phase"] = derive_structural_phase(
        seed_card, structural_overrides
    )

    scene_type = seed_card.get("scene_type")
    if scene_type in ("action", "sequel"):
        card["scene_type"] = scene_type

    if "scene_role" in seed_card:
        card["scene_role"] = seed_card["scene_role"]

    card["pov_character"] = seed_card.get("pov_character", "")
    card["mission"] = pick("mission", "scene_goal")
    card["why_now"] = seed_card.get("why_now", "")
    card["conflict"] = pick("conflict", "scene_conflict")
    card["conflict_type"] = seed_card.get("conflict_type", default_conflict_type)
    card["turning_point"] = seed_card.get("turning_point", "")
    card["opening_hook"] = seed_card.get("opening_hook", "")
    card["closing_hook"] = seed_card.get("closing_hook", "")
    card["emotional_trajectory"] = seed_card.get("emotional_trajectory", "")

    if "stakes" in seed_card:
        card["stakes"] = seed_card["stakes"]

    card["characters_present"] = seed_card.get("characters_present", [])

    if "dialogue_expectation" in seed_card:
        card["dialogue_expectation"] = seed_card["dialogue_expectation"]

    card["setting"] = pick("setting", "location")
    card["sensory_details"] = seed_card.get("sensory_details", "")
    card["canon_elements_needed"] = seed_card.get("canon_elements_needed", [])
    card["target_word_count"] = pick(
        "target_word_count", "estimated_word_count", default_target_word_count
    )

    if "action_beats" in seed_card:
        card["action_beats"] = seed_card["action_beats"]

    card["active_subplots"] = pick_list("active_subplots", "subplot_references")
    card["plot_threads_advanced"] = seed_card.get("plot_threads_advanced", [])
    card["promises_planted"] = seed_card.get("promises_planted", [])
    card["promises_paid"] = seed_card.get("promises_paid", [])
    card["hook_actions"] = pick_list("hook_actions", "hook_references")
    card["revelations"] = pick_list("revelations", "revelation_references")
    card["pov_arc_phase"] = pick("pov_arc_phase", "arc_phase")

    # Scene-level voice permissions are authoring metadata, not generated
    # defaults. Preserve both the legacy fields and the additive generic
    # object when present so mixed migration states do not silently lose them.
    for field in (
        "anti_patterns",
        "primary_anchor",
        "supporting_anchor",
        "stover_permitted",
        "scene_voice_permissions",
    ):
        if field in seed_card:
            card[field] = seed_card[field]

    if "arc_phase_transition" in seed_card:
        card["arc_phase_transition"] = seed_card["arc_phase_transition"]

    card["notes"] = (
        seed_card["notes"]
        if seed_card.get("notes")
        else build_scene_card_notes(seed_card)
    )

    return card
