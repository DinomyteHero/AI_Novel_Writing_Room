"""Tests for story physics validation layer.

Tests CausalityChainValidator, RevelationMap, PromisePayoffLedger,
PressureMatrix, SceneEconomics, and the top-level StoryPhysicsValidator.
"""

import pytest

from src.planning.story_physics import (
    CausalityChainValidator,
    PromisePayoffLedger,
    RevelationMap,
    StoryPhysicsValidator,
)
from src.planning.pressure_matrix import PressureMatrix
from src.planning.scene_economics import SceneEconomics


# ===================================================================
# CausalityChainValidator
# ===================================================================

class TestCausalityChainValidator:
    """Tests for CausalityChainValidator."""

    def test_valid_chain_no_issues(self):
        """A well-formed chain with causes and consequences produces no issues."""
        chains = [
            {
                "event_id": "e1",
                "chapter": 1,
                "causes": [],
                "consequences": ["e2"],
            },
            {
                "event_id": "e2",
                "chapter": 3,
                "causes": ["e1"],
                "consequences": ["e3"],
            },
            {
                "event_id": "e3",
                "chapter": 5,
                "causes": ["e2"],
                "consequences": [],
            },
        ]
        validator = CausalityChainValidator(chains)
        issues = validator.validate()
        assert issues == []

    def test_orphaned_event_flagged(self):
        """An event with no causes in a non-first chapter is flagged as orphaned."""
        chains = [
            {
                "event_id": "e1",
                "chapter": 1,
                "causes": [],
                "consequences": ["e2"],
            },
            {
                "event_id": "e2",
                "chapter": 3,
                "causes": [],
                "consequences": ["e3"],
            },
            {
                "event_id": "e3",
                "chapter": 5,
                "causes": ["e2"],
                "consequences": [],
            },
        ]
        validator = CausalityChainValidator(chains)
        issues = validator.validate()
        orphaned = [i for i in issues if i["issue_type"] == "orphaned"]
        assert len(orphaned) == 1
        assert orphaned[0]["event_id"] == "e2"

    def test_dead_end_event_flagged(self):
        """An event with no consequences in a non-final chapter is flagged as dead end."""
        chains = [
            {
                "event_id": "e1",
                "chapter": 1,
                "causes": [],
                "consequences": ["e2"],
            },
            {
                "event_id": "e2",
                "chapter": 3,
                "causes": ["e1"],
                "consequences": [],
            },
            {
                "event_id": "e3",
                "chapter": 5,
                "causes": ["e1"],
                "consequences": [],
            },
        ]
        validator = CausalityChainValidator(chains)
        issues = validator.validate()
        dead_ends = [i for i in issues if i["issue_type"] == "dead_end"]
        assert len(dead_ends) == 1
        assert dead_ends[0]["event_id"] == "e2"

    def test_chapter1_inciting_incident_allowed(self):
        """Events at chapter 1 with no causes are not flagged."""
        chains = [
            {
                "event_id": "inciting",
                "chapter": 1,
                "causes": [],
                "consequences": ["e2"],
            },
            {
                "event_id": "e2",
                "chapter": 3,
                "causes": ["inciting"],
                "consequences": [],
            },
        ]
        validator = CausalityChainValidator(chains)
        issues = validator.validate()
        orphaned = [i for i in issues if i["issue_type"] == "orphaned"]
        assert len(orphaned) == 0

    def test_final_chapter_no_consequences_allowed(self):
        """Events in the final chapter with no consequences are not flagged."""
        chains = [
            {
                "event_id": "e1",
                "chapter": 1,
                "causes": [],
                "consequences": ["climax"],
            },
            {
                "event_id": "climax",
                "chapter": 10,
                "causes": ["e1"],
                "consequences": [],
            },
        ]
        validator = CausalityChainValidator(chains)
        issues = validator.validate()
        dead_ends = [i for i in issues if i["issue_type"] == "dead_end"]
        assert len(dead_ends) == 0

    def test_empty_chains(self):
        """An empty chain list produces no issues."""
        validator = CausalityChainValidator([])
        assert validator.validate() == []

    def test_get_graph(self):
        """get_graph returns adjacency dict with correct edges."""
        chains = [
            {
                "event_id": "e1",
                "chapter": 1,
                "causes": [],
                "consequences": ["e2", "e3"],
            },
            {
                "event_id": "e2",
                "chapter": 2,
                "causes": ["e1"],
                "consequences": [],
            },
            {
                "event_id": "e3",
                "chapter": 3,
                "causes": ["e1"],
                "consequences": [],
            },
        ]
        validator = CausalityChainValidator(chains)
        graph = validator.get_graph()
        assert graph["e1"] == ["e2", "e3"]
        assert graph["e2"] == []
        assert graph["e3"] == []


# ===================================================================
# RevelationMap
# ===================================================================

class TestRevelationMap:
    """Tests for RevelationMap."""

    def test_climactic_revelation_early_flagged(self):
        """Climactic revelations before the 40% mark are flagged."""
        revelations = [
            {
                "info_id": "big_secret",
                "revealed_chapter": 1,
                "significance": "climactic",
            },
            {
                "info_id": "minor_thing",
                "revealed_chapter": 5,
                "significance": "minor",
            },
            {
                "info_id": "ending",
                "revealed_chapter": 10,
                "significance": "climactic",
            },
        ]
        rmap = RevelationMap(revelations)
        issues = rmap.validate_ordering()
        too_early = [i for i in issues if i["issue_type"] == "too_early"]
        assert len(too_early) == 1
        assert too_early[0]["info_id"] == "big_secret"

    def test_minor_revelation_late_flagged(self):
        """Minor revelations past the 80% mark are flagged."""
        revelations = [
            {
                "info_id": "setup_fact",
                "revealed_chapter": 2,
                "significance": "minor",
            },
            {
                "info_id": "late_minor",
                "revealed_chapter": 9,
                "significance": "minor",
            },
            {
                "info_id": "climax_reveal",
                "revealed_chapter": 10,
                "significance": "climactic",
            },
        ]
        rmap = RevelationMap(revelations)
        issues = rmap.validate_ordering()
        too_late = [i for i in issues if i["issue_type"] == "too_late"]
        assert len(too_late) == 1
        assert too_late[0]["info_id"] == "late_minor"

    def test_valid_ordering_no_issues(self):
        """Properly placed revelations produce no issues."""
        revelations = [
            {
                "info_id": "early_minor",
                "revealed_chapter": 2,
                "significance": "minor",
            },
            {
                "info_id": "mid_major",
                "revealed_chapter": 5,
                "significance": "major",
            },
            {
                "info_id": "climax_reveal",
                "revealed_chapter": 8,
                "significance": "climactic",
            },
            {
                "info_id": "final",
                "revealed_chapter": 10,
                "significance": "climactic",
            },
        ]
        rmap = RevelationMap(revelations)
        issues = rmap.validate_ordering()
        assert issues == []

    def test_empty_revelations(self):
        """Empty revelations list produces no issues."""
        rmap = RevelationMap([])
        assert rmap.validate_ordering() == []

    def test_get_timeline_sorted(self):
        """get_timeline returns revelations sorted by revealed_chapter."""
        revelations = [
            {"info_id": "c", "revealed_chapter": 10, "significance": "climactic"},
            {"info_id": "a", "revealed_chapter": 1, "significance": "minor"},
            {"info_id": "b", "revealed_chapter": 5, "significance": "major"},
        ]
        rmap = RevelationMap(revelations)
        timeline = rmap.get_timeline()
        assert [r["info_id"] for r in timeline] == ["a", "b", "c"]


# ===================================================================
# PromisePayoffLedger
# ===================================================================

class TestPromisePayoffLedger:
    """Tests for PromisePayoffLedger."""

    def test_overdue_promise_flagged(self):
        """A promise past its payoff chapter and still unfulfilled is flagged."""
        promises = [
            {
                "promise_id": "gun_on_wall",
                "planted_chapter": 1,
                "payoff_chapter": 5,
                "status": "unfulfilled",
                "type": "setup",
            },
        ]
        ledger = PromisePayoffLedger(promises)
        issues = ledger.check_at_milestone(chapter=7, total_chapters=20)
        overdue = [i for i in issues if i["issue_type"] == "overdue"]
        assert len(overdue) == 1
        assert overdue[0]["promise_id"] == "gun_on_wall"

    def test_fulfilled_promise_not_flagged(self):
        """A fulfilled promise is never flagged."""
        promises = [
            {
                "promise_id": "gun_on_wall",
                "planted_chapter": 1,
                "payoff_chapter": 5,
                "status": "fulfilled",
                "type": "setup",
            },
        ]
        ledger = PromisePayoffLedger(promises)
        issues = ledger.check_at_milestone(chapter=10, total_chapters=20)
        assert issues == []

    def test_chekhov_promise_lingering_too_long(self):
        """A chekhov-type promise unfulfilled for >60% of the story is flagged."""
        promises = [
            {
                "promise_id": "mysterious_box",
                "planted_chapter": 1,
                "status": "unfulfilled",
                "type": "chekhov",
            },
        ]
        ledger = PromisePayoffLedger(promises)
        # At chapter 15 of 20, the box was planted at 1 => age=14 > 12 (60% of 20)
        issues = ledger.check_at_milestone(chapter=15, total_chapters=20)
        no_payoff = [i for i in issues if i["issue_type"] == "no_payoff_planned"]
        assert len(no_payoff) == 1
        assert no_payoff[0]["promise_id"] == "mysterious_box"

    def test_update_status(self):
        """update_status changes the promise status and optional payoff_chapter."""
        promises = [
            {
                "promise_id": "gun_on_wall",
                "planted_chapter": 1,
                "status": "unfulfilled",
                "type": "setup",
            },
        ]
        ledger = PromisePayoffLedger(promises)
        ledger.update_status("gun_on_wall", "fulfilled", payoff_chapter=8)

        # Now it should not be in unfulfilled list
        unfulfilled = ledger.get_unfulfilled()
        assert len(unfulfilled) == 0

    def test_update_status_unknown_promise_raises(self):
        """update_status raises KeyError for an unknown promise_id."""
        ledger = PromisePayoffLedger([])
        with pytest.raises(KeyError, match="Unknown promise_id"):
            ledger.update_status("nonexistent", "fulfilled")

    def test_get_unfulfilled(self):
        """get_unfulfilled returns only promises with status 'unfulfilled'."""
        promises = [
            {"promise_id": "a", "planted_chapter": 1, "status": "unfulfilled", "type": "setup"},
            {"promise_id": "b", "planted_chapter": 2, "status": "fulfilled", "type": "setup"},
            {"promise_id": "c", "planted_chapter": 3, "status": "unfulfilled", "type": "chekhov"},
        ]
        ledger = PromisePayoffLedger(promises)
        unfulfilled = ledger.get_unfulfilled()
        assert len(unfulfilled) == 2
        assert {p["promise_id"] for p in unfulfilled} == {"a", "c"}


# ===================================================================
# PressureMatrix
# ===================================================================

class TestPressureMatrix:
    """Tests for PressureMatrix."""

    def test_coasting_characters_flagged(self):
        """Characters with pressure <= 2 for more than 1 consecutive chapter are flagged."""
        matrix = {
            "Ben": [
                {"chapter": 1, "pressure_level": 1, "external_pressure": "low", "internal_pressure": "low"},
                {"chapter": 2, "pressure_level": 2, "external_pressure": "low", "internal_pressure": "low"},
                {"chapter": 3, "pressure_level": 5, "external_pressure": "med", "internal_pressure": "med"},
                {"chapter": 4, "pressure_level": 7, "external_pressure": "high", "internal_pressure": "high"},
                {"chapter": 5, "pressure_level": 8, "external_pressure": "high", "internal_pressure": "high"},
                {"chapter": 6, "pressure_level": 9, "external_pressure": "high", "internal_pressure": "high"},
            ],
        }
        pm = PressureMatrix(matrix)
        issues = pm.validate_escalation()
        coasting = [i for i in issues if i["issue_type"] == "coasting"]
        assert len(coasting) == 1
        assert coasting[0]["character"] == "Ben"

    def test_flat_pressure_arc_flagged(self):
        """Characters whose early average >= late average are flagged."""
        matrix = {
            "Scholar": [
                {"chapter": 1, "pressure_level": 8, "external_pressure": "high", "internal_pressure": "high"},
                {"chapter": 2, "pressure_level": 7, "external_pressure": "high", "internal_pressure": "high"},
                {"chapter": 3, "pressure_level": 6, "external_pressure": "med", "internal_pressure": "high"},
                {"chapter": 4, "pressure_level": 5, "external_pressure": "med", "internal_pressure": "med"},
                {"chapter": 5, "pressure_level": 4, "external_pressure": "low", "internal_pressure": "med"},
                {"chapter": 6, "pressure_level": 3, "external_pressure": "low", "internal_pressure": "low"},
            ],
        }
        pm = PressureMatrix(matrix)
        issues = pm.validate_escalation()
        flat = [i for i in issues if i["issue_type"] == "flat_arc"]
        assert len(flat) == 1
        assert flat[0]["character"] == "Scholar"

    def test_valid_escalating_pressure_passes(self):
        """A properly escalating arc produces no coasting or flat arc issues."""
        matrix = {
            "Hero": [
                {"chapter": 1, "pressure_level": 3, "external_pressure": "low", "internal_pressure": "med"},
                {"chapter": 2, "pressure_level": 4, "external_pressure": "med", "internal_pressure": "med"},
                {"chapter": 3, "pressure_level": 5, "external_pressure": "med", "internal_pressure": "med"},
                {"chapter": 4, "pressure_level": 6, "external_pressure": "high", "internal_pressure": "med"},
                {"chapter": 5, "pressure_level": 7, "external_pressure": "high", "internal_pressure": "high"},
                {"chapter": 6, "pressure_level": 9, "external_pressure": "high", "internal_pressure": "high"},
            ],
        }
        pm = PressureMatrix(matrix)
        issues = pm.validate_escalation()
        assert issues == []

    def test_no_climax_peak_flagged(self):
        """Peak pressure outside the final third is flagged."""
        matrix = {
            "Mando": [
                {"chapter": 1, "pressure_level": 3, "external_pressure": "low", "internal_pressure": "low"},
                {"chapter": 2, "pressure_level": 10, "external_pressure": "high", "internal_pressure": "high"},
                {"chapter": 3, "pressure_level": 4, "external_pressure": "med", "internal_pressure": "med"},
                {"chapter": 4, "pressure_level": 5, "external_pressure": "med", "internal_pressure": "med"},
                {"chapter": 5, "pressure_level": 6, "external_pressure": "high", "internal_pressure": "med"},
                {"chapter": 6, "pressure_level": 7, "external_pressure": "high", "internal_pressure": "high"},
            ],
        }
        pm = PressureMatrix(matrix)
        issues = pm.validate_escalation()
        no_peak = [i for i in issues if i["issue_type"] == "no_climax_peak"]
        assert len(no_peak) == 1
        assert no_peak[0]["character"] == "Mando"

    def test_empty_matrix(self):
        """An empty matrix produces no issues."""
        pm = PressureMatrix({})
        assert pm.validate_escalation() == []

    def test_get_pressure_for_chapter(self):
        """get_pressure_for_chapter returns correct entry or None."""
        matrix = {
            "Ben": [
                {"chapter": 1, "pressure_level": 3, "external_pressure": "low", "internal_pressure": "low"},
                {"chapter": 2, "pressure_level": 5, "external_pressure": "med", "internal_pressure": "med"},
            ],
        }
        pm = PressureMatrix(matrix)
        entry = pm.get_pressure_for_chapter("Ben", 1)
        assert entry is not None
        assert entry["pressure_level"] == 3

        assert pm.get_pressure_for_chapter("Ben", 99) is None
        assert pm.get_pressure_for_chapter("Nobody", 1) is None

    def test_get_max_pressure_chapter(self):
        """get_max_pressure_chapter returns the chapter with peak pressure."""
        matrix = {
            "Ben": [
                {"chapter": 1, "pressure_level": 3, "external_pressure": "low", "internal_pressure": "low"},
                {"chapter": 5, "pressure_level": 9, "external_pressure": "high", "internal_pressure": "high"},
                {"chapter": 3, "pressure_level": 6, "external_pressure": "med", "internal_pressure": "med"},
            ],
        }
        pm = PressureMatrix(matrix)
        assert pm.get_max_pressure_chapter("Ben") == 5

    def test_get_max_pressure_chapter_unknown_raises(self):
        """get_max_pressure_chapter raises KeyError for unknown character."""
        pm = PressureMatrix({})
        with pytest.raises(KeyError):
            pm.get_max_pressure_chapter("Nobody")


# ===================================================================
# SceneEconomics
# ===================================================================

class TestSceneEconomics:
    """Tests for SceneEconomics."""

    def test_missing_why_now_flagged(self):
        """Scene cards without a why_now field are flagged."""
        cards = [
            {"chapter_number": 1, "scene_number": 1},
            {"chapter_number": 1, "scene_number": 2, "why_now": ""},
        ]
        se = SceneEconomics()
        issues = se.validate_scene_cards(cards)
        missing = [i for i in issues if i["issue_type"] == "missing_why_now"]
        assert len(missing) == 2

    def test_generic_why_now_flagged(self):
        """Scene cards with generic boilerplate why_now are flagged."""
        cards = [
            {
                "chapter_number": 2,
                "scene_number": 1,
                "why_now": "Because the outline says so",
            },
            {
                "chapter_number": 3,
                "scene_number": 1,
                "why_now": "To advance the plot",
            },
            {
                "chapter_number": 4,
                "scene_number": 1,
                "why_now": "Per the outline, this happens here",
            },
        ]
        se = SceneEconomics()
        issues = se.validate_scene_cards(cards)
        generic = [i for i in issues if i["issue_type"] == "generic_why_now"]
        assert len(generic) == 3

    def test_valid_why_now_passes(self):
        """Scene cards with substantive why_now produce no issues."""
        cards = [
            {
                "chapter_number": 1,
                "scene_number": 1,
                "why_now": "Ben must confront the scholar about the inconsistencies "
                           "he noticed at the Celestial marker before the crew "
                           "descends into the next wound region.",
            },
            {
                "chapter_number": 1,
                "scene_number": 2,
                "why_now": "The Mandalorian's discovery of footprints near the "
                           "installation forces the crew to acknowledge the "
                           "scholar's hidden knowledge.",
            },
        ]
        se = SceneEconomics()
        issues = se.validate_scene_cards(cards)
        assert issues == []

    def test_empty_cards(self):
        """Empty scene cards list produces no issues."""
        se = SceneEconomics()
        assert se.validate_scene_cards([]) == []


# ===================================================================
# StoryPhysicsValidator (top-level orchestrator)
# ===================================================================

class TestStoryPhysicsValidator:
    """Tests for the top-level StoryPhysicsValidator."""

    def test_validate_all_runs_all_sub_validators(self):
        """validate_all returns a combined report with keys for each sub-validator."""
        story_physics = {
            "causality_chains": [
                {
                    "event_id": "e1",
                    "chapter": 1,
                    "causes": [],
                    "consequences": ["e2"],
                },
                {
                    "event_id": "e2",
                    "chapter": 5,
                    "causes": ["e1"],
                    "consequences": [],
                },
            ],
            "revelation_map": [
                {"info_id": "r1", "revealed_chapter": 3, "significance": "minor"},
                {"info_id": "r2", "revealed_chapter": 5, "significance": "climactic"},
            ],
            "promise_payoff_ledger": [
                {
                    "promise_id": "p1",
                    "planted_chapter": 1,
                    "status": "unfulfilled",
                    "type": "setup",
                },
            ],
            "pressure_matrix": {
                "Ben": [
                    {"chapter": 1, "pressure_level": 3, "external_pressure": "low", "internal_pressure": "low"},
                    {"chapter": 2, "pressure_level": 5, "external_pressure": "med", "internal_pressure": "med"},
                    {"chapter": 3, "pressure_level": 7, "external_pressure": "high", "internal_pressure": "med"},
                    {"chapter": 4, "pressure_level": 8, "external_pressure": "high", "internal_pressure": "high"},
                    {"chapter": 5, "pressure_level": 9, "external_pressure": "high", "internal_pressure": "high"},
                ],
            },
        }
        validator = StoryPhysicsValidator(story_physics)
        report = validator.validate_all(total_chapters=5)

        assert "causality_issues" in report
        assert "revelation_issues" in report
        assert "promise_issues" in report
        assert "pressure_issues" in report
        assert isinstance(report["causality_issues"], list)
        assert isinstance(report["revelation_issues"], list)
        assert isinstance(report["promise_issues"], list)
        assert isinstance(report["pressure_issues"], list)

    def test_validate_all_with_empty_data(self):
        """validate_all handles fully empty data gracefully."""
        validator = StoryPhysicsValidator({})
        report = validator.validate_all()
        assert report["causality_issues"] == []
        assert report["revelation_issues"] == []
        assert report["promise_issues"] == []
        assert report["pressure_issues"] == []

    def test_sub_validators_accessible(self):
        """The top-level validator exposes sub-validators as attributes."""
        story_physics = {
            "causality_chains": [],
            "revelation_map": [],
            "promise_payoff_ledger": [],
            "pressure_matrix": {},
        }
        validator = StoryPhysicsValidator(story_physics)
        assert isinstance(validator.causality, CausalityChainValidator)
        assert isinstance(validator.revelations, RevelationMap)
        assert isinstance(validator.promises, PromisePayoffLedger)
        assert isinstance(validator.pressure, PressureMatrix)
