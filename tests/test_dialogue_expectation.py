"""Tests for src.quality.dialogue_expectation.derive()."""
from src.quality.dialogue_expectation import derive, is_dialogue_led


class TestDerive:
    def test_explicit_override_wins(self):
        # Even if the derivation rules would say "dialogue_led",
        # an explicit "interior" on the card must win.
        card = {
            "conflict_type": "interpersonal",
            "characters_present": ["A", "B"],
            "dialogue_expectation": "interior",
        }
        assert derive(card) == "interior"

    def test_explicit_invalid_falls_back_to_derivation(self):
        # Bogus override value is ignored; derivation applies.
        card = {
            "conflict_type": "interpersonal",
            "characters_present": ["A", "B"],
            "dialogue_expectation": "garbage",
        }
        assert derive(card) == "dialogue_led"

    def test_interpersonal_multichar_is_dialogue_led(self):
        card = {
            "conflict_type": "interpersonal",
            "characters_present": ["A", "B"],
        }
        assert derive(card) == "dialogue_led"

    def test_decision_role_multichar_is_dialogue_led(self):
        card = {
            "scene_role": "decision",
            "conflict_type": "external",  # not interpersonal
            "characters_present": ["A", "B"],
        }
        assert derive(card) == "dialogue_led"

    def test_internal_sequel_is_interior(self):
        card = {
            "conflict_type": "internal",
            "scene_type": "sequel",
            "characters_present": ["A", "B"],  # count does NOT flip this
        }
        assert derive(card) == "interior"

    def test_single_character_is_interior(self):
        card = {
            "conflict_type": "external",
            "characters_present": ["A"],
        }
        assert derive(card) == "interior"

    def test_empty_card_resolves_to_interior(self):
        # Empty card has no characters_present, which trips the
        # `char_count <= 1` rule before the balanced default. That's
        # the right call — a scene with no characters can't be
        # dialogue-led, so suppressing dialogue pressure is safest.
        assert derive({}) == "interior"

    def test_balanced_default_when_unclassifiable_multichar(self):
        # The "balanced" default fires when two or more characters are
        # present but no other qualifying conditions match.
        card = {
            "characters_present": ["A", "B"],
            # no conflict_type, no scene_role, no scene_type
        }
        assert derive(card) == "balanced"

    def test_multichar_external_conflict_is_balanced(self):
        # Two characters, external conflict, no other qualifying conditions:
        # should be balanced, NOT dialogue_led. This is the regression case
        # the field was introduced to fix.
        card = {
            "conflict_type": "external",
            "characters_present": ["A", "B"],
        }
        assert derive(card) == "balanced"

    def test_scene1_regression(self):
        # Reproduces the ch01 scene 01 pattern: sequel scene with internal
        # conflict and a background second character. Before the fix, the
        # `characters_present >= 2` proxy wrongly classified this as
        # dialogue-led. After the fix, it derives to "interior".
        card = {
            "conflict_type": "interpersonal",  # scene 1 is actually flagged interpersonal in data
            "scene_type": "sequel",
            "characters_present": ["Ben Skywalker", "Jedi Knight (sparring partner)"],
        }
        # With no explicit override, the interpersonal+multichar rule wins.
        # The scene-1 override in data/.../chapter_01_scene_01.json will set
        # dialogue_expectation: interior explicitly to fix this case.
        assert derive(card) == "dialogue_led"
        # With explicit override applied:
        card["dialogue_expectation"] = "interior"
        assert derive(card) == "interior"


class TestIsDialogueLed:
    def test_dialogue_led_card(self):
        assert is_dialogue_led({
            "conflict_type": "interpersonal",
            "characters_present": ["A", "B"],
        }) is True

    def test_interior_card(self):
        assert is_dialogue_led({"characters_present": ["A"]}) is False

    def test_balanced_card(self):
        assert is_dialogue_led({
            "conflict_type": "external",
            "characters_present": ["A", "B"],
        }) is False
