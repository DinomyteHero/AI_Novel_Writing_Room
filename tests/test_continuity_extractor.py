"""Slice 4 ContinuityExtractor unit tests.

Covers agent-level validation (event-type whitelist, details shape, per-type
required-field checks) using a mocked router so no network calls fire.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agents.continuity_extractor import ContinuityExtractor, EXTRACTOR_VERSION


class _FakeRouter:
    """Returns a pre-canned response from ``complete_structured`` so the
    agent can be driven without hitting the network. Matches the subset of
    ``ModelRouter`` surface BaseAgent uses (``complete`` + ``complete_structured``).
    """

    def __init__(self, response):
        self._response = response
        self.mode = "cloud"

    async def complete_structured(self, role, messages):
        return self._response

    async def complete(self, role, messages):
        return self._response


@pytest.fixture
def scene_card():
    return {
        "chapter_number": 1,
        "scene_number": 2,
        "pov_character": "Ben",
        "mission": "x",
        "characters_present": ["Ben", "Desh"],
        "revelations": ["R01"],
        "canon_elements_needed": [],
    }


@pytest.fixture
def concept_seed():
    return {
        "meta": {"franchise": "test", "project_title": "t"},
        "story_physics": {
            "revelation_map": [
                {"info_id": "R01", "content": "x"},
            ],
        },
    }


@pytest.mark.asyncio
async def test_extract_returns_valid_event(scene_card, concept_seed):
    router = _FakeRouter({"events": [
        {
            "event_type": "location_change",
            "subject": "Ben",
            "details": {"from_location": "academy", "to_location": "hangar"},
            "confidence": 0.96,
        },
    ]})
    extractor = ContinuityExtractor(router)
    events = await extractor.extract(
        prose="Ben walked from the academy to the hangar.",
        scene_card=scene_card,
        concept_seed=concept_seed,
    )
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "location_change"
    assert ev["scene_id"] == "ch01_sc02"
    assert ev["extractor_version"] == EXTRACTOR_VERSION
    assert ev["confidence"] == 0.96


@pytest.mark.asyncio
async def test_extract_drops_unknown_event_type(scene_card, concept_seed):
    router = _FakeRouter({"events": [
        {"event_type": "mood_shift", "subject": "Ben",
         "details": {"from": "calm", "to": "angry"}, "confidence": 0.9},
    ]})
    extractor = ContinuityExtractor(router)
    assert await extractor.extract(
        prose="", scene_card=scene_card, concept_seed=concept_seed,
    ) == []


@pytest.mark.asyncio
async def test_extract_drops_rows_with_extra_details_keys(scene_card, concept_seed):
    router = _FakeRouter({"events": [
        {
            "event_type": "location_change",
            "subject": "Ben",
            "details": {
                "from_location": "a", "to_location": "b",
                "vibe": "ominous",  # not in allowed set
            },
            "confidence": 0.9,
        },
    ]})
    extractor = ContinuityExtractor(router)
    assert await extractor.extract(
        prose="", scene_card=scene_card, concept_seed=concept_seed,
    ) == []


@pytest.mark.asyncio
async def test_extract_drops_rows_with_missing_details(scene_card, concept_seed):
    router = _FakeRouter({"events": [
        {"event_type": "injury_state", "subject": "Ben",
         "details": {"severity": "minor"}, "confidence": 0.9},
    ]})
    extractor = ContinuityExtractor(router)
    assert await extractor.extract(
        prose="", scene_card=scene_card, concept_seed=concept_seed,
    ) == []


@pytest.mark.asyncio
async def test_extract_drops_rows_with_bad_severity_enum(scene_card, concept_seed):
    router = _FakeRouter({"events": [
        {"event_type": "injury_state", "subject": "Ben",
         "details": {"severity": "crippled", "body_part": "leg", "mechanism": "fall"},
         "confidence": 0.9},
    ]})
    extractor = ContinuityExtractor(router)
    assert await extractor.extract(
        prose="", scene_card=scene_card, concept_seed=concept_seed,
    ) == []


@pytest.mark.asyncio
async def test_extract_handles_empty_response(scene_card, concept_seed):
    router = _FakeRouter({"events": []})
    extractor = ContinuityExtractor(router)
    assert await extractor.extract(
        prose="", scene_card=scene_card, concept_seed=concept_seed,
    ) == []


@pytest.mark.asyncio
async def test_extract_swallows_router_errors(scene_card, concept_seed):
    router = SimpleNamespace(
        complete_structured=AsyncMock(side_effect=RuntimeError("boom")),
        complete=AsyncMock(side_effect=RuntimeError("boom")),
        mode="cloud",
    )
    extractor = ContinuityExtractor(router)
    # Must not raise \u2014 extractor failure cannot abort the pipeline.
    assert await extractor.extract(
        prose="x", scene_card=scene_card, concept_seed=concept_seed,
    ) == []


@pytest.mark.asyncio
async def test_extract_drops_confidence_out_of_range(scene_card, concept_seed):
    router = _FakeRouter({"events": [
        {"event_type": "location_change", "subject": "Ben",
         "details": {"from_location": "a", "to_location": "b"}, "confidence": 1.5},
    ]})
    extractor = ContinuityExtractor(router)
    assert await extractor.extract(
        prose="", scene_card=scene_card, concept_seed=concept_seed,
    ) == []
