"""Tests for StateDiffApplier.sanitize_diff() — fuzzy matching, no-op stripping, phase mapping."""

import pytest

from src.memory.story_state import StoryState
from src.memory.knowledge_layers import KnowledgeLayers
from src.memory.state_diff import StateDiffApplier
from src.run_ledger import RunLedger


@pytest.fixture
def diff_env(tmp_path):
    db_path = str(tmp_path / "sanitize_test.db")
    state = StoryState(db_path=db_path)
    knowledge = KnowledgeLayers(state)
    ledger = RunLedger(str(tmp_path / "ledger.db"))
    applier = StateDiffApplier(state, knowledge, ledger)
    state.add_character(id="hero", name="Hero", emotional_state="calm")
    state.add_character_arc(
        character_id="hero", arc_type="positive_change",
        lie_believed="test", ghost="test", want="test", need="test",
    )
    state.add_subplot(
        subplot_id="sp1", subplot_name="Subplot 1",
        line_type="B", current_status="planned",
    )
    state.add_hook(
        hook_id="h1", description="Hook 1",
        hook_type="foreshadow", planted_chapter=1, priority="hard",
    )
    yield state, knowledge, ledger, applier
    state.close()
    ledger.close()


class TestHookStatusFuzzy:
    def test_active_to_advancing(self, diff_env):
        _, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "hook_updates": [{
                    "hook_id": "h1",
                    "field": "current_status",
                    "new_value": "active",
                }],
            },
        }
        sanitized, warnings = applier.sanitize_diff(diff)
        assert sanitized["changes"]["hook_updates"][0]["new_value"] == "advancing"
        assert any("fuzzy" in w for w in warnings)

    def test_completed_to_resolved(self, diff_env):
        _, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "hook_updates": [{
                    "hook_id": "h1",
                    "field": "status",  # LLM alias for current_status
                    "new_value": "completed",
                }],
            },
        }
        sanitized, warnings = applier.sanitize_diff(diff)
        assert sanitized["changes"]["hook_updates"][0]["new_value"] == "resolved"

    def test_valid_status_not_changed(self, diff_env):
        _, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "hook_updates": [{
                    "hook_id": "h1",
                    "field": "current_status",
                    "new_value": "advancing",
                }],
            },
        }
        sanitized, warnings = applier.sanitize_diff(diff)
        assert sanitized["changes"]["hook_updates"][0]["new_value"] == "advancing"
        assert not any("fuzzy" in w for w in warnings)


class TestSubplotStatusFuzzy:
    def test_escalating_to_climaxing(self, diff_env):
        _, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "subplot_updates": [{
                    "subplot_id": "sp1",
                    "field": "current_status",
                    "new_value": "escalating",
                }],
            },
        }
        sanitized, warnings = applier.sanitize_diff(diff)
        assert sanitized["changes"]["subplot_updates"][0]["new_value"] == "climaxing"


class TestArcPhaseLabelMapping:
    def test_concept_seed_label_mapped(self, diff_env):
        _, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "arc_phase_updates": [{
                    "character_id": "hero",
                    "new_phase": "lie_challenged",  # Planning label, not DB phase
                }],
            },
        }
        sanitized, warnings = applier.sanitize_diff(diff)
        assert sanitized["changes"]["arc_phase_updates"][0]["new_phase"] == "lie_questioned"

    def test_valid_phase_not_changed(self, diff_env):
        _, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "arc_phase_updates": [{
                    "character_id": "hero",
                    "new_phase": "lie_reinforced",
                }],
            },
        }
        sanitized, warnings = applier.sanitize_diff(diff)
        assert sanitized["changes"]["arc_phase_updates"][0]["new_phase"] == "lie_reinforced"


class TestOldValueCorrection:
    def test_mismatched_old_value_corrected(self, diff_env):
        state, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "character_updates": [{
                    "character_id": "hero",
                    "field": "emotional_state",
                    "old_value": "angry",  # Wrong! Actual is "calm"
                    "new_value": "fearful",
                }],
            },
        }
        sanitized, warnings = applier.sanitize_diff(diff)
        assert sanitized["changes"]["character_updates"][0]["old_value"] == "calm"
        assert any("corrected" in w for w in warnings)


class TestNoOpStripping:
    def test_noop_removed(self, diff_env):
        _, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "character_updates": [{
                    "character_id": "hero",
                    "field": "emotional_state",
                    "old_value": "calm",
                    "new_value": "calm",  # No change
                }],
            },
        }
        sanitized, warnings = applier.sanitize_diff(diff)
        assert len(sanitized["changes"]["character_updates"]) == 0
        assert any("no-op" in w for w in warnings)

    def test_real_change_kept(self, diff_env):
        _, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "character_updates": [{
                    "character_id": "hero",
                    "field": "emotional_state",
                    "old_value": "calm",
                    "new_value": "fearful",
                }],
            },
        }
        sanitized, warnings = applier.sanitize_diff(diff)
        assert len(sanitized["changes"]["character_updates"]) == 1


class TestEndToEndSanitization:
    """Verify sanitize_diff runs automatically as part of apply_diff."""

    def test_fuzzy_status_applied_through_apply_diff(self, diff_env):
        state, _, _, applier = diff_env
        diff = {
            "chapter_number": 1,
            "changes": {
                "hook_updates": [{
                    "hook_id": "h1",
                    "field": "current_status",
                    "new_value": "active",  # Fuzzy -> "advancing"
                }],
            },
        }
        applier.apply_diff(diff, chapter_number=1)
        hook = state.get_hook("h1")
        assert hook["current_status"] == "advancing"
