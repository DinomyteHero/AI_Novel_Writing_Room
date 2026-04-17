"""Tests for the ChapterGateCritic agent and orchestrator chapter detection."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.chapter_gate_critic import (
    BLUEPRINT_CHECK_CODES,
    ChapterGateCritic,
    _load_blueprint,
    _resolve_blueprint_path,
)
from src.orchestrator import Orchestrator


SAMPLE_BLUEPRINT = {
    "chapter_number": 1,
    "chapter_mission": "Establish restlessness and launch the investigation.",
    "chapter_turn": "Protagonist moves from passive unease to active pursuit.",
    "structural_phase": "setup",
    "scene_count": 3,
    "scene_plan": [
        {"scene_number": 1, "role": "hook", "dialogue_expectation": "interior", "target_word_count": 1250, "purpose": "establish wrongness"},
        {"scene_number": 2, "role": "reveal", "dialogue_expectation": "balanced", "target_word_count": 1250, "purpose": "validate and assign"},
        {"scene_number": 3, "role": "decision", "dialogue_expectation": "balanced", "target_word_count": 1250, "purpose": "depart"},
    ],
    "reveal_payload": ["R01"],
    "subplot_obligations": ["SP-A", "SP3"],
    "pacing_curve": "rising",
    "exit_vector": "Ben in hyperspace, wrongness now directional",
    "chapter_word_target": 3750,
}


class TestIsLastSceneInChapter:
    """Test the static _is_last_scene_in_chapter helper."""

    def test_last_scene_in_multi_scene_chapter(self):
        cards = [
            {"chapter_number": 1, "scene_number": 1},
            {"chapter_number": 1, "scene_number": 2},
            {"chapter_number": 2, "scene_number": 1},
        ]
        assert not Orchestrator._is_last_scene_in_chapter(0, cards)
        assert Orchestrator._is_last_scene_in_chapter(1, cards)
        assert Orchestrator._is_last_scene_in_chapter(2, cards)

    def test_single_scene_chapter(self):
        cards = [
            {"chapter_number": 1, "scene_number": 1},
            {"chapter_number": 2, "scene_number": 1},
        ]
        assert Orchestrator._is_last_scene_in_chapter(0, cards)
        assert Orchestrator._is_last_scene_in_chapter(1, cards)

    def test_single_card(self):
        cards = [{"chapter_number": 1, "scene_number": 1}]
        assert Orchestrator._is_last_scene_in_chapter(0, cards)


class TestChapterGateCriticFormatting:
    """Test the ChapterGateCritic context formatting."""

    def test_format_includes_all_scenes(self, multi_scene_chapter_cards, mock_router):
        critic = ChapterGateCritic(mock_router)

        context = {
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": [
                "Scene 1 prose here.",
                "Scene 2 prose here.",
                "Scene 3 prose here.",
            ],
            "chapter_number": 5,
        }

        formatted = critic._format_context(context)
        assert "Chapter 5" in formatted
        assert "Scene 1 — Card" in formatted
        assert "Scene 2 — Card" in formatted
        assert "Scene 3 — Card" in formatted
        assert "Scene 1 prose here." in formatted
        assert "Scene 3 prose here." in formatted

    @pytest.mark.asyncio
    async def test_run_parses_pass_response(self, multi_scene_chapter_cards):
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_passed": True,
            "chapter_level_failures": [],
            "scene_level_flags": [],
            "metrics": {
                "scene_variety_index": 0.7,
                "conflict_density": 0.5,
                "chapter_hook_strength": 0.8,
                "arc_pressure_progression": "ascending",
            },
        })

        critic = ChapterGateCritic(router)
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["prose 1", "prose 2", "prose 3"],
            "chapter_number": 5,
        })

        assert result["chapter_passed"] is True
        assert result["chapter_level_failures"] == []

    @pytest.mark.asyncio
    async def test_run_handles_non_dict_response(self, multi_scene_chapter_cards):
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "content": "not valid json at all"
        })

        critic = ChapterGateCritic(router)
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["prose 1", "prose 2", "prose 3"],
            "chapter_number": 5,
        })

        assert result["chapter_passed"] is False
        assert len(result["chapter_level_failures"]) > 0
        assert result["chapter_level_failures"][0]["check"] == "parse_error"


class TestBlueprintPathResolution:
    """Tests for the _resolve_blueprint_path helper."""

    def test_explicit_path_wins(self):
        path = _resolve_blueprint_path({
            "blueprint_path": "/explicit/path/chapter_07.json",
            "franchise_slug": "sw",
            "book_slug": "ra",
            "chapter_number": 1,
        })
        assert str(path).endswith("chapter_07.json")

    def test_derives_from_identifiers(self, tmp_path):
        path = _resolve_blueprint_path({
            "franchise_slug": "star-wars-legends-eu",
            "book_slug": "the-ruusan-atonement",
            "chapter_number": 1,
            "base_dir": str(tmp_path),
        })
        assert path is not None
        assert path.parts[-4:] == (
            "star-wars-legends-eu",
            "books",
            "the-ruusan-atonement",
            "chapter_blueprints",
        ) or path.name == "chapter_01.json"
        assert path.name == "chapter_01.json"

    def test_returns_none_when_identifiers_missing(self):
        assert _resolve_blueprint_path({"chapter_number": 1}) is None
        assert _resolve_blueprint_path({"franchise_slug": "x", "book_slug": "y"}) is None


class TestBlueprintLoading:
    """Tests for the _load_blueprint helper."""

    def test_preloaded_blueprint_returned_unchanged(self):
        assert _load_blueprint({"chapter_blueprint": SAMPLE_BLUEPRINT}) is SAMPLE_BLUEPRINT

    def test_reads_json_from_disk(self, tmp_path):
        blueprint_dir = tmp_path / "data" / "franchises" / "sw" / "books" / "rb" / "chapter_blueprints"
        blueprint_dir.mkdir(parents=True)
        (blueprint_dir / "chapter_01.json").write_text(json.dumps(SAMPLE_BLUEPRINT), encoding="utf-8")

        loaded = _load_blueprint({
            "franchise_slug": "sw",
            "book_slug": "rb",
            "chapter_number": 1,
            "base_dir": str(tmp_path),
        })
        assert loaded == SAMPLE_BLUEPRINT

    def test_missing_file_returns_none(self, tmp_path):
        assert (
            _load_blueprint({
                "franchise_slug": "sw",
                "book_slug": "rb",
                "chapter_number": 99,
                "base_dir": str(tmp_path),
            })
            is None
        )

    def test_unparseable_file_returns_none(self, tmp_path, caplog):
        blueprint_dir = tmp_path / "data" / "franchises" / "sw" / "books" / "rb" / "chapter_blueprints"
        blueprint_dir.mkdir(parents=True)
        (blueprint_dir / "chapter_01.json").write_text("{ not valid json", encoding="utf-8")

        result = _load_blueprint({
            "franchise_slug": "sw",
            "book_slug": "rb",
            "chapter_number": 1,
            "base_dir": str(tmp_path),
        })
        assert result is None


class TestBlueprintAwarePrompt:
    """Tests that verify blueprint-aware checks appear in the prompt context."""

    def test_blueprint_section_present_when_loaded(
        self, multi_scene_chapter_cards, mock_router
    ):
        critic = ChapterGateCritic(mock_router)
        formatted = critic._format_context({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
            "chapter_blueprint": SAMPLE_BLUEPRINT,
        })
        assert "## Chapter Blueprint" in formatted
        assert SAMPLE_BLUEPRINT["chapter_mission"] in formatted
        assert "exit_vector" in formatted

    def test_blueprint_check_codes_listed_in_prompt(
        self, multi_scene_chapter_cards, mock_router
    ):
        critic = ChapterGateCritic(mock_router)
        formatted = critic._format_context({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
            "chapter_blueprint": SAMPLE_BLUEPRINT,
        })
        for code in BLUEPRINT_CHECK_CODES:
            assert code in formatted, f"check code {code!r} missing from prompt"

    def test_blueprint_absent_leaves_prompt_unchanged(
        self, multi_scene_chapter_cards, mock_router
    ):
        critic = ChapterGateCritic(mock_router)
        formatted = critic._format_context({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        })
        assert "## Chapter Blueprint" not in formatted
        for code in BLUEPRINT_CHECK_CODES:
            assert code not in formatted
        # The six composition-only checks must still be in place
        assert "mission_distinctness" in formatted
        assert "stakes_escalation" in formatted
        assert "pressure_progression" in formatted


class TestBlueprintAwareEvaluation:
    """Tests that blueprint-check failures and the blueprint_used flag flow
    through to the run() return value."""

    @pytest.mark.asyncio
    async def test_blueprint_used_flag_true_when_loaded(
        self, multi_scene_chapter_cards
    ):
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_passed": True,
            "chapter_level_failures": [],
            "scene_level_flags": [],
            "metrics": {},
        })
        critic = ChapterGateCritic(router)
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
            "chapter_blueprint": SAMPLE_BLUEPRINT,
        })
        assert result["blueprint_used"] is True

    @pytest.mark.asyncio
    async def test_blueprint_used_flag_false_when_absent(
        self, multi_scene_chapter_cards
    ):
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_passed": True,
            "chapter_level_failures": [],
            "scene_level_flags": [],
            "metrics": {},
        })
        critic = ChapterGateCritic(router)
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        })
        assert result["blueprint_used"] is False

    @pytest.mark.asyncio
    async def test_blueprint_failure_code_surfaces(
        self, multi_scene_chapter_cards
    ):
        """A reveal_payload_delivered failure from the critic surfaces in
        chapter_level_failures."""
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_passed": False,
            "chapter_level_failures": [
                {
                    "check": "reveal_payload_delivered",
                    "description": "R01 is never surfaced in scene 3.",
                },
            ],
            "scene_level_flags": [],
            "metrics": {},
        })
        critic = ChapterGateCritic(router)
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
            "chapter_blueprint": SAMPLE_BLUEPRINT,
        })
        codes = [f["check"] for f in result["chapter_level_failures"]]
        assert "reveal_payload_delivered" in codes
        assert result["chapter_passed"] is False


# ---------------------------------------------------------------------------
# Phase 7.4 — ChapterGateCritic lore wiring
# ---------------------------------------------------------------------------


def _mock_lore_service(entries: list[dict]) -> MagicMock:
    """Build a lore service whose get_lore_for_context returns ``entries``."""
    svc = MagicMock()
    svc.get_lore_for_context = MagicMock(return_value=entries)
    return svc


CANONICAL_LORE = [
    {
        "title": "Ruusan Memorial",
        "category": "location",
        "content": (
            "A long ridge on the planet Ruusan marked by seven obelisks, "
            "each commemorating a Jedi who fell during the Seventh Battle."
        ),
        "metadata": {},
    },
    {
        "title": "Thought Bomb",
        "category": "force_mechanic",
        "content": (
            "A Sith technique that consumes all Force-users within range, "
            "binding their essence to a single crystalline core."
        ),
        "metadata": {},
    },
]


class TestChapterGateCriticLoreWiring:
    """Phase 7.4 — when lore_service + universe_id are supplied, the
    critic retrieves canonical lore and adds lore_consistency_check to
    its evaluation."""

    def test_lore_section_absent_when_service_missing(
        self, multi_scene_chapter_cards, mock_router
    ):
        critic = ChapterGateCritic(mock_router)  # no lore_service
        context = {
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        }
        formatted = critic._format_context(context)
        assert "Lore Context" not in formatted
        assert "lore_consistency_check" not in formatted

    def test_lore_section_present_when_service_supplied(
        self, multi_scene_chapter_cards, mock_router
    ):
        lore = _mock_lore_service(CANONICAL_LORE)
        critic = ChapterGateCritic(
            mock_router, lore_service=lore, universe_id="fr-test"
        )
        formatted = critic._format_context({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        })
        assert "Lore Context" in formatted
        assert "Ruusan Memorial" in formatted
        assert "Thought Bomb" in formatted
        assert "lore_consistency_check" in formatted
        # Retrieval was called with the top_k default and only canonical.
        call = lore.get_lore_for_context.call_args
        assert call.kwargs["universe_id"] == "fr-test"
        assert call.kwargs["include_provisional"] is False

    def test_lore_section_omits_when_universe_id_missing(
        self, multi_scene_chapter_cards, mock_router
    ):
        lore = _mock_lore_service(CANONICAL_LORE)
        # lore_service is set but universe_id is None — retrieval skipped.
        critic = ChapterGateCritic(mock_router, lore_service=lore, universe_id=None)
        formatted = critic._format_context({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        })
        assert "Lore Context" not in formatted
        lore.get_lore_for_context.assert_not_called()

    def test_empty_lore_result_hides_section(
        self, multi_scene_chapter_cards, mock_router
    ):
        """No canonical entries returned — section omitted, no lore check."""
        lore = _mock_lore_service([])
        critic = ChapterGateCritic(mock_router, lore_service=lore, universe_id="fr")
        formatted = critic._format_context({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        })
        assert "Lore Context" not in formatted
        assert "lore_consistency_check" not in formatted

    def test_lore_retrieval_failure_degrades_gracefully(
        self, multi_scene_chapter_cards, mock_router
    ):
        """An exception from lore_service.get_lore_for_context is caught —
        the critic still formats a valid prompt without the lore section."""
        lore = MagicMock()
        lore.get_lore_for_context = MagicMock(side_effect=RuntimeError("db offline"))
        critic = ChapterGateCritic(mock_router, lore_service=lore, universe_id="fr")
        formatted = critic._format_context({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        })
        assert "Lore Context" not in formatted
        # Must still have the baseline checks so the prompt is usable.
        assert "mission_distinctness" in formatted

    def test_long_content_is_truncated(self, multi_scene_chapter_cards, mock_router):
        """Content over 300 chars gets an ellipsis so the prompt stays tight."""
        big = "X" * 500
        entries = [{"title": "Big Entry", "category": "faction", "content": big, "metadata": {}}]
        lore = _mock_lore_service(entries)
        critic = ChapterGateCritic(mock_router, lore_service=lore, universe_id="fr")
        formatted = critic._format_context({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        })
        assert "..." in formatted
        # Full 500-char payload should NOT be in the prompt.
        assert big not in formatted

    @pytest.mark.asyncio
    async def test_lore_used_flag_surfaces_in_evaluation(
        self, multi_scene_chapter_cards
    ):
        """The evaluation dict gets lore_used=True plus lore_entry_count."""
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_passed": True,
            "chapter_level_failures": [],
            "scene_level_flags": [],
            "metrics": {},
        })
        lore = _mock_lore_service(CANONICAL_LORE)
        critic = ChapterGateCritic(router, lore_service=lore, universe_id="fr")
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        })
        assert result["lore_used"] is True
        assert result["lore_entry_count"] == 2

    @pytest.mark.asyncio
    async def test_lore_used_false_when_service_absent(
        self, multi_scene_chapter_cards
    ):
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_passed": True,
            "chapter_level_failures": [],
            "scene_level_flags": [],
            "metrics": {},
        })
        critic = ChapterGateCritic(router)  # no lore_service
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["p1", "p2", "p3"],
            "chapter_number": 1,
        })
        assert result["lore_used"] is False
        assert result["lore_entry_count"] == 0

    @pytest.mark.asyncio
    async def test_lore_consistency_failure_surfaces(
        self, multi_scene_chapter_cards
    ):
        """When the LLM emits a lore_consistency_check failure, it
        propagates to chapter_level_failures."""
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_passed": False,
            "chapter_level_failures": [
                {
                    "check": "lore_consistency_check",
                    "description": (
                        "Prose says the Ruusan Memorial has 12 obelisks; "
                        "canon specifies 7."
                    ),
                }
            ],
            "scene_level_flags": [],
            "metrics": {},
        })
        lore = _mock_lore_service(CANONICAL_LORE)
        critic = ChapterGateCritic(router, lore_service=lore, universe_id="fr")
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["twelve obelisks stood at ruusan", "p2", "p3"],
            "chapter_number": 1,
        })
        codes = [f["check"] for f in result["chapter_level_failures"]]
        assert "lore_consistency_check" in codes
