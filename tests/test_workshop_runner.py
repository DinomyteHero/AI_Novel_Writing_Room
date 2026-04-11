"""Tests for WorkshopRunner."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.concept_workshop.workshop_runner import WorkshopRunner


@pytest.fixture
def mock_router():
    """ModelRouter mock that returns predictable responses."""
    router = MagicMock()
    router.mode = "local"
    router.start_workshop_session = MagicMock()
    router.end_workshop_session = MagicMock()
    router.close = AsyncMock()

    # complete() returns assistant text.
    router.complete = AsyncMock(return_value="I'm your concept workshop facilitator. Let's begin.")

    # complete_structured() for decision detection — default to no decision.
    router.complete_structured = AsyncMock(return_value={
        "contains_decision": False,
        "field_path": None,
        "decision_value": None,
        "confidence": 0.1,
    })

    return router


def _make_detection_responses(scripted_turns: list[tuple[str, str]]) -> list[dict]:
    """Build a list of detection mock responses matching the scripted turns.

    Each scripted turn generates one detection call (both human and assistant
    turns are processed).  Some are marked as confirmed decisions.
    """
    responses = []
    for role, content in scripted_turns:
        if "Star Wars Legends" in content and role == "human":
            responses.append({
                "contains_decision": True,
                "field_path": "meta.franchise",
                "decision_value": "Star Wars (Legends)",
                "confidence": 0.95,
            })
        elif "47 ABY" in content and role == "human":
            responses.append({
                "contains_decision": True,
                "field_path": "meta.era",
                "decision_value": "47 ABY",
                "confidence": 0.92,
            })
        elif "dark and gritty" in content and role == "human":
            responses.append({
                "contains_decision": True,
                "field_path": "meta.tone",
                "decision_value": "dark_gritty",
                "confidence": 0.90,
            })
        elif "collective will" in content and role == "human":
            responses.append({
                "contains_decision": True,
                "field_path": "premise.what_if",
                "decision_value": "What if the Force responds only to collective will?",
                "confidence": 0.93,
            })
        else:
            responses.append({
                "contains_decision": False,
                "field_path": None,
                "decision_value": None,
                "confidence": 0.1,
            })
    return responses


class TestWorkshopRunnerIntegration:
    """Integration test with mocked model and scripted input."""

    @pytest.mark.asyncio
    async def test_scripted_session(self, tmp_path, mock_router):
        """Run 10 exchanges with 4 confirmable decisions."""
        # Scripted user inputs (the assistant response is always the same mock).
        user_inputs = [
            "Star Wars Legends for sure.",           # Decision: franchise
            "Post-FOTJ, 47 ABY.",                    # Decision: era
            "I want it dark and gritty.",             # Decision: tone
            "What if the Force responds only to collective will?",  # Decision: premise
            "Tell me about the structure.",           # No decision
            "Interesting, keep going.",               # No decision
            "What about antagonists?",               # No decision
            "I need to think about the cast.",        # No decision
            "Any name suggestions?",                  # No decision
            "done",                                   # Exit
        ]
        input_iter = iter(user_inputs)

        # Patch data directory into tmp_path.
        project_dir = tmp_path / "data" / "projects" / "test-session"

        with patch("src.concept_workshop.workshop_runner.Path") as MockPath:
            # Make Path("data/projects/test-session") resolve to tmp_path.
            # Easier: just monkey-patch the runner after creation.
            pass

        # Build all the turns (including the initial assistant greeting).
        # The greeting generates one detection call.
        all_turns: list[tuple[str, str]] = [("assistant", "greeting")]
        for ui in user_inputs[:-1]:  # Skip "done"
            all_turns.append(("human", ui))
            all_turns.append(("assistant", "response"))

        detection_responses = _make_detection_responses(all_turns)
        mock_router.complete_structured.side_effect = detection_responses

        output: list[str] = []
        runner = WorkshopRunner(
            "test_session",
            mock_router,
            resume=False,
            input_fn=lambda _prompt: next(input_iter),
            print_fn=lambda msg: output.append(msg),
        )
        # Override project_dir to use tmp_path.
        runner.project_dir = project_dir
        runner.project_dir.mkdir(parents=True, exist_ok=True)
        sessions_dir = project_dir / "workshop_sessions"
        sessions_dir.mkdir(exist_ok=True)
        runner.state_writer.project_dir = project_dir
        runner.state_writer.state_path = project_dir / "workshop_state.json"
        runner.transcript_path = sessions_dir / "session_001.jsonl"
        runner.summarizer.project_dir = project_dir

        await runner.run()

        # Verify state has 4 confirmed decisions.
        state = runner.state_writer.state
        assert state.meta.get("franchise") == "Star Wars (Legends)"
        assert state.meta.get("era") == "47 ABY"
        assert state.meta.get("tone") == "dark_gritty"
        assert state.premise.get("what_if") == "What if the Force responds only to collective will?"
        assert len(state.confirmed_fields) == 4

        # Verify transcript was written.
        assert runner.transcript_path.exists()
        lines = runner.transcript_path.read_text().strip().split("\n")
        assert len(lines) > 0
        first_entry = json.loads(lines[0])
        assert first_entry["role"] in ("human", "assistant")

        # Verify workshop session lifecycle was called.
        mock_router.start_workshop_session.assert_called_once()
        mock_router.end_workshop_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_saves_state(self, tmp_path, mock_router):
        """KeyboardInterrupt triggers clean shutdown with state save."""
        call_count = 0

        def input_fn(_prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "Star Wars Legends"
            raise KeyboardInterrupt

        # Detection for the greeting + first human turn + assistant response.
        mock_router.complete_structured.side_effect = [
            {"contains_decision": False, "field_path": None, "decision_value": None, "confidence": 0.1},
            {"contains_decision": True, "field_path": "meta.franchise", "decision_value": "Star Wars", "confidence": 0.9},
            {"contains_decision": False, "field_path": None, "decision_value": None, "confidence": 0.1},
        ]

        output: list[str] = []
        runner = WorkshopRunner(
            "test_interrupt",
            mock_router,
            input_fn=input_fn,
            print_fn=lambda msg: output.append(msg),
        )
        runner.project_dir = tmp_path
        runner.project_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "workshop_sessions").mkdir(exist_ok=True)
        runner.state_writer.project_dir = tmp_path
        runner.state_writer.state_path = tmp_path / "workshop_state.json"
        runner.transcript_path = tmp_path / "workshop_sessions" / "session_001.jsonl"
        runner.summarizer.project_dir = tmp_path

        await runner.run()

        # State should have been saved.
        state_file = tmp_path / "workshop_state.json"
        assert state_file.exists()
        # Session lifecycle still cleaned up.
        mock_router.end_workshop_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_via_command(self, tmp_path, mock_router):
        """Typing 'finalize' produces concept seed JSON."""
        user_inputs = [
            "Star Wars Legends",
            "finalize",
        ]
        input_iter = iter(user_inputs)

        mock_router.complete_structured.side_effect = [
            # Greeting detection
            {"contains_decision": False, "field_path": None, "decision_value": None, "confidence": 0.1},
            # Human franchise decision
            {"contains_decision": True, "field_path": "meta.franchise", "decision_value": "Star Wars", "confidence": 0.9},
            # Assistant response detection
            {"contains_decision": False, "field_path": None, "decision_value": None, "confidence": 0.1},
        ]

        output: list[str] = []
        runner = WorkshopRunner(
            "test_finalize",
            mock_router,
            input_fn=lambda _p: next(input_iter),
            print_fn=lambda msg: output.append(msg),
        )
        runner.project_dir = tmp_path
        runner.project_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "workshop_sessions").mkdir(exist_ok=True)
        runner.state_writer.project_dir = tmp_path
        runner.state_writer.state_path = tmp_path / "workshop_state.json"
        runner.transcript_path = tmp_path / "workshop_sessions" / "session_001.jsonl"
        runner.summarizer.project_dir = tmp_path

        await runner.run()

        seed_path = tmp_path / "book_1_seed.json"
        assert seed_path.exists()
        data = json.loads(seed_path.read_text())
        assert data["meta"]["franchise"] == "Star Wars"
        assert "confirmed_fields" not in data


class TestWorkshopRunnerSessionId:
    """Session ID auto-increments."""

    def test_first_session(self, tmp_path, mock_router):
        sessions_dir = tmp_path / "workshop_sessions"
        sessions_dir.mkdir(parents=True)
        runner = WorkshopRunner.__new__(WorkshopRunner)
        assert runner._next_session_id(sessions_dir) == "session_001"

    def test_increments(self, tmp_path, mock_router):
        sessions_dir = tmp_path / "workshop_sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "session_001.jsonl").write_text("{}\n")
        (sessions_dir / "session_002.jsonl").write_text("{}\n")
        runner = WorkshopRunner.__new__(WorkshopRunner)
        assert runner._next_session_id(sessions_dir) == "session_003"
