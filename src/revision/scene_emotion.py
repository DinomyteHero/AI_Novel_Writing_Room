"""Band 2: Scene/Emotion revision agent.

Checks conflict quality, turning points, show-don't-tell, and emotional arc.
Returns revised prose with emotional/scene improvements.
"""

import json
from pathlib import Path

from src.agents.base_agent import BaseAgent


class SceneEmotionReviewer(BaseAgent):
    """Band 2 revision agent for scene dynamics and emotional quality."""

    def __init__(self, router, role: str = "scene_emotion_reviewer"):
        super().__init__(router, role)

    def _load_system_prompt(self) -> str:
        """Load from revision_prompts directory."""
        prompt_path = Path(f"prompts/revision_prompts/scene_emotion.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return f"You are the {self.role} agent."

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context["scene_card"]
        character_voices = context.get("character_voices", "")

        parts = []

        if character_voices:
            parts.append(f"## Character Voice Profiles\n{character_voices}")

        parts.append(f"## Scene Card\n```json\n{json.dumps(scene_card, indent=2)}\n```")
        parts.append(f"## Current Prose\n{prose}")

        parts.append(
            "## Task\n"
            "Review this prose for scene dynamics and emotional quality. Fix:\n"
            "- Conflict quality — is the conflict tangible and escalating?\n"
            "- Turning point — does the scene end differently than it began?\n"
            "- Show-don't-tell — replace emotion-naming with emotion-showing\n"
            "- Emotional arc — match the scene card's emotional_trajectory\n"
            "- Dialogue quality — dialogue should reveal character and advance conflict\n\n"
            "Return ONLY the complete revised prose text. Preserve the plot, "
            "structure, and continuity. Only improve emotional resonance and scene dynamics."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        """Extract revised prose from the response."""
        return {"prose": response.strip()}
