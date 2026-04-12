"""Chapter Gate Critic agent — evaluates a full chapter after all scenes pass scene-level gates.

Assesses composition: mission distinctness, stakes escalation, hook strength,
scene variety, and pressure progression across scenes within a chapter.
"""

import json

from src.agents.base_agent import BaseAgent


class ChapterGateCritic(BaseAgent):
    """Chapter-level quality gate. Evaluates the entire chapter after all
    scenes have individually passed the scene-level GateCritic."""

    def __init__(self, router, role: str = "chapter_gate_critic"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        scene_cards = context["scene_cards"]
        scene_prose = context["scene_prose"]
        chapter_number = context["chapter_number"]

        parts = [f"## Chapter {chapter_number} — Full Chapter Evaluation"]

        # Include each scene card + prose pair
        for i, (card, prose) in enumerate(zip(scene_cards, scene_prose)):
            sc_num = card.get("scene_number", i + 1)
            parts.append(f"### Scene {sc_num} — Card")
            parts.append(f"```json\n{json.dumps(card, indent=2)}\n```")
            parts.append(f"### Scene {sc_num} — Prose")
            parts.append(prose)

        parts.append(
            "## Task\n"
            "Evaluate this chapter as a whole. All scenes have already passed "
            "scene-level evaluation. Now assess whether they work together.\n\n"
            "Return a JSON object:\n"
            "```json\n"
            "{\n"
            '  "chapter_passed": true|false,\n'
            '  "chapter_level_failures": [\n'
            "    {\n"
            '      "check": "mission_distinctness|stakes_escalation|opening_hook|'
            'end_hook|scene_variety|pressure_progression",\n'
            '      "description": "specific explanation"\n'
            "    }\n"
            "  ],\n"
            '  "scene_level_flags": [\n'
            '    {"scene_number": 1, "flags": ["..."]}\n'
            "  ],\n"
            '  "metrics": {\n'
            '    "scene_variety_index": 0.0,\n'
            '    "conflict_density": 0.0,\n'
            '    "chapter_hook_strength": 0.0,\n'
            '    "arc_pressure_progression": "ascending|flat|descending|varied"\n'
            "  }\n"
            "}\n"
            "```\n\n"
            "Checks:\n"
            "1. Mission distinctness: no two adjacent scenes accomplish the same goal.\n"
            "2. Stakes escalation: stakes must increase or transform by the final scene.\n"
            "3. Opening hook: first ~200 words of scene 1 must engage immediately.\n"
            "4. End hook: final scene must end with a chapter-end hook.\n"
            "5. Scene variety: scene types and conflict types should not be uniform.\n"
            "6. Pressure progression: final scene should not be lowest-pressure.\n\n"
            "Return ONLY the JSON object."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        # Not used — run() overrides the flow to use complete_structured
        return {}

    async def run(self, context: dict) -> dict:
        """Run the chapter gate and return structured evaluation.

        Args:
            context: Must contain:
                - scene_cards: list[dict] — all scene cards for this chapter
                - scene_prose: list[str] — all scene prose (same order)
                - chapter_number: int

        Returns:
            {
                "chapter_passed": bool,
                "chapter_level_failures": list[dict],
                "scene_level_flags": list[dict],
                "metrics": dict,
            }
        """
        messages = self._build_messages(context)
        result = await self.router.complete_structured(self.role, messages)

        # If complete_structured returned parsed dict, use directly
        if isinstance(result, dict) and "chapter_passed" in result:
            evaluation = result
        else:
            # Fallback: parse from string response
            text = result.get("content", "") if isinstance(result, dict) else str(result)

            # Strip markdown fences if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            try:
                evaluation = json.loads(text)
            except (json.JSONDecodeError, IndexError):
                evaluation = {
                    "chapter_passed": False,
                    "chapter_level_failures": [
                        {"check": "parse_error", "description": f"Failed to parse critic response: {text[:200]}"}
                    ],
                    "scene_level_flags": [],
                    "metrics": {
                        "scene_variety_index": 0.0,
                        "conflict_density": 0.0,
                        "chapter_hook_strength": 0.0,
                        "arc_pressure_progression": "unknown",
                    },
                }

        # Ensure expected keys exist
        evaluation.setdefault("chapter_passed", False)
        evaluation.setdefault("chapter_level_failures", [])
        evaluation.setdefault("scene_level_flags", [])
        evaluation.setdefault("metrics", {})

        return evaluation
