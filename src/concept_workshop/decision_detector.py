"""DecisionDetector — classifies conversation turns for confirmable decisions.

Uses the utility model via ModelRouter to determine whether an assistant turn
contains a confirmed decision and what concept seed field it maps to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from src.model_router import ModelRouter

# The classification prompt sent to the utility model.
_CLASSIFICATION_PROMPT = """\
You are a decision classifier for a concept-workshop conversation.

Given a conversation turn, determine whether it contains a CONFIRMED decision
about a novel's concept seed.  Only flag decisions that have been explicitly
approved or confirmed by the human — exploratory options, open questions, and
rejected alternatives are NOT decisions.

Decision categories and their field paths:
- Franchise / canon_status / era / tone → meta.<field>
- Project title → meta.project_title
- Target word count / chapters / POV structure → meta.<field>
- What-if / central dramatic question / logline → premise.<field>
- Primary antagonistic force / secondary pressures / lock-in → conflict.<field>
- Thematic premise / argument / arc tests → theme.<field>
- Protagonist arc type → protagonist_arc_type
- Character name confirmed → ensemble_cast.<index>.name
- Character profile confirmed → ensemble_cast.<index>.three_dimensions
- Character voice notes → ensemble_cast.<index>.voice_notes
- Force/magic mechanics → force_mechanics.<field>
- Canon constraints → canon_constraints.<field>
- Brooks structure milestones → structural_notes.brooks_alignment.<field>

Respond with JSON only:
{
  "contains_decision": true/false,
  "field_path": "dot.notation.path" or null,
  "decision_value": <extracted value> or null,
  "confidence": 0.0-1.0
}
"""


@dataclass
class DecisionResult:
    """Result of classifying a single conversation turn."""

    contains_decision: bool
    field_path: Optional[str] = None
    decision_value: Any = None
    confidence: float = 0.0


class DecisionDetector:
    """Classifies assistant turns for confirmable concept-seed decisions."""

    CONFIDENCE_THRESHOLD = 0.8

    def __init__(self, router: ModelRouter):
        self.router = router

    async def detect(self, role: str, content: str) -> DecisionResult:
        """Classify a conversation turn for decision content.

        Returns a ``DecisionResult``.  Only results with
        ``confidence >= CONFIDENCE_THRESHOLD`` will have
        ``contains_decision == True``.
        """
        messages = [
            {"role": "system", "content": _CLASSIFICATION_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Conversation turn ({role}):\n\n{content}\n\n"
                    "Classify this turn."
                ),
            },
        ]

        try:
            raw = await self.router.complete_structured(
                "summarizer",  # Uses utility model.
                messages,
            )
        except Exception:
            # If the model call fails, be conservative — no decision.
            return DecisionResult(contains_decision=False)

        confidence = float(raw.get("confidence", 0.0))

        if not raw.get("contains_decision") or confidence < self.CONFIDENCE_THRESHOLD:
            return DecisionResult(contains_decision=False, confidence=confidence)

        return DecisionResult(
            contains_decision=True,
            field_path=raw.get("field_path"),
            decision_value=raw.get("decision_value"),
            confidence=confidence,
        )
