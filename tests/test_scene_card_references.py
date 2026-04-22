"""Tests for workflows/_shared/scene_card_references.py \u2014 cross-surface
reference validation run at bundle-compile time."""

from workflows._shared.scene_card_references import (
    validate_all_scene_card_references,
    validate_scene_card_references,
)


SEED = {
    "ensemble_cast": [
        {"name": "Alex Reyes"},
        {"name": "Mara Jade"},
    ],
    "referenced_characters": [
        {"name": "Luke Skywalker"},
    ],
    "promise_payoff_ledger": [
        {"promise_id": "prom_alex_falls"},
    ],
    "hooks": [
        {"hook_id": "hook_dark_hooded_enemy"},
        {"hook_id": "hook_sealed_file"},
    ],
    "subplots": [
        {"subplot_id": "sub_adumar_investigation"},
    ],
    "revelation_schedule": [
        {"revelation_id": "rev_luke_dream"},
        {"info_id": "info_legacy_id"},
    ],
}


def _base_card(**overrides) -> dict:
    card = {
        "chapter_number": 1,
        "scene_number": 1,
    }
    card.update(overrides)
    return card


def test_valid_references_produce_no_warnings():
    card = _base_card(
        characters_present=["Alex Reyes", "Luke Skywalker"],
        promises_planted=["prom_alex_falls", "hook_sealed_file"],
        promises_paid=["hook_dark_hooded_enemy"],
        promises_progressed=["prom_alex_falls"],
        hook_actions=[{"hook_id": "hook_dark_hooded_enemy", "action": "plant"}],
        revelations=["rev_luke_dream", "info_legacy_id"],
        active_subplots=["sub_adumar_investigation"],
    )
    assert validate_scene_card_references(card, SEED) == []


def test_unknown_character_flagged():
    card = _base_card(characters_present=["Unknown Person"])
    warnings = validate_scene_card_references(card, SEED)
    assert any(
        "'Unknown Person'" in w and "characters_present" in w for w in warnings
    )


def test_known_character_in_referenced_characters_accepted():
    # Characters in referenced_characters (not ensemble_cast) still resolve.
    card = _base_card(characters_present=["Luke Skywalker"])
    assert validate_scene_card_references(card, SEED) == []


def test_unknown_promise_flagged():
    card = _base_card(promises_planted=["prom_nonexistent"])
    warnings = validate_scene_card_references(card, SEED)
    assert any("prom_nonexistent" in w for w in warnings)


def test_hook_id_accepted_as_promise_id_for_backcompat():
    """Legacy cards reuse hook_ids as promise placeholders; accept both."""
    card = _base_card(promises_planted=["hook_dark_hooded_enemy"])
    assert validate_scene_card_references(card, SEED) == []


def test_unknown_hook_action_flagged():
    card = _base_card(
        hook_actions=[{"hook_id": "hook_not_in_seed", "action": "plant"}],
    )
    warnings = validate_scene_card_references(card, SEED)
    assert any("hook_not_in_seed" in w for w in warnings)


def test_legacy_info_id_resolved():
    """revelation_schedule items can carry legacy `info_id` instead of
    `revelation_id`; both resolve."""
    card = _base_card(revelations=["info_legacy_id"])
    assert validate_scene_card_references(card, SEED) == []


def test_unknown_revelation_flagged():
    card = _base_card(revelations=["rev_missing"])
    warnings = validate_scene_card_references(card, SEED)
    assert any("rev_missing" in w for w in warnings)


def test_unknown_subplot_flagged():
    card = _base_card(active_subplots=["sub_phantom"])
    warnings = validate_scene_card_references(card, SEED)
    assert any("sub_phantom" in w for w in warnings)


def test_empty_card_produces_no_warnings():
    assert validate_scene_card_references(_base_card(), SEED) == []


def test_empty_seed_flags_everything():
    card = _base_card(
        characters_present=["Alex"],
        active_subplots=["sub_a"],
    )
    warnings = validate_scene_card_references(card, {})
    assert len(warnings) == 2


def test_validate_all_aggregates_warnings():
    cards = [
        _base_card(chapter_number=1, scene_number=1, characters_present=["Unknown"]),
        _base_card(chapter_number=2, scene_number=1, promises_planted=["prom_missing"]),
    ]
    warnings = validate_all_scene_card_references(cards, SEED)
    assert len(warnings) == 2
    assert any("chapter_01_scene_01" in w for w in warnings)
    assert any("chapter_02_scene_01" in w for w in warnings)


def test_non_string_values_silently_ignored():
    # Schema-invalid payloads (e.g. None or objects in a string list) must
    # not crash the validator; jsonschema surfaces those as hard errors.
    card = _base_card(
        characters_present=[None, 42, "Alex Reyes"],
        active_subplots=[{"not": "a string"}],
    )
    warnings = validate_scene_card_references(card, SEED)
    # Only the valid "Alex Reyes" was actually checked; it resolves clean.
    assert warnings == []
