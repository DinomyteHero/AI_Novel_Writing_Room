"""Story Physics validation layer.

Validates that structural plans have causal and emotional infrastructure
using the StoryPhysics schema (schemas/story_physics.json).
"""

from __future__ import annotations

from src.planning.pressure_matrix import PressureMatrix


class CausalityChainValidator:
    """Builds a directed graph from causality chains and flags structural issues."""

    def __init__(self, chains: list[dict]) -> None:
        self._chains = chains
        self._events: dict[str, dict] = {e["event_id"]: e for e in chains}

    def validate(self) -> list[dict]:
        """Flag causally orphaned or dead-end events.

        Orphaned: no upstream cause (empty causes list), unless the event
        is an inciting-incident type at chapter 1.
        Dead-end: no downstream consequence (empty consequences list),
        unless the event occurs in the final chapter.
        """
        issues: list[dict] = []
        if not self._chains:
            return issues

        max_chapter = max(
            (e.get("chapter", 1) for e in self._chains), default=1
        )

        for event in self._chains:
            eid = event["event_id"]
            chapter = event.get("chapter", 1)

            # Orphaned check — skip inciting incidents at chapter 1
            if not event.get("causes"):
                if chapter != 1:
                    issues.append({
                        "event_id": eid,
                        "issue_type": "orphaned",
                        "description": (
                            f"Event '{eid}' at chapter {chapter} has no "
                            f"upstream cause and is not an inciting incident."
                        ),
                    })

            # Dead-end check — skip events in the final chapter
            if not event.get("consequences"):
                if chapter != max_chapter:
                    issues.append({
                        "event_id": eid,
                        "issue_type": "dead_end",
                        "description": (
                            f"Event '{eid}' at chapter {chapter} has no "
                            f"downstream consequences."
                        ),
                    })

        return issues

    def get_graph(self) -> dict:
        """Return an adjacency-dict representation of the causality graph.

        Keys are event_ids, values are lists of event_ids that this event
        directly causes (its consequences that reference other events).
        """
        graph: dict[str, list[str]] = {eid: [] for eid in self._events}
        for event in self._chains:
            for consequence_id in event.get("consequences", []):
                graph[event["event_id"]].append(consequence_id)
        return graph


class RevelationMap:
    """Tracks information revelations and validates their timing."""

    def __init__(self, revelations: list[dict]) -> None:
        self._revelations = revelations

    def validate_ordering(self) -> list[dict]:
        """Flag mis-timed revelations.

        - Climactic revelations placed before the 40% mark.
        - Minor revelations saved past the 80% mark.
        """
        issues: list[dict] = []
        if not self._revelations:
            return issues

        max_chapter = max(r["revealed_chapter"] for r in self._revelations)
        if max_chapter == 0:
            return issues

        for rev in self._revelations:
            position = rev["revealed_chapter"] / max_chapter
            significance = rev.get("significance", "minor")
            info_id = rev["info_id"]

            if significance == "climactic" and position < 0.4:
                issues.append({
                    "info_id": info_id,
                    "issue_type": "too_early",
                    "description": (
                        f"Climactic revelation '{info_id}' placed at chapter "
                        f"{rev['revealed_chapter']} ({position:.0%} through "
                        f"the story). Climactic reveals should not appear "
                        f"before the 40% mark."
                    ),
                })

            if significance == "minor" and position > 0.8:
                issues.append({
                    "info_id": info_id,
                    "issue_type": "too_late",
                    "description": (
                        f"Minor revelation '{info_id}' held until chapter "
                        f"{rev['revealed_chapter']} ({position:.0%} through "
                        f"the story). Minor info should be revealed earlier."
                    ),
                })

        return issues

    def get_timeline(self) -> list[dict]:
        """Return revelations ordered by revealed_chapter."""
        return sorted(self._revelations, key=lambda r: r["revealed_chapter"])


class PromisePayoffLedger:
    """Tracks narrative promises and checks fulfilment at milestones."""

    def __init__(self, promises: list[dict]) -> None:
        self._promises = {p["promise_id"]: dict(p) for p in promises}

    def check_at_milestone(
        self, chapter: int, total_chapters: int
    ) -> list[dict]:
        """Flag overdue or unresolved promises at a given chapter milestone.

        - Promises planted before *chapter* that are still unfulfilled and
          should have resolved by now (payoff_chapter <= chapter).
        - Chekhov-type promises unfulfilled for more than 60% of the story.
        """
        issues: list[dict] = []
        threshold_60 = total_chapters * 0.6

        for p in self._promises.values():
            if p["status"] != "unfulfilled":
                continue
            if p["planted_chapter"] >= chapter:
                continue

            # Has a planned payoff that has already passed
            payoff = p.get("payoff_chapter")
            if payoff is not None and payoff <= chapter:
                issues.append({
                    "promise_id": p["promise_id"],
                    "issue_type": "overdue",
                    "description": (
                        f"Promise '{p['promise_id']}' was planted at chapter "
                        f"{p['planted_chapter']} with payoff expected at "
                        f"chapter {payoff}, but remains unfulfilled at "
                        f"chapter {chapter}."
                    ),
                })

            # Chekhov items lingering too long
            if p.get("type") == "chekhov":
                age = chapter - p["planted_chapter"]
                if age > threshold_60:
                    issues.append({
                        "promise_id": p["promise_id"],
                        "issue_type": "no_payoff_planned",
                        "description": (
                            f"Chekhov promise '{p['promise_id']}' planted at "
                            f"chapter {p['planted_chapter']} has been "
                            f"unfulfilled for {age} chapters (>{threshold_60:.0f} "
                            f"= 60% of story)."
                        ),
                    })

        return issues

    def get_unfulfilled(self) -> list[dict]:
        """Return all promises with status 'unfulfilled'."""
        return [
            p for p in self._promises.values() if p["status"] == "unfulfilled"
        ]

    def update_status(
        self,
        promise_id: str,
        status: str,
        payoff_chapter: int | None = None,
    ) -> None:
        """Update the status (and optional payoff_chapter) of a promise."""
        if promise_id not in self._promises:
            raise KeyError(f"Unknown promise_id: {promise_id}")
        self._promises[promise_id]["status"] = status
        if payoff_chapter is not None:
            self._promises[promise_id]["payoff_chapter"] = payoff_chapter


class StoryPhysicsValidator:
    """Top-level validator that orchestrates all Story Physics checks."""

    def __init__(self, story_physics: dict) -> None:
        self._data = story_physics
        self.causality = CausalityChainValidator(
            story_physics.get("causality_chains", [])
        )
        self.revelations = RevelationMap(
            story_physics.get("revelation_map", [])
        )
        self.promises = PromisePayoffLedger(
            story_physics.get("promise_payoff_ledger", [])
        )
        self.pressure = PressureMatrix(
            story_physics.get("pressure_matrix", {})
        )

    def validate_all(self, total_chapters: int = 20) -> dict:
        """Run every validator and return a combined report."""
        return {
            "causality_issues": self.causality.validate(),
            "revelation_issues": self.revelations.validate_ordering(),
            "promise_issues": self.promises.check_at_milestone(
                total_chapters, total_chapters
            ),
            "pressure_issues": self.pressure.validate_escalation(),
        }
