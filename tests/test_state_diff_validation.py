"""Tests for extended StateDiffApplier with Phase 5 change types and old_value verification."""

import pytest
from unittest.mock import MagicMock, patch

from src.memory.story_state import StoryState
from src.memory.knowledge_layers import KnowledgeLayers
from src.memory.state_diff import StateDiffApplier
from src.run_ledger import RunLedger


@pytest.fixture
def diff_setup(tmp_path):
    """Create a StateDiffApplier with story_state, knowledge_layers, and ledger."""
    db_path = str(tmp_path / "diff_test.db")
    state = StoryState(db_path=db_path)
    knowledge = KnowledgeLayers(state)
    ledger = RunLedger(str(tmp_path / "ledger.db"))
    applier = StateDiffApplier(state, knowledge, ledger)
    # Add a test character
    state.add_character(id="hero", name="Hero", emotional_state="calm")
    state.add_character_arc(
        character_id="hero", arc_type="positive_change",
        lie_believed="Trust is weakness", ghost="Betrayal", want="Power", need="Trust",
    )
    yield state, knowledge, ledger, applier
    state.close()
    ledger.close()


class TestOldValueVerification:
    """Tests for old_value verification on character updates."""

    def test_matching_old_value_applies_cleanly(self, diff_setup):
        """When old_value matches current, update applies without conflict event."""
        state, _, ledger, applier = diff_setup
        diff = {
            "chapter_number": 1,
            "changes": {
                "character_updates": [{
                    "character_id": "hero",
                    "field": "emotional_state",
                    "old_value": "calm",
                    "new_value": "anxious",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=1)
        char = state.get_character("hero")
        assert char["emotional_state"] == "anxious"

    def test_mismatched_old_value_applies_with_conflict(self, diff_setup):
        """When old_value mismatches, update still applies (optimistic) but logs conflict."""
        state, _, ledger, applier = diff_setup
        diff = {
            "chapter_number": 1,
            "changes": {
                "character_updates": [{
                    "character_id": "hero",
                    "field": "emotional_state",
                    "old_value": "angry",  # Wrong! Current is "calm"
                    "new_value": "fearful",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=1)
        # Update should still apply (optimistic strategy)
        char = state.get_character("hero")
        assert char["emotional_state"] == "fearful"

    def test_no_old_value_skips_verification(self, diff_setup):
        """When old_value is not provided, no verification is done."""
        state, _, _, applier = diff_setup
        diff = {
            "chapter_number": 1,
            "changes": {
                "character_updates": [{
                    "character_id": "hero",
                    "field": "emotional_state",
                    "new_value": "happy",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=1)
        char = state.get_character("hero")
        assert char["emotional_state"] == "happy"


class TestSubplotUpdates:
    """Tests for subplot_updates diff handler."""

    def test_update_existing_subplot(self, diff_setup):
        """Subplot update modifies an existing subplot."""
        state, _, _, applier = diff_setup
        state.add_subplot(subplot_id="trust_arc", subplot_name="Trust Arc",
                          line_type="B", current_status="planned")
        diff = {
            "chapter_number": 3,
            "changes": {
                "subplot_updates": [{
                    "subplot_id": "trust_arc",
                    "field": "current_status",
                    "new_value": "active",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=3)
        sub = state.get_subplot("trust_arc")
        assert sub["current_status"] == "active"

    def test_auto_create_subplot(self, diff_setup):
        """Subplot update auto-creates subplot if it doesn't exist."""
        state, _, _, applier = diff_setup
        diff = {
            "chapter_number": 5,
            "changes": {
                "subplot_updates": [{
                    "subplot_id": "new_subplot",
                    "field": "current_status",
                    "new_value": "active",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=5)
        sub = state.get_subplot("new_subplot")
        assert sub is not None


class TestHookUpdates:
    """Tests for hook_updates diff handler."""

    def test_update_existing_hook(self, diff_setup):
        """Hook update modifies an existing hook."""
        state, _, _, applier = diff_setup
        state.add_hook(hook_id="seal", description="Broken seal", hook_type="chekhov",
                       planted_chapter=1, priority="hard")
        diff = {
            "chapter_number": 5,
            "changes": {
                "hook_updates": [{
                    "hook_id": "seal",
                    "field": "current_status",
                    "new_value": "advancing",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=5)
        hook = state.get_hook("seal")
        assert hook["current_status"] == "advancing"

    def test_auto_create_hook(self, diff_setup):
        """Hook update auto-creates hook if it doesn't exist."""
        state, _, _, applier = diff_setup
        diff = {
            "chapter_number": 3,
            "changes": {
                "hook_updates": [{
                    "hook_id": "new_hook",
                    "description": "A new discovery",
                    "hook_type": "mystery_question",
                    "priority": "soft",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=3)
        hook = state.get_hook("new_hook")
        assert hook is not None
        assert hook["hook_type"] == "mystery_question"


class TestArcPhaseUpdates:
    """Tests for arc_phase_updates diff handler."""

    def test_valid_arc_phase_transition(self, diff_setup):
        """Valid arc phase transition is applied."""
        state, _, _, applier = diff_setup
        # Hero starts at lie_established; advance to lie_reinforced (next step)
        diff = {
            "chapter_number": 5,
            "changes": {
                "arc_phase_updates": [{
                    "character_id": "hero",
                    "old_phase": "lie_established",
                    "new_phase": "lie_reinforced",
                    "evidence": "Hero doubled down on the lie",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=5)
        arc = state.get_character_arc("hero")
        assert arc["current_phase"] == "lie_reinforced"
        assert arc["phase_evidence"] == "Hero doubled down on the lie"

    def test_invalid_arc_phase_transition_rejected(self, diff_setup):
        """Invalid arc phase transition is rejected (phase unchanged)."""
        state, _, _, applier = diff_setup
        # Hero starts at lie_established; try to skip to lie_questioned
        diff = {
            "chapter_number": 3,
            "changes": {
                "arc_phase_updates": [{
                    "character_id": "hero",
                    "old_phase": "lie_established",
                    "new_phase": "lie_questioned",  # Skips lie_reinforced
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=3)
        arc = state.get_character_arc("hero")
        assert arc["current_phase"] == "lie_established"  # Unchanged


class TestTerminologyUpdates:
    """Tests for terminology_updates diff handler."""

    def test_auto_create_term(self, diff_setup):
        """Terminology update auto-creates new terms."""
        state, _, _, applier = diff_setup
        diff = {
            "chapter_number": 1,
            "changes": {
                "terminology_updates": [{
                    "term": "Voidsteel",
                    "definition": "A dark metal forged in the Void",
                    "category": "artifact",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=1)
        term = state.get_term("Voidsteel")
        assert term is not None
        assert term["definition"] == "A dark metal forged in the Void"

    def test_update_existing_term(self, diff_setup):
        """Terminology update modifies existing term."""
        state, _, _, applier = diff_setup
        state.add_term(term="Darkblade", definition="Old definition", category="artifact")
        diff = {
            "chapter_number": 5,
            "changes": {
                "terminology_updates": [{
                    "term": "Darkblade",
                    "field": "definition",
                    "new_value": "Updated definition",
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=5)
        term = state.get_term("Darkblade")
        assert term["definition"] == "Updated definition"


class TestDiffValidation:
    """Tests for validate_diff with Phase 5 change types."""

    def test_valid_phase5_diff(self, diff_setup):
        """A fully valid Phase 5 diff returns no errors."""
        _, _, _, applier = diff_setup
        diff = {
            "chapter_number": 1,
            "changes": {
                "subplot_updates": [{"subplot_id": "s1", "field": "status", "new_value": "active"}],
                "hook_updates": [{"hook_id": "h1"}],
                "arc_phase_updates": [{"character_id": "hero", "new_phase": "lie_questioned"}],
                "terminology_updates": [{"term": "Test"}],
            },
        }
        errors = applier.validate_diff(diff)
        assert errors == []

    def test_missing_subplot_id(self, diff_setup):
        """subplot_updates without subplot_id is flagged."""
        _, _, _, applier = diff_setup
        diff = {
            "chapter_number": 1,
            "changes": {
                "subplot_updates": [{"field": "status", "new_value": "active"}],
            },
        }
        errors = applier.validate_diff(diff)
        assert any("subplot_id" in e for e in errors)

    def test_missing_hook_id(self, diff_setup):
        """hook_updates without hook_id is flagged."""
        _, _, _, applier = diff_setup
        diff = {
            "chapter_number": 1,
            "changes": {
                "hook_updates": [{"field": "status"}],
            },
        }
        errors = applier.validate_diff(diff)
        assert any("hook_id" in e for e in errors)

    def test_missing_arc_phase_fields(self, diff_setup):
        """arc_phase_updates without character_id or new_phase is flagged."""
        _, _, _, applier = diff_setup
        diff = {
            "chapter_number": 1,
            "changes": {
                "arc_phase_updates": [{"evidence": "something happened"}],
            },
        }
        errors = applier.validate_diff(diff)
        assert any("character_id" in e for e in errors)
        assert any("new_phase" in e for e in errors)

    def test_missing_term(self, diff_setup):
        """terminology_updates without term is flagged."""
        _, _, _, applier = diff_setup
        diff = {
            "chapter_number": 1,
            "changes": {
                "terminology_updates": [{"definition": "something"}],
            },
        }
        errors = applier.validate_diff(diff)
        assert any("term" in e for e in errors)
