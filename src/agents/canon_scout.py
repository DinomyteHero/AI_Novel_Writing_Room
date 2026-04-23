"""Planning-time Canon Scout agent.

Canon Scout enriches scene cards before drafting. It is deliberately narrow:
identify continuity risks and drafter-facing constraints from project rules,
but do not act as a final canon authority.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from src.agents.base_agent import BaseAgent
from src.pipeline.canon_guidance import (
    GUIDANCE_LIST_FIELDS,
    build_concept_seed_canon_slice,
)


class CanonScout(BaseAgent):
    """Generate static canon guidance for one scene card."""

    def __init__(self, router, role: str = "canon_scout"):
        super().__init__(router, role)

    async def run(self, context: dict) -> dict:
        messages = self._build_messages(context)
        return await self.router.complete_structured(
            self.role,
            messages,
            override_params={"temperature": 0.1, "max_tokens": 1800},
        )

    def _format_context(self, context: dict) -> str:
        concept_seed = context.get("concept_seed", {}) or {}
        chapter_blueprint = context.get("chapter_blueprint", {}) or {}
        scene_card = context.get("scene_card", {}) or {}
        canon_contract = context.get("canon_contract_text", "") or ""

        return build_canon_scout_context(
            concept_seed=concept_seed,
            chapter_blueprint=chapter_blueprint,
            scene_card=scene_card,
            canon_contract_text=canon_contract,
        )

    def _parse_response(self, response: str, context: dict) -> dict:
        return json.loads(response)


def build_canon_scout_context(
    *,
    concept_seed: Mapping[str, Any],
    chapter_blueprint: Mapping[str, Any] | None,
    scene_card: Mapping[str, Any],
    canon_contract_text: str,
) -> str:
    """Build the user prompt for cost estimation and API calls."""
    required_shape = {
        "hard_constraints": [],
        "canon_risks": [],
        "legends_continuity_notes": [],
        "possible_disney_bleed": [],
        "required_context_for_drafter": [],
        "allowed_au_divergences": [],
        "open_questions": [],
        "confidence": 0.0,
    }

    parts = [
        "You are enriching one planned scene before drafting.",
        "Use only the project contract and supplied planning artifacts.",
        "If a fact is uncertain, put it in open_questions. Do not invent lore.",
        "Flag Disney Canon bleed only when it appears possible from the plan.",
        "Return JSON only with this exact top-level shape:",
        json.dumps(required_shape, indent=2),
        "",
        "## Canon Contract",
        canon_contract_text.strip() or "(no separate canon contract supplied)",
        "",
        "## Concept Seed Canon Slice",
        json.dumps(build_concept_seed_canon_slice(concept_seed), indent=2),
        "",
        "## Chapter Blueprint",
        json.dumps(dict(chapter_blueprint or {}), indent=2),
        "",
        "## Scene Card",
        json.dumps(dict(scene_card), indent=2),
        "",
        "## Field Rules",
        "- hard_constraints: only explicit project rules the drafter must obey.",
        "- canon_risks: likely continuity risks in this scene plan.",
        "- legends_continuity_notes: useful Legends-era context for drafting.",
        "- possible_disney_bleed: Disney-only terms/concepts to avoid here.",
        "- required_context_for_drafter: facts to keep salient while writing.",
        "- allowed_au_divergences: project-authorized departures from Legends.",
        "- open_questions: anything that needs human/source review.",
        "- confidence: number from 0 to 1 for your confidence in this guidance.",
    ]
    return "\n".join(parts)


def empty_canon_scout_output() -> dict:
    """Return an empty but schema-shaped scout result."""
    payload = {field: [] for field in GUIDANCE_LIST_FIELDS}
    payload["confidence"] = 0.0
    return payload


__all__ = [
    "CanonScout",
    "build_canon_scout_context",
    "empty_canon_scout_output",
]
