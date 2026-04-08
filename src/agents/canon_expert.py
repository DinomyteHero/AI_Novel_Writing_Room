"""Canon Expert agent — validates scene canon accuracy using RAG evidence."""

import json

from src.agents.base_agent import BaseAgent
from src.rag.canon_evidence import CanonEvidenceRanker


class CanonExpert(BaseAgent):
    """Validates scene-level canon accuracy using retrieved evidence.

    Retrieves canon evidence for each element listed in the scene card's
    canon_elements_needed, then produces structured notes the Prose Stylist
    and other agents can reference to maintain franchise accuracy.
    """

    def __init__(
        self,
        router,
        canon_evidence: CanonEvidenceRanker,
        role: str = "canon_expert",
    ):
        self.canon_evidence = canon_evidence
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        scene_card = context.get("scene_card", {})
        canon_elements = scene_card.get("canon_elements_needed", [])

        # Retrieve evidence for each needed canon element
        all_evidence: list[dict] = []
        for element in canon_elements:
            evidence = self.canon_evidence.get_evidence(element, k=3)
            all_evidence.extend(evidence)

        formatted = self.canon_evidence.format_evidence_for_context(all_evidence)

        parts = [
            "## Scene Card",
            json.dumps(scene_card, indent=2),
            "",
            "## Retrieved Canon Evidence",
            formatted,
            "",
            "## Task",
            "Review the canon elements needed for this scene against the retrieved evidence.",
            "For each canon element, provide accuracy notes and any warnings.",
            "Output your analysis as structured notes the prose stylist can reference.",
        ]
        return "\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {
            "canon_notes": response,
            "canon_elements_needed": context.get("scene_card", {}).get(
                "canon_elements_needed", []
            ),
        }
