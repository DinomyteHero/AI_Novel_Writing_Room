"""Tests for the hooks table and hook governance methods."""

import pytest

from src.memory.story_state import StoryState


class TestHookCRUD:
    """Tests for basic CRUD on the hooks table."""

    def test_add_and_get_hook(self, story_state):
        """add_hook followed by get_hook round-trips correctly."""
        story_state.add_hook(
            hook_id="broken_seal",
            description="The broken seal on the ancient door",
            hook_type="chekhov",
            planted_chapter=2,
            payoff_chapter=18,
            priority="hard",
            advancement_chapters=[5, 10, 14],
        )
        hook = story_state.get_hook("broken_seal")
        assert hook is not None
        assert hook["description"] == "The broken seal on the ancient door"
        assert hook["hook_type"] == "chekhov"
        assert hook["planted_chapter"] == 2
        assert hook["payoff_chapter"] == 18
        assert hook["priority"] == "hard"
        assert hook["advancement_chapters"] == [5, 10, 14]
        assert hook["current_status"] == "planted"
        assert hook["mention_only_count"] == 0

    def test_get_missing_hook_returns_none(self, story_state):
        """get_hook returns None for nonexistent hook."""
        assert story_state.get_hook("nonexistent") is None

    def test_update_hook(self, story_state):
        """update_hook modifies specific fields."""
        story_state.add_hook(
            hook_id="h1", description="Test hook", hook_type="foreshadow",
            planted_chapter=1, priority="soft",
        )
        story_state.update_hook("h1", current_status="advancing", last_advanced_chapter=5)
        hook = story_state.get_hook("h1")
        assert hook["current_status"] == "advancing"
        assert hook["last_advanced_chapter"] == 5

    def test_get_all_hooks(self, story_state):
        """get_all_hooks returns all hooks."""
        story_state.add_hook(hook_id="a", description="A", hook_type="chekhov",
                             planted_chapter=1, priority="hard")
        story_state.add_hook(hook_id="b", description="B", hook_type="foreshadow",
                             planted_chapter=2, priority="soft")
        hooks = story_state.get_all_hooks()
        assert len(hooks) == 2

    def test_get_all_hooks_filtered_by_book(self, story_state):
        """get_all_hooks filters by planted_book."""
        story_state.add_hook(hook_id="b1", description="Book 1 hook", hook_type="chekhov",
                             planted_chapter=1, planted_book=1, priority="hard")
        story_state.add_hook(hook_id="b2", description="Book 2 hook", hook_type="chekhov",
                             planted_chapter=1, planted_book=2, priority="hard")
        assert len(story_state.get_all_hooks(book_number=1)) == 1
        assert len(story_state.get_all_hooks(book_number=2)) == 1


class TestHookAdmissionControl:
    """Tests for hook budget enforcement."""

    def test_can_admit_soft_hook_always(self, story_state):
        """Soft hooks are always admitted regardless of budget."""
        assert story_state.can_admit_hook("soft", target_chapters=3) is True

    def test_can_admit_series_hook_always(self, story_state):
        """Series hooks are always admitted."""
        assert story_state.can_admit_hook("series", target_chapters=3) is True

    def test_can_admit_hard_hook_under_budget(self, story_state):
        """Hard hook admitted when under budget (target_chapters / 3)."""
        # Budget for 30 chapters = 10 hard hooks
        assert story_state.can_admit_hook("hard", target_chapters=30) is True

    def test_cannot_admit_hard_hook_over_budget(self, story_state):
        """Hard hook denied when at budget capacity."""
        # Budget for 6 chapters = 2 hard hooks. Fill with 2.
        story_state.add_hook(hook_id="h1", description="X", hook_type="chekhov",
                             planted_chapter=1, priority="hard")
        story_state.add_hook(hook_id="h2", description="Y", hook_type="chekhov",
                             planted_chapter=2, priority="hard")
        assert story_state.can_admit_hook("hard", target_chapters=6) is False

    def test_resolved_hooks_dont_count_against_budget(self, story_state):
        """Resolved hard hooks free up budget capacity."""
        story_state.add_hook(hook_id="h1", description="X", hook_type="chekhov",
                             planted_chapter=1, priority="hard")
        story_state.add_hook(hook_id="h2", description="Y", hook_type="chekhov",
                             planted_chapter=2, priority="hard")
        story_state.update_hook("h1", current_status="resolved")
        # Budget for 6 chapters = 2. One resolved, one active = room for 1 more.
        assert story_state.can_admit_hook("hard", target_chapters=6) is True


class TestHookAdvancement:
    """Tests for advance_hook and mention tracking."""

    def test_real_advancement_updates_chapters(self, story_state):
        """Real advancement adds chapter to advancement_chapters."""
        story_state.add_hook(hook_id="h1", description="X", hook_type="foreshadow",
                             planted_chapter=1, priority="soft")
        story_state.advance_hook("h1", chapter=5, is_real_advancement=True)
        hook = story_state.get_hook("h1")
        assert 5 in hook["advancement_chapters"]
        assert hook["current_status"] == "advancing"
        assert hook["last_advanced_chapter"] == 5

    def test_mention_only_increments_count(self, story_state):
        """Non-real advancement increments mention_only_count."""
        story_state.add_hook(hook_id="h2", description="Y", hook_type="foreshadow",
                             planted_chapter=1, priority="soft")
        result = story_state.advance_hook("h2", chapter=3, is_real_advancement=False)
        assert result is None  # No warning yet
        hook = story_state.get_hook("h2")
        assert hook["mention_only_count"] == 1

    def test_mention_only_warns_after_three(self, story_state):
        """Warning returned when mention_only_count exceeds 2."""
        story_state.add_hook(hook_id="h3", description="Z", hook_type="foreshadow",
                             planted_chapter=1, priority="soft")
        story_state.advance_hook("h3", chapter=2, is_real_advancement=False)
        story_state.advance_hook("h3", chapter=4, is_real_advancement=False)
        warning = story_state.advance_hook("h3", chapter=6, is_real_advancement=False)
        assert warning is not None
        assert warning["mention_only_count"] == 3
        assert "flag for review" in warning["message"]

    def test_advance_missing_hook_returns_none(self, story_state):
        """advance_hook returns None for nonexistent hook."""
        result = story_state.advance_hook("missing", chapter=1)
        assert result is None


class TestHookDebt:
    """Tests for get_hook_debt."""

    def test_hook_debt_returns_overdue_hard_hooks(self, story_state):
        """get_hook_debt returns hard hooks past payoff chapter."""
        story_state.add_hook(hook_id="overdue", description="Overdue hook",
                             hook_type="chekhov", planted_chapter=1,
                             payoff_chapter=10, priority="hard")
        debts = story_state.get_hook_debt(current_chapter=15)
        assert len(debts) == 1
        assert debts[0]["hook_id"] == "overdue"

    def test_hook_debt_ignores_resolved(self, story_state):
        """Resolved hooks are not counted as debt."""
        story_state.add_hook(hook_id="resolved", description="Resolved hook",
                             hook_type="chekhov", planted_chapter=1,
                             payoff_chapter=10, priority="hard")
        story_state.update_hook("resolved", current_status="resolved")
        debts = story_state.get_hook_debt(current_chapter=15)
        assert len(debts) == 0

    def test_hook_debt_ignores_soft_hooks(self, story_state):
        """Soft hooks are not counted as debt."""
        story_state.add_hook(hook_id="soft_overdue", description="Soft hook",
                             hook_type="foreshadow", planted_chapter=1,
                             payoff_chapter=10, priority="soft")
        debts = story_state.get_hook_debt(current_chapter=15)
        assert len(debts) == 0


class TestChapterHookAgenda:
    """Tests for get_chapter_hook_agenda."""

    def test_agenda_includes_hooks_to_plant(self, story_state):
        """Hooks planted at a chapter appear in to_plant."""
        story_state.add_hook(hook_id="plant_me", description="Plant this",
                             hook_type="chekhov", planted_chapter=3,
                             priority="hard")
        agenda = story_state.get_chapter_hook_agenda(3)
        assert len(agenda["to_plant"]) == 1
        assert agenda["to_plant"][0]["hook_id"] == "plant_me"

    def test_agenda_includes_hooks_to_resolve(self, story_state):
        """Hooks with payoff at a chapter appear in to_resolve."""
        story_state.add_hook(hook_id="resolve_me", description="Resolve this",
                             hook_type="chekhov", planted_chapter=1,
                             payoff_chapter=10, priority="hard")
        story_state.update_hook("resolve_me", current_status="advancing")
        agenda = story_state.get_chapter_hook_agenda(10)
        assert len(agenda["to_resolve"]) == 1

    def test_agenda_empty_for_quiet_chapter(self, story_state):
        """Chapters with no hook activity return empty agenda."""
        agenda = story_state.get_chapter_hook_agenda(99)
        assert agenda["to_plant"] == []
        assert agenda["to_advance"] == []
        assert agenda["to_resolve"] == []
