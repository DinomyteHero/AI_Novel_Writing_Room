"""Structural validation for schemas/chapter_blueprint.json.

Phase 2 defines the schema; Phase 3 wires the Chapter Gate Critic to consume
it. These tests confirm the schema file is well-formed and matches the Phase 2
spec field set. No runtime schema validation exists in the codebase — these
tests are structural only.
"""

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "chapter_blueprint.json"


def _load() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestSchemaTopLevel:
    def test_schema_is_valid_json(self):
        assert isinstance(_load(), dict)

    def test_uses_draft7(self):
        assert _load()["$schema"] == "http://json-schema.org/draft-07/schema#"

    def test_title_and_type(self):
        schema = _load()
        assert schema["title"] == "ChapterBlueprint"
        assert schema["type"] == "object"


class TestRequiredFields:
    def test_required_list_matches_spec(self):
        """Required fields per spec §Chapter blueprint schema: chapter_number,
        chapter_mission, chapter_turn, structural_phase, scene_count,
        scene_plan, chapter_word_target."""
        schema = _load()
        assert set(schema["required"]) == {
            "chapter_number",
            "chapter_mission",
            "chapter_turn",
            "structural_phase",
            "scene_count",
            "scene_plan",
            "chapter_word_target",
        }


class TestAllSpecFieldsPresent:
    SPEC_FIELDS = {
        "chapter_number",
        "chapter_mission",
        "chapter_turn",
        "structural_phase",
        "pov_allocation",
        "scene_count",
        "scene_plan",
        "reveal_payload",
        "hook_movements",
        "subplot_obligations",
        "relationship_turns",
        "pacing_curve",
        "exit_vector",
        "chapter_word_target",
        "notes",
    }

    def test_all_fields_declared(self):
        schema = _load()
        assert self.SPEC_FIELDS.issubset(set(schema["properties"].keys()))


class TestNestedStructures:
    def test_scene_plan_items_match_spec(self):
        schema = _load()
        items = schema["properties"]["scene_plan"]["items"]
        assert items["type"] == "object"
        # Required at minimum: scene_number, role, target_word_count, purpose
        assert {"scene_number", "role", "target_word_count", "purpose"}.issubset(
            set(items["required"])
        )
        # dialogue_expectation present as optional property
        assert "dialogue_expectation" in items["properties"]

    def test_scene_plan_role_enum_matches_scene_card(self):
        """The scene_plan.role enum must match scene_card.scene_role."""
        schema = _load()
        role_enum = schema["properties"]["scene_plan"]["items"]["properties"]["role"]["enum"]
        assert set(role_enum) == {
            "hook", "escalation", "reveal", "decision", "aftermath",
            "decision_and_plant",
        }

    def test_dialogue_expectation_enum_matches_scene_card(self):
        schema = _load()
        de = schema["properties"]["scene_plan"]["items"]["properties"]["dialogue_expectation"]
        assert set(de["enum"]) == {"dialogue_led", "balanced", "interior"}

    def test_structural_phase_enum_matches_scene_card(self):
        """structural_phase enum must match the scene_card enum."""
        schema = _load()
        sp_enum = schema["properties"]["structural_phase"]["enum"]
        expected = {
            "setup", "first_plot_point", "response", "first_pinch",
            "midpoint", "attack", "second_pinch", "second_plot_point",
            "resolution", "climax",
        }
        assert set(sp_enum) == expected

    def test_hook_movements_has_three_arrays(self):
        schema = _load()
        hm_props = schema["properties"]["hook_movements"]["properties"]
        for key in ("planted", "advanced", "resolved"):
            assert hm_props[key]["type"] == "array"
            assert hm_props[key]["items"]["type"] == "string"

    def test_relationship_turns_items_have_dyad_from_to(self):
        schema = _load()
        items = schema["properties"]["relationship_turns"]["items"]
        assert items["type"] == "object"
        assert set(items["required"]) == {"dyad", "from", "to"}

    def test_pacing_curve_enum(self):
        schema = _load()
        pc = schema["properties"]["pacing_curve"]
        assert set(pc["enum"]) == {"rising", "falling", "steady", "mixed"}

    def test_chapter_word_target_is_positive_integer(self):
        schema = _load()
        cwt = schema["properties"]["chapter_word_target"]
        assert cwt["type"] == "integer"
        assert cwt["minimum"] == 1


class TestConsistencyWithSceneCard:
    """Where fields overlap with scene_card.json, enum values must match to
    avoid chapter-scene mismatches when Phase 3 wires the Chapter Gate."""

    def test_scene_card_schema_exists_and_shares_enums(self):
        scene_card_path = Path(__file__).parent.parent / "schemas" / "scene_card.json"
        with open(scene_card_path, encoding="utf-8") as f:
            scene_card = json.load(f)
        blueprint = _load()

        # Compare structural_phase enum
        assert (
            scene_card["properties"]["structural_phase"]["enum"]
            == blueprint["properties"]["structural_phase"]["enum"]
        )
        # Compare scene_role enum
        assert (
            scene_card["properties"]["scene_role"]["enum"]
            == blueprint["properties"]["scene_plan"]["items"]["properties"]["role"]["enum"]
        )
        # Compare dialogue_expectation enum
        assert (
            scene_card["properties"]["dialogue_expectation"]["enum"]
            == blueprint["properties"]["scene_plan"]["items"]["properties"]["dialogue_expectation"]["enum"]
        )


class TestRuusanChapter1Blueprint:
    """Phase 2 spec verification criterion 3: the Ruusan chapter 1 blueprint
    validates against the schema. This exercises the schema against a real
    reverse-derived instance, not just a synthetic fixture."""

    RUUSAN_BLUEPRINT_PATH = (
        Path(__file__).parent.parent
        / "data"
        / "franchises"
        / "star-wars-legends-eu"
        / "books"
        / "the-ruusan-atonement"
        / "chapter_blueprints"
        / "chapter_01.json"
    )

    def _load_blueprint(self) -> dict:
        with open(self.RUUSAN_BLUEPRINT_PATH, encoding="utf-8") as f:
            return json.load(f)

    def test_blueprint_file_exists(self):
        assert self.RUUSAN_BLUEPRINT_PATH.exists(), (
            f"Ruusan chapter 1 blueprint not found at {self.RUUSAN_BLUEPRINT_PATH}"
        )

    def test_blueprint_has_all_required_fields(self):
        schema = _load()
        blueprint = self._load_blueprint()
        missing = [f for f in schema["required"] if f not in blueprint]
        assert missing == [], f"missing required fields: {missing}"

    def test_blueprint_scene_plan_items_have_required_fields(self):
        schema = _load()
        blueprint = self._load_blueprint()
        scene_plan_required = schema["properties"]["scene_plan"]["items"]["required"]
        for i, scene in enumerate(blueprint["scene_plan"]):
            missing = [f for f in scene_plan_required if f not in scene]
            assert missing == [], (
                f"scene_plan[{i}] (scene {scene.get('scene_number')}) missing: {missing}"
            )

    def test_blueprint_enums_are_valid(self):
        schema = _load()
        blueprint = self._load_blueprint()

        sp_enum = schema["properties"]["structural_phase"]["enum"]
        assert blueprint["structural_phase"] in sp_enum

        role_enum = schema["properties"]["scene_plan"]["items"]["properties"]["role"]["enum"]
        de_enum = schema["properties"]["scene_plan"]["items"]["properties"]["dialogue_expectation"]["enum"]
        for scene in blueprint["scene_plan"]:
            assert scene["role"] in role_enum
            if "dialogue_expectation" in scene:
                assert scene["dialogue_expectation"] in de_enum

        pc_enum = schema["properties"]["pacing_curve"]["enum"]
        if "pacing_curve" in blueprint:
            assert blueprint["pacing_curve"] in pc_enum

    def test_scene_count_matches_scene_plan_length(self):
        blueprint = self._load_blueprint()
        assert blueprint["scene_count"] == len(blueprint["scene_plan"])

    def test_chapter_word_target_matches_sum_of_scene_targets(self):
        """Semantic consistency: chapter_word_target should equal the sum of
        scene_plan[].target_word_count. Not a schema rule, but a sanity check
        for a hand-authored blueprint."""
        blueprint = self._load_blueprint()
        scene_sum = sum(s["target_word_count"] for s in blueprint["scene_plan"])
        assert blueprint["chapter_word_target"] == scene_sum

    def test_chapter_number_is_one(self):
        blueprint = self._load_blueprint()
        assert blueprint["chapter_number"] == 1

    def test_scene_numbers_are_sequential(self):
        blueprint = self._load_blueprint()
        numbers = [s["scene_number"] for s in blueprint["scene_plan"]]
        assert numbers == sorted(numbers) == list(range(1, len(numbers) + 1))
