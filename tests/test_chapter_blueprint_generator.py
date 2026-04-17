"""Tests for ChapterBlueprintGenerator — Phase 5.

Covers deterministic rollups (pure-function unit tests), schema validation,
ID purity (no hallucination), save/skip semantics, and a Ruusan ch1
equivalence test that mocks the synthesizer to confirm deterministic
fields exactly match the hand-authored blueprint.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import jsonschema
import pytest

from src.planning.chapter_blueprint_generator import (
    ChapterBlueprintGenerator,
    ChapterBlueprintSynthesizer,
    _build_concept_excerpt,
    _build_deterministic_rollup,
    _compute_chapter_word_target,
    _compute_hook_movements,
    _compute_pov_allocation,
    _compute_reveal_payload,
    _compute_scene_plan_skeleton,
    _compute_structural_phase,
    _compute_subplot_obligations,
    _filter_scene_card_for_synthesizer,
    _merge_synthesis_into_blueprint,
    save_blueprints,
)


SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "chapter_blueprint.json"


@pytest.fixture
def schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def ruusan_chapter_1_cards():
    """Load the real Ruusan chapter 1 scene cards from disk."""
    cards_dir = (
        Path(__file__).parent.parent
        / "data"
        / "franchises"
        / "star-wars-legends-eu"
        / "books"
        / "the-ruusan-atonement"
        / "scene_cards"
    )
    cards = []
    for path in sorted(cards_dir.glob("chapter_01_scene_*.json")):
        with open(path, encoding="utf-8") as f:
            cards.append(json.load(f))
    return cards


@pytest.fixture
def ruusan_chapter_1_blueprint():
    """Load the hand-authored Ruusan chapter 1 blueprint as the golden reference."""
    bp_path = (
        Path(__file__).parent.parent
        / "data"
        / "franchises"
        / "star-wars-legends-eu"
        / "books"
        / "the-ruusan-atonement"
        / "chapter_blueprints"
        / "chapter_01.json"
    )
    with open(bp_path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# Deterministic rollup unit tests                                              #
# --------------------------------------------------------------------------- #


class TestComputePovAllocation:
    def test_orders_by_first_appearance(self):
        cards = [
            {"pov_character": "Alice"},
            {"pov_character": "Bob"},
            {"pov_character": "Alice"},
        ]
        assert _compute_pov_allocation(cards) == ["Alice", "Bob"]

    def test_empty_cards_returns_empty_list(self):
        assert _compute_pov_allocation([]) == []

    def test_skips_missing_pov(self):
        cards = [{"pov_character": ""}, {"pov_character": "Alice"}, {}]
        assert _compute_pov_allocation(cards) == ["Alice"]


class TestComputeScenePlanSkeleton:
    def test_pulls_role_word_count_dialogue_verbatim(self):
        cards = [
            {"scene_number": 1, "scene_role": "hook", "dialogue_expectation": "interior", "target_word_count": 1250},
            {"scene_number": 2, "scene_role": "reveal", "dialogue_expectation": "balanced", "target_word_count": 1500},
        ]
        plan = _compute_scene_plan_skeleton(cards)
        assert plan == [
            {"scene_number": 1, "role": "hook", "target_word_count": 1250, "purpose": "", "dialogue_expectation": "interior"},
            {"scene_number": 2, "role": "reveal", "target_word_count": 1500, "purpose": "", "dialogue_expectation": "balanced"},
        ]

    def test_omits_dialogue_expectation_when_missing(self):
        cards = [{"scene_number": 1, "scene_role": "hook", "target_word_count": 1000}]
        plan = _compute_scene_plan_skeleton(cards)
        assert "dialogue_expectation" not in plan[0]

    def test_falls_back_to_escalation_for_unknown_role(self):
        cards = [{"scene_number": 1, "scene_role": "weird_unknown_role", "target_word_count": 1000}]
        plan = _compute_scene_plan_skeleton(cards)
        assert plan[0]["role"] == "escalation"

    def test_falls_back_when_role_missing(self):
        cards = [{"scene_number": 1, "target_word_count": 1000}]
        plan = _compute_scene_plan_skeleton(cards)
        assert plan[0]["role"] == "escalation"


class TestComputeChapterWordTarget:
    def test_sum_of_targets(self):
        cards = [
            {"target_word_count": 1250},
            {"target_word_count": 1250},
            {"target_word_count": 1250},
        ]
        assert _compute_chapter_word_target(cards) == 3750

    def test_handles_missing_word_counts(self):
        assert _compute_chapter_word_target([{"target_word_count": 1000}, {}]) == 1000

    def test_empty_returns_zero(self):
        assert _compute_chapter_word_target([]) == 0


class TestComputeRevealPayload:
    def test_sorted_union(self):
        cards = [
            {"revelations": ["R03", "R01"]},
            {"revelations": ["R02", "R01"]},
            {"revelations": []},
        ]
        assert _compute_reveal_payload(cards) == ["R01", "R02", "R03"]

    def test_empty_when_no_revelations(self):
        cards = [{"revelations": []}, {}]
        assert _compute_reveal_payload(cards) == []

    def test_skips_non_string_entries(self):
        cards = [{"revelations": ["R01", None, 42, ""]}]
        assert _compute_reveal_payload(cards) == ["R01"]


class TestComputeHookMovements:
    def test_buckets_by_action_verb(self):
        cards = [
            {"hook_actions": [{"hook_id": "H01", "action": "plant"}]},
            {"hook_actions": [
                {"hook_id": "H01", "action": "advance"},
                {"hook_id": "H02", "action": "resolve"},
            ]},
        ]
        result = _compute_hook_movements(cards)
        assert result == {
            "planted": ["H01"],
            "advanced": ["H01"],
            "resolved": ["H02"],
        }

    def test_subvert_maps_to_resolved(self):
        cards = [{"hook_actions": [{"hook_id": "H03", "action": "subvert"}]}]
        result = _compute_hook_movements(cards)
        assert result["resolved"] == ["H03"]

    def test_unknown_action_is_skipped(self):
        cards = [{"hook_actions": [
            {"hook_id": "H01", "action": "plant"},
            {"hook_id": "H02", "action": "wiggle"},
        ]}]
        result = _compute_hook_movements(cards)
        assert result == {"planted": ["H01"], "advanced": [], "resolved": []}

    def test_empty_chapter_emits_three_empty_buckets(self):
        result = _compute_hook_movements([])
        assert result == {"planted": [], "advanced": [], "resolved": []}

    def test_dedupes_within_bucket(self):
        cards = [
            {"hook_actions": [{"hook_id": "H01", "action": "plant"}]},
            {"hook_actions": [{"hook_id": "H01", "action": "plant"}]},
        ]
        result = _compute_hook_movements(cards)
        assert result["planted"] == ["H01"]


class TestComputeSubplotObligations:
    def test_sorted_union(self):
        cards = [
            {"active_subplots": ["SP-A", "SP4"]},
            {"active_subplots": ["SP-A", "SP3"]},
        ]
        assert _compute_subplot_obligations(cards) == ["SP-A", "SP3", "SP4"]

    def test_empty_returns_empty(self):
        assert _compute_subplot_obligations([{"active_subplots": []}, {}]) == []


class TestComputeStructuralPhase:
    def test_uses_last_scene_phase(self):
        cards = [
            {"structural_phase": "setup"},
            {"structural_phase": "first_plot_point"},
        ]
        assert _compute_structural_phase(cards) == "first_plot_point"

    def test_empty_falls_back_to_setup(self):
        assert _compute_structural_phase([]) == "setup"

    def test_unknown_phase_falls_back_to_setup(self):
        assert _compute_structural_phase([{"structural_phase": "made_up"}]) == "setup"


# --------------------------------------------------------------------------- #
# Schema validation invariants                                                 #
# --------------------------------------------------------------------------- #


class TestRollupAlwaysEmitsOptionalFields:
    """Phase 5 design choice: optional fields always present (possibly empty)
    to match hand-authored Ruusan precedent."""

    def test_empty_chapter_emits_empty_optional_fields(self):
        rollup = _build_deterministic_rollup(1, [])
        assert rollup["pov_allocation"] == []
        assert rollup["scene_plan"] == []
        assert rollup["reveal_payload"] == []
        assert rollup["hook_movements"] == {"planted": [], "advanced": [], "resolved": []}
        assert rollup["subplot_obligations"] == []

    def test_chapter_with_no_hook_actions_still_emits_three_buckets(self):
        cards = [{"chapter_number": 1, "scene_number": 1, "scene_role": "hook", "target_word_count": 1000}]
        rollup = _build_deterministic_rollup(1, cards)
        assert "planted" in rollup["hook_movements"]
        assert "advanced" in rollup["hook_movements"]
        assert "resolved" in rollup["hook_movements"]


class TestMergeSynthesisIntoBlueprint:
    def test_merges_narrative_fields(self):
        rollup = _build_deterministic_rollup(1, [
            {"scene_number": 1, "scene_role": "hook", "target_word_count": 1000, "pov_character": "Ben"},
            {"scene_number": 2, "scene_role": "reveal", "target_word_count": 1000, "pov_character": "Ben"},
        ])
        synthesis = {
            "chapter_mission": "Establish the wrongness.",
            "chapter_turn": "Ben moves from passive to active.",
            "scene_purposes": [
                {"scene_number": 1, "purpose": "ground the wrongness"},
                {"scene_number": 2, "purpose": "validate and assign"},
            ],
            "pacing_curve": "rising",
            "exit_vector": "departure into hyperspace",
            "relationship_turns": [{"dyad": "Ben/Luke", "from": "distant", "to": "trusted"}],
            "notes": "Voice anchor: Zahn",
        }
        blueprint = _merge_synthesis_into_blueprint(rollup, synthesis)
        assert blueprint["chapter_mission"] == "Establish the wrongness."
        assert blueprint["chapter_turn"] == "Ben moves from passive to active."
        assert blueprint["pacing_curve"] == "rising"
        assert blueprint["exit_vector"] == "departure into hyperspace"
        assert blueprint["scene_plan"][0]["purpose"] == "ground the wrongness"
        assert blueprint["scene_plan"][1]["purpose"] == "validate and assign"
        assert blueprint["relationship_turns"] == [{"dyad": "Ben/Luke", "from": "distant", "to": "trusted"}]
        assert blueprint["notes"] == "Voice anchor: Zahn"

    def test_invalid_pacing_curve_falls_back_to_mixed(self):
        rollup = _build_deterministic_rollup(1, [
            {"scene_number": 1, "scene_role": "hook", "target_word_count": 1000},
        ])
        blueprint = _merge_synthesis_into_blueprint(rollup, {
            "chapter_mission": "x", "chapter_turn": "y",
            "scene_purposes": [{"scene_number": 1, "purpose": "z"}],
            "pacing_curve": "exploding",
            "exit_vector": "v",
        })
        assert blueprint["pacing_curve"] == "mixed"

    def test_filters_malformed_relationship_turns(self):
        rollup = _build_deterministic_rollup(1, [
            {"scene_number": 1, "scene_role": "hook", "target_word_count": 1000},
        ])
        blueprint = _merge_synthesis_into_blueprint(rollup, {
            "chapter_mission": "x", "chapter_turn": "y",
            "scene_purposes": [], "pacing_curve": "rising", "exit_vector": "v",
            "relationship_turns": [
                {"dyad": "Ben/Luke", "from": "a", "to": "b"},  # valid
                {"dyad": "Bad"},  # missing from/to
                "not a dict",
            ],
        })
        assert blueprint["relationship_turns"] == [{"dyad": "Ben/Luke", "from": "a", "to": "b"}]


class TestSchemaValidation:
    def test_generated_blueprint_validates_against_schema(self, schema, multi_scene_chapter_cards):
        rollup = _build_deterministic_rollup(5, multi_scene_chapter_cards)
        synthesis = {
            "chapter_mission": "Alex pivots from passive observation to active confrontation.",
            "chapter_turn": "Trust between Alex and Jordan inverts and rebuilds on harder terms.",
            "scene_purposes": [
                {"scene_number": 1, "purpose": "Alex finds the hidden logs"},
                {"scene_number": 2, "purpose": "the confrontation"},
                {"scene_number": 3, "purpose": "the envelope reveals the conspiracy"},
            ],
            "pacing_curve": "rising",
            "exit_vector": "Alex pulled toward Voss with a target on her back",
            "relationship_turns": [
                {"dyad": "Alex/Jordan", "from": "professional partners", "to": "co-conspirators against Voss"},
            ],
            "notes": "",
        }
        blueprint = _merge_synthesis_into_blueprint(rollup, synthesis)
        # Should not raise
        jsonschema.validate(blueprint, schema)


class TestIdPurity:
    """No-hallucination invariant: the deterministic rollup IDs must be a
    subset of the IDs present in the source scene cards."""

    def test_reveal_payload_subset_of_scene_revelations(self, multi_scene_chapter_cards):
        rollup = _build_deterministic_rollup(5, multi_scene_chapter_cards)
        scene_ids = set()
        for c in multi_scene_chapter_cards:
            scene_ids.update(c.get("revelations", []))
        assert set(rollup["reveal_payload"]).issubset(scene_ids)

    def test_hook_movements_subset_of_scene_hook_actions(self, multi_scene_chapter_cards):
        rollup = _build_deterministic_rollup(5, multi_scene_chapter_cards)
        scene_hook_ids = set()
        for c in multi_scene_chapter_cards:
            for entry in c.get("hook_actions", []):
                scene_hook_ids.add(entry["hook_id"])
        all_bucket_ids = set(rollup["hook_movements"]["planted"]) | set(
            rollup["hook_movements"]["advanced"]) | set(rollup["hook_movements"]["resolved"])
        assert all_bucket_ids.issubset(scene_hook_ids)

    def test_subplot_obligations_subset_of_scene_active_subplots(self, multi_scene_chapter_cards):
        rollup = _build_deterministic_rollup(5, multi_scene_chapter_cards)
        scene_subplot_ids = set()
        for c in multi_scene_chapter_cards:
            scene_subplot_ids.update(c.get("active_subplots", []))
        assert set(rollup["subplot_obligations"]).issubset(scene_subplot_ids)


# --------------------------------------------------------------------------- #
# Synthesizer card filter                                                      #
# --------------------------------------------------------------------------- #


class TestFilterSceneCardForSynthesizer:
    def test_drops_voice_specific_fields(self, multi_scene_chapter_cards):
        filtered = _filter_scene_card_for_synthesizer(multi_scene_chapter_cards[0])
        assert "mission" in filtered
        assert "turning_point" in filtered
        assert "stakes" in filtered
        # Voice/draft-specific fields dropped
        assert "sensory_details" not in filtered
        assert "action_beats" not in filtered
        assert "canon_elements_needed" not in filtered
        assert "notes" not in filtered

    def test_preserves_id_carrying_fields(self, multi_scene_chapter_cards):
        filtered = _filter_scene_card_for_synthesizer(multi_scene_chapter_cards[1])
        assert "hook_actions" in filtered
        assert "revelations" in filtered
        assert "active_subplots" in filtered


class TestBuildConceptExcerpt:
    def test_picks_only_relevant_keys(self):
        seed = {
            "revelations": [{"id": "R01"}],
            "hooks": [{"id": "H01"}],
            "subplots": [{"id": "SP-A"}],
            "ensemble_cast": [{"name": "Ben"}],
            "theme": {"thematic_premise": "x"},
            "premise": {"logline": "y"},
            "meta": {"project_title": "test"},  # NOT in excerpt
            "voice_definition": {},  # NOT in excerpt
        }
        excerpt = _build_concept_excerpt(seed)
        assert set(excerpt.keys()) == {
            "revelations", "hooks", "subplots", "ensemble_cast", "theme", "premise"
        }

    def test_handles_missing_keys(self):
        excerpt = _build_concept_excerpt({"revelations": []})
        assert excerpt == {"revelations": []}


# --------------------------------------------------------------------------- #
# save_blueprints — hand-authored precedence                                   #
# --------------------------------------------------------------------------- #


class TestSaveBlueprints:
    def test_writes_to_canonical_path(self, tmp_path):
        bp = {"chapter_number": 1, "chapter_mission": "x"}
        written = save_blueprints(
            [bp], "test-franchise", "test-book", base_dir=str(tmp_path),
        )
        expected = tmp_path / "data" / "franchises" / "test-franchise" / "books" / "test-book" / "chapter_blueprints" / "chapter_01.json"
        assert expected.exists()
        assert written == [expected]
        loaded = json.loads(expected.read_text(encoding="utf-8"))
        assert loaded == bp

    def test_skips_existing(self, tmp_path, caplog):
        sentinel = {"chapter_number": 1, "chapter_mission": "HAND_AUTHORED"}
        bp_dir = tmp_path / "data" / "franchises" / "fr" / "books" / "bk" / "chapter_blueprints"
        bp_dir.mkdir(parents=True)
        (bp_dir / "chapter_01.json").write_text(json.dumps(sentinel), encoding="utf-8")

        new_bp = {"chapter_number": 1, "chapter_mission": "GENERATED"}
        written = save_blueprints([new_bp], "fr", "bk", base_dir=str(tmp_path))

        assert written == []  # nothing written
        # sentinel preserved
        loaded = json.loads((bp_dir / "chapter_01.json").read_text(encoding="utf-8"))
        assert loaded == sentinel

    def test_force_overwrites(self, tmp_path):
        sentinel = {"chapter_number": 1, "chapter_mission": "OLD"}
        bp_dir = tmp_path / "data" / "franchises" / "fr" / "books" / "bk" / "chapter_blueprints"
        bp_dir.mkdir(parents=True)
        (bp_dir / "chapter_01.json").write_text(json.dumps(sentinel), encoding="utf-8")

        new_bp = {"chapter_number": 1, "chapter_mission": "NEW"}
        written = save_blueprints([new_bp], "fr", "bk", base_dir=str(tmp_path), force=True)

        assert len(written) == 1
        loaded = json.loads((bp_dir / "chapter_01.json").read_text(encoding="utf-8"))
        assert loaded["chapter_mission"] == "NEW"

    def test_base_dir_isolation(self, tmp_path):
        """Tests must not pollute real data/franchises/."""
        save_blueprints(
            [{"chapter_number": 99, "chapter_mission": "x"}],
            "isolated-test-franchise", "isolated-test-book",
            base_dir=str(tmp_path),
        )
        # Real data directory should not have been touched
        real_path = Path("data") / "franchises" / "isolated-test-franchise"
        assert not real_path.exists()

    def test_skips_blueprint_without_chapter_number(self, tmp_path):
        written = save_blueprints(
            [{"chapter_mission": "no chapter number"}],
            "fr", "bk", base_dir=str(tmp_path),
        )
        assert written == []


# --------------------------------------------------------------------------- #
# ChapterBlueprintSynthesizer fallback behavior                                #
# --------------------------------------------------------------------------- #


class TestSynthesizerFallback:
    @pytest.mark.asyncio
    async def test_returns_empty_narrative_on_parse_failure(self, multi_scene_chapter_cards):
        router = MagicMock()
        router.complete_structured = AsyncMock(side_effect=json.JSONDecodeError("nope", "", 0))
        synth = ChapterBlueprintSynthesizer(router)
        result = await synth.run({
            "chapter_number": 5,
            "scene_cards": multi_scene_chapter_cards,
            "deterministic_rollup": _build_deterministic_rollup(5, multi_scene_chapter_cards),
            "concept_excerpt": {},
        })
        assert result["chapter_mission"] == ""
        assert result["chapter_turn"] == ""
        assert "Synthesizer parse failure" in result["notes"]
        assert len(result["scene_purposes"]) == len(multi_scene_chapter_cards)

    @pytest.mark.asyncio
    async def test_returns_empty_narrative_on_non_dict_response(self, multi_scene_chapter_cards):
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value="just a string, not a dict")
        synth = ChapterBlueprintSynthesizer(router)
        result = await synth.run({
            "chapter_number": 5,
            "scene_cards": multi_scene_chapter_cards,
            "deterministic_rollup": _build_deterministic_rollup(5, multi_scene_chapter_cards),
            "concept_excerpt": {},
        })
        assert result["chapter_mission"] == ""
        assert "non-dict" in result["notes"]


# --------------------------------------------------------------------------- #
# End-to-end generator with mocked synthesizer                                 #
# --------------------------------------------------------------------------- #


class TestChapterBlueprintGenerator:
    @pytest.mark.asyncio
    async def test_generate_returns_one_blueprint_per_chapter(self, multi_scene_chapter_cards):
        # Synthesizer returns the same canned narrative payload for any chapter
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_mission": "x", "chapter_turn": "y",
            "scene_purposes": [
                {"scene_number": 1, "purpose": "p1"},
                {"scene_number": 2, "purpose": "p2"},
                {"scene_number": 3, "purpose": "p3"},
            ],
            "pacing_curve": "rising", "exit_vector": "v",
            "relationship_turns": [], "notes": "",
        })
        gen = ChapterBlueprintGenerator(router)
        blueprints = await gen.generate({"revelations": []}, multi_scene_chapter_cards)
        assert len(blueprints) == 1
        assert blueprints[0]["chapter_number"] == 5
        assert blueprints[0]["scene_count"] == 3

    @pytest.mark.asyncio
    async def test_empty_scene_cards_returns_empty_list(self):
        router = MagicMock()
        gen = ChapterBlueprintGenerator(router)
        assert await gen.generate({}, []) == []

    @pytest.mark.asyncio
    async def test_groups_cards_by_chapter(self):
        cards = [
            {"chapter_number": 1, "scene_number": 1, "scene_role": "hook", "target_word_count": 1000, "pov_character": "A"},
            {"chapter_number": 2, "scene_number": 1, "scene_role": "hook", "target_word_count": 1000, "pov_character": "B"},
            {"chapter_number": 1, "scene_number": 2, "scene_role": "reveal", "target_word_count": 1000, "pov_character": "A"},
        ]
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_mission": "", "chapter_turn": "",
            "scene_purposes": [], "pacing_curve": "rising", "exit_vector": "",
            "relationship_turns": [], "notes": "",
        })
        gen = ChapterBlueprintGenerator(router)
        blueprints = await gen.generate({}, cards)
        assert [b["chapter_number"] for b in blueprints] == [1, 2]
        assert blueprints[0]["scene_count"] == 2
        assert blueprints[1]["scene_count"] == 1


# --------------------------------------------------------------------------- #
# Acceptance: Ruusan ch1 deterministic equivalence                             #
# --------------------------------------------------------------------------- #


class TestRuusanChapter1Equivalence:
    """Acceptance criterion: when the synthesizer returns the hand-authored
    narrative fields, the resulting blueprint's deterministic fields must
    match the hand-authored Ruusan ch1 blueprint exactly."""

    @pytest.mark.asyncio
    async def test_deterministic_fields_match_hand_authored(
        self, ruusan_chapter_1_cards, ruusan_chapter_1_blueprint, schema,
    ):
        # Mock synthesizer to return the hand-authored narrative fields,
        # mapping scene_plan purposes back into scene_purposes shape.
        scene_purposes = [
            {"scene_number": s["scene_number"], "purpose": s["purpose"]}
            for s in ruusan_chapter_1_blueprint["scene_plan"]
        ]
        synthesizer_payload = {
            "chapter_mission": ruusan_chapter_1_blueprint["chapter_mission"],
            "chapter_turn": ruusan_chapter_1_blueprint["chapter_turn"],
            "scene_purposes": scene_purposes,
            "pacing_curve": ruusan_chapter_1_blueprint["pacing_curve"],
            "exit_vector": ruusan_chapter_1_blueprint["exit_vector"],
            "relationship_turns": ruusan_chapter_1_blueprint["relationship_turns"],
            "notes": ruusan_chapter_1_blueprint["notes"],
        }
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value=synthesizer_payload)

        gen = ChapterBlueprintGenerator(router)
        blueprints = await gen.generate({}, ruusan_chapter_1_cards)
        assert len(blueprints) == 1
        generated = blueprints[0]

        # Schema validity first
        jsonschema.validate(generated, schema)

        # Deterministic field-by-field equivalence
        assert generated["chapter_number"] == ruusan_chapter_1_blueprint["chapter_number"]
        assert generated["scene_count"] == ruusan_chapter_1_blueprint["scene_count"]
        assert generated["chapter_word_target"] == ruusan_chapter_1_blueprint["chapter_word_target"]
        assert generated["pov_allocation"] == ruusan_chapter_1_blueprint["pov_allocation"]
        assert generated["structural_phase"] == ruusan_chapter_1_blueprint["structural_phase"]
        assert generated["reveal_payload"] == ruusan_chapter_1_blueprint["reveal_payload"]
        assert generated["subplot_obligations"] == sorted(ruusan_chapter_1_blueprint["subplot_obligations"])
        assert generated["hook_movements"] == ruusan_chapter_1_blueprint["hook_movements"]

        # scene_plan: same length, same role/word_count/dialogue_expectation per scene
        assert len(generated["scene_plan"]) == len(ruusan_chapter_1_blueprint["scene_plan"])
        for gen_scene, hand_scene in zip(
            generated["scene_plan"], ruusan_chapter_1_blueprint["scene_plan"]
        ):
            assert gen_scene["scene_number"] == hand_scene["scene_number"]
            assert gen_scene["role"] == hand_scene["role"]
            assert gen_scene["target_word_count"] == hand_scene["target_word_count"]
            # dialogue_expectation is optional in scene cards; skip strict equality
            # if either side omits it
            if "dialogue_expectation" in gen_scene and "dialogue_expectation" in hand_scene:
                assert gen_scene["dialogue_expectation"] == hand_scene["dialogue_expectation"]
