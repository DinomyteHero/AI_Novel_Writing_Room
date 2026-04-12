"""Seed Builder agent — converts a planning manuscript into a concept seed.

Takes free-form text from an external LLM chat session and produces a
structured concept_seed dict with Weiland arcs and Brooks structure applied.
Validates the output and retries on compliance failures.
"""

import json
import logging
from typing import TYPE_CHECKING

from src.agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from src.concept_workshop.compliance_validator import ValidationReport

logger = logging.getLogger(__name__)


class SeedBuilder(BaseAgent):
    """Converts an unstructured planning manuscript into a concept_seed dict.

    Uses the primary model for nuanced extraction from long, narrative-style
    manuscripts. Validates with the compliance validator and retries on failure.
    """

    def __init__(self, router, role: str = "seed_builder"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        summary = context["summary_text"]
        return (
            "## Planning Manuscript\n\n"
            f"{summary}\n\n"
            "## Task\n\n"
            "Extract a complete concept seed JSON from the manuscript above. "
            "Apply the Weiland character arc framework and Brooks four-part "
            "structure as described in your system prompt. "
            "Return ONLY the JSON object."
        )

    def _format_fixup_context(
        self, summary: str, current_seed: dict, failures: list[str]
    ) -> str:
        return (
            "## Original Planning Manuscript\n\n"
            f"{summary}\n\n"
            "## Current Seed (needs fixes)\n\n"
            f"```json\n{json.dumps(current_seed, indent=2)}\n```\n\n"
            "## Compliance Failures\n\n"
            + "\n".join(f"- {f}" for f in failures)
            + "\n\n## Task\n\n"
            "Fix the compliance failures listed above. Return the complete, "
            "corrected concept seed JSON. Preserve all existing valid content. "
            "Return ONLY the JSON object."
        )

    def _parse_response(self, response: str, context: dict) -> dict:
        # Not used — build_seed overrides the flow
        return {}

    async def build_seed(
        self, summary_text: str, max_retries: int = 2
    ) -> tuple[dict, "ValidationReport"]:
        """Extract a concept seed from a planning manuscript.

        Args:
            summary_text: The user's planning manuscript (markdown or text).
            max_retries: Max fix-up attempts on validation failure.

        Returns:
            Tuple of (concept_seed dict, ValidationReport).
        """
        from src.concept_workshop.compliance_validator import validate_concept_seed

        # Initial extraction
        context = {"summary_text": summary_text}
        messages = self._build_messages(context)
        seed = await self.router.complete_structured(self.role, messages)

        # Ensure we have a dict
        if not isinstance(seed, dict):
            seed = {}

        # Validate and retry loop
        for attempt in range(max_retries):
            report = validate_concept_seed(seed)
            if report.passed:
                logger.info("Seed passed compliance on attempt %d", attempt + 1)
                return seed, report

            logger.warning(
                "Seed failed compliance (attempt %d/%d): %d critical failure(s)",
                attempt + 1,
                max_retries,
                len(report.critical_failures),
            )

            # Build fix-up prompt with the failures
            fixup_content = self._format_fixup_context(
                summary_text, seed, report.critical_failures
            )
            fixup_messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": fixup_content},
            ]
            seed = await self.router.complete_structured(self.role, fixup_messages)
            if not isinstance(seed, dict):
                seed = {}

        # Final validation after all retries
        report = validate_concept_seed(seed)
        return seed, report
