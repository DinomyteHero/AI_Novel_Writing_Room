"""Tests for the three-layer knowledge state system (KnowledgeLayers)."""

import pytest

from src.memory.knowledge_layers import KnowledgeLayers, TRUTH_ENTITY


class TestTruthLayer:
    """Tests for the truth layer."""

    def test_add_truth_and_get_truths(self, knowledge_layers):
        """add_truth stores a world-level fact retrievable by get_truths."""
        knowledge_layers.add_truth(
            fact_id="abeloth_defeated",
            description="Abeloth was defeated but not permanently destroyed",
            chapter=0,
        )
        truths = knowledge_layers.get_truths()
        assert len(truths) >= 1
        fact_ids = [t["fact_id"] for t in truths]
        assert "abeloth_defeated" in fact_ids

    def test_get_truth_specific(self, knowledge_layers):
        """get_truth returns a specific fact by fact_id."""
        knowledge_layers.add_truth(
            fact_id="scholar_agenda",
            description="The scholar plans to reactivate the Celestial network",
            chapter=0,
        )
        truth = knowledge_layers.get_truth("scholar_agenda")
        assert truth is not None
        assert truth["fact_description"] == "The scholar plans to reactivate the Celestial network"

    def test_get_truth_returns_none_for_missing(self, knowledge_layers):
        """get_truth returns None for a fact_id that does not exist."""
        assert knowledge_layers.get_truth("nonexistent") is None


class TestBeliefLayer:
    """Tests for the belief layer."""

    def test_add_accurate_belief(self, knowledge_layers):
        """add_belief stores an accurate belief for a character."""
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="scholar_trustworthy",
            description="The scholar is a trusted ally",
            is_accurate=True,
            chapter=1,
            source="witnessed",
        )
        beliefs = knowledge_layers.get_beliefs("alex_reyes")
        assert len(beliefs) == 1
        assert beliefs[0]["is_accurate"] == 1  # SQLite stores as int

    def test_add_inaccurate_belief(self, knowledge_layers):
        """add_belief stores an inaccurate belief for a character."""
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="scholar_agenda",
            description="The scholar has no hidden agenda",
            is_accurate=False,
            chapter=2,
            source="inferred",
        )
        beliefs = knowledge_layers.get_beliefs("alex_reyes")
        assert len(beliefs) == 1
        assert beliefs[0]["is_accurate"] == 0  # SQLite stores as int


class TestExposureLayer:
    """Tests for the narrative exposure layer."""

    def test_add_exposure(self, knowledge_layers):
        """add_exposure records what the reader has been shown."""
        knowledge_layers.add_exposure(
            character_id="alex_reyes",
            fact_id="scholar_inconsistency",
            description="Reader sees the scholar recognize a marker too quickly",
            chapter=3,
        )
        exposures = knowledge_layers.get_exposures("alex_reyes")
        assert len(exposures) == 1
        assert exposures[0]["fact_id"] == "scholar_inconsistency"
        assert exposures[0]["layer"] == "narrative_exposure"


class TestGetBeliefsForCharacters:
    """Tests for get_beliefs_for_characters context formatting."""

    def test_returns_formatted_string(self, knowledge_layers):
        """get_beliefs_for_characters returns a formatted context string."""
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="fact_a",
            description="The Force is collective in wound regions",
            is_accurate=True,
            chapter=2,
            source="witnessed",
        )
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="fact_b",
            description="The scholar is trustworthy",
            is_accurate=False,
            chapter=1,
            source="inferred",
        )
        result = knowledge_layers.get_beliefs_for_characters(["alex_reyes"])
        assert "### alex_reyes" in result
        assert "[accurate]" in result
        assert "[inaccurate]" in result
        assert "witnessed" in result

    def test_returns_no_beliefs_message_when_empty(self, knowledge_layers):
        """Returns a default message when no beliefs exist."""
        result = knowledge_layers.get_beliefs_for_characters(["alex_reyes"])
        assert result == "No character beliefs recorded."


class TestCheckBeliefAccuracy:
    """Tests for check_belief_accuracy."""

    def test_returns_true_for_accurate_belief(self, knowledge_layers):
        """check_belief_accuracy returns True for an accurate belief."""
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="force_collective",
            description="Force is collective in wound regions",
            is_accurate=True,
            chapter=2,
            source="witnessed",
        )
        assert knowledge_layers.check_belief_accuracy("alex_reyes", "force_collective") is True

    def test_returns_false_for_inaccurate_belief(self, knowledge_layers):
        """check_belief_accuracy returns False for an inaccurate belief."""
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="scholar_agenda",
            description="The scholar has no hidden agenda",
            is_accurate=False,
            chapter=1,
            source="inferred",
        )
        assert knowledge_layers.check_belief_accuracy("alex_reyes", "scholar_agenda") is False

    def test_returns_none_for_unknown_belief(self, knowledge_layers):
        """check_belief_accuracy returns None when no matching belief exists."""
        assert knowledge_layers.check_belief_accuracy("alex_reyes", "nonexistent") is None


class TestDramaticIrony:
    """Tests for get_dramatic_irony detection."""

    def test_detects_dramatic_irony(self, knowledge_layers):
        """Detects when reader knows truth but character has false belief."""
        # Set up truth
        knowledge_layers.add_truth(
            fact_id="scholar_agenda",
            description="The scholar secretly plans to activate the Celestial mechanism",
            chapter=0,
        )
        # Character has false belief
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="scholar_agenda",
            description="The scholar is only here to study the wound regions",
            is_accurate=False,
            chapter=1,
            source="inferred",
        )
        # Reader has been exposed to the truth
        knowledge_layers.add_exposure(
            character_id="alex_reyes",
            fact_id="scholar_agenda",
            description="Reader sees the scholar's secret datacron",
            chapter=2,
        )

        ironies = knowledge_layers.get_dramatic_irony(chapter=3)
        assert len(ironies) >= 1

        irony = ironies[0]
        assert irony["character_id"] == "alex_reyes"
        assert irony["fact_id"] == "scholar_agenda"
        assert irony["irony_type"] == "dramatic_irony"
        assert irony["reader_knows_truth"] is True

    def test_hidden_irony_when_reader_not_exposed(self, knowledge_layers):
        """Detects hidden irony when character has false belief but reader not yet exposed."""
        knowledge_layers.add_truth(
            fact_id="betrayal_plan",
            description="The scholar will activate the mechanism",
            chapter=0,
        )
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="betrayal_plan",
            description="Everything is fine",
            is_accurate=False,
            chapter=1,
            source="assumed",
        )
        # No exposure added for reader

        ironies = knowledge_layers.get_dramatic_irony(chapter=3)
        assert len(ironies) >= 1
        assert ironies[0]["irony_type"] == "hidden_irony"
        assert ironies[0]["reader_knows_truth"] is False

    def test_no_irony_when_belief_accurate(self, knowledge_layers):
        """No irony is returned when character belief is accurate."""
        knowledge_layers.add_truth(
            fact_id="force_collective",
            description="The Force is collective in wound regions",
            chapter=1,
        )
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="force_collective",
            description="The Force is collective in wound regions",
            is_accurate=True,
            chapter=2,
            source="witnessed",
        )
        ironies = knowledge_layers.get_dramatic_irony(chapter=3)
        assert len(ironies) == 0

    def test_no_irony_when_empty(self, knowledge_layers):
        """No irony is returned when no beliefs or truths exist."""
        ironies = knowledge_layers.get_dramatic_irony(chapter=1)
        assert ironies == []

    def test_irony_respects_chapter_filter(self, knowledge_layers):
        """Irony is not returned for beliefs acquired after the query chapter."""
        knowledge_layers.add_truth(
            fact_id="late_fact",
            description="A late-breaking truth",
            chapter=0,
        )
        knowledge_layers.add_belief(
            character_id="alex_reyes",
            fact_id="late_fact",
            description="Wrong belief about late fact",
            is_accurate=False,
            chapter=10,
            source="inferred",
        )
        # Query at chapter 5 should not see the belief acquired at chapter 10
        ironies = knowledge_layers.get_dramatic_irony(chapter=5)
        assert len(ironies) == 0
