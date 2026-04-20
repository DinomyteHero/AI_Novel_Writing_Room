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

from workflows._shared.seed_transforms import (
    ARC_TYPE_ENUM,
    CANON_STATUS_ENUM,
    RELATIONSHIP_ARC_TYPE_ENUM,
    TONE_ENUM,
    apply_arc_phase_maps,
    apply_branch_point,
    apply_canon_constraints,
    apply_canon_profile,
    apply_force_mechanics,
    apply_hooks,
    apply_promise_payoff_ledger,
    apply_quality_overrides,
    apply_referenced_characters,
    apply_relationship_arcs,
    apply_revelation_schedule,
    apply_stress_test_scores,
    apply_subplots,
    apply_terminology_registry,
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


# ---------------------------------------------------------------------------
# Drift-closure transforms — one test each covering no-op behaviour and
# deep-copy isolation. A single composite test covers the full per-section
# injection path since every drift-closure transform follows the same
# minimal pattern (None => no-op, dict/list => deep-copied top-level set).
# ---------------------------------------------------------------------------


class TestDriftClosureTransforms:
    """Exercise the ten transforms added to close the pre-Phase-3 drift.

    Each transform is a minimal mutate-if-truthy injector; the suite below
    verifies both the happy path and the no-op branch, plus deep-copy
    isolation so mutating the installed seed cannot leak back into the
    caller's patch dict.
    """

    def test_apply_canon_profile_noop_on_none(self):
        seed = {"meta": {}}
        apply_canon_profile(seed, None)
        assert "canon_profile" not in seed

    def test_apply_canon_profile_injects(self):
        seed = {"meta": {}}
        profile = {"franchise": "star_wars", "continuity": "legends_eu"}
        apply_canon_profile(seed, profile)
        assert seed["canon_profile"] == profile

    def test_apply_canon_profile_deep_copies(self):
        seed = {"meta": {}}
        profile = {"franchise": "star_wars", "anachronistic_terms": {"LIDAR": ["sensor sweep"]}}
        apply_canon_profile(seed, profile)
        seed["canon_profile"]["anachronistic_terms"]["LIDAR"].append("mutated")
        assert profile["anachronistic_terms"]["LIDAR"] == ["sensor sweep"]

    def test_apply_force_mechanics_noop_on_none(self):
        seed = {"meta": {}}
        apply_force_mechanics(seed, None)
        assert "force_mechanics" not in seed

    def test_apply_force_mechanics_injects(self):
        seed = {"meta": {}}
        mechanics = {
            "primary_rule": "The lattice maintains light/dark distinction.",
            "sensory_vocabulary": {"normal_lattice": {"force_sensitive": "handrail"}},
        }
        apply_force_mechanics(seed, mechanics)
        assert seed["force_mechanics"] == mechanics

    def test_apply_quality_overrides_noop_on_none(self):
        seed = {"meta": {}}
        apply_quality_overrides(seed, None)
        assert "quality_overrides" not in seed

    def test_apply_quality_overrides_injects(self):
        seed = {"meta": {}}
        overrides = {
            "word_frequency_allowlist": ["Force", "Jedi"],
            "semantic_similarity_threshold": 0.88,
        }
        apply_quality_overrides(seed, overrides)
        assert seed["quality_overrides"] == overrides

    def test_apply_referenced_characters_noop_on_none(self):
        seed = {"meta": {}}
        apply_referenced_characters(seed, None)
        assert "referenced_characters" not in seed

    def test_apply_referenced_characters_noop_on_empty(self):
        seed = {"meta": {}}
        apply_referenced_characters(seed, [])
        assert "referenced_characters" not in seed

    def test_apply_referenced_characters_injects(self):
        seed = {"meta": {}}
        minors = [
            {"name": "Luke Skywalker", "role": "Grand Master"},
            {"name": "Jori Teth", "role": "Sparring partner"},
        ]
        apply_referenced_characters(seed, minors)
        assert seed["referenced_characters"] == minors

    def test_apply_subplots_noop_on_none(self):
        seed = {"meta": {}}
        apply_subplots(seed, None)
        assert "subplots" not in seed

    def test_apply_subplots_injects(self):
        seed = {"meta": {}}
        subplots = [{"subplot_id": "SP-A", "name": "Main throughline"}]
        apply_subplots(seed, subplots)
        assert seed["subplots"] == subplots

    def test_apply_hooks_noop_on_none(self):
        seed = {"meta": {}}
        apply_hooks(seed, None)
        assert "hooks" not in seed

    def test_apply_hooks_injects(self):
        seed = {"meta": {}}
        hooks = [{"hook_id": "H01", "hook_type": "soft"}]
        apply_hooks(seed, hooks)
        assert seed["hooks"] == hooks

    def test_apply_revelation_schedule_noop_on_none(self):
        seed = {"meta": {}}
        apply_revelation_schedule(seed, None)
        assert "revelation_schedule" not in seed

    def test_apply_revelation_schedule_injects(self):
        seed = {"meta": {}}
        revs = [{"revelation_id": "R01", "what": "the wrongness has a source"}]
        apply_revelation_schedule(seed, revs)
        assert seed["revelation_schedule"] == revs

    def test_apply_terminology_registry_noop_on_none(self):
        seed = {"meta": {}}
        apply_terminology_registry(seed, None)
        assert "terminology_registry" not in seed

    def test_apply_terminology_registry_injects(self):
        seed = {"meta": {}}
        terms = [{"canonical_form": "Veranthos", "category": "place_name", "definition": "A planet."}]
        apply_terminology_registry(seed, terms)
        assert seed["terminology_registry"] == terms

    def test_apply_relationship_arcs_noop_on_none(self):
        seed = {"meta": {}}
        apply_relationship_arcs(seed, None)
        assert "relationship_arcs" not in seed

    def test_apply_relationship_arcs_injects(self):
        seed = {"meta": {}}
        arcs = [
            {
                "dyad": "Ben/Luke",
                "arc_type": "reconciling",
                "arc_summary": "distance to candor",
            }
        ]
        apply_relationship_arcs(seed, arcs)
        assert seed["relationship_arcs"] == arcs

    def test_apply_relationship_arcs_deep_copies(self):
        seed = {"meta": {}}
        arcs = [{"dyad": "Ben/Desh", "arc_type": "deepening", "arc_phase_map": {"a": "b"}}]
        apply_relationship_arcs(seed, arcs)
        seed["relationship_arcs"][0]["arc_phase_map"]["a"] = "mutated"
        assert arcs[0]["arc_phase_map"]["a"] == "b"

    def test_apply_stress_test_scores_noop_on_none(self):
        seed = {"meta": {}}
        apply_stress_test_scores(seed, None)
        assert "stress_test_scores" not in seed

    def test_apply_stress_test_scores_injects(self):
        seed = {"meta": {}}
        scores = {
            "structural_integrity": 9.2,
            "character_depth": 9.0,
            "overall": 9.0,
        }
        apply_stress_test_scores(seed, scores)
        assert seed["stress_test_scores"] == scores

    def test_apply_stress_test_scores_injects_nulls(self):
        """Null-valued score objects are valid pre-assessment placeholders."""
        seed = {"meta": {}}
        scores = {"structural_integrity": None, "overall": None}
        apply_stress_test_scores(seed, scores)
        assert seed["stress_test_scores"] == scores


class TestNormalizeEnumsCorruptionArc:
    """Torin's corruption arc is a new canonical arc_type. normalize_enums
    must treat corruption as a valid enum member when supplied via
    arc_type_map, and must not clobber an existing prose arc_summary when
    the current arc_type is already canonical."""

    def test_corruption_mapped_without_stomping_existing_arc_summary(self):
        seed = {
            "meta": {},
            "ensemble_cast": [
                {
                    "name": "Torin Hal",
                    "weiland_arc": {
                        "arc_type": "negative",
                        "arc_summary": "Negative (tragic) - moves deeper into the lie.",
                    },
                }
            ],
        }
        normalize_enums(seed, arc_type_map={"Torin Hal": "corruption"})
        torin = seed["ensemble_cast"][0]["weiland_arc"]
        assert torin["arc_type"] == "corruption"
        assert torin["arc_summary"] == (
            "Negative (tragic) - moves deeper into the lie."
        )

    def test_corruption_enum_is_recognized(self):
        assert "corruption" in ARC_TYPE_ENUM
        assert "fall" in ARC_TYPE_ENUM


class TestRelationshipArcTypeEnum:
    def test_expected_values(self):
        assert RELATIONSHIP_ARC_TYPE_ENUM == {
            "deepening",
            "rupturing",
            "reconciling",
            "transactional",
            "static",
        }


# ---------------------------------------------------------------------------
# apply_branch_point (Phase 6.3b)
# ---------------------------------------------------------------------------


class TestApplyBranchPoint:
    """Phase 6.3b — copy universe_meta.branch_point into concept_seed.meta.

    Decision D4: concept_seed.meta is the authoritative runtime source. The
    installer / bundle compiler mirrors it from universe_meta at build time.
    """

    def _populated_branch_point(self) -> dict:
        return {
            "source_canon": "Star Wars Legends EU",
            "divergence_point": "post-Lost Tribe crisis, circa 44 ABY",
            "divergence_description": "Jedi take a Ruusan-style reformation path.",
        }

    def test_noop_on_none(self):
        seed = _blank_seed()
        apply_branch_point(seed, None)
        assert "branch_point" not in seed["meta"]

    def test_noop_on_missing_key(self):
        seed = _blank_seed()
        apply_branch_point(seed, {"franchise": "Some Franchise"})
        assert "branch_point" not in seed["meta"]

    def test_noop_on_empty_branch_point_dict(self):
        """Empty dict matches canon_expert's 'not declarative' treatment."""
        seed = _blank_seed()
        apply_branch_point(seed, {"branch_point": {}})
        assert "branch_point" not in seed["meta"]

    def test_noop_when_all_fields_blank(self):
        """A branch_point with all-empty values is treated as absent."""
        seed = _blank_seed()
        apply_branch_point(
            seed,
            {"branch_point": {"source_canon": "", "divergence_point": ""}},
        )
        assert "branch_point" not in seed["meta"]

    def test_populated_branch_point_is_copied(self):
        seed = _blank_seed()
        universe_meta = {"branch_point": self._populated_branch_point()}
        apply_branch_point(seed, universe_meta)
        assert seed["meta"]["branch_point"] == self._populated_branch_point()

    def test_partial_branch_point_is_copied(self):
        """Just source_canon set is enough to be declarative."""
        seed = _blank_seed()
        universe_meta = {"branch_point": {"source_canon": "X"}}
        apply_branch_point(seed, universe_meta)
        assert seed["meta"]["branch_point"] == {"source_canon": "X"}

    def test_existing_branch_point_is_preserved(self):
        """Caller-supplied branch_point wins over universe-level default."""
        seed = _blank_seed()
        seed["meta"]["branch_point"] = {"source_canon": "caller_value"}
        universe_meta = {"branch_point": self._populated_branch_point()}
        apply_branch_point(seed, universe_meta)
        assert seed["meta"]["branch_point"] == {"source_canon": "caller_value"}

    def test_deep_copies_so_mutation_does_not_leak(self):
        seed = _blank_seed()
        source = {"branch_point": self._populated_branch_point()}
        apply_branch_point(seed, source)
        seed["meta"]["branch_point"]["source_canon"] = "mutated"
        assert source["branch_point"]["source_canon"] == "Star Wars Legends EU"

    def test_non_dict_branch_point_is_ignored(self):
        """Defensive: don't crash if universe_meta schema is violated."""
        seed = _blank_seed()
        apply_branch_point(seed, {"branch_point": "not a dict"})
        assert "branch_point" not in seed["meta"]

    def test_seed_without_meta_gets_meta_created(self):
        seed = {}
        apply_branch_point(
            seed, {"branch_point": self._populated_branch_point()}
        )
        assert "meta" in seed
        assert seed["meta"]["branch_point"] == self._populated_branch_point()
