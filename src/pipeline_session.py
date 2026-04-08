"""Pipeline session persistence for save/resume capability.

Serializes pipeline progress to JSON so multi-hour runs can be
paused and resumed. Sessions are saved after each completed chapter.
"""

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path


class PipelineSession:
    """Manages pipeline session state for save/resume.

    Each session tracks which scene cards have been processed,
    quality metrics per chapter, and a story state hash for
    continuity verification.
    """

    def __init__(self, session_dir: str = "data/sessions"):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session_id: str, state: dict) -> Path:
        """Save pipeline session state to JSON.

        Args:
            session_id: Unique session identifier.
            state: Session state dict.

        Returns:
            Path to the saved session file.
        """
        path = self.session_dir / f"{session_id}.json"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        return path

    def load(self, session_id: str) -> dict | None:
        """Load session state. Returns None if not found."""
        path = self.session_dir / f"{session_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_sessions(self) -> list[dict]:
        """List all saved sessions with metadata."""
        sessions = []
        for path in self.session_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", path.stem),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "completed_count": len(data.get("completed_chapters", [])),
                    "total_cards": data.get("total_cards", 0),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions

    def create_session(
        self, session_id: str = None, scene_cards: list[dict] = None, config: dict = None
    ) -> dict:
        """Create a new session state dict.

        Args:
            session_id: Optional ID (auto-generated if None).
            scene_cards: List of scene cards to process.
            config: Pipeline configuration snapshot.

        Returns:
            New session state dict.
        """
        if session_id is None:
            session_id = self.generate_session_id()

        state = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "state_hash": self._compute_state_hash(scene_cards or []),
            "completed_chapters": [],
            "total_cards": len(scene_cards or []),
            "pipeline_config": config or {},
        }
        self.save(session_id, state)
        return state

    def mark_chapter_complete(
        self,
        session_id: str,
        chapter_num: int,
        scene_num: int,
        result: dict,
    ) -> None:
        """Update session with a completed chapter.

        Args:
            session_id: Session identifier.
            chapter_num: Chapter number completed.
            scene_num: Scene number completed.
            result: Chapter generation result dict.
        """
        state = self.load(session_id)
        if state is None:
            raise ValueError(f"Session '{session_id}' not found")

        # Avoid duplicates
        for entry in state["completed_chapters"]:
            if entry["chapter_number"] == chapter_num and entry["scene_number"] == scene_num:
                entry["result"] = self._sanitize_result(result)
                self.save(session_id, state)
                return

        state["completed_chapters"].append({
            "chapter_number": chapter_num,
            "scene_number": scene_num,
            "result": self._sanitize_result(result),
        })
        self.save(session_id, state)

    def get_pending_cards(
        self, session_id: str, scene_cards: list[dict]
    ) -> list[dict]:
        """Filter scene cards to only those not yet completed.

        Args:
            session_id: Session identifier.
            scene_cards: Full list of scene cards.

        Returns:
            List of scene cards that haven't been processed yet.
        """
        state = self.load(session_id)
        if state is None:
            return scene_cards

        completed = {
            (e["chapter_number"], e["scene_number"])
            for e in state.get("completed_chapters", [])
        }

        return [
            card
            for card in scene_cards
            if (card["chapter_number"], card.get("scene_number", 1)) not in completed
        ]

    @staticmethod
    def generate_session_id() -> str:
        """Generate a unique session ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = secrets.token_hex(2)
        return f"{timestamp}_{suffix}"

    @staticmethod
    def _compute_state_hash(scene_cards: list[dict]) -> str:
        """Compute a hash of the scene cards for consistency verification."""
        content = json.dumps(scene_cards, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @staticmethod
    def _sanitize_result(result: dict) -> dict:
        """Extract serializable summary from a chapter result."""
        return {
            "chapter_number": result.get("chapter_number"),
            "scene_number": result.get("scene_number"),
            "word_count": result.get("word_count"),
            "output_path": str(result.get("output_path", "")),
        }
