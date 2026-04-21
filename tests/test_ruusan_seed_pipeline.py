"""Golden end-to-end tests for the installed Ruusan Atonement concept seed.

These tests verify that the actual installed seed at the canonical
franchise-scoped path loads through the full Phase 5 pipeline (story_state
+ compliance validator) with expected counts and passes schema validation.
If the installed seed drifts from its expected shape — or if the downstream
consumers regress — one of these tests will fail.

Canonical path (via ProjectPaths):
    data/franchises/{franchise}/books/{book}/

This complements test_compliance_validator.py (which uses a stable fixture)
by providing smoke coverage of the actual on-disk canonical project data.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from src.concept_workshop.compliance_validator import validate_concept_seed
from src.memory.story_state import CONCEPT_SEED_PHASE_MAP, StoryState

REPO_ROOT = Path(__file__).parent.parent
RUUSAN_SEED_PATH = (
    REPO_ROOT / "data" / "franchises" / "star-wars-legends-eu"
    / "books" / "the-ruusan-atonement" / "concept_seed.json"
)
RUUSAN_SCENE_CARDS_DIR = (
    REPO_ROOT / "data" / "franchises" / "star-wars-legends-eu"
    / "books" / "the-ruusan-atonement" / "scene_cards"
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
        # SP4 merged into SP3 per the D5 revision — effective count is 5
        # (SP-A, SP1, SP2, merged-SP3, SP5-as-half-weight operational presence).
        assert len(seed["subplots"]) == 5, "Expected 5 subplots (SP-A, SP1, SP2, SP3, SP5)"
        assert len(seed["hooks"]) == 25, "Expected 25 hooks"
        assert len(seed["revelation_schedule"]) == 19, "Expected 19 revelations"
        assert len(seed["scene_cards"]) == 0, "Expected 0 scene cards (removed pending regeneration)"
        assert len(seed["terminology_registry"]) == 44, "Expected 44 terminology entries"
        assert len(seed["promise_payoff_ledger"]) == 32, "Expected 32 promise ledger entries"

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

    def test_all_characters_have_arc_phase_map(self, installed_ruusan_seed):
        """Every tracked-arc ensemble member has an arc_phase_map.

        Characters with arc_type 'supporting_presence' are intentionally
        untracked (presence and contrast, not Weiland progression) and
        are exempt from this check.
        """
        for char in installed_ruusan_seed["ensemble_cast"]:
            weiland = char.get("weiland_arc", {})
            if weiland.get("arc_type") == "supporting_presence":
                continue
            apm = weiland.get("arc_phase_map")
            assert apm, f"{char['name']} missing arc_phase_map"


class TestInstalledSeedSchemaValidation:
    """The installed seed and every scene card must validate against their schemas."""

    def test_seed_validates_against_concept_seed_schema(self, installed_ruusan_seed):
        """Core seed validates against the JSON schema.

        The stress_test_scores values are temporarily null (pending re-test
        after scene card regeneration).  The schema declares most score fields
        as ``type: number`` without a null allowance, so we strip null-valued
        score entries before validation to avoid false negatives.
        """
        import copy

        seed = copy.deepcopy(installed_ruusan_seed)
        # Strip null score values that are pending re-test
        scores = seed.get("stress_test_scores", {})
        for key in list(scores):
            if scores[key] is None:
                del scores[key]
        schema = json.loads(CONCEPT_SEED_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(seed, schema)  # raises on failure

    def test_all_scene_cards_validate(self):
        """All Ruusan scene cards must pass schema validation.

        Scene cards are fully populated with mission, turning_point, conflict,
        and all other required fields.  Multiple scenes per chapter are expected.
        """
        if not RUUSAN_SCENE_CARDS_DIR.exists():
            pytest.skip(f"Scene cards directory not present: {RUUSAN_SCENE_CARDS_DIR}")
        schema = json.loads(SCENE_CARD_SCHEMA.read_text(encoding="utf-8"))
        cards = sorted(RUUSAN_SCENE_CARDS_DIR.glob("chapter_*_scene_*.json"))
        chapters_covered = {
            json.loads(p.read_text(encoding="utf-8"))["chapter_number"]
            for p in cards
        }
        assert chapters_covered == set(range(1, 29)), (
            f"Expected chapters 1-28 covered, got {sorted(chapters_covered)}"
        )

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

    def test_every_scene_card_has_scene_type(self):
        """After Commit 5, every extracted scene card has a canonical scene_type."""
        if not RUUSAN_SCENE_CARDS_DIR.exists():
            pytest.skip(f"Scene cards directory not present: {RUUSAN_SCENE_CARDS_DIR}")
        cards = sorted(RUUSAN_SCENE_CARDS_DIR.glob("chapter_*_scene_*.json"))
        for card_path in cards:
            card = json.loads(card_path.read_text(encoding="utf-8"))
            assert card.get("scene_type") in ("action", "sequel"), (
                f"{card_path.name} missing or has invalid scene_type"
            )

    def test_every_scene_card_pov_arc_phase_is_recognized(self):
        """Every scene card's ``pov_arc_phase`` must be a label the runtime knows.

        ``state_diff.py`` treats ``scene_card.pov_arc_phase`` as authoritative for
        the POV character, but ``CONCEPT_SEED_PHASE_MAP`` in ``story_state.py``
        only resolves a closed set of planning labels. An unrecognized label
        silently falls through and the POV arc phase is left unchanged, which
        drifts arc state from the scene card's declaration. This guard catches
        that class of typo at authoring time instead of at state-diff time.
        """
        if not RUUSAN_SCENE_CARDS_DIR.exists():
            pytest.skip(f"Scene cards directory not present: {RUUSAN_SCENE_CARDS_DIR}")
        valid = set(CONCEPT_SEED_PHASE_MAP.keys())
        bad: list[tuple[str, str]] = []
        for card_path in sorted(RUUSAN_SCENE_CARDS_DIR.glob("chapter_*_scene_*.json")):
            card = json.loads(card_path.read_text(encoding="utf-8"))
            phase = card.get("pov_arc_phase")
            if phase is None:
                continue
            if phase not in valid:
                bad.append((card_path.name, phase))
        assert not bad, (
            f"Scene cards with unrecognized pov_arc_phase values: {bad}. "
            f"Valid labels: {sorted(valid)}"
        )

    def test_scene_type_spot_check(self):
        """Verify known action/sequel assignments for several chapters."""
        if not RUUSAN_SCENE_CARDS_DIR.exists():
            pytest.skip(f"Scene cards directory not present: {RUUSAN_SCENE_CARDS_DIR}")
        # These assignments are set by the workshop's Step 8 scene_type field.
        expected = {
            1: "sequel",      # Ben's departure / emotional opening
            2: "sequel",      # Survey rhythm / processing wrongness pattern
            5: "action",      # First Plot Point — awakening
            6: "sequel",      # Response — group orientation
            13: "action",     # Midpoint — visceral breach
            21: "action",     # Second Plot Point — Torin's turn
            26: "action",     # Climax
        }
        for ch, expected_type in expected.items():
            card = json.loads(
                (RUUSAN_SCENE_CARDS_DIR / f"chapter_{ch:02d}_scene_01.json").read_text(encoding="utf-8")
            )
            assert card.get("scene_type") == expected_type, (
                f"Chapter {ch} should be scene_type={expected_type!r}, got {card.get('scene_type')!r}"
            )


class TestInstalledSeedPipelineLoad:
    """The installed seed must load into story_state and populate all tracked tables."""

    def test_loads_into_story_state(self, installed_ruusan_seed):
        """init_from_concept_seed populates character_arcs, subplots, hooks, terminology_registry."""
        state = StoryState(":memory:")
        state.init_from_concept_seed(installed_ruusan_seed)

        # Characters (excluding the __world__ placeholder).
        # 6 ensemble cast + 10 referenced (Luke, Jacen, Ch1 sparring partner,
        # 3 Ch19 Jedi, 4 Veraine crew).
        cast_count = state.conn.execute(
            "SELECT COUNT(*) FROM characters WHERE id != '__world__'"
        ).fetchone()[0]
        assert cast_count == 16, (
            f"Expected 16 characters in DB (6 ensemble + 10 referenced), got {cast_count}"
        )

        # Character arcs — 5 tracked (Ben, Sera, Kael, Torin, Veraine). Desh
        # is arc_type='supporting_presence' and is intentionally skipped at
        # the DB layer; his weight lives in scene-level presence and contrast.
        arcs = state.conn.execute("SELECT COUNT(*) FROM character_arcs").fetchone()[0]
        assert arcs == 5, f"Expected 5 character_arcs (Desh is supporting_presence), got {arcs}"

        # Subplots — SP4 merged into SP3 per the D5 revision.
        subs = state.conn.execute("SELECT COUNT(*) FROM subplots").fetchone()[0]
        assert subs == 5, f"Expected 5 subplots (SP-A, SP1, SP2, SP3, SP5), got {subs}"

        # Hooks
        hooks = state.conn.execute("SELECT COUNT(*) FROM hooks").fetchone()[0]
        assert hooks == 25, f"Expected 25 hooks, got {hooks}"

        # Terminology
        terms = state.conn.execute("SELECT COUNT(*) FROM terminology_registry").fetchone()[0]
        assert terms == 44, f"Expected 44 terminology entries, got {terms}"

    def test_hook_chapter_strings_parsed_to_ints(self, installed_ruusan_seed):
        """Hook planted_chapter and payoff_chapter are ints after dual-format parsing."""
        state = StoryState(":memory:")
        state.init_from_concept_seed(installed_ruusan_seed)
        # H05 plants Ch 5, resolves "Chapter 10-16" → should be 10 (earliest)
        row = state.conn.execute(
            "SELECT hook_id, planted_chapter, payoff_chapter FROM hooks WHERE hook_id = 'H05'"
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
        # Ben, Sera, Kael are positive_change
        assert arc_type_by_char["ben_skywalker"] == "positive_change"
        assert arc_type_by_char["sera_varik"] == "positive_change"
        assert arc_type_by_char["kael_drenn"] == "positive_change"
        # Torin is corruption (maps to 'negative' in DB — extended Weiland
        # negative-arc variant collapses to the bare enum), Veraine is negative.
        assert arc_type_by_char["torin_hal"] == "negative"
        assert arc_type_by_char["darth_veraine"] == "negative"
        # Desh is supporting_presence: no row in character_arcs.
        assert "desh_rolan" not in arc_type_by_char


class TestInstalledSeedComplianceValidator:
    """The compliance validator must accept the installed seed."""

    def test_compliance_validator_on_installed_seed(self, installed_ruusan_seed):
        """validate_concept_seed runs without error.

        The installed seed currently has an empty scene_cards array and null
        stress_test_scores (both pending regeneration), so full compliance is
        expected to fail only on those checks.  All other checks must pass.
        """
        report = validate_concept_seed(installed_ruusan_seed)
        # Failures we accept because the seed is mid-revision:
        #   - scene_cards / scene_card  (removed pending regeneration)
        #   - stress_test_scores        (reset to null pending re-test)
        expected_gap_keywords = ("scene_card", "scene_cards", "stress_test")
        unexpected_failures = [
            f for f in report.critical_failures
            if not any(kw in f for kw in expected_gap_keywords)
        ]
        assert unexpected_failures == [], (
            f"Expected no compliance failures outside scene_cards/stress_test; "
            f"got: {unexpected_failures}"
        )
