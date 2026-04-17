"""Phase 7.1 verification — lore_extractor is invoked post-save.

The Phase 7 roadmap specifies ``Invoke lore_extractor after scene save``
(orchestrator.py:770-789). This wiring was implemented before Phase 7
formally kicked off; the step now is to verify that the wiring still
holds and to lock in a regression test.

Covered invariants:

1. When ``lore_service`` + ``universe_id`` + ``project_id`` are all present
   AND ``worldbuilding_auto_extract=True``, ``_run_post_save`` invokes
   ``lore_service.extract_worldbuilding_from_chapter`` with the right
   arguments and the provisional IDs it returns propagate into the
   orchestrator's saved result (indirectly via stdout — we assert the call).
2. Flipping the ``worldbuilding_auto_extract`` flag OFF disables the call.
3. Missing ``universe_id`` disables the call (defensive: the pipeline
   continues without worldbuilding rather than crashing).
4. Exceptions from the extractor are caught and logged, not fatal — the
   surrounding orchestrator flow continues.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator import Orchestrator
from src.run_ledger import RunLedger


@pytest.fixture
def ledger(temp_dir):
    _ledger = RunLedger(db_path=str(Path(temp_dir) / "test_ledger.db"))
    yield _ledger
    _ledger.close()


@pytest.fixture
def mock_assembler():
    a = MagicMock()
    a.get_bible_summary.return_value = ""
    a.assemble.return_value = ""
    a.get_negative_constraints.return_value = ""
    a.concept_seed = {}
    return a


def _make_lore_service(return_ids: list[str] | None = None, raise_exc: Exception | None = None) -> MagicMock:
    svc = MagicMock()
    if raise_exc is not None:
        svc.extract_worldbuilding_from_chapter = AsyncMock(side_effect=raise_exc)
    else:
        svc.extract_worldbuilding_from_chapter = AsyncMock(
            return_value=list(return_ids or [])
        )
    return svc


def _build_orchestrator(
    *,
    mock_router,
    mock_assembler,
    ledger,
    temp_dir,
    lore_service=None,
    universe_id: str | None = None,
    project_id: str | None = None,
    worldbuilding_auto_extract: bool = False,
) -> Orchestrator:
    mock_router.complete = AsyncMock(return_value="Mock prose.")
    mock_router.complete_structured = AsyncMock(return_value={
        "verdict": "pass",
        "failure_codes": [],
        "severity": "non_blocking",
        "route_to": None,
        "structural_score": 0.85,
        "voice_score": 0.80,
        "polish_score": 0.75,
    })

    # A minimal summarizer — _run_post_save's early steps require one.
    summarizer = MagicMock()
    summarizer.run = AsyncMock(return_value={
        "summary": "mock summary",
        "state_diff": {"changes": []},
        "established_concepts": [],
    })

    return Orchestrator(
        router=mock_router,
        context_assembler=mock_assembler,
        ledger=ledger,
        manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
        summarizer=summarizer,
        lore_service=lore_service,
        universe_id=universe_id,
        project_id=project_id,
        worldbuilding_auto_extract=worldbuilding_auto_extract,
    )


@pytest.fixture
def scene_card():
    return {
        "chapter_number": 1,
        "scene_number": 1,
        "pov_character": "alice",
        "scene_description": "Alice stands at the Ruusan memorial.",
        "structural_phase": "part_1_setup",
    }


class TestLoreExtractionWiring:
    @pytest.mark.asyncio
    async def test_called_when_all_dependencies_present(
        self, mock_router, mock_assembler, ledger, temp_dir, scene_card,
    ):
        lore = _make_lore_service(return_ids=["entry_a", "entry_b"])
        orch = _build_orchestrator(
            mock_router=mock_router, mock_assembler=mock_assembler,
            ledger=ledger, temp_dir=temp_dir,
            lore_service=lore, universe_id="fr-test", project_id="book-1",
            worldbuilding_auto_extract=True,
        )
        await orch._run_post_save(
            scene_card=scene_card,
            prose="Prose body for extraction.",
            evaluation={"verdict": "pass"},
        )
        lore.extract_worldbuilding_from_chapter.assert_awaited_once()
        # Verify argument names match the documented contract.
        kwargs = lore.extract_worldbuilding_from_chapter.await_args.kwargs
        assert kwargs["chapter_text"] == "Prose body for extraction."
        assert kwargs["scene_card"] == scene_card
        assert kwargs["universe_id"] == "fr-test"
        assert kwargs["project_id"] == "book-1"
        assert kwargs["router"] is mock_router

    @pytest.mark.asyncio
    async def test_auto_extract_flag_off_skips_call(
        self, mock_router, mock_assembler, ledger, temp_dir, scene_card,
    ):
        lore = _make_lore_service(return_ids=["x"])
        orch = _build_orchestrator(
            mock_router=mock_router, mock_assembler=mock_assembler,
            ledger=ledger, temp_dir=temp_dir,
            lore_service=lore, universe_id="fr", project_id="bk",
            worldbuilding_auto_extract=False,  # flag off
        )
        await orch._run_post_save(
            scene_card=scene_card, prose="...",
            evaluation={"verdict": "pass"},
        )
        lore.extract_worldbuilding_from_chapter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_universe_id_skips_call(
        self, mock_router, mock_assembler, ledger, temp_dir, scene_card,
    ):
        lore = _make_lore_service(return_ids=["x"])
        orch = _build_orchestrator(
            mock_router=mock_router, mock_assembler=mock_assembler,
            ledger=ledger, temp_dir=temp_dir,
            lore_service=lore, universe_id=None, project_id="bk",
            worldbuilding_auto_extract=True,
        )
        await orch._run_post_save(
            scene_card=scene_card, prose="...",
            evaluation={"verdict": "pass"},
        )
        lore.extract_worldbuilding_from_chapter.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_extractor_exception_is_caught_and_not_fatal(
        self, mock_router, mock_assembler, ledger, temp_dir, scene_card,
    ):
        lore = _make_lore_service(raise_exc=RuntimeError("db offline"))
        orch = _build_orchestrator(
            mock_router=mock_router, mock_assembler=mock_assembler,
            ledger=ledger, temp_dir=temp_dir,
            lore_service=lore, universe_id="fr", project_id="bk",
            worldbuilding_auto_extract=True,
        )
        # Should not raise — the wiring swallows exceptions and logs them.
        await orch._run_post_save(
            scene_card=scene_card, prose="...",
            evaluation={"verdict": "pass"},
        )
        lore.extract_worldbuilding_from_chapter.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_lore_service_skips_call_silently(
        self, mock_router, mock_assembler, ledger, temp_dir, scene_card,
    ):
        orch = _build_orchestrator(
            mock_router=mock_router, mock_assembler=mock_assembler,
            ledger=ledger, temp_dir=temp_dir,
            lore_service=None, universe_id="fr", project_id="bk",
            worldbuilding_auto_extract=True,
        )
        # Sanity: _run_post_save completes without raising.
        await orch._run_post_save(
            scene_card=scene_card, prose="...",
            evaluation={"verdict": "pass"},
        )


class TestConflictDetectorWiring:
    """Phase 7.2 — LoreConflictDetector is invoked after extraction and
    flags land in the run ledger as `lore_conflicts` events."""

    @pytest.mark.asyncio
    async def test_conflict_scan_emits_ledger_event(
        self, mock_router, mock_assembler, ledger, temp_dir, scene_card,
    ):
        # Build a lore service with a fake DB that stores a canonical entry
        # plus the freshly-extracted provisional entry with a colliding
        # title — this should fire a title_collision flag.
        from tests.test_lore_conflict_detector import FakeLoreDB

        canonical = {
            "entry_id": "c1", "universe_id": "fr",
            "title": "Ruusan Holocron",
            "content": "Canonical.", "category": "artifact",
            "status": "canonical", "tags": None,
            "timeline_sort_start": None, "timeline_sort_end": None,
        }
        provisional = {
            "entry_id": "p1", "universe_id": "fr",
            "title": "Ruusan Holocron",
            "content": "Provisional variant.", "category": "artifact",
            "status": "provisional", "tags": None,
            "timeline_sort_start": None, "timeline_sort_end": None,
        }
        lore = MagicMock()
        lore.db = FakeLoreDB([canonical, provisional])
        lore.extract_worldbuilding_from_chapter = AsyncMock(
            return_value=["p1"]
        )

        mock_assembler.concept_seed = {
            "canon_profile": {"cross_continuity_violations": []}
        }
        orch = _build_orchestrator(
            mock_router=mock_router, mock_assembler=mock_assembler,
            ledger=ledger, temp_dir=temp_dir,
            lore_service=lore, universe_id="fr", project_id="bk",
            worldbuilding_auto_extract=True,
        )
        await orch._run_post_save(
            scene_card=scene_card, prose="Prose.",
            evaluation={"verdict": "pass"},
        )
        events = ledger.get_events()
        lore_events = [e for e in events if e["event_type"] == "lore_conflicts"]
        assert len(lore_events) == 1
        payload = lore_events[0]["payload"]
        assert payload["flag_count"] >= 1
        assert payload["high_severity_count"] >= 1
        assert payload["strict_mode"] is False

    @pytest.mark.asyncio
    async def test_advisory_mode_does_not_populate_contradiction_flags(
        self, mock_router, mock_assembler, ledger, temp_dir, scene_card,
    ):
        """In advisory mode the high-severity flags go to the ledger but
        NOT to the scene's contradiction_flags — the scene save proceeds
        without the lore flag blocking it."""
        from tests.test_lore_conflict_detector import FakeLoreDB

        canonical = {
            "entry_id": "c1", "universe_id": "fr",
            "title": "X", "content": "A.", "category": "faction",
            "status": "canonical", "tags": None,
            "timeline_sort_start": None, "timeline_sort_end": None,
        }
        provisional = {
            "entry_id": "p1", "universe_id": "fr",
            "title": "X", "content": "B.", "category": "faction",
            "status": "provisional", "tags": None,
            "timeline_sort_start": None, "timeline_sort_end": None,
        }
        lore = MagicMock()
        lore.db = FakeLoreDB([canonical, provisional])
        lore.extract_worldbuilding_from_chapter = AsyncMock(
            return_value=["p1"]
        )
        mock_assembler.concept_seed = {}
        orch = _build_orchestrator(
            mock_router=mock_router, mock_assembler=mock_assembler,
            ledger=ledger, temp_dir=temp_dir,
            lore_service=lore, universe_id="fr", project_id="bk",
            worldbuilding_auto_extract=True,
            # strict_lore defaults to False
        )
        _summary, flags = await orch._run_post_save(
            scene_card=scene_card, prose="Prose.",
            evaluation={"verdict": "pass"},
        )
        # No contradiction flags sourced from the lore detector in advisory mode.
        assert not any(
            f.get("source") == "lore_conflict_detector" for f in flags
        )

    @pytest.mark.asyncio
    async def test_strict_mode_promotes_high_flags_to_contradictions(
        self, mock_router, mock_assembler, ledger, temp_dir, scene_card,
    ):
        from tests.test_lore_conflict_detector import FakeLoreDB

        canonical = {
            "entry_id": "c1", "universe_id": "fr",
            "title": "X", "content": "A.", "category": "faction",
            "status": "canonical", "tags": None,
            "timeline_sort_start": None, "timeline_sort_end": None,
        }
        provisional = {
            "entry_id": "p1", "universe_id": "fr",
            "title": "X", "content": "B.", "category": "faction",
            "status": "provisional", "tags": None,
            "timeline_sort_start": None, "timeline_sort_end": None,
        }
        lore = MagicMock()
        lore.db = FakeLoreDB([canonical, provisional])
        lore.extract_worldbuilding_from_chapter = AsyncMock(
            return_value=["p1"]
        )
        mock_assembler.concept_seed = {}

        orch = _build_orchestrator(
            mock_router=mock_router, mock_assembler=mock_assembler,
            ledger=ledger, temp_dir=temp_dir,
            lore_service=lore, universe_id="fr", project_id="bk",
            worldbuilding_auto_extract=True,
        )
        orch._strict_lore = True  # Flip into strict mode after construction.

        _summary, flags = await orch._run_post_save(
            scene_card=scene_card, prose="Prose.",
            evaluation={"verdict": "pass"},
        )
        lore_flags = [
            f for f in flags if f.get("source") == "lore_conflict_detector"
        ]
        assert len(lore_flags) >= 1
        assert all(f["severity"] == "high" for f in lore_flags)
