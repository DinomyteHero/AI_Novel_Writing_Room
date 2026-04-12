"""Tests for per-arc-type phase progressions.

Validates that each arc type (positive_change, negative, flat, disillusionment)
has a correct step-by-step progression and that cross-type / skip violations
are rejected.
"""

import pytest

from src.memory.story_state import (
    ARC_PHASE_PROGRESSIONS,
    ALL_ARC_PHASES,
    CONCEPT_SEED_PHASE_MAP,
    StoryState,
)


@pytest.fixture
def state(tmp_path):
    db_path = str(tmp_path / "arc_test.db")
    s = StoryState(db_path=db_path)
    yield s
    s.close()


def _add_char_with_arc(state, char_id, arc_type):
    """Helper: register a character and arc starting at lie_established."""
    state.add_character(id=char_id, name=char_id.replace("_", " ").title())
    state.add_character_arc(
        character_id=char_id,
        arc_type=arc_type,
        lie_believed="test lie",
        ghost="test ghost",
        want="test want",
        need="test need",
    )


class TestPositiveChangeArc:
    """Positive change arc: lie_established -> ... -> truth_accepted."""

    def test_full_progression(self, state):
        _add_char_with_arc(state, "hero", "positive_change")
        phases = ARC_PHASE_PROGRESSIONS["positive_change"]
        for i in range(1, len(phases)):
            ok = state.advance_arc_phase("hero", phases[i], chapter=i)
            assert ok, f"Failed to advance to {phases[i]}"
        arc = state.get_character_arc("hero")
        assert arc["current_phase"] == "truth_accepted"

    def test_starts_at_lie_established(self, state):
        _add_char_with_arc(state, "hero", "positive_change")
        arc = state.get_character_arc("hero")
        assert arc["current_phase"] == "lie_established"


class TestNegativeArc:
    """Negative arc: lie_established -> ... -> truth_rejected."""

    def test_full_progression(self, state):
        _add_char_with_arc(state, "villain", "negative")
        phases = ARC_PHASE_PROGRESSIONS["negative"]
        for i in range(1, len(phases)):
            ok = state.advance_arc_phase("villain", phases[i], chapter=i)
            assert ok, f"Failed to advance to {phases[i]}"
        arc = state.get_character_arc("villain")
        assert arc["current_phase"] == "truth_rejected"

    def test_rejects_positive_phase(self, state):
        """Cannot use positive-arc phases on a negative arc."""
        _add_char_with_arc(state, "villain", "negative")
        # Advance to lie_reinforced first (shared phase)
        state.advance_arc_phase("villain", "lie_reinforced", chapter=1)
        # Try to advance to lie_questioned (positive-arc phase, not in negative progression)
        ok = state.advance_arc_phase("villain", "lie_questioned", chapter=2)
        assert not ok
        arc = state.get_character_arc("villain")
        assert arc["current_phase"] == "lie_reinforced"


class TestFlatArc:
    """Flat arc: lie_established -> truth_tested -> truth_pressured -> truth_reaffirmed."""

    def test_full_progression(self, state):
        _add_char_with_arc(state, "mentor", "flat")
        phases = ARC_PHASE_PROGRESSIONS["flat"]
        for i in range(1, len(phases)):
            ok = state.advance_arc_phase("mentor", phases[i], chapter=i)
            assert ok, f"Failed to advance to {phases[i]}"
        arc = state.get_character_arc("mentor")
        assert arc["current_phase"] == "truth_reaffirmed"


class TestDisillusionmentArc:
    """Disillusionment: lie_established -> ... -> disillusionment_accepted."""

    def test_full_progression(self, state):
        _add_char_with_arc(state, "cynic", "disillusionment")
        phases = ARC_PHASE_PROGRESSIONS["disillusionment"]
        for i in range(1, len(phases)):
            ok = state.advance_arc_phase("cynic", phases[i], chapter=i)
            assert ok, f"Failed to advance to {phases[i]}"
        arc = state.get_character_arc("cynic")
        assert arc["current_phase"] == "disillusionment_accepted"


class TestSkipping:
    """Cannot skip phases."""

    def test_skip_rejected(self, state):
        _add_char_with_arc(state, "hero", "positive_change")
        # Try to skip from lie_established directly to lie_questioned (skipping lie_reinforced)
        ok = state.advance_arc_phase("hero", "lie_questioned", chapter=1)
        assert not ok

    def test_backward_rejected(self, state):
        _add_char_with_arc(state, "hero", "positive_change")
        state.advance_arc_phase("hero", "lie_reinforced", chapter=1)
        state.advance_arc_phase("hero", "lie_questioned", chapter=2)
        # Try to go backward
        ok = state.advance_arc_phase("hero", "lie_reinforced", chapter=3)
        assert not ok


class TestConceptSeedPhaseMap:
    """CONCEPT_SEED_PHASE_MAP maps planning labels to valid DB phases."""

    def test_all_mapped_values_are_valid(self):
        for label, phase in CONCEPT_SEED_PHASE_MAP.items():
            assert phase in ALL_ARC_PHASES, (
                f"Mapped phase '{phase}' (from '{label}') not in ALL_ARC_PHASES"
            )

    def test_negative_arc_labels(self):
        assert CONCEPT_SEED_PHASE_MAP["lie_deepened"] == "lie_deepened"
        assert CONCEPT_SEED_PHASE_MAP["arc_resolved_tragic"] == "truth_rejected"

    def test_flat_arc_labels(self):
        assert CONCEPT_SEED_PHASE_MAP["lie_tested"] == "truth_tested"
        assert CONCEPT_SEED_PHASE_MAP["lie_unchanged"] == "truth_rejected"

    def test_positive_arc_labels(self):
        assert CONCEPT_SEED_PHASE_MAP["lie_challenged"] == "lie_questioned"
        assert CONCEPT_SEED_PHASE_MAP["moment_of_truth"] == "lie_confronted"
        assert CONCEPT_SEED_PHASE_MAP["truth_resolved"] == "truth_accepted"


class TestGetStateSnapshot:
    """get_state_snapshot() returns structured state data."""

    def test_snapshot_includes_characters_and_arcs(self, state):
        _add_char_with_arc(state, "hero", "positive_change")
        snap = state.get_state_snapshot()
        assert len(snap["characters"]) >= 1
        hero = next(c for c in snap["characters"] if c["id"] == "hero")
        assert hero["arc"]["arc_type"] == "positive_change"
        assert hero["arc"]["current_phase"] == "lie_established"

    def test_snapshot_includes_subplots_and_hooks(self, state):
        state.add_subplot(
            subplot_id="sp1", subplot_name="Subplot 1",
            line_type="B", current_status="active",
        )
        state.add_character(id="dummy", name="Dummy")
        state.add_hook(
            hook_id="h1", description="Hook 1",
            hook_type="foreshadow", planted_chapter=1, priority="hard",
        )
        snap = state.get_state_snapshot()
        assert any(s["subplot_id"] == "sp1" for s in snap["subplots"])
        assert any(h["hook_id"] == "h1" for h in snap["hooks"])
