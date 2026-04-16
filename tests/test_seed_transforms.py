"""Unit tests for src/concept_workshop/seed_transforms.py.

Each transform is a pure mutation on a concept-seed dict. Tests cover:
  - No-op behaviour when input data is missing/None.
  - Correct injection when data is present.
  - Enum normalization with and without arc_type_map.
  - Deep-copy isolation (mutating the installed seed must not leak back
    into the caller's patch dict).
"""

from __future__ import annotations

import copy

from src.concept_workshop.seed_transforms import (
    ARC_TYPE_ENUM,
    CANON_STATUS_ENUM,
    TONE_ENUM,
    apply_arc_phase_maps,
    apply_canon_constraints,
    apply_promise_payoff_ledger,
    apply_voice_definition,
    apply_workshop_origin,
    move_to_extended_metadata,
    normalize_enums,
)


def _blank_seed() -> dict:
    return {
        "meta": {},
        "ensemble_cast": [],
    }


# ---------------------------------------------------------------------------
# normalize_enums
# ---------------------------------------------------------------------------


class TestNormalizeEnums:
    def test_canonical_tone_untouched(self):
        seed = {"meta": {"tone": "heroic_with_weight"}}
        normalize_enums(seed)
        assert seed["meta"]["tone"] == "heroic_with_weight"
        assert "tone_description" not in seed["meta"]

    def test_descriptive_tone_coerced_to_fallback(self):
        seed = {"meta": {"tone": "emotionally heavy space opera"}}
        normalize_enums(seed, tone_fallback="heroic_with_weight")
        assert seed["meta"]["tone"] == "heroic_with_weight"
        assert seed["meta"]["tone_description"] == "emotionally heavy space opera"

    def test_empty_tone_untouched(self):
        seed = {"meta": {"tone": ""}}
        normalize_enums(seed)
        assert seed["meta"]["tone"] == ""
        assert "tone_description" not in seed["meta"]

    def test_canonical_canon_status_untouched(self):
        seed = {"meta": {"canon_status": "AU"}}
        normalize_enums(seed)
        assert seed["meta"]["canon_status"] == "AU"
        assert "canon_status_description" not in seed["meta"]

    def test_descriptive_canon_status_coerced(self):
        seed = {"meta": {"canon_status": "alternate-universe fanfic"}}
        normalize_enums(seed, canon_status_fallback="AU")
        assert seed["meta"]["canon_status"] == "AU"
        assert (
            seed["meta"]["canon_status_description"]
            == "alternate-universe fanfic"
        )

    def test_arc_type_map_applied(self):
        seed = {
            "meta": {},
            "ensemble_cast": [
                {
                    "name": "Alice",
                    "weiland_arc": {"arc_type": "slow positive growth under pressure"},
                },
                {"name": "Bob", "weiland_arc": {"arc_type": "tragic decline"}},
                {"name": "Carol", "weiland_arc": {"arc_type": "positive_change"}},
            ],
        }
        normalize_enums(
            seed,
            arc_type_map={
                "Alice": "positive_change",
                "Bob": "negative",
                "Carol": "positive_change",
            },
        )
        alice = seed["ensemble_cast"][0]["weiland_arc"]
        bob = seed["ensemble_cast"][1]["weiland_arc"]
        carol = seed["ensemble_cast"][2]["weiland_arc"]
        assert alice["arc_type"] == "positive_change"
        assert alice["arc_summary"] == "slow positive growth under pressure"
        assert bob["arc_type"] == "negative"
        assert bob["arc_summary"] == "tragic decline"
        # Already canonical — no arc_summary should be added.
        assert carol["arc_type"] == "positive_change"
        assert "arc_summary" not in carol

    def test_no_arc_type_map_leaves_arcs_alone(self):
        seed = {
            "meta": {},
            "ensemble_cast": [
                {"name": "Alice", "weiland_arc": {"arc_type": "mystery"}},
            ],
        }
        normalize_enums(seed)  # no arc_type_map
        assert seed["ensemble_cast"][0]["weiland_arc"]["arc_type"] == "mystery"

    def test_characters_outside_arc_type_map_untouched(self):
        seed = {
            "meta": {},
            "ensemble_cast": [
                {"name": "Alice", "weiland_arc": {"arc_type": "mystery"}},
                {"name": "Bob", "weiland_arc": {"arc_type": "positive_change"}},
            ],
        }
        normalize_enums(seed, arc_type_map={"Bob": "positive_change"})
        # Alice was not in the map → untouched.
        assert seed["ensemble_cast"][0]["weiland_arc"]["arc_type"] == "mystery"

    def test_enums_are_lists_of_strings(self):
        """Smoke test that the enum constants match the schema expectations."""
        assert "heroic_with_weight" in TONE_ENUM
        assert "AU" in CANON_STATUS_ENUM
        assert "positive_change" in ARC_TYPE_ENUM


# ---------------------------------------------------------------------------
# apply_voice_definition
# ---------------------------------------------------------------------------


class TestApplyVoiceDefinition:
    def test_no_op_when_voice_is_none(self):
        seed = _blank_seed()
        apply_voice_definition(seed, None)
        assert "voice_definition" not in seed

    def test_no_op_when_voice_is_empty(self):
        seed = _blank_seed()
        apply_voice_definition(seed, {})
        assert "voice_definition" not in seed

    def test_injects_voice(self):
        seed = _blank_seed()
        voice = {"pov_approach": "close third", "anti_slop_rules": ["rule1"]}
        apply_voice_definition(seed, voice)
        assert seed["voice_definition"] == voice

    def test_deep_copied(self):
        seed = _blank_seed()
        voice = {"anti_slop_rules": ["rule1"]}
        apply_voice_definition(seed, voice)
        seed["voice_definition"]["anti_slop_rules"].append("mutated")
        assert voice["anti_slop_rules"] == ["rule1"]


# ---------------------------------------------------------------------------
# apply_arc_phase_maps
# ---------------------------------------------------------------------------


class TestApplyArcPhaseMaps:
    def test_no_op_when_maps_is_none(self):
        seed = {"ensemble_cast": [{"name": "Alice", "weiland_arc": {}}]}
        apply_arc_phase_maps(seed, None)
        assert "arc_phase_map" not in seed["ensemble_cast"][0]["weiland_arc"]

    def test_injects_per_character(self):
        seed = {
            "ensemble_cast": [
                {"name": "Alice", "weiland_arc": {}},
                {"name": "Bob", "weiland_arc": {}},
            ]
        }
        maps = {
            "Alice": {"lie_established": "Ch 1", "moment_of_truth": "Ch 5"},
            "Bob": {"lie_established": "Ch 2"},
        }
        apply_arc_phase_maps(seed, maps)
        assert seed["ensemble_cast"][0]["weiland_arc"]["arc_phase_map"] == maps["Alice"]
        assert seed["ensemble_cast"][1]["weiland_arc"]["arc_phase_map"] == maps["Bob"]

    def test_character_not_in_map_is_untouched(self):
        seed = {
            "ensemble_cast": [
                {"name": "Alice", "weiland_arc": {}},
                {"name": "Bob", "weiland_arc": {}},
            ]
        }
        apply_arc_phase_maps(seed, {"Alice": {"moment_of_truth": "Ch 5"}})
        assert "arc_phase_map" not in seed["ensemble_cast"][1]["weiland_arc"]

    def test_creates_weiland_arc_if_missing(self):
        seed = {"ensemble_cast": [{"name": "Alice"}]}
        apply_arc_phase_maps(seed, {"Alice": {"moment_of_truth": "Ch 5"}})
        assert "weiland_arc" in seed["ensemble_cast"][0]


# ---------------------------------------------------------------------------
# apply_promise_payoff_ledger
# ---------------------------------------------------------------------------


class TestApplyPromisePayoffLedger:
    def test_no_op_when_ledger_is_none(self):
        seed = _blank_seed()
        apply_promise_payoff_ledger(seed, None)
        assert "promise_payoff_ledger" not in seed

    def test_no_op_when_ledger_is_empty(self):
        seed = _blank_seed()
        apply_promise_payoff_ledger(seed, [])
        assert "promise_payoff_ledger" not in seed

    def test_sets_ledger(self):
        seed = _blank_seed()
        ledger = [{"promise_id": "PP01", "promise": "something happens"}]
        apply_promise_payoff_ledger(seed, ledger)
        assert seed["promise_payoff_ledger"] == ledger

    def test_deep_copied(self):
        seed = _blank_seed()
        ledger = [{"promise_id": "PP01"}]
        apply_promise_payoff_ledger(seed, ledger)
        seed["promise_payoff_ledger"][0]["mutated"] = True
        assert "mutated" not in ledger[0]


# ---------------------------------------------------------------------------
# apply_canon_constraints
# ---------------------------------------------------------------------------


class TestApplyCanonConstraints:
    def test_no_op_when_constraints_is_none(self):
        seed = _blank_seed()
        apply_canon_constraints(seed, None)
        assert "canon_constraints" not in seed

    def test_sets_constraints(self):
        seed = _blank_seed()
        constraints = {"continuity": "main", "style_constraints": ["rule1"]}
        apply_canon_constraints(seed, constraints)
        assert seed["canon_constraints"] == constraints


# ---------------------------------------------------------------------------
# apply_workshop_origin
# ---------------------------------------------------------------------------


class TestApplyWorkshopOrigin:
    def test_no_op_when_origin_is_none(self):
        seed = _blank_seed()
        apply_workshop_origin(seed, None)
        assert "extended_metadata" not in seed

    def test_sets_origin_under_extended_metadata(self):
        seed = _blank_seed()
        origin = {"source": "claude_ai_simulation", "date": "2026-04-09"}
        apply_workshop_origin(seed, origin)
        assert seed["extended_metadata"]["workshop_origin"] == origin

    def test_preserves_existing_extended_metadata(self):
        seed = {"meta": {}, "extended_metadata": {"existing_field": "kept"}}
        apply_workshop_origin(seed, {"source": "x"})
        assert seed["extended_metadata"]["existing_field"] == "kept"
        assert seed["extended_metadata"]["workshop_origin"] == {"source": "x"}


# ---------------------------------------------------------------------------
# move_to_extended_metadata
# ---------------------------------------------------------------------------


class TestMoveToExtendedMetadata:
    def test_no_op_when_field_list_empty(self):
        seed = {"meta": {}, "technique_lineage": {"stages": 3}}
        move_to_extended_metadata(seed, [])
        assert "technique_lineage" in seed
        assert "extended_metadata" not in seed

    def test_moves_single_field(self):
        seed = {"meta": {}, "technique_lineage": {"stages": 3}}
        move_to_extended_metadata(seed, ["technique_lineage"])
        assert "technique_lineage" not in seed
        assert seed["extended_metadata"]["technique_lineage"] == {"stages": 3}

    def test_moves_multiple_fields(self):
        seed = {
            "meta": {},
            "technique_lineage": {"stages": 3},
            "jacen_parallel": {"touchpoints": 4},
        }
        move_to_extended_metadata(seed, ["technique_lineage", "jacen_parallel"])
        assert "technique_lineage" not in seed
        assert "jacen_parallel" not in seed
        assert seed["extended_metadata"]["technique_lineage"] == {"stages": 3}
        assert seed["extended_metadata"]["jacen_parallel"] == {"touchpoints": 4}

    def test_missing_field_is_skipped(self):
        seed = {"meta": {}, "technique_lineage": {"stages": 3}}
        move_to_extended_metadata(seed, ["technique_lineage", "nonexistent"])
        assert seed["extended_metadata"]["technique_lineage"] == {"stages": 3}
        assert "nonexistent" not in seed["extended_metadata"]

    def test_preserves_existing_extended_metadata(self):
        seed = {
            "meta": {},
            "extended_metadata": {"pre_existing": "kept"},
            "technique_lineage": {"stages": 3},
        }
        move_to_extended_metadata(seed, ["technique_lineage"])
        assert seed["extended_metadata"]["pre_existing"] == "kept"
        assert seed["extended_metadata"]["technique_lineage"] == {"stages": 3}


# ---------------------------------------------------------------------------
# Composition regression: the Ruusan sequence
# ---------------------------------------------------------------------------


class TestRuusanTransformSequenceRegression:
    """Exercise the exact call sequence used in install_ruusan_seed.py,
    confirming the transforms compose to the same output that the
    previous inline code produced."""

    def test_full_sequence(self):
        # Minimal Ruusan-shaped raw seed.
        raw = {
            "meta": {
                "tone": "dark but hopeful EU space opera",
                "canon_status": "alternate-universe fanfic",
            },
            "ensemble_cast": [
                {
                    "name": "Ben Skywalker",
                    "weiland_arc": {"arc_type": "slow growth under pressure"},
                },
                {
                    "name": "Torin Hal",
                    "weiland_arc": {"arc_type": "tragic fall"},
                },
            ],
            "scene_cards": [],
            "technique_lineage": {"stages": ["Nathema", "Malachor"]},
            "jacen_parallel": {"touchpoints": 4},
        }
        seed = copy.deepcopy(raw)

        apply_voice_definition(seed, {"pov_approach": "close third"})
        normalize_enums(
            seed,
            tone_fallback="heroic_with_weight",
            canon_status_fallback="AU",
            arc_type_map={
                "Ben Skywalker": "positive_change",
                "Torin Hal": "negative",
            },
        )
        apply_arc_phase_maps(
            seed,
            {"Ben Skywalker": {"moment_of_truth": "Ch 21"}},
        )
        apply_promise_payoff_ledger(seed, [{"promise_id": "PP01"}])
        move_to_extended_metadata(seed, ["technique_lineage", "jacen_parallel"])
        apply_workshop_origin(seed, {"source": "test", "date": "2026-04-09"})
        apply_canon_constraints(seed, {"continuity": "Legends EU"})

        # Enums coerced correctly.
        assert seed["meta"]["tone"] == "heroic_with_weight"
        assert seed["meta"]["tone_description"] == "dark but hopeful EU space opera"
        assert seed["meta"]["canon_status"] == "AU"
        assert seed["meta"]["canon_status_description"] == "alternate-universe fanfic"

        # Arc types normalized, arc_summary preserved.
        ben = seed["ensemble_cast"][0]["weiland_arc"]
        assert ben["arc_type"] == "positive_change"
        assert ben["arc_summary"] == "slow growth under pressure"
        assert ben["arc_phase_map"] == {"moment_of_truth": "Ch 21"}
        torin = seed["ensemble_cast"][1]["weiland_arc"]
        assert torin["arc_type"] == "negative"
        assert torin["arc_summary"] == "tragic fall"
        assert "arc_phase_map" not in torin  # not in the maps dict

        # Restructured top-level keys.
        assert "technique_lineage" not in seed
        assert "jacen_parallel" not in seed
        assert seed["extended_metadata"]["technique_lineage"] == {
            "stages": ["Nathema", "Malachor"]
        }
        assert seed["extended_metadata"]["jacen_parallel"] == {"touchpoints": 4}
        assert seed["extended_metadata"]["workshop_origin"]["source"] == "test"

        # Added fields.
        assert seed["voice_definition"] == {"pov_approach": "close third"}
        assert seed["promise_payoff_ledger"] == [{"promise_id": "PP01"}]
        assert seed["canon_constraints"] == {"continuity": "Legends EU"}
