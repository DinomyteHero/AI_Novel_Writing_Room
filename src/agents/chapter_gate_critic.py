"""Chapter Gate Critic agent — evaluates a full chapter after all scenes pass scene-level gates.

Assesses composition: mission distinctness, stakes escalation, hook strength,
scene variety, and pressure progression across scenes within a chapter.

When a `chapter_blueprint.json` is available at
``data/franchises/{franchise}/books/{book}/chapter_blueprints/chapter_{NN}.json``
the critic extends its prompt with blueprint-aware checks (mission, turn,
reveal payload, subplot obligations, pacing curve, exit vector). Blueprint
checks are advisory — failures surface in ``chapter_level_failures`` for
diagnostics, they do not deterministically block the save.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from src.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


# Failure-code namespace for blueprint checks. Kept here so tests and the
# prompt stay aligned in one place.
BLUEPRINT_CHECK_CODES = (
    "mission_achieved",
    "chapter_turn_landed",
    "reveal_payload_delivered",
    "subplot_obligations_touched",
    "pacing_curve_matches",
    "exit_vector_reached",
)


def _resolve_blueprint_path(context: dict) -> Optional[Path]:
    """Resolve the chapter-blueprint file for this chapter.

    Accepts an explicit ``blueprint_path`` in context, or constructs the
    path from ``franchise_slug`` / ``book_slug`` / ``chapter_number``. The
    ``base_dir`` override is respected when the caller is using a
    non-default working directory (tests, CI).
    """
    explicit = context.get("blueprint_path")
    if explicit:
        return Path(explicit)

    franchise_slug = context.get("franchise_slug")
    book_slug = context.get("book_slug")
    chapter_number = context.get("chapter_number")
    base_dir = context.get("base_dir", ".")

    if not (franchise_slug and book_slug and chapter_number is not None):
        return None

    return (
        Path(base_dir)
        / "data"
        / "franchises"
        / franchise_slug
        / "books"
        / book_slug
        / "chapter_blueprints"
        / f"chapter_{int(chapter_number):02d}.json"
    )


def _load_blueprint(context: dict) -> Optional[dict]:
    """Load a chapter blueprint from disk, or accept one already in context.

    Returns ``None`` (graceful fallback) when:
    - ``context["chapter_blueprint"]`` is absent AND no resolvable path
    - the resolved path does not exist
    - the file cannot be parsed as JSON

    A pre-loaded dict at ``context["chapter_blueprint"]`` is preferred so
    tests and callers that already hold the blueprint in memory don't need
    to round-trip through the filesystem.
    """
    preloaded = context.get("chapter_blueprint")
    if isinstance(preloaded, dict):
        return preloaded

    path = _resolve_blueprint_path(context)
    if path is None or not path.exists():
        return None

    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "ChapterGateCritic: failed to load blueprint at %s (%s) — "
            "falling back to composition-only checks",
            path,
            exc,
        )
        return None


class ChapterGateCritic(BaseAgent):
    """Chapter-level quality gate. Evaluates the entire chapter after all
    scenes have individually passed the scene-level GateCritic."""

    def __init__(self, router, role: str = "chapter_gate_critic"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        scene_cards = context["scene_cards"]
        scene_prose = context["scene_prose"]
        chapter_number = context["chapter_number"]
        blueprint = _load_blueprint(context)

        parts = [f"## Chapter {chapter_number} — Full Chapter Evaluation"]

        if blueprint:
            parts.append(
                "## Chapter Blueprint\n"
                "This blueprint is the chapter-level planning contract. Evaluate "
                "whether the scenes collectively honour it.\n\n"
                f"```json\n{json.dumps(blueprint, indent=2)}\n```"
            )

        # Include each scene card + prose pair
        for i, (card, prose) in enumerate(zip(scene_cards, scene_prose)):
            sc_num = card.get("scene_number", i + 1)
            parts.append(f"### Scene {sc_num} — Card")
            parts.append(f"```json\n{json.dumps(card, indent=2)}\n```")
            parts.append(f"### Scene {sc_num} — Prose")
            parts.append(prose)

        check_list = [
            "1. mission_distinctness: no two adjacent scenes accomplish the same goal.",
            "2. stakes_escalation: stakes must increase or transform by the final scene.",
            "3. opening_hook: first ~200 words of scene 1 must engage immediately.",
            "4. end_hook: final scene must end with a chapter-end hook.",
            "5. scene_variety: scene types and conflict types should not be uniform.",
            "6. pressure_progression: final scene should not be lowest-pressure.",
        ]

        check_enum = (
            "mission_distinctness|stakes_escalation|opening_hook|"
            "end_hook|scene_variety|pressure_progression"
        )

        if blueprint:
            check_list.extend([
                "7. mission_achieved: scenes collectively execute `chapter_mission`.",
                "8. chapter_turn_landed: chapter end reflects `chapter_turn`.",
                "9. reveal_payload_delivered: every ID in `reveal_payload` surfaces in prose.",
                "10. subplot_obligations_touched: every ID in `subplot_obligations` is referenced.",
                "11. pacing_curve_matches: scene-level pressure matches `pacing_curve`.",
                "12. exit_vector_reached: final scene lands on `exit_vector`.",
            ])
            check_enum += "|" + "|".join(BLUEPRINT_CHECK_CODES)

        parts.append(
            "## Task\n"
            "Evaluate this chapter as a whole. All scenes have already passed "
            "scene-level evaluation. Now assess whether they work together"
            + (" and honour the chapter blueprint" if blueprint else "")
            + ".\n\n"
            "Return a JSON object:\n"
            "```json\n"
            "{\n"
            '  "chapter_passed": true|false,\n'
            '  "chapter_level_failures": [\n'
            "    {\n"
            f'      "check": "{check_enum}",\n'
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
            + "\n".join(check_list)
            + "\n\n"
            + (
                "Blueprint checks (7-12) are advisory — include them when you "
                "can point to concrete prose evidence, and skip them when the "
                "blueprint does not specify a given dimension (e.g. empty "
                "reveal_payload).\n\n"
                if blueprint
                else ""
            )
            + "Return ONLY the JSON object."
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
              Optional:
                - chapter_blueprint: dict — pre-loaded blueprint
                - blueprint_path: str — explicit path to the blueprint file
                - franchise_slug / book_slug / base_dir — used to resolve
                  the default blueprint path when no explicit one is given

        Returns:
            {
                "chapter_passed": bool,
                "chapter_level_failures": list[dict],
                "scene_level_flags": list[dict],
                "metrics": dict,
                "blueprint_used": bool,  # whether blueprint-aware checks ran
            }
        """
        blueprint = _load_blueprint(context)
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
        evaluation["blueprint_used"] = blueprint is not None

        return evaluation
