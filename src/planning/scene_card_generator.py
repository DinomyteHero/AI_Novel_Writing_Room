"""Scene card auto-generation from concept seed.

Uses an OutlinePlanner agent to generate a chapter-by-chapter outline,
then converts each outline entry into a valid scene card. Optionally
validates with PhysicsEnforcer and retries failed cards.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from src.model_router import ModelRouter
    from src.planning.physics_enforcer import PhysicsEnforcer


class OutlinePlanner(BaseAgent):
    """Agent that generates a chapter-by-chapter outline from a concept seed.

    Assigns structural phases (Brooks 4-part), distributes plot threads,
    assigns POV characters, and generates why_now justifications.
    """

    def __init__(self, router: "ModelRouter", role: str = "outline_planner"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        """Format concept seed into the planning prompt."""
        seed = context.get("concept_seed", {})
        meta = seed.get("meta", {})
        premise = seed.get("premise", {})
        conflict = seed.get("conflict", {})
        theme = seed.get("theme", {})
        cast = seed.get("ensemble_cast", [])
        structural = seed.get("structural_notes", {})
        target_chapters = meta.get("target_chapters", 20)

        parts = [
            "## Project Overview",
            f"Title: {meta.get('project_title', 'Untitled')}",
            f"Franchise: {meta.get('franchise', 'Original')}",
            f"Target chapters: {target_chapters}",
            f"Target word count: {meta.get('target_word_count', 75000)}",
            f"POV structure: {meta.get('pov_structure', 'single')}",
            "",
            "## Premise",
            f"What-if: {premise.get('what_if', '')}",
            f"Central question: {premise.get('central_dramatic_question', '')}",
            f"Logline: {premise.get('logline', '')}",
            "",
            "## Conflict",
            f"Antagonistic force: {json.dumps(conflict.get('primary_antagonistic_force', {}), indent=2)}",
            "",
            "## Theme",
            f"Thematic premise: {theme.get('thematic_premise', '')}",
            f"Thematic argument: {theme.get('thematic_argument', '')}",
            "",
            "## Cast",
        ]

        for char in cast:
            parts.append(f"- {char.get('name', 'Unknown')} ({char.get('role', '')})")
            dims = char.get("three_dimensions", {})
            if dims:
                parts.append(f"  Surface: {dims.get('surface', '')}")
                parts.append(f"  Inner: {dims.get('backstory_inner_demons', '')}")
            parts.append("")

        if structural:
            parts.append("## Structural Notes (Brooks 4-part)")
            for phase, desc in structural.items():
                parts.append(f"- {phase}: {desc}")
            parts.append("")

        parts.append(
            f"## Task\n"
            f"Generate a complete {target_chapters}-chapter outline.\n"
            f"Return a JSON array of scene card objects. Each object must have:\n"
            f"- chapter_number (int)\n"
            f"- scene_number (int, usually 1)\n"
            f"- structural_phase (one of: setup, first_plot_point, response, "
            f"first_pinch, midpoint, attack, second_pinch, second_plot_point, "
            f"resolution, climax)\n"
            f"- pov_character (string)\n"
            f"- mission (string, what this scene accomplishes)\n"
            f"- why_now (string, specific causal justification)\n"
            f"- conflict (string)\n"
            f"- conflict_type (one of: internal, interpersonal, external, environmental)\n"
            f"- turning_point (string)\n"
            f"- emotional_trajectory (string)\n"
            f"- characters_present (list of strings)\n"
            f"- plot_threads_advanced (list of strings)\n"
            f"- promises_planted (list of strings)\n"
            f"- promises_paid (list of strings)\n"
            f"- canon_elements_needed (list of strings)\n"
            f"- target_word_count (int)\n\n"
            f"Distribute POV characters using the {meta.get('pov_structure', 'rotating')} pattern.\n"
            f"Ensure pressure escalates toward the climax.\n"
            f"Return ONLY the JSON array, no other text."
        )

        return "\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        """Parse the outline response into structured data."""
        # Try to extract JSON from response
        text = response.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            outline = json.loads(text)
            if isinstance(outline, list):
                return {"outline": outline, "scene_cards": outline}
            elif isinstance(outline, dict) and "scene_cards" in outline:
                return outline
            else:
                return {"outline": [outline], "scene_cards": [outline]}
        except json.JSONDecodeError:
            return {"outline": [], "scene_cards": [], "raw": text}


class SceneCardGenerator:
    """Generates and validates scene cards from a concept seed.

    Uses OutlinePlanner to generate scene cards, then optionally
    validates them with PhysicsEnforcer and retries failed ones.
    """

    def __init__(
        self,
        router: "ModelRouter",
        physics_enforcer: "PhysicsEnforcer | None" = None,
    ):
        self.planner = OutlinePlanner(router)
        self.physics = physics_enforcer

    async def generate(
        self, concept_seed: dict, max_retries: int = 3
    ) -> list[dict]:
        """Generate all scene cards for a novel.

        Args:
            concept_seed: The concept seed dict.
            max_retries: Maximum validation retry attempts.

        Returns:
            List of scene card dicts matching schemas/scene_card.json.
        """
        # Generate initial outline
        result = await self.planner.run_structured(
            {"concept_seed": concept_seed}
        )

        scene_cards = result.get("scene_cards", result.get("outline", []))
        if not scene_cards:
            # Fallback to non-structured run
            result = await self.planner.run({"concept_seed": concept_seed})
            scene_cards = result.get("scene_cards", result.get("outline", []))

        # Ensure required fields with defaults
        scene_cards = [self._ensure_defaults(card, concept_seed) for card in scene_cards]

        # Validate with physics enforcer if available
        if self.physics and scene_cards:
            scene_cards = await self._validate_and_fix(
                scene_cards, concept_seed, max_retries
            )

        return scene_cards

    async def _validate_and_fix(
        self, scene_cards: list[dict], concept_seed: dict, max_retries: int
    ) -> list[dict]:
        """Validate scene cards with physics enforcer and retry failures."""
        for attempt in range(max_retries):
            failed_indices = []
            for i, card in enumerate(scene_cards):
                result = self.physics.validate_pre_chapter(card)
                if not result["passed"]:
                    failed_indices.append(i)

            if not failed_indices:
                break

            # Regenerate failed cards (simplified: regenerate all and keep good ones)
            regen_result = await self.planner.run_structured(
                {"concept_seed": concept_seed}
            )
            new_cards = regen_result.get(
                "scene_cards", regen_result.get("outline", [])
            )
            new_cards = [self._ensure_defaults(c, concept_seed) for c in new_cards]

            # Replace only the failed cards if we have enough new ones
            for idx in failed_indices:
                if idx < len(new_cards):
                    scene_cards[idx] = new_cards[idx]

        return scene_cards

    def _ensure_defaults(self, card: dict, concept_seed: dict) -> dict:
        """Ensure a scene card has all required fields with sensible defaults."""
        meta = concept_seed.get("meta", {})
        target_chapters = meta.get("target_chapters", 20)
        total_words = meta.get("target_word_count", 75000)
        per_chapter = total_words // target_chapters

        defaults = {
            "chapter_number": 1,
            "scene_number": 1,
            "structural_phase": "setup",
            "pov_character": "",
            "mission": "",
            "why_now": "",
            "conflict": "",
            "conflict_type": "internal",
            "turning_point": "",
            "emotional_trajectory": "",
            "characters_present": [],
            "plot_threads_advanced": [],
            "promises_planted": [],
            "promises_paid": [],
            "canon_elements_needed": [],
            "target_word_count": per_chapter,
            "notes": "",
        }

        result = {**defaults, **card}
        return result

    def save_scene_cards(
        self, scene_cards: list[dict], output_dir: str
    ) -> list[Path]:
        """Save scene cards as individual JSON files.

        Args:
            scene_cards: List of scene card dicts.
            output_dir: Directory to save files.

        Returns:
            List of paths to saved files.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        paths = []
        for card in scene_cards:
            ch = card.get("chapter_number", 1)
            sc = card.get("scene_number", 1)
            filename = f"chapter_{ch:02d}_scene_{sc:02d}.json"
            path = out / filename
            path.write_text(
                json.dumps(card, indent=2), encoding="utf-8"
            )
            paths.append(path)

        return paths
