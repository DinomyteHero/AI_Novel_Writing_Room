"""Concept-seed enrichment transforms.

Pure, composable functions that mutate a concept-seed dict in-place. Each
transform owns one slice of the enrichment that used to live as hardcoded
Python literals inside ``scripts/install_ruusan_seed.py``. Extracting them
here means:

1. The generic ``scripts/install_seed.py`` can stage enrichment by calling
   these in a fixed order given a workshop_patch JSON document.
2. The Ruusan wrapper and any future franchise wrapper can feed their own
   data through the same pipeline without duplicating logic.
3. Each transform is unit-testable in isolation (tests/test_seed_transforms.py).

All transforms are no-ops when their input data is ``None`` or empty, so a
partial workshop_patch that omits, say, ``promise_payoff_ledger`` does not
error out — it simply skips that step.

The canonical enum lists below mirror ``schemas/concept_seed.json``:
    - ``meta.tone`` — TONE_ENUM
    - ``meta.canon_status`` — CANON_STATUS_ENUM
    - ``ensemble_cast[].weiland_arc.arc_type`` — ARC_TYPE_ENUM

When a seed's enum field holds a descriptive string that is NOT in the
canonical set, ``normalize_enums`` moves the descriptive string to a
sibling ``*_description`` key and replaces the enum with the caller-
supplied canonical value. This was the original installer behaviour; it
is exposed as opt-in via an explicit kwarg so a non-Ruusan install that
already ships canonical enum values leaves the seed untouched.
"""

from __future__ import annotations

import copy
from typing import Any

TONE_ENUM = {
    "dark_gritty",
    "adventurous_hopeful",
    "political_intrigue",
    "character_study",
    "heroic_with_weight",
}

CANON_STATUS_ENUM = {"canon_compliant", "AU", "original"}

ARC_TYPE_ENUM = {"positive_change", "flat", "negative", "disillusionment"}


# ---------------------------------------------------------------------------
# Enum normalization
# ---------------------------------------------------------------------------


def normalize_enums(
    seed: dict,
    *,
    tone_fallback: str = "heroic_with_weight",
    canon_status_fallback: str = "AU",
    arc_type_map: dict[str, str] | None = None,
) -> None:
    """Coerce descriptive enum values to their canonical enum member.

    Behaviour:
        - ``meta.tone`` — if already empty or already in TONE_ENUM, leave
          untouched. Otherwise move the current value to ``meta.tone_description``
          and set ``meta.tone = tone_fallback``.
        - ``meta.canon_status`` — same pattern with CANON_STATUS_ENUM and
          ``canon_status_fallback``.
        - ``ensemble_cast[].weiland_arc.arc_type`` — if ``arc_type_map`` is
          supplied, every character whose name appears in the map has its
          arc_type forced to the mapped canonical value; the original
          descriptive string (if different) is preserved as ``arc_summary``.
          Characters not in the map are left untouched.

    The whole function is a no-op on seeds that already ship canonical
    enum values, which is what we want for non-Ruusan installs.
    """
    meta = seed.setdefault("meta", {})

    current_tone = meta.get("tone", "")
    if current_tone and current_tone not in TONE_ENUM:
        meta["tone_description"] = current_tone
        meta["tone"] = tone_fallback

    current_canon = meta.get("canon_status", "")
    if current_canon and current_canon not in CANON_STATUS_ENUM:
        meta["canon_status_description"] = current_canon
        meta["canon_status"] = canon_status_fallback

    if arc_type_map:
        for char in seed.get("ensemble_cast", []):
            name = char.get("name")
            if not name or name not in arc_type_map:
                continue
            weiland = char.setdefault("weiland_arc", {})
            descriptive = weiland.get("arc_type", "")
            canonical = arc_type_map[name]
            weiland["arc_type"] = canonical
            if descriptive and descriptive != canonical:
                weiland["arc_summary"] = descriptive


# ---------------------------------------------------------------------------
# Injection helpers
# ---------------------------------------------------------------------------


def apply_voice_definition(seed: dict, voice: dict | None) -> None:
    """Replace seed['voice_definition'] with a deep copy of ``voice``.

    No-op when ``voice`` is falsy. Always deep-copies so mutating the
    installed seed cannot leak back into the caller's workshop_patch dict.
    """
    if not voice:
        return
    seed["voice_definition"] = copy.deepcopy(voice)


def apply_arc_phase_maps(
    seed: dict,
    maps: dict[str, dict[str, Any]] | None,
) -> None:
    """Inject per-character arc_phase_map into ensemble_cast entries.

    ``maps`` is keyed by character name; value is the arc_phase_map dict
    that gets assigned to ``character['weiland_arc']['arc_phase_map']``.
    Characters not in the map are left untouched. No-op when ``maps`` is
    falsy.
    """
    if not maps:
        return
    for char in seed.get("ensemble_cast", []):
        name = char.get("name")
        if name in maps:
            char.setdefault("weiland_arc", {})
            char["weiland_arc"]["arc_phase_map"] = copy.deepcopy(maps[name])


def apply_promise_payoff_ledger(seed: dict, ledger: list | None) -> None:
    """Set seed['promise_payoff_ledger'] to a deep copy of ``ledger``."""
    if not ledger:
        return
    seed["promise_payoff_ledger"] = copy.deepcopy(ledger)


def apply_canon_constraints(seed: dict, constraints: dict | None) -> None:
    """Set seed['canon_constraints'] to a deep copy of ``constraints``."""
    if not constraints:
        return
    seed["canon_constraints"] = copy.deepcopy(constraints)


def apply_workshop_origin(seed: dict, origin: dict | None) -> None:
    """Set seed['extended_metadata']['workshop_origin'] to ``origin``.

    Creates extended_metadata if absent. Does NOT overwrite other keys
    already present under extended_metadata.
    """
    if not origin:
        return
    seed.setdefault("extended_metadata", {})
    seed["extended_metadata"]["workshop_origin"] = copy.deepcopy(origin)


def move_to_extended_metadata(seed: dict, field_names: list[str] | None) -> None:
    """Move top-level seed keys into seed['extended_metadata'].

    For each name in ``field_names`` that exists at the top level of the
    seed, pop it from the top level and set it under extended_metadata.
    Missing keys are silently skipped. Creates extended_metadata if
    absent. No-op when ``field_names`` is empty or None.
    """
    if not field_names:
        return
    ext = seed.setdefault("extended_metadata", {})
    for name in field_names:
        if name in seed:
            ext[name] = seed.pop(name)
