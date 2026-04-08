"""ConceptWorkshopStateWriter — coordinates decision detection and state persistence.

Processes conversation turns, detects confirmed decisions via DecisionDetector,
writes them to ConceptWorkshopState, and persists to disk atomically.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.model_router import ModelRouter
from src.concept_workshop.workshop_state import ConceptWorkshopState
from src.concept_workshop.decision_detector import DecisionDetector

logger = logging.getLogger(__name__)


class ConceptWorkshopStateWriter:
    """Incremental state writer for concept workshop sessions."""

    def __init__(self, project_name: str, project_dir: Path, router: ModelRouter):
        self.project_name = project_name
        self.project_dir = Path(project_dir)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.project_dir / "workshop_state.json"
        self.state = ConceptWorkshopState.load(self.state_path)
        self.detector = DecisionDetector(router)

    async def process_turn(self, role: str, content: str) -> None:
        """Detect decisions in a turn and persist confirmed ones.

        Only human turns and the immediately preceding assistant turn are
        checked — but both roles are accepted so the caller doesn't have
        to filter.
        """
        result = await self.detector.detect(role, content)

        if result.contains_decision and result.field_path:
            self.state.set_field(result.field_path, result.decision_value)
            self.state.confirm(result.field_path)
            self.state.save(self.state_path)
            logger.info(
                "Decision confirmed: %s = %s (confidence %.2f)",
                result.field_path,
                result.decision_value,
                result.confidence,
            )

    def finalize(self, output_path: str) -> None:
        """Validate and write the finalized concept seed JSON.

        Logs warnings for any fields that are still incomplete — the human
        may have intentionally left some fields as TBD.
        """
        open_questions = self.state.get_open_questions()
        if open_questions:
            logger.warning(
                "Finalizing with %d incomplete fields:", len(open_questions),
            )
            for q in open_questions:
                logger.warning("  - %s", q)

        seed = self.state.to_dict()
        # Remove the confirmed_fields tracking key — it's workshop metadata,
        # not part of the concept seed schema.
        seed.pop("confirmed_fields", None)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(seed, f, indent=2, ensure_ascii=False)

        logger.info("Concept seed finalized → %s", output_path)

    def get_session_context(self) -> str:
        """Return a formatted summary for injection into the system prompt."""
        confirmed = self.state.get_confirmed_summary()
        open_qs = self.state.get_open_questions()

        lines = ["## Decisions confirmed in previous sessions"]
        lines.append(confirmed)
        lines.append("")
        lines.append("## Fields still requiring confirmation")
        if open_qs:
            for q in open_qs:
                lines.append(f"- {q}")
        else:
            lines.append("All fields confirmed.")
        return "\n".join(lines)
