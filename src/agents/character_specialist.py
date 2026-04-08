"""Character Specialist agent — voice profiles and OOC detection.

Analyzes prose for out-of-character dialogue, actions, and knowledge violations.
Supplementary check (not a gate) — results are informational.
"""

import json

from src.agents.base_agent import BaseAgent


class CharacterSpecialist(BaseAgent):
    """Voice fidelity and out-of-character detection agent.

    Evaluates each present character's dialogue, actions, and knowledge
    usage against their profiles from the concept seed.
    """

    def __init__(self, router, role: str = "character_specialist"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context["scene_card"]
        character_voices = context.get("character_voices", "")
        character_knowledge = context.get("character_knowledge", "")
        character_profiles = context.get("character_profiles", [])

        parts = []

        # Character profiles (three dimensions)
        if character_profiles:
            parts.append("## Character Profiles")
            for char in character_profiles:
                name = char.get("name", "Unknown")
                dims = char.get("three_dimensions", {})
                voice = char.get("voice_notes", "")
                parts.append(f"### {name}")
                if dims.get("surface"):
                    parts.append(f"**Surface:** {dims['surface']}")
                if dims.get("backstory_inner_demons"):
                    parts.append(f"**Inner demons:** {dims['backstory_inner_demons']}")
                if dims.get("action_under_pressure"):
                    parts.append(f"**Under pressure:** {dims['action_under_pressure']}")
                if voice:
                    parts.append(f"**Voice notes:** {voice}")
                parts.append("")

        # Voice sheets
        if character_voices:
            parts.append(f"## Character Voice Sheets\n{character_voices}")

        # Knowledge state
        if character_knowledge:
            parts.append(f"## Character Knowledge State\n{character_knowledge}")

        # Scene card
        parts.append(f"## Scene Card\n```json\n{json.dumps(scene_card, indent=2)}\n```")

        # Prose to evaluate
        parts.append(f"## Prose to Evaluate\n{prose}")

        # Task instruction
        parts.append(
            "## Task\n"
            "Analyze each character present in this scene for voice consistency, "
            "out-of-character behavior, and knowledge violations. Return a JSON object:\n"
            "```json\n"
            "{\n"
            '  "verdict": "pass | fail_voice | fail_action",\n'
            '  "character_analyses": [\n'
            "    {\n"
            '      "character_name": "Name",\n'
            '      "voice_consistent": true/false,\n'
            '      "actions_consistent": true/false,\n'
            '      "knowledge_respected": true/false,\n'
            '      "emotional_arc_match": true/false,\n'
            '      "notes": "specific observations"\n'
            "    }\n"
            "  ],\n"
            '  "overall_voice_score": 0.0-1.0,\n'
            '  "overall_notes": "summary"\n'
            "}\n"
            "```\n\n"
            "Check:\n"
            "1. Voice fidelity — Does each character's dialogue match their voice_notes?\n"
            "2. OOC actions — Do actions align with their action_under_pressure dimension?\n"
            "3. Knowledge consistency — Does any character act on knowledge they shouldn't have?\n"
            "4. Emotional arc — Does the POV character's emotional trajectory match the scene card?\n"
        )

        return "\n\n".join(parts)

    async def run(self, context: dict) -> dict:
        """Run the character specialist and return structured OOC analysis."""
        messages = self._build_messages(context)
        result = await self.router.complete_structured(self.role, messages)

        # Normalize the result
        character_analyses = result.get("character_analyses", [])
        verdict = result.get("verdict", "pass")

        # Derive verdict from analyses if not provided
        if verdict == "pass" and character_analyses:
            has_voice_issue = any(
                not c.get("voice_consistent", True)
                for c in character_analyses
            )
            has_action_issue = any(
                not c.get("actions_consistent", True)
                for c in character_analyses
            )
            if has_action_issue:
                verdict = "fail_action"
            elif has_voice_issue:
                verdict = "fail_voice"

        return {
            "verdict": verdict,
            "character_analyses": character_analyses,
            "overall_voice_score": result.get("overall_voice_score", 0.0),
            "overall_notes": result.get("overall_notes", ""),
        }

    def _parse_response(self, response: str, context: dict) -> dict:
        # Not used — run() overrides to use complete_structured
        return {}
