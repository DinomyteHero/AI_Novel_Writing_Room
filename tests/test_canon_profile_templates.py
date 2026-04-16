"""Phase 3: validate the canon_profile templates against the live sub-schema
extracted from schemas/concept_seed.json.

Extracting the sub-schema at test time (rather than freezing a copy) means
when concept_seed.json's canon_profile definition evolves, these templates
fail loudly until they are updated — preventing silent drift.
"""

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema", reason="jsonschema not installed")


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "templates" / "canon_profile"
CONCEPT_SEED_SCHEMA = REPO_ROOT / "schemas" / "concept_seed.json"

TEMPLATE_NAMES = [
    "fanfic_elseworlds",
    "fanfic_compliant",
    "original_deep",
    "original_light",
    "realistic",
]


def _canon_profile_sub_schema() -> dict:
    """Extract the canon_profile sub-schema from the live concept_seed.json."""
    full = json.loads(CONCEPT_SEED_SCHEMA.read_text(encoding="utf-8"))
    return full["properties"]["canon_profile"]


def _load_template(name: str) -> dict:
    return json.loads((TEMPLATES_DIR / f"{name}.json").read_text(encoding="utf-8"))


class TestTemplatesExist:
    def test_all_five_templates_exist(self):
        for name in TEMPLATE_NAMES:
            path = TEMPLATES_DIR / f"{name}.json"
            assert path.exists(), f"missing template: {path}"

    def test_no_extra_template_files(self):
        actual = {p.stem for p in TEMPLATES_DIR.glob("*.json")}
        expected = set(TEMPLATE_NAMES)
        assert actual == expected, (
            f"canon_profile/ should contain exactly the 5 locked templates; "
            f"got {sorted(actual)}"
        )


class TestTemplatesMatchSubSchema:
    """Each template, after stripping the _template_notes metadata key,
    must validate against the canon_profile sub-schema."""

    @pytest.mark.parametrize("name", TEMPLATE_NAMES)
    def test_template_validates(self, name):
        schema = _canon_profile_sub_schema()
        template = _load_template(name)
        # Strip the loader-only metadata key before validation.
        template.pop("_template_notes", None)
        jsonschema.validate(instance=template, schema=schema)

    @pytest.mark.parametrize("name", TEMPLATE_NAMES)
    def test_template_has_notes(self, name):
        """Every template must carry a _template_notes string so that
        authors picking a template see why they would choose it."""
        template = _load_template(name)
        notes = template.get("_template_notes")
        assert isinstance(notes, str) and len(notes) > 50, (
            f"template {name} must have a _template_notes string describing "
            f"when to pick it (got {notes!r})"
        )


class TestTemplateStructureByProfile:
    """Cross-template invariants locked by the Phase 3 roadmap."""

    def test_elseworlds_has_populated_violations_and_terms(self):
        tpl = _load_template("fanfic_elseworlds")
        assert len(tpl["cross_continuity_violations"]) >= 1
        assert len(tpl["anachronistic_terms"]) >= 1

    def test_fanfic_compliant_has_larger_violation_list(self):
        """Compliant mode is stricter; its violations list should be longer
        than the Elseworlds illustrative list."""
        elseworlds = _load_template("fanfic_elseworlds")
        compliant = _load_template("fanfic_compliant")
        assert len(compliant["cross_continuity_violations"]) >= len(
            elseworlds["cross_continuity_violations"]
        )

    def test_original_profiles_have_empty_cross_continuity(self):
        """Original fiction has no external canon to cross with, so the
        cross_continuity_violations list must be empty."""
        for name in ["original_deep", "original_light", "realistic"]:
            tpl = _load_template(name)
            assert tpl["cross_continuity_violations"] == [], (
                f"{name} must have empty cross_continuity_violations "
                f"(got {tpl['cross_continuity_violations']})"
            )

    def test_realistic_has_minimal_canon(self):
        """Realistic / literary fiction has near-empty canon constraints."""
        tpl = _load_template("realistic")
        assert tpl["cross_continuity_violations"] == []
        assert tpl["anachronistic_terms"] == {}

    def test_original_profiles_use_original_franchise_marker(self):
        for name in ["original_deep", "original_light", "realistic"]:
            tpl = _load_template(name)
            assert tpl["franchise"] == "original", (
                f"{name} should declare franchise='original' "
                f"(got {tpl['franchise']!r})"
            )
