"""Tests for terminology_registry table."""

import pytest

from src.memory.story_state import StoryState


class TestTerminologyCRUD:
    """Tests for basic CRUD on the terminology_registry table."""

    def test_add_and_get_term(self, story_state):
        """add_term followed by get_term round-trips."""
        story_state.add_term(
            term="Kael'thar",
            definition="The ancient citadel of the Dragon Lords",
            category="place_name",
            aliases=["Kael", "The Citadel", "Dragon Keep"],
            first_appearance_chapter=1,
        )
        term = story_state.get_term("Kael'thar")
        assert term is not None
        assert term["definition"] == "The ancient citadel of the Dragon Lords"
        assert term["category"] == "place_name"
        assert term["aliases"] == ["Kael", "The Citadel", "Dragon Keep"]

    def test_get_missing_term_returns_none(self, story_state):
        """get_term returns None for nonexistent term."""
        assert story_state.get_term("nonexistent") is None

    def test_update_term(self, story_state):
        """update_term modifies specific fields."""
        story_state.add_term(term="Voidsteel", definition="A dark metal",
                              category="artifact")
        story_state.update_term("Voidsteel", definition="A dark metal forged in the Void")
        term = story_state.get_term("Voidsteel")
        assert term["definition"] == "A dark metal forged in the Void"

    def test_get_all_terms(self, story_state):
        """get_all_terms returns all terms."""
        story_state.add_term(term="A", definition="Def A", category="concept")
        story_state.add_term(term="B", definition="Def B", category="species")
        terms = story_state.get_all_terms()
        assert len(terms) == 2

    def test_get_all_terms_filtered_by_book(self, story_state):
        """get_all_terms filters by book_number."""
        story_state.add_term(term="X", definition="X", category="concept", book_number=1)
        story_state.add_term(term="Y", definition="Y", category="concept", book_number=2)
        assert len(story_state.get_all_terms(book_number=1)) == 1

    def test_aliases_json_round_trip(self, story_state):
        """Aliases list serializes and deserializes through JSON."""
        story_state.add_term(term="Test", definition="Test",
                              category="character_name",
                              aliases=["T", "Tee", "Testing"])
        term = story_state.get_term("Test")
        assert term["aliases"] == ["T", "Tee", "Testing"]


class TestTermLookup:
    """Tests for find_term alias matching."""

    def test_find_by_canonical_form(self, story_state):
        """find_term finds by exact canonical match."""
        story_state.add_term(term="Lightsaber", definition="Energy blade",
                              category="artifact")
        result = story_state.find_term("Lightsaber")
        assert result is not None
        assert result["term"] == "Lightsaber"

    def test_find_by_alias(self, story_state):
        """find_term finds by alias match."""
        story_state.add_term(term="Lightsaber", definition="Energy blade",
                              category="artifact", aliases=["laser sword", "saber"])
        result = story_state.find_term("laser sword")
        assert result is not None
        assert result["term"] == "Lightsaber"

    def test_find_case_insensitive(self, story_state):
        """find_term is case-insensitive for both canonical and aliases."""
        story_state.add_term(term="Darksaber", definition="Black blade",
                              category="artifact", aliases=["dark saber"])
        assert story_state.find_term("darksaber") is not None
        assert story_state.find_term("DARK SABER") is not None

    def test_find_returns_none_for_no_match(self, story_state):
        """find_term returns None when nothing matches."""
        assert story_state.find_term("nonexistent_term") is None
