"""Band 2: Scene/Emotion revision agent.

Checks conflict quality, turning points, show-don't-tell, and emotional arc.
Returns revised prose with emotional/scene improvements.
"""

import json
from pathlib import Path

from src.agents.base_agent import BaseAgent
from src.quality.dialogue_expectation import derive as derive_dialogue_expectation


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
        quality_metrics = context.get("quality_metrics", {})

        parts = []

        if character_voices:
            parts.append(f"## Character Voice Profiles\n{character_voices}")

        # Runtime-gated rebalancing flags. Both blocks below only fire when
        # the metrics actually signal imbalance AND the scene card's
        # dialogue_expectation says intervention is appropriate. The static
        # "Don't flag — convert" instruction that used to live in
        # scene_emotion.md was moved here so Band 2 only pressures the LLM
        # to rewrite when there is a real, scene-appropriate reason.
        expectation = derive_dialogue_expectation(scene_card)
        if quality_metrics:
            for scene_result in quality_metrics.get("per_scene", []):
                pacing = scene_result.get("pacing", {})
                dist = pacing.get("scene_type_distribution", {})
                desc_ratio = dist.get("description", 0) + dist.get("introspection", 0)

                # Block 1: Description imbalance. Fires regardless of
                # dialogue_expectation (even interior scenes shouldn't be
                # 60%+ description — that's flagged as description-heavy
                # prose, not as a dialogue deficit). The remediation
                # language below is phrased as "rebalance" not "convert
                # to dialogue" so it works for interior scenes too.
                if desc_ratio > 0.60:
                    ratio_pct = int(desc_ratio * 100)
                    parts.append(
                        f"## DESCRIPTION IMBALANCE\n"
                        f"This scene is {ratio_pct}% description/interiority. "
                        f"Rebalance by:\n"
                        f"- Replacing narrated emotion ('he felt angry') with behavioral indicators ('his jaw set', 'he turned the mug too hard')\n"
                        f"- Breaking long descriptive passages with physical movement or sensory interruption\n"
                        f"- For `dialogue_led` or `balanced` scenes, converting some narrated observations into brief dialogue or action beats\n"
                        f"Do not add filler. Convert existing description into more active modes of storytelling."
                    )

                # Block 2: Dialogue-led scene with low dialogue ratio. Only
                # fires when the scene is explicitly expected to be
                # dialogue-led AND the ratio is below the 35% floor. This
                # carries the "convert interiority to dialogue" pressure
                # that used to be static in scene_emotion.md.
                dialogue_ratio = pacing.get("dialogue_ratio", 0)
                if expectation == "dialogue_led" and dialogue_ratio < 0.35:
                    ratio_pct = int(dialogue_ratio * 100)
                    parts.append(
                        f"## LOW DIALOGUE FOR DIALOGUE-LED SCENE\n"
                        f"Dialogue ratio is {ratio_pct}% but this scene is marked `dialogue_led` (back-and-forth carries the scene). Target is 40-55%.\n"
                        f"Actively rewrite at least 2 interiority passages as dialogue exchanges. Preserve the information "
                        f"but deliver it through character reaction, question, or observation. Worldbuilding delivered by "
                        f"the narrator here can plausibly be moved into character dialogue."
                    )

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
