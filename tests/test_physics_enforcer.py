"""Tests for the PhysicsEnforcer."""

import pytest

from src.planning.physics_enforcer import PhysicsEnforcer


@pytest.fixture
def concept_seed_with_physics():
    """Concept seed with story physics data."""
    return {
        "meta": {"target_chapters": 10, "project_title": "Test Novel"},
        "story_physics": {
            "causality_chains": [
                {
                    "event_id": "inciting_incident",
                    "chapter": 1,
                    "causes": [],
                    "consequences": ["rising_action"],
                },
                {
                    "event_id": "rising_action",
                    "chapter": 3,
                    "causes": ["inciting_incident"],
                    "consequences": ["climax"],
                },
                {
                    "event_id": "climax",
                    "chapter": 10,
                    "causes": ["rising_action"],
                    "consequences": [],
                },
            ],
            "revelation_map": [
                {"info_id": "secret_1", "revealed_chapter": 5, "significance": "minor"},
                {"info_id": "big_reveal", "revealed_chapter": 8, "significance": "climactic"},
            ],
            "promise_payoff_ledger": [
                {
                    "promise_id": "gun_on_wall",
                    "type": "chekhov",
                    "planted_chapter": 1,
                    "payoff_chapter": 8,
                    "status": "unfulfilled",
                },
            ],
            "pressure_matrix": {
                "protagonist": [
                    {"chapter": 1, "pressure_level": 3, "external_pressure": "low", "internal_pressure": "low"},
                    {"chapter": 5, "pressure_level": 5, "external_pressure": "med", "internal_pressure": "med"},
                    {"chapter": 10, "pressure_level": 9, "external_pressure": "high", "internal_pressure": "high"},
                ],
            },
        },
    }


@pytest.fixture
def scene_card_valid():
    return {
        "chapter_number": 1,
        "scene_number": 1,
        "pov_character": "protagonist",
        "why_now": "Opening scene establishes the protagonist's normal world before disruption.",
    }


@pytest.fixture
def scene_card_missing_why_now():
    return {
        "chapter_number": 3,
        "scene_number": 1,
        "pov_character": "protagonist",
    }


class TestPhysicsEnforcer:

    def test_validate_pre_chapter_clean(self, concept_seed_with_physics, scene_card_valid):
        enforcer = PhysicsEnforcer(concept_seed_with_physics)
        result = enforcer.validate_pre_chapter(scene_card_valid)

        assert result["passed"] is True
        assert len(result["issues"]) == 0

    def test_validate_pre_chapter_missing_why_now(self, concept_seed_with_physics, scene_card_missing_why_now):
        enforcer = PhysicsEnforcer(concept_seed_with_physics)
        result = enforcer.validate_pre_chapter(scene_card_missing_why_now)

        assert result["passed"] is False
        assert any(i["issue_type"] == "missing_why_now" for i in result["issues"])

    def test_validate_post_chapter(self, concept_seed_with_physics, scene_card_valid):
        enforcer = PhysicsEnforcer(concept_seed_with_physics)
        result = enforcer.validate_post_chapter(scene_card_valid, "Some prose text.", 1)

        # No orphaned events with our valid chain
        assert isinstance(result["passed"], bool)
        assert isinstance(result["issues"], list)

    def test_validate_milestone(self, concept_seed_with_physics):
        enforcer = PhysicsEnforcer(concept_seed_with_physics)
        chapter_results = [{"chapter_number": i} for i in range(1, 6)]
        result = enforcer.validate_milestone("midpoint", chapter_results)

        assert "summary" in result
        assert "midpoint" in result["summary"]
        assert isinstance(result["passed"], bool)

    def test_empty_story_physics(self):
        """Graceful handling of concept seed without story_physics."""
        seed = {"meta": {"target_chapters": 10}}
        enforcer = PhysicsEnforcer(seed)
        card = {"chapter_number": 1, "scene_number": 1, "why_now": "Good reason."}
        result = enforcer.validate_pre_chapter(card)

        assert result["passed"] is True

    def test_low_pressure_flagged(self, concept_seed_with_physics):
        """Low pressure on POV character generates a recommendation."""
        # Modify pressure to be very low at chapter 5
        concept_seed_with_physics["story_physics"]["pressure_matrix"]["hero"] = [
            {"chapter": 5, "pressure_level": 1, "external_pressure": "none", "internal_pressure": "none"},
        ]
        enforcer = PhysicsEnforcer(concept_seed_with_physics)
        card = {"chapter_number": 5, "scene_number": 1, "pov_character": "hero", "why_now": "Valid."}
        result = enforcer.validate_pre_chapter(card)

        assert any(i["issue_type"] == "low_pressure" for i in result["issues"])

    def test_promise_overdue_flagged(self, concept_seed_with_physics):
        """Overdue promise is flagged at late chapter."""
        enforcer = PhysicsEnforcer(concept_seed_with_physics)
        card = {"chapter_number": 9, "scene_number": 1, "pov_character": "protagonist", "why_now": "Valid."}
        result = enforcer.validate_pre_chapter(card)

        # The chekhov promise has payoff_chapter=8, checking at chapter 9 should flag it
        assert any(
            i.get("promise_id") == "gun_on_wall" and i["issue_type"] == "overdue"
            for i in result["issues"]
        )


class TestStrictMode:
    """Strict mode raises PhysicsViolationError on critical issues."""

    def test_strict_raises_on_missing_why_now(self, concept_seed_with_physics):
        from src.planning.physics_enforcer import PhysicsViolationError

        enforcer = PhysicsEnforcer(concept_seed_with_physics, strict_mode=True)
        card = {"chapter_number": 1, "scene_number": 1}  # no why_now
        with pytest.raises(PhysicsViolationError) as exc_info:
            enforcer.validate_pre_chapter(card)
        assert len(exc_info.value.violations) >= 1
        assert exc_info.value.violations[0]["issue_type"] == "missing_why_now"

    def test_strict_raises_on_overdue_promise(self, concept_seed_with_physics):
        from src.planning.physics_enforcer import PhysicsViolationError

        enforcer = PhysicsEnforcer(concept_seed_with_physics, strict_mode=True)
        card = {"chapter_number": 9, "scene_number": 1, "why_now": "Valid."}
        with pytest.raises(PhysicsViolationError) as exc_info:
            enforcer.validate_pre_chapter(card)
        assert any(v["issue_type"] == "overdue" for v in exc_info.value.violations)

    def test_advisory_mode_does_not_raise(self, concept_seed_with_physics):
        """Default advisory mode returns issues without raising."""
        enforcer = PhysicsEnforcer(concept_seed_with_physics, strict_mode=False)
        card = {"chapter_number": 1, "scene_number": 1}  # no why_now
        result = enforcer.validate_pre_chapter(card)
        assert result["passed"] is False  # issues exist, but no exception

    def test_strict_passes_valid_card(self, concept_seed_with_physics, scene_card_valid):
        """Strict mode does not raise when card is valid."""
        enforcer = PhysicsEnforcer(concept_seed_with_physics, strict_mode=True)
        result = enforcer.validate_pre_chapter(scene_card_valid)
        assert result["passed"] is True
