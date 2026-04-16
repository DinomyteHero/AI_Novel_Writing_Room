"""Phase 3: validate the voice_definition default template against the live
sub-schema extracted from schemas/concept_seed.json.
"""

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema", reason="jsonschema not installed")


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "templates" / "voice_definition" / "default.json"
CONCEPT_SEED_SCHEMA = REPO_ROOT / "schemas" / "concept_seed.json"


def _voice_definition_sub_schema() -> dict:
    full = json.loads(CONCEPT_SEED_SCHEMA.read_text(encoding="utf-8"))
    return full["properties"]["voice_definition"]


def _load_template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


class TestVoiceDefinitionDefaultTemplate:
    def test_template_exists(self):
        assert TEMPLATE_PATH.exists(), f"missing template: {TEMPLATE_PATH}"

    def test_validates_against_sub_schema(self):
        schema = _voice_definition_sub_schema()
        template = _load_template()
        template.pop("_template_notes", None)
        jsonschema.validate(instance=template, schema=schema)

    def test_has_template_notes(self):
        template = _load_template()
        notes = template.get("_template_notes")
        assert isinstance(notes, str) and len(notes) > 50

    def test_has_universal_anti_slop_rules(self):
        """The default template ships with a starter set of franchise-agnostic
        anti-slop rules. These are the Phase 3 baseline; if the count falls
        below 5 a reviewer has likely pruned too aggressively."""
        template = _load_template()
        rules = template.get("anti_slop_rules", [])
        assert len(rules) >= 5, (
            f"default voice template should carry at least 5 universal "
            f"anti-slop rules (got {len(rules)})"
        )

    def test_reference_authors_and_character_voices_start_empty(self):
        """The concept workshop or hand-authoring fills these in; the
        default scaffold must not bake in project-specific content."""
        template = _load_template()
        assert template.get("reference_authors") == []
        assert template.get("character_voices") == {}

    def test_no_force_description_guidelines(self):
        """force_description_guidelines is Star-Wars-specific and must
        not appear in the universal default template."""
        template = _load_template()
        assert "force_description_guidelines" not in template
