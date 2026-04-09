"""Golden end-to-end tests for the installed Ruusan Atonement concept seed.

These tests verify that the actual installed seed at
data/story_bibles/the_ruusan_atonement/concept_seed.json loads through the
full Phase 5 pipeline (story_state + compliance validator) with expected
counts and passes schema validation. If the installed seed drifts from its
expected shape — or if the downstream consumers regress — one of these
tests will fail.

This complements test_compliance_validator.py (which uses a stable fixture)
by providing smoke coverage of the actual on-disk canonical project data.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from src.concept_workshop.compliance_validator import validate_concept_seed
from src.memory.story_state import StoryState

REPO_ROOT = Path(__file__).parent.parent
RUUSAN_SEED_PATH = (
    REPO_ROOT / "data" / "story_bibles" / "the_ruusan_atonement" / "concept_seed.json"
)
RUUSAN_SCENE_CARDS_DIR = (
    REPO_ROOT / "data" / "story_bibles" / "the_ruusan_atonement" / "scene_cards"
)
CONCEPT_SEED_SCHEMA = REPO_ROOT / "schemas" / "concept_seed.json"
SCENE_CARD_SCHEMA = REPO_ROOT / "schemas" / "scene_card.json"


@pytest.fixture
def installed_ruusan_seed():
    """Load the actual installed Ruusan seed (not the fixtures copy)."""
    if not RUUSAN_SEED_PATH.exists():
        pytest.skip(f"Installed seed not present at {RUUSAN_SEED_PATH}")
    return json.loads(RUUSAN_SEED_PATH.read_text(encoding="utf-8"))


class TestInstalledSeedShape:
    """Verify the installed seed has the expected top-level shape."""

    def test_required_top_level_fields_present(self, installed_ruusan_seed):
        """All required top-level fields exist."""
        required = [
            "meta", "premise", "conflict", "theme", "ensemble_cast",
            "voice_definition", "subplots", "hooks", "revelation_schedule",
            "scene_cards", "terminology_registry", "stress_test_scores",
            "promise_payoff_ledger", "extended_metadata", "canon_constraints",
        ]
        for field in required:
            assert field in installed_ruusan_seed, f"Missing top-level field: {field}"

    def test_counts_match_workshop_output(self, installed_ruusan_seed):
        """Seed has the expected number of entries for each tracked artifact."""
        seed = installed_ruusan_seed
        assert len(seed["ensemble_cast"]) == 6, "Expected 6 cast members"
        assert len(seed["subplots"]) == 5, "Expected 5 subplots"
        assert len(seed["hooks"]) == 25, "Expected 25 hooks"
        assert len(seed["revelation_schedule"]) == 14, "Expected 14 revelations"
        assert len(seed["scene_cards"]) == 28, "Expected 28 scene cards"
        assert len(seed["terminology_registry"]) == 30, "Expected 30 terminology entries"
        assert len(seed["promise_payoff_ledger"]) == 25, "Expected 25 promise ledger entries"

    def test_extended_metadata_contains_story_specific_fields(self, installed_ruusan_seed):
        """technique_lineage and jacen_parallel are under extended_metadata, not top-level."""
        ext = installed_ruusan_seed["extended_metadata"]
        assert "technique_lineage" in ext
        assert "jacen_parallel" in ext
        assert "workshop_origin" in ext
        # Must NOT be at top-level
        assert "technique_lineage" not in installed_ruusan_seed
        assert "jacen_parallel" not in installed_ruusan_seed

    def test_voice_definition_has_new_structure(self, installed_ruusan_seed):
        """voice_definition uses the post-Phase-5 structure (not nested anti_slop)."""
        voice = installed_ruusan_seed["voice_definition"]
        assert "anti_slop_rules" in voice, "Expected flat anti_slop_rules"
        assert "character_voices" in voice
        assert "force_description_guidelines" in voice
        # reference_authors are objects, not strings
        assert isinstance(voice["reference_authors"][0], dict)
        assert "what_to_emulate" in voice["reference_authors"][0]
        # Old nested structure should be absent
        assert "anti_slop" not in voice or not isinstance(voice.get("anti_slop"), dict) or "banned_words" not in voice.get("anti_slop", {})

    def test_main_characters_have_arc_phase_map(self, installed_ruusan_seed):
        """All 5 main characters have arc_phase_map; Desh (supporting) does not."""
        main = {"Ben Skywalker", "Sera Varik", "Kael Drenn", "Torin Hal", "Darth Veraine"}
        for char in installed_ruusan_seed["ensemble_cast"]:
            apm = char.get("weiland_arc", {}).get("arc_phase_map")
            if char["name"] in main:
                assert apm, f"Main character {char['name']} missing arc_phase_map"
            elif char["name"] == "Desh Rolan":
                assert not apm, "Supporting character Desh should not have arc_phase_map"


class TestInstalledSeedSchemaValidation:
    """The installed seed and every scene card must validate against their schemas."""

    def test_seed_validates_against_concept_seed_schema(self, installed_ruusan_seed):
        schema = json.loads(CONCEPT_SEED_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(installed_ruusan_seed, schema)  # raises on failure

    def test_all_28_scene_cards_validate(self):
        """All 28 scene cards in the scene_cards directory validate against scene_card.json."""
        if not RUUSAN_SCENE_CARDS_DIR.exists():
            pytest.skip(f"Scene cards directory not present: {RUUSAN_SCENE_CARDS_DIR}")
        schema = json.loads(SCENE_CARD_SCHEMA.read_text(encoding="utf-8"))
        cards = sorted(RUUSAN_SCENE_CARDS_DIR.glob("chapter_*_scene_*.json"))
        assert len(cards) == 28, f"Expected 28 scene card files, found {len(cards)}"
        for card_path in cards:
            card = json.loads(card_path.read_text(encoding="utf-8"))
            jsonschema.validate(card, schema)  # raises on failure

    def test_critical_structural_phases_correct(self):
        """The plot-point chapters have the correct structural_phase labels."""
        if not RUUSAN_SCENE_CARDS_DIR.exists():
            pytest.skip(f"Scene cards directory not present: {RUUSAN_SCENE_CARDS_DIR}")
        expected = {
            5: "first_plot_point",
            13: "midpoint",
            21: "second_plot_point",
            26: "climax",
        }
        for ch, phase in expected.items():
            card = json.loads(
                (RUUSAN_SCENE_CARDS_DIR / f"chapter_{ch:02d}_scene_01.json").read_text(encoding="utf-8")
            )
            assert card["structural_phase"] == phase, (
                f"Chapter {ch} should be {phase}, got {card['structural_phase']}"
            )


class TestInstalledSeedPipelineLoad:
    """The installed seed must load into story_state and populate all tracked tables."""

    def test_loads_into_story_state(self, installed_ruusan_seed):
        """init_from_concept_seed populates character_arcs, subplot_board, hook_ledger, terminology_registry."""
        state = StoryState(":memory:")
        state.init_from_concept_seed(installed_ruusan_seed)

        # Characters (excluding the __world__ placeholder)
        cast_count = state.conn.execute(
            "SELECT COUNT(*) FROM characters WHERE id != '__world__'"
        ).fetchone()[0]
        assert cast_count == 6, f"Expected 6 cast characters in DB, got {cast_count}"

        # Character arcs — all 6 including Desh (positive_change)
        arcs = state.conn.execute("SELECT COUNT(*) FROM character_arcs").fetchone()[0]
        assert arcs == 6, f"Expected 6 character_arcs, got {arcs}"

        # Subplots
        subs = state.conn.execute("SELECT COUNT(*) FROM subplot_board").fetchone()[0]
        assert subs == 5, f"Expected 5 subplots, got {subs}"

        # Hooks
        hooks = state.conn.execute("SELECT COUNT(*) FROM hook_ledger").fetchone()[0]
        assert hooks == 25, f"Expected 25 hooks, got {hooks}"

        # Terminology
        terms = state.conn.execute("SELECT COUNT(*) FROM terminology_registry").fetchone()[0]
        assert terms == 30, f"Expected 30 terminology entries, got {terms}"

    def test_hook_chapter_strings_parsed_to_ints(self, installed_ruusan_seed):
        """Hook planted_chapter and payoff_chapter are ints after dual-format parsing."""
        state = StoryState(":memory:")
        state.init_from_concept_seed(installed_ruusan_seed)
        # H05 plants Ch 5, resolves "Chapter 10-16" → should be 10 (earliest)
        row = state.conn.execute(
            "SELECT hook_id, planted_chapter, payoff_chapter FROM hook_ledger WHERE hook_id = 'H05'"
        ).fetchone()
        assert row is not None
        assert row["planted_chapter"] == 5
        assert row["payoff_chapter"] == 10  # earliest in "Chapter 10-16"

    def test_arc_types_normalized_from_descriptive_strings(self, installed_ruusan_seed):
        """Descriptive arc_type strings are coerced to canonical enum values."""
        state = StoryState(":memory:")
        state.init_from_concept_seed(installed_ruusan_seed)
        rows = state.conn.execute(
            "SELECT character_id, arc_type FROM character_arcs"
        ).fetchall()
        arc_type_by_char = {row["character_id"]: row["arc_type"] for row in rows}
        # Ben, Sera, Kael, Desh are positive_change (including the "minor positive" for Desh)
        assert arc_type_by_char["ben_skywalker"] == "positive_change"
        assert arc_type_by_char["sera_varik"] == "positive_change"
        assert arc_type_by_char["kael_drenn"] == "positive_change"
        assert arc_type_by_char["desh_rolan"] == "positive_change"
        # Torin is negative (tragic), Veraine is negative (flat negative maps to negative)
        assert arc_type_by_char["torin_hal"] == "negative"
        assert arc_type_by_char["darth_veraine"] == "negative"


class TestInstalledSeedComplianceValidator:
    """The compliance validator must accept the installed seed."""

    def test_compliance_validator_passes_on_installed_seed(self, installed_ruusan_seed):
        """validate_concept_seed returns passed=True with no critical failures."""
        report = validate_concept_seed(installed_ruusan_seed)
        assert report.passed is True, (
            f"Expected installed seed to pass compliance; "
            f"got failures: {report.critical_failures}"
        )
        assert report.critical_failures == []
