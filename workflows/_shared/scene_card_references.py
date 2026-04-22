"""Cross-surface reference validation for scene cards.

After ``scene_card_translator.translate_scene_card`` has produced a card in
the canonical schema shape, this module verifies that every reference on
the card (character names, promise IDs, hook IDs, revelation IDs, subplot
IDs) resolves to an entry in the compiled concept seed. This is compile-time
validation, not runtime: the pipeline still tolerates missing references
with warn-level telemetry, but bundle compile should surface them early so
authors fix them before drafting.

The validator is advisory. It never raises; it returns a list of human-
readable warning strings that ``scripts/compile_bundle.py`` appends to the
``CompileReport.warnings`` list (and ``--strict`` promotes to failure).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def _names_from(seed: Mapping[str, Any], key: str) -> set[str]:
    """Return the set of ``name`` values from ``seed[key]``.

    ``ensemble_cast`` and ``referenced_characters`` are both lists of
    objects that use the character's ``name`` as the reference key (no
    separate ``character_id`` field in the current seed shape).
    """
    out: set[str] = set()
    items = seed.get(key)
    if not isinstance(items, list):
        return out
    for item in items:
        if isinstance(item, Mapping):
            name = item.get("name")
            if isinstance(name, str) and name:
                out.add(name)
    return out


def _ids_from(
    seed: Mapping[str, Any], seed_key: str, *id_keys: str,
) -> set[str]:
    """Return the set of IDs from ``seed[seed_key]`` under any of ``id_keys``.

    Some surfaces (revelation_schedule) have carried two id key names over
    time (``revelation_id`` and legacy ``info_id``); accept either so a
    partially-migrated seed still resolves cleanly.
    """
    out: set[str] = set()
    items = seed.get(seed_key)
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, Mapping):
            continue
        for key in id_keys:
            value = item.get(key)
            if isinstance(value, str) and value:
                out.add(value)
    return out


def _card_label(card: Mapping[str, Any]) -> str:
    try:
        ch = int(card["chapter_number"])
        sn = int(card.get("scene_number", 1))
    except (KeyError, TypeError, ValueError):
        return "<unknown card>"
    return f"chapter_{ch:02d}_scene_{sn:02d}"


def validate_scene_card_references(
    card: Mapping[str, Any],
    seed: Mapping[str, Any],
) -> list[str]:
    """Return a list of warning strings for references on ``card`` that do
    not resolve in ``seed``.

    Reference rules:
    - ``characters_present`` must match an ensemble_cast or
      referenced_characters name.
    - ``promises_planted`` / ``promises_paid`` / ``promises_progressed``
      resolve against ``promise_payoff_ledger.promise_id`` OR
      ``hooks.hook_id`` (legacy data pre-ledger reused hook_ids as promise
      placeholders; accept both).
    - ``hook_actions[].hook_id`` must match ``hooks.hook_id``.
    - ``revelations`` (list of strings) must match
      ``revelation_schedule.revelation_id`` or legacy ``info_id``.
    - ``active_subplots`` must match ``subplots.subplot_id``.
    """
    label = _card_label(card)
    warnings: list[str] = []

    cast_names = _names_from(seed, "ensemble_cast") | _names_from(
        seed, "referenced_characters"
    )
    promise_ids = _ids_from(seed, "promise_payoff_ledger", "promise_id")
    hook_ids = _ids_from(seed, "hooks", "hook_id")
    subplot_ids = _ids_from(seed, "subplots", "subplot_id")
    revelation_ids = _ids_from(
        seed, "revelation_schedule", "revelation_id", "info_id",
    )
    promise_pool = promise_ids | hook_ids

    for name in card.get("characters_present", []) or []:
        if isinstance(name, str) and name and name not in cast_names:
            warnings.append(
                f"{label}: characters_present {name!r} not in "
                f"ensemble_cast or referenced_characters"
            )

    for field in ("promises_planted", "promises_paid", "promises_progressed"):
        for pid in card.get(field) or []:
            if isinstance(pid, str) and pid and pid not in promise_pool:
                warnings.append(
                    f"{label}: {field} id {pid!r} not in "
                    f"promise_payoff_ledger or hooks"
                )

    for action in card.get("hook_actions") or []:
        if not isinstance(action, Mapping):
            continue
        hid = action.get("hook_id")
        if isinstance(hid, str) and hid and hid not in hook_ids:
            warnings.append(
                f"{label}: hook_actions hook_id {hid!r} not in hooks"
            )

    for rev in card.get("revelations") or []:
        rid = rev if isinstance(rev, str) else (
            rev.get("revelation_id") if isinstance(rev, Mapping) else None
        )
        if isinstance(rid, str) and rid and rid not in revelation_ids:
            warnings.append(
                f"{label}: revelation id {rid!r} not in revelation_schedule"
            )

    for sid in card.get("active_subplots") or []:
        if isinstance(sid, str) and sid and sid not in subplot_ids:
            warnings.append(
                f"{label}: active_subplots id {sid!r} not in subplots"
            )

    return warnings


def validate_all_scene_card_references(
    cards: Iterable[Mapping[str, Any]],
    seed: Mapping[str, Any],
) -> list[str]:
    """Run ``validate_scene_card_references`` over every card; concatenate."""
    out: list[str] = []
    for card in cards:
        out.extend(validate_scene_card_references(card, seed))
    return out
