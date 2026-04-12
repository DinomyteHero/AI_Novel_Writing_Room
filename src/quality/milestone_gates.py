"""Milestone gate support for structural transitions.

At major structural milestones (First Plot Point, Midpoint, Second Plot Point),
the pipeline pauses for human review and enforces structural constraints.
"""

from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.run_ledger import RunLedger


# Structural phases that trigger milestone gates
MILESTONE_PHASES = {"first_plot_point", "midpoint", "second_plot_point"}

# Constraints that apply after each milestone
PHASE_CONSTRAINTS = {
    "first_plot_point": [
        "Narrative quest must be locked — no more setup exposition",
        "Protagonist should shift from reactive to responsive",
        "The central dramatic question should be clearly established",
    ],
    "midpoint": [
        "Protagonist must shift from reactive/responsive to proactive",
        "No new major quest introductions",
        "Stakes should be fully raised",
    ],
    "second_plot_point": [
        "No new world-building data — all canon context should be established",
        "No new information reveals after this point",
        "All characters should be positioned for the final confrontation",
    ],
}

MILESTONE_NAMES = {
    "first_plot_point": "First Plot Point",
    "midpoint": "Midpoint",
    "second_plot_point": "Second Plot Point",
}


class MilestoneGates:
    """Check for structural milestone transitions and enforce constraints."""

    def __init__(
        self,
        ledger: "RunLedger",
        on_pause_callback: Optional[Callable[[dict], bool]] = None,
    ):
        self.ledger = ledger
        self.on_pause_callback = on_pause_callback
        self._fired_milestones: set[str] = set()

    def check(self, scene_card: dict) -> Optional[dict]:
        """Check if the current scene is at a milestone phase.

        Returns milestone info dict if a milestone is reached, else None.
        If on_pause_callback is set, calls it and includes the continue/abort decision.
        """
        structural_phase = scene_card.get("structural_phase", "")
        if structural_phase not in MILESTONE_PHASES:
            return None
        if structural_phase in self._fired_milestones:
            return None

        chapter_num = scene_card.get("chapter_number", 0)
        milestone_name = MILESTONE_NAMES.get(structural_phase, structural_phase)
        constraints = PHASE_CONSTRAINTS.get(structural_phase, [])

        milestone_info = {
            "milestone_name": milestone_name,
            "structural_phase": structural_phase,
            "chapter_number": chapter_num,
            "constraints": constraints,
        }

        self._fired_milestones.add(structural_phase)

        # Emit milestone_reached event
        self.ledger.emit(
            "milestone_reached",
            chapter_number=chapter_num,
            payload={
                "milestone_name": milestone_name,
                "structural_phase": structural_phase,
                "constraints": constraints,
            },
        )

        # If callback provided, pause for human review
        if self.on_pause_callback:
            self.ledger.emit(
                "milestone_gate_paused",
                chapter_number=chapter_num,
                payload={"milestone_name": milestone_name},
            )

            should_continue = self.on_pause_callback(milestone_info)
            milestone_info["continue"] = should_continue
        else:
            milestone_info["continue"] = True

        return milestone_info
