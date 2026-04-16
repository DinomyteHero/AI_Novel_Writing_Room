"""Structural validation for schemas/generation_brief.json.

The codebase does not use runtime JSON Schema validation via `jsonschema` —
schemas are documentation and LLM-output contracts. These tests confirm the
schema file is well-formed JSON with the expected top-level shape, and that
every field named in the Phase 2 spec is present.
"""

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "generation_brief.json"


def _load() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestSchemaTopLevel:
    def test_schema_is_valid_json(self):
        schema = _load()
        assert isinstance(schema, dict)

    def test_uses_draft7(self):
        schema = _load()
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"

    def test_title_and_type(self):
        schema = _load()
        assert schema["title"] == "GenerationBrief"
        assert schema["type"] == "object"

    def test_has_description(self):
        schema = _load()
        assert "description" in schema
        assert "planner" in schema["description"].lower()


class TestRequiredFields:
    def test_required_list_matches_spec(self):
        """Required fields must match the Phase 2 spec: scene_objective,
        turning_point, closing_beat, emotional_arc, target_word_count."""
        schema = _load()
        assert set(schema["required"]) == {
            "scene_objective",
            "turning_point",
            "closing_beat",
            "emotional_arc",
            "target_word_count",
        }


class TestAllSpecFieldsPresent:
    """Every field named in spec §Typed generation brief schema must appear
    in `properties`, whether required or optional."""

    SPEC_FIELDS = {
        "scene_objective",
        "opening_mode",
        "key_beats",
        "turning_point",
        "closing_beat",
        "emotional_arc",
        "voice_guidance",
        "forbidden_moves",
        "delivery_preferences",
        "required_hooks",
        "required_subplots",
        "required_revelations",
        "anti_patterns",
        "target_word_count",
    }

    def test_all_fields_declared(self):
        schema = _load()
        assert self.SPEC_FIELDS.issubset(set(schema["properties"].keys()))


class TestNestedStructures:
    def test_turning_point_is_object_with_trigger_shift_cost(self):
        schema = _load()
        tp = schema["properties"]["turning_point"]
        assert tp["type"] == "object"
        assert set(tp["required"]) == {"trigger", "shift", "cost"}

    def test_emotional_arc_is_object_with_start_shift_end(self):
        schema = _load()
        ea = schema["properties"]["emotional_arc"]
        assert ea["type"] == "object"
        assert set(ea["required"]) == {"start", "shift", "end"}

    def test_key_beats_is_array_of_objects_with_three_fields(self):
        schema = _load()
        kb = schema["properties"]["key_beats"]
        assert kb["type"] == "array"
        item = kb["items"]
        assert item["type"] == "object"
        assert set(item["required"]) == {"beat_description", "state_change", "pov_reaction"}

    def test_opening_mode_enum(self):
        schema = _load()
        om = schema["properties"]["opening_mode"]
        assert om["type"] == "string"
        assert set(om["enum"]) == {"in_medias_res", "sensory_hook", "dialogue_hook", "contrast"}

    def test_delivery_preferences_enums(self):
        schema = _load()
        dp = schema["properties"]["delivery_preferences"]["properties"]
        assert set(dp["reveal_mode"]["enum"]) == {"direct", "gradual", "subtext"}
        assert set(dp["exposition_budget"]["enum"]) == {"concise", "moderate", "none"}
        # register_override allows null per spec
        assert "null" in dp["register_override"]["type"]

    def test_target_word_count_is_positive_integer(self):
        schema = _load()
        twc = schema["properties"]["target_word_count"]
        assert twc["type"] == "integer"
        assert twc["minimum"] == 1


class TestArrayFields:
    """String-array fields that Prose Stylist surfaces as bullet lists."""

    STRING_ARRAY_FIELDS = ["forbidden_moves", "required_hooks", "required_subplots",
                            "required_revelations", "anti_patterns"]

    def test_all_string_arrays_declared(self):
        schema = _load()
        for field in self.STRING_ARRAY_FIELDS:
            prop = schema["properties"][field]
            assert prop["type"] == "array"
            assert prop["items"]["type"] == "string"
