"""Tests for the PipelineSession."""

import json
from pathlib import Path

import pytest

from src.pipeline_session import PipelineSession


@pytest.fixture
def session(temp_dir):
    return PipelineSession(session_dir=temp_dir)


@pytest.fixture
def sample_scene_cards():
    return [
        {"chapter_number": 1, "scene_number": 1, "mission": "Setup"},
        {"chapter_number": 2, "scene_number": 1, "mission": "Rising action"},
        {"chapter_number": 3, "scene_number": 1, "mission": "Climax"},
    ]


@pytest.fixture
def sample_result():
    return {
        "chapter_number": 1,
        "scene_number": 1,
        "word_count": 3000,
        "output_path": "data/manuscripts/chapter_01_scene_01.md",
    }


class TestPipelineSession:

    def test_save_and_load(self, session):
        state = {"session_id": "test_001", "data": "hello"}
        session.save("test_001", state)

        loaded = session.load("test_001")
        assert loaded is not None
        assert loaded["session_id"] == "test_001"
        assert loaded["data"] == "hello"
        assert "updated_at" in loaded

    def test_load_nonexistent(self, session):
        result = session.load("nonexistent")
        assert result is None

    def test_create_session(self, session, sample_scene_cards):
        state = session.create_session(
            session_id="test_002",
            scene_cards=sample_scene_cards,
        )

        assert state["session_id"] == "test_002"
        assert state["total_cards"] == 3
        assert len(state["completed_chapters"]) == 0
        assert "state_hash" in state

        # Verify it was saved
        loaded = session.load("test_002")
        assert loaded is not None

    def test_mark_chapter_complete(self, session, sample_scene_cards, sample_result):
        session.create_session("test_003", sample_scene_cards)
        session.mark_chapter_complete("test_003", 1, 1, sample_result)

        loaded = session.load("test_003")
        assert len(loaded["completed_chapters"]) == 1
        assert loaded["completed_chapters"][0]["chapter_number"] == 1

    def test_mark_chapter_complete_no_duplicates(self, session, sample_scene_cards, sample_result):
        session.create_session("test_004", sample_scene_cards)
        session.mark_chapter_complete("test_004", 1, 1, sample_result)
        session.mark_chapter_complete("test_004", 1, 1, sample_result)

        loaded = session.load("test_004")
        assert len(loaded["completed_chapters"]) == 1

    def test_get_pending_cards(self, session, sample_scene_cards, sample_result):
        session.create_session("test_005", sample_scene_cards)
        session.mark_chapter_complete("test_005", 1, 1, sample_result)
        session.mark_chapter_complete("test_005", 2, 1, {
            "chapter_number": 2, "scene_number": 1, "word_count": 2500,
        })

        pending = session.get_pending_cards("test_005", sample_scene_cards)
        assert len(pending) == 1
        assert pending[0]["chapter_number"] == 3

    def test_get_pending_cards_all_complete(self, session, sample_scene_cards):
        session.create_session("test_006", sample_scene_cards)
        for card in sample_scene_cards:
            session.mark_chapter_complete(
                "test_006", card["chapter_number"], card["scene_number"],
                {"chapter_number": card["chapter_number"], "scene_number": card["scene_number"]},
            )

        pending = session.get_pending_cards("test_006", sample_scene_cards)
        assert len(pending) == 0

    def test_get_pending_cards_nonexistent_session(self, session, sample_scene_cards):
        pending = session.get_pending_cards("nonexistent", sample_scene_cards)
        assert len(pending) == 3

    def test_list_sessions(self, session, sample_scene_cards):
        session.create_session("sess_a", sample_scene_cards)
        session.create_session("sess_b", sample_scene_cards)

        sessions = session.list_sessions()
        assert len(sessions) == 2
        ids = {s["session_id"] for s in sessions}
        assert "sess_a" in ids
        assert "sess_b" in ids

    def test_session_id_generation(self):
        sid = PipelineSession.generate_session_id()
        assert isinstance(sid, str)
        assert len(sid) > 10
        parts = sid.split("_")
        assert len(parts) >= 3  # date_time_hex

    def test_state_hash_consistency(self):
        cards = [{"chapter_number": 1}, {"chapter_number": 2}]
        hash1 = PipelineSession._compute_state_hash(cards)
        hash2 = PipelineSession._compute_state_hash(cards)
        assert hash1 == hash2

        # Different cards produce different hash
        cards2 = [{"chapter_number": 1}, {"chapter_number": 3}]
        hash3 = PipelineSession._compute_state_hash(cards2)
        assert hash1 != hash3

    def test_mark_chapter_complete_nonexistent_session(self, session):
        with pytest.raises(ValueError, match="not found"):
            session.mark_chapter_complete("nonexistent", 1, 1, {})
