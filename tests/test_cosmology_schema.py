"""Phase 2: validate the new cosmology_meta.json schema and the additive
fields on universe_meta.json.

Uses jsonschema for runtime validation (no project code relies on this
library at runtime in Phase 2; it is a test-only dependency used here to
exercise the schema documents as contracts)."""

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema", reason="jsonschema not installed")


SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _load(schema_name: str) -> dict:
    return json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))


class TestCosmologyMetaSchema:
    def test_valid_cosmology_meta(self):
        schema = _load("cosmology_meta.json")
        valid = {
            "cosmology_id": "test-cosmo",
            "cosmology_name": "Test Cosmology",
            "description": "A shared creation myth across member universes.",
            "shared_lore": ["Investiture", "Shards"],
            "shared_rules": ["Magic stems from Investiture"],
            "member_universes": ["roshar", "scadrial"],
        }
        jsonschema.validate(instance=valid, schema=schema)

    def test_minimal_valid_cosmology_meta(self):
        schema = _load("cosmology_meta.json")
        minimal = {
            "cosmology_id": "test-cosmo",
            "cosmology_name": "Test Cosmology",
        }
        jsonschema.validate(instance=minimal, schema=schema)

    def test_missing_cosmology_id_fails(self):
        schema = _load("cosmology_meta.json")
        invalid = {"cosmology_name": "Test Cosmology"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid, schema=schema)

    def test_missing_cosmology_name_fails(self):
        schema = _load("cosmology_meta.json")
        invalid = {"cosmology_id": "test-cosmo"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid, schema=schema)

    def test_non_kebab_case_cosmology_id_fails(self):
        schema = _load("cosmology_meta.json")
        invalid = {
            "cosmology_id": "Test Cosmo",  # uppercase + whitespace
            "cosmology_name": "Test Cosmology",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid, schema=schema)


class TestUniverseMetaExtensions:
    """Phase 2 additions: cosmology_id, branch_point, commercial_intent are
    all optional. Existing universe_meta documents must still validate."""

    def test_legacy_universe_meta_still_valid(self):
        schema = _load("universe_meta.json")
        legacy = {
            "universe_name": "Star Wars Legends EU",
            "franchise": "star-wars-legends-eu",
            "canon_status": "AU",
            "notes": "Ruusan Atonement",
        }
        jsonschema.validate(instance=legacy, schema=schema)

    def test_universe_meta_with_cosmology_id(self):
        schema = _load("universe_meta.json")
        extended = {
            "universe_name": "Roshar",
            "franchise": "stormlight-archive",
            "canon_status": "original",
            "cosmology_id": "the-cosmere",
        }
        jsonschema.validate(instance=extended, schema=schema)

    def test_universe_meta_with_branch_point(self):
        schema = _load("universe_meta.json")
        extended = {
            "universe_name": "Ruusan AU",
            "franchise": "star-wars-legends-eu",
            "canon_status": "AU",
            "branch_point": {
                "source_canon": "Star Wars Legends EU",
                "divergence_point": "post-Lost Tribe crisis, 44 ABY",
                "divergence_description": "The Sith never return as expected.",
            },
        }
        jsonschema.validate(instance=extended, schema=schema)

    def test_universe_meta_with_commercial_intent(self):
        schema = _load("universe_meta.json")
        for intent in [
            "fanfiction_noncommercial",
            "fanfiction_monetized",
            "commercial_original",
            "commercial_licensed",
            "private",
        ]:
            extended = {
                "universe_name": "Test",
                "franchise": "test",
                "commercial_intent": intent,
            }
            jsonschema.validate(instance=extended, schema=schema)

    def test_invalid_commercial_intent_fails(self):
        schema = _load("universe_meta.json")
        invalid = {
            "universe_name": "Test",
            "franchise": "test",
            "commercial_intent": "made_up_value",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid, schema=schema)
