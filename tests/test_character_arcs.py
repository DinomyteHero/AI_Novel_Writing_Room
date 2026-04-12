"""Tests for character_arcs table and Weiland arc tracking."""

import pytest

from src.memory.story_state import StoryState


class TestCharacterArcsCRUD:
    """Tests for basic CRUD on the character_arcs table."""

    def test_add_and_get_character_arc(self, story_state):
        """add_character_arc followed by get_character_arc round-trips."""
        story_state.add_character(id="kael", name="Kael")
        story_state.add_character_arc(
            character_id="kael",
            lie_believed="Showing vulnerability is weakness",
            ghost="Betrayed by a trusted mentor at age 12",
            want="To become the strongest warrior in the guild",
            need="To accept help from others",
            arc_type="positive_change",
            arc_phase_targets={
                "lie_reinforced": "Part 1 - Setup",
                "lie_questioned": "First Plot Point",
                "lie_cracking": "Midpoint",
                "lie_confronted": "Second Plot Point",
                "truth_resolved": "Part 4 - Resolution",
            },
        )
        arc = story_state.get_character_arc("kael")
        assert arc is not None
        assert arc["lie_believed"] == "Showing vulnerability is weakness"
        assert arc["ghost"] == "Betrayed by a trusted mentor at age 12"
        assert arc["want"] == "To become the strongest warrior in the guild"
        assert arc["need"] == "To accept help from others"
        assert arc["arc_type"] == "positive_change"
        assert arc["current_phase"] == "lie_established"
        assert arc["arc_phase_targets"]["lie_reinforced"] == "Part 1 - Setup"

    def test_get_missing_arc_returns_none(self, story_state):
        """get_character_arc returns None for nonexistent arc."""
        assert story_state.get_character_arc("nonexistent") is None

    def test_update_character_arc(self, story_state):
        """update_character_arc modifies specific fields."""
        story_state.add_character(id="lyra", name="Lyra")
        story_state.add_character_arc(
            character_id="lyra", lie_believed="Trust no one", arc_type="positive_change",
            ghost="Parents abandoned her", want="Independence", need="Community",
        )
        story_state.update_character_arc("lyra", phase_evidence="Ch3: opened up to ally")
        arc = story_state.get_character_arc("lyra")
        assert arc["phase_evidence"] == "Ch3: opened up to ally"

    def test_get_all_character_arcs(self, story_state):
        """get_all_character_arcs returns all arcs."""
        story_state.add_character(id="a", name="A")
        story_state.add_character(id="b", name="B")
        story_state.add_character_arc(character_id="a", arc_type="flat",
                                       lie_believed="N/A", ghost="N/A", want="Justice", need="Justice")
        story_state.add_character_arc(character_id="b", arc_type="negative",
                                       lie_believed="Power is freedom", ghost="Enslaved", want="Power", need="Connection")
        arcs = story_state.get_all_character_arcs()
        assert len(arcs) == 2

    def test_get_all_character_arcs_filtered_by_book(self, story_state):
        """get_all_character_arcs filters by book_number."""
        story_state.add_character(id="c", name="C")
        story_state.add_character_arc(character_id="c", book_number=1, arc_type="flat",
                                       lie_believed="x", ghost="x", want="x", need="x")
        story_state.add_character_arc(character_id="c", book_number=2, arc_type="negative",
                                       lie_believed="y", ghost="y", want="y", need="y")
        assert len(story_state.get_all_character_arcs(book_number=1)) == 1
        assert len(story_state.get_all_character_arcs(book_number=2)) == 1


class TestArcPhaseProgression:
    """Tests for Weiland arc phase transitions."""

    def test_advance_arc_phase_valid(self, story_state):
        """Valid single-step phase advancement succeeds."""
        story_state.add_character(id="hero", name="Hero")
        story_state.add_character_arc(
            character_id="hero", arc_type="positive_change",
            lie_believed="x", ghost="x", want="x", need="x",
        )
        result = story_state.advance_arc_phase("hero", "lie_reinforced", chapter=3)
        assert result is True
        arc = story_state.get_character_arc("hero")
        assert arc["current_phase"] == "lie_reinforced"
        assert arc["phase_chapter"] == 3

    def test_advance_arc_phase_backwards_rejected(self, story_state):
        """Cannot go backwards in arc phase."""
        story_state.add_character(id="hero2", name="Hero2")
        story_state.add_character_arc(
            character_id="hero2", arc_type="positive_change",
            lie_believed="x", ghost="x", want="x", need="x",
            current_phase="lie_cracking",
        )
        result = story_state.advance_arc_phase("hero2", "lie_reinforced", chapter=5)
        assert result is False
        arc = story_state.get_character_arc("hero2")
        assert arc["current_phase"] == "lie_cracking"  # Unchanged

    def test_advance_arc_phase_skip_rejected(self, story_state):
        """Cannot skip more than one phase ahead."""
        story_state.add_character(id="hero3", name="Hero3")
        story_state.add_character_arc(
            character_id="hero3", arc_type="positive_change",
            lie_believed="x", ghost="x", want="x", need="x",
        )
        # Try to skip from lie_established to lie_cracking (skipping lie_reinforced & lie_questioned)
        result = story_state.advance_arc_phase("hero3", "lie_cracking", chapter=5)
        assert result is False

    def test_advance_arc_phase_self_transition_allowed(self, story_state):
        """Self-transition (same phase) is allowed — updates evidence without changing phase."""
        story_state.add_character(id="hero4", name="Hero4")
        story_state.add_character_arc(
            character_id="hero4", arc_type="positive_change",
            lie_believed="x", ghost="x", want="x", need="x",
        )
        result = story_state.advance_arc_phase(
            "hero4", "lie_established", chapter=2, evidence="reinforcing scene"
        )
        assert result is True
        arc = story_state.get_character_arc("hero4")
        assert arc["current_phase"] == "lie_established"
        assert arc["phase_chapter"] == 2

    def test_truth_accepted_from_lie_confronted(self, story_state):
        """Can advance from lie_confronted to truth_accepted."""
        story_state.add_character(id="hero5", name="Hero5")
        story_state.add_character_arc(
            character_id="hero5", arc_type="positive_change",
            lie_believed="x", ghost="x", want="x", need="x",
            current_phase="lie_confronted",
        )
        result = story_state.advance_arc_phase(
            "hero5", "truth_accepted", chapter=20, evidence="Chose truth over lie",
        )
        assert result is True
        arc = story_state.get_character_arc("hero5")
        assert arc["current_phase"] == "truth_accepted"
        assert arc["phase_evidence"] == "Chose truth over lie"

    def test_truth_rejected_from_lie_consequence(self, story_state):
        """Negative arcs can reach truth_rejected from lie_consequence."""
        story_state.add_character(id="villain", name="Villain")
        story_state.add_character_arc(
            character_id="villain", arc_type="negative",
            lie_believed="x", ghost="x", want="x", need="x",
            current_phase="lie_consequence",
        )
        result = story_state.advance_arc_phase("villain", "truth_rejected", chapter=20)
        assert result is True
        arc = story_state.get_character_arc("villain")
        assert arc["current_phase"] == "truth_rejected"

    def test_advance_missing_character_returns_false(self, story_state):
        """advance_arc_phase returns False for nonexistent character."""
        result = story_state.advance_arc_phase("ghost_char", "lie_questioned", chapter=1)
        assert result is False

    def test_full_positive_arc_progression(self, story_state):
        """Full positive arc: lie_established -> ... -> truth_accepted."""
        story_state.add_character(id="protag", name="Protagonist")
        story_state.add_character_arc(
            character_id="protag", arc_type="positive_change",
            lie_believed="x", ghost="x", want="x", need="x",
        )
        phases = ["lie_reinforced", "lie_questioned", "lie_cracking", "lie_confronted", "truth_accepted"]
        for i, phase in enumerate(phases, start=1):
            assert story_state.advance_arc_phase("protag", phase, chapter=i * 5)
        arc = story_state.get_character_arc("protag")
        assert arc["current_phase"] == "truth_accepted"
