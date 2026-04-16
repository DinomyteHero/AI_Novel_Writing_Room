"""Integration test for the full Phase 2 pipeline.

Runs the orchestrator with all 28 scene cards using mock LLM responses.
Verifies chapter generation, run ledger events, chapter memory storage,
story state chapter logs, and scene card loading.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

chromadb = pytest.importorskip("chromadb", reason="chromadb not installed")

from src.agents.summarizer import Summarizer
from src.memory.chapter_memory import ChapterMemory
from src.memory.context_assembler import ContextAssembler
from src.memory.contradiction_scanner import ContradictionScanner
from src.memory.knowledge_layers import KnowledgeLayers
from src.memory.state_diff import StateDiffApplier
from src.memory.story_state import StoryState
from src.orchestrator import Orchestrator
from src.rag.embedding import MockEmbeddingFunction
from src.run_ledger import RunLedger


# ------------------------------------------------------------------ #
# Scene card loading
#
# Canonical path (via ProjectPaths):
#     data/franchises/{franchise}/books/{book}/
# ------------------------------------------------------------------ #

SCENE_CARDS_DIR = (
    Path(__file__).parent.parent
    / "data"
    / "franchises"
    / "star-wars-legends-eu"
    / "books"
    / "the-ruusan-atonement"
    / "scene_cards"
)

CONCEPT_SEED_PATH = (
    Path(__file__).parent.parent
    / "data"
    / "franchises"
    / "star-wars-legends-eu"
    / "books"
    / "the-ruusan-atonement"
    / "concept_seed.json"
)

NEGATIVE_CONSTRAINTS_PATH = (
    Path(__file__).parent.parent / "config" / "negative_constraints.yaml"
)

# The Ruusan project plans 28 chapters, ~3 scenes each = 87 scene cards.
# Tests are derived from the actual data so they survive minor scene-card edits.
CHAPTER_COUNT = 28


def _load_scene_cards() -> list[dict]:
    """Load all scene cards, sorted by chapter and scene number."""
    cards = []
    for path in sorted(SCENE_CARDS_DIR.glob("chapter_*_scene_*.json")):
        with open(path, encoding="utf-8") as f:
            cards.append(json.load(f))
    return cards


SCENE_COUNT = len(_load_scene_cards()) if SCENE_CARDS_DIR.exists() else 0


# ------------------------------------------------------------------ #
# Mock router factory
# ------------------------------------------------------------------ #

# Track the chapter counter across calls so summarizer can return
# the correct chapter number dynamically.
_chapter_counter = {"current": 0}


def _make_mock_router() -> MagicMock:
    """Build a MockRouter that dispatches by agent role.

    The mock router inspects the agent_role argument to decide
    which canned response to return. The gate critic and summarizer
    use complete_structured (returns dict); others use complete
    (returns str).
    """
    router = MagicMock()
    router.mode = "local"

    _chapter_counter["current"] = 0

    # Mock prose sized to sit inside the Ruusan scene cards' ±20% target
    # word-count tolerance (1250 ±20% = 1000-1500). 90 repetitions of the
    # 13-word sentence pair produces ~1170 words, which both the Scene Gate
    # programmatic word-count check and the post-polish compression guard
    # accept without firing WORD_COUNT_VIOLATION.
    _MOCK_PROSE = (
        "The scene began with tension. Characters moved through "
        "the space with purpose. " * 90
    )

    async def mock_complete(agent_role, messages, *args, **kwargs):
        if agent_role == "prose_stylist":
            return _MOCK_PROSE
        elif agent_role == "quality_polish":
            # Polish returns prose unchanged so neither the compression
            # guard (<80% of gate-passed) nor Final Gate sees a change.
            return _MOCK_PROSE
        return "Mock response"

    async def mock_complete_structured(agent_role, messages, *args, **kwargs):
        if agent_role == "plot_architect":
            # Phase 2: Plot Architect emits typed generation brief via complete_structured.
            return {
                "scene_objective": "Draft the scene following the scene card.",
                "turning_point": {
                    "trigger": "Mock trigger.",
                    "shift": "Mock shift.",
                    "cost": "Mock cost.",
                },
                "closing_beat": "Mock closing beat.",
                "emotional_arc": {
                    "start": "mock start",
                    "shift": "mock shift",
                    "end": "mock end",
                },
                "target_word_count": 3750,
            }
        elif agent_role == "gate_critic":
            return {
                "verdict": "pass",
                "failure_codes": [],
                "severity": "non_blocking",
                "route_to": None,
                "structural_score": 0.85,
                "voice_score": 0.80,
                "polish_score": 0.75,
            }
        elif agent_role == "final_gate":
            return {
                "verdict": "pass",
                "failure_codes": [],
            }
        elif agent_role == "summarizer":
            _chapter_counter["current"] += 1
            ch = _chapter_counter["current"]
            return {
                "summary": (
                    f"Chapter {ch}: The crew assembled and departed. "
                    "Tensions emerged between members."
                ),
                "state_diff": {
                    "chapter_number": ch,
                    "changes": {
                        "character_updates": [
                            {
                                "character_id": "ben_skywalker",
                                "field": "emotional_state",
                                "old_value": None,
                                "new_value": "determined",
                            }
                        ],
                        "plot_thread_updates": [
                            {
                                "thread_id": "mission_briefing",
                                "field": "status",
                                "old_value": None,
                                "new_value": "active",
                            }
                        ],
                        "new_knowledge": [
                            {
                                "character_id": "ben_skywalker",
                                "fact": "The wound regions are expanding",
                                "source": "told",
                            }
                        ],
                    },
                },
            }
        return {}

    router.complete = AsyncMock(side_effect=mock_complete)
    router.complete_structured = AsyncMock(side_effect=mock_complete_structured)
    router.close = AsyncMock()
    return router


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def scene_cards():
    """Load scene cards from the franchise-scoped data directory.

    The fixture asserts data presence (non-empty load) and delegates count
    expectations to `SCENE_COUNT` / `CHAPTER_COUNT` module constants so the
    test survives minor scene-card edits.
    """
    cards = _load_scene_cards()
    assert len(cards) > 0, f"No scene cards loaded from {SCENE_CARDS_DIR}"
    chapters = {c["chapter_number"] for c in cards}
    assert chapters == set(range(1, CHAPTER_COUNT + 1)), (
        f"Expected chapters 1..{CHAPTER_COUNT}, found {sorted(chapters)}"
    )
    return cards


@pytest.fixture
def pipeline_env(tmp_path):
    """Set up the full Phase 2 pipeline environment with mock router.

    Returns a dict with: orchestrator, ledger, state, chapter_memory,
    knowledge_layers, mock_router.
    """
    mock_router = _make_mock_router()

    # Temp directories
    manuscripts_dir = str(tmp_path / "manuscripts")
    Path(manuscripts_dir).mkdir(parents=True, exist_ok=True)

    # Core components
    mock_ef = MockEmbeddingFunction(dimension=384)

    ledger = RunLedger(db_path=str(tmp_path / "test_ledger.db"))
    state = StoryState(db_path=str(tmp_path / "test_state.db"))
    knowledge = KnowledgeLayers(state)
    chapter_memory = ChapterMemory(
        persist_directory=str(tmp_path / "test_chapter_memory"),
        embedding_function=mock_ef,
    )

    # Initialize state from concept seed
    with open(CONCEPT_SEED_PATH, encoding="utf-8") as f:
        concept_seed = json.load(f)
    state.init_from_concept_seed(concept_seed)

    # Phase 2 components
    summarizer = Summarizer(mock_router)
    state_diff_applier = StateDiffApplier(state, knowledge, ledger)
    contradiction_scanner = ContradictionScanner(state, knowledge, ledger)

    # Context assembler (Phase 1 mode for simplicity -- no canon_db)
    assembler = ContextAssembler(
        concept_seed_path=str(CONCEPT_SEED_PATH),
        negative_constraints_path=str(NEGATIVE_CONSTRAINTS_PATH),
        manuscripts_dir=manuscripts_dir,
        story_state=state,
        knowledge_layers=knowledge,
        chapter_memory=chapter_memory,
    )

    # Orchestrator with all Phase 2 deps
    orchestrator = Orchestrator(
        router=mock_router,
        context_assembler=assembler,
        ledger=ledger,
        manuscripts_dir=manuscripts_dir,
        summarizer=summarizer,
        state_diff_applier=state_diff_applier,
        contradiction_scanner=contradiction_scanner,
        chapter_memory=chapter_memory,
        story_state=state,
    )

    yield {
        "orchestrator": orchestrator,
        "ledger": ledger,
        "state": state,
        "chapter_memory": chapter_memory,
        "knowledge": knowledge,
        "mock_router": mock_router,
    }

    state.close()
    ledger.close()


# ================================================================== #
# Scene card loading verification
# ================================================================== #


class TestSceneCardLoading:
    """Verify all scene cards load successfully."""

    def test_all_scene_cards_exist(self):
        """All scene card files should be present, covering chapters 1-28."""
        cards = _load_scene_cards()
        chapters = {c["chapter_number"] for c in cards}
        assert chapters == set(range(1, 29))

    def test_scene_cards_have_required_fields(self):
        """Each card should have chapter_number, mission, and characters_present."""
        cards = _load_scene_cards()
        required = {"chapter_number", "scene_number", "mission", "characters_present"}

        for card in cards:
            missing = required - card.keys()
            assert not missing, (
                f"Chapter {card.get('chapter_number', '?')} missing: {missing}"
            )

    def test_scene_cards_sequential(self):
        """Cards should cover chapters 1 through 28 in order."""
        cards = _load_scene_cards()
        chapter_nums = sorted({c["chapter_number"] for c in cards})
        assert chapter_nums == list(range(1, 29))


# ================================================================== #
# Full pipeline integration test
# ================================================================== #


@pytest.mark.asyncio
class TestPipelineIntegration:
    """Integration test: run the full Phase 2 pipeline with 28 scene cards."""

    async def test_pipeline_generates_all_chapters(self, pipeline_env, scene_cards):
        """Run the pipeline and verify every scene is generated and every
        chapter number 1..CHAPTER_COUNT is represented."""
        orch = pipeline_env["orchestrator"]

        results = await orch.run_pipeline(scene_cards)

        assert len(results) == SCENE_COUNT
        for result in results:
            assert result["word_count"] > 0
            assert "output_path" in result
        chapters_seen = {r["chapter_number"] for r in results}
        assert chapters_seen == set(range(1, CHAPTER_COUNT + 1))

    async def test_pipeline_ledger_events(self, pipeline_env, scene_cards):
        """The run ledger should contain the expected event sequence."""
        orch = pipeline_env["orchestrator"]
        ledger = pipeline_env["ledger"]

        await orch.run_pipeline(scene_cards)

        # Collect all events. Limit must exceed total event count — the
        # ledger query applies ORDER BY id DESC LIMIT N then reverses, so a
        # small limit returns a suffix of events rather than the start.
        # Each scene emits ~10 events; 87 scenes + pipeline-level events
        # means well over 500, so we use a generous ceiling.
        all_events = ledger.get_events(limit=10_000)
        event_types = [e["event_type"] for e in all_events]

        # Pipeline-level events
        assert event_types[0] == "pipeline_start"
        assert event_types[-1] == "pipeline_complete"

        # One chapter_start per scene (the orchestrator emits chapter_start at
        # the top of each run_chapter call, and run_chapter runs per scene).
        chapter_starts = [e for e in all_events if e["event_type"] == "chapter_start"]
        assert len(chapter_starts) == SCENE_COUNT

        # Per-scene agent events: plot_architect, prose_stylist, gate_critic.
        # Quality Polish and Final Gate run via run()/run_structured directly
        # and don't emit agent_start events.
        for agent_role in ["plot_architect", "prose_stylist", "gate_critic"]:
            agent_starts = [
                e for e in all_events
                if e["event_type"] == "agent_start" and e["agent_role"] == agent_role
            ]
            # At least one per scene; possibly more with gate retries.
            assert len(agent_starts) >= SCENE_COUNT, (
                f"Expected at least {SCENE_COUNT} agent_start events for "
                f"{agent_role}, got {len(agent_starts)}"
            )

        # Every scene exits the gate loop with either a pass or a non-blocking
        # polish-level fail. (Scene cards across the Ruusan book span target
        # word counts 800-1700, while the mock prose is a fixed length; some
        # scenes trip the programmatic WORD_COUNT_VIOLATION check, which is a
        # non-blocking fail_polish verdict that still proceeds to polish.)
        gate_exits = [
            e for e in all_events if e["event_type"] in ("gate_pass", "gate_fail")
        ]
        assert len(gate_exits) >= SCENE_COUNT

        # Final Gate completions — one per scene (polish output validated).
        final_gate_completes = [
            e for e in all_events if e["event_type"] == "final_gate_complete"
        ]
        assert len(final_gate_completes) == SCENE_COUNT

        # Phase 2 events — summarizer + state diff run per scene.
        summarizer_completes = [
            e for e in all_events if e["event_type"] == "summarizer_complete"
        ]
        assert len(summarizer_completes) == SCENE_COUNT

        state_diff_proposed = [
            e for e in all_events if e["event_type"] == "state_diff_proposed"
        ]
        assert len(state_diff_proposed) == SCENE_COUNT

        state_diff_committed = [
            e for e in all_events if e["event_type"] == "state_diff_committed"
        ]
        assert len(state_diff_committed) == SCENE_COUNT

    async def test_chapter_memory_has_summaries(self, pipeline_env, scene_cards):
        """After the pipeline, chapter memory should have one summary per scene."""
        orch = pipeline_env["orchestrator"]
        chapter_memory = pipeline_env["chapter_memory"]

        await orch.run_pipeline(scene_cards)

        assert chapter_memory.count() == SCENE_COUNT

        # Every chapter 1..CHAPTER_COUNT should be retrievable
        for ch_num in range(1, CHAPTER_COUNT + 1):
            summary = chapter_memory.get_summary(ch_num)
            assert summary is not None, f"No summary found for chapter {ch_num}"
            assert len(summary) > 0

    async def test_story_state_has_chapter_logs(self, pipeline_env, scene_cards):
        """After the pipeline, story state should have chapter logs for all 5."""
        orch = pipeline_env["orchestrator"]
        state = pipeline_env["state"]

        await orch.run_pipeline(scene_cards)

        for ch_num in range(1, 6):
            log = state.get_chapter_log(ch_num)
            assert log is not None, f"No chapter log for chapter {ch_num}"
            assert log["chapter_number"] == ch_num
            assert log["word_count"] is not None
            assert log["word_count"] > 0

    async def test_state_diff_applies_character_updates(self, pipeline_env, scene_cards):
        """State diffs should update character emotional state via the pipeline."""
        orch = pipeline_env["orchestrator"]
        state = pipeline_env["state"]

        await orch.run_pipeline(scene_cards)

        # Mock summarizer always sets ben_skywalker emotional_state to "determined"
        ben = state.get_character("ben_skywalker")
        assert ben is not None
        assert ben["emotional_state"] == "determined"

    async def test_state_diff_creates_plot_threads(self, pipeline_env, scene_cards):
        """State diffs should create/update plot threads."""
        orch = pipeline_env["orchestrator"]
        state = pipeline_env["state"]

        await orch.run_pipeline(scene_cards)

        # Mock summarizer references "mission_briefing" thread
        thread = state.get_plot_thread("mission_briefing")
        assert thread is not None
        assert thread["status"] == "active"

    async def test_pipeline_results_contain_summaries(self, pipeline_env, scene_cards):
        """Each result should include a summary from the summarizer."""
        orch = pipeline_env["orchestrator"]

        results = await orch.run_pipeline(scene_cards)

        for result in results:
            assert "summary" in result
            assert len(result["summary"]) > 0

    async def test_manuscripts_written_to_disk(self, pipeline_env, scene_cards):
        """Chapter prose files should exist on disk after the pipeline."""
        orch = pipeline_env["orchestrator"]

        results = await orch.run_pipeline(scene_cards)

        for result in results:
            output_path = Path(result["output_path"])
            assert output_path.exists(), f"Missing file: {output_path}"
            content = output_path.read_text(encoding="utf-8")
            assert len(content) > 0

    async def test_new_knowledge_applied(self, pipeline_env, scene_cards):
        """State diffs should add new knowledge entries as beliefs."""
        orch = pipeline_env["orchestrator"]
        knowledge = pipeline_env["knowledge"]

        await orch.run_pipeline(scene_cards)

        # Mock summarizer adds a belief to ben_skywalker about wound regions
        beliefs = knowledge.get_beliefs("ben_skywalker")
        wound_beliefs = [
            b for b in beliefs
            if "wound regions" in b.get("fact_description", "").lower()
        ]
        assert len(wound_beliefs) >= 1
