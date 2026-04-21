"""State firewall for the Slice 1 architecture upgrade.

When ``runtime.firewall.enabled`` is true and the save-blocker layer fires,
the orchestrator routes the failure through :class:`StateFirewall` instead
of aborting the run. The firewall:

1. Writes a ``gap_manifest.json`` beside the quarantined scene.
2. Records a ``gap_notes`` row in ``story_state.db``.
3. Asks the :class:`SuccessorClassifier` (§5.3) whether each remaining scene
   in the chapter — plus the first scene of the next chapter — should
   ``soft_halt``, ``continue_cautiously``, or ``continue_with_note``.
4. Emits typed ledger events (``scene_isolated``, ``gap_note_recorded``).
5. Returns a :class:`FirewallDecision` the caller consults to decide whether
   to break the scene loop or advance to the next scene.

When the classifier sub-flag is off, the firewall defaults to soft-halting on
the first blocker — but still isolates rather than raising. Partial run
progress is preserved either way.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from src.pipeline.successor_classifier import (
    SuccessorClassifier,
    SuccessorDecision,
    scene_id_from_card,
)

if TYPE_CHECKING:  # avoid import cycles at runtime
    from src.memory.story_state import StoryState
    from src.pipeline.save_blockers import Blocker
    from src.project_paths import ProjectPaths
    from src.run_ledger import RunLedger

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirewallDecision:
    """Result of :meth:`StateFirewall.handle_blocker`.

    - ``isolated``: always ``True`` when the firewall handled at least one
      blocker; left as a field so tests can guard.
    - ``gap_id``: the caller-addressable identifier for the newly-recorded
      gap note (used by the patch workflow in Slice 6).
    - ``continue_run``: ``False`` when any subsequent scene was classified as
      ``soft_halt``. Callers break the scene loop cleanly.
    - ``soft_halted_scenes`` / ``continue_with_gap_note``: scene_ids grouped
      by classifier recommendation.
    - ``ledger_events``: informational copy of emitted events; the firewall
      already wrote them to the ledger by the time this returns.
    """

    isolated: bool
    gap_id: str
    continue_run: bool
    soft_halted_scenes: list[str] = field(default_factory=list)
    continue_with_gap_note: list[str] = field(default_factory=list)
    ledger_events: list[dict] = field(default_factory=list)


def _get_flag(runtime_flags: dict, dotted: str, default: Any) -> Any:
    cursor: Any = runtime_flags
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def _derive_gap_id(
    isolated_scene: str, *, now: datetime | None = None,
) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"gap_{stamp}_{isolated_scene}"


def _chapter_index_for_subsequent(
    blocked_scene: dict, subsequent_scenes: list[dict],
) -> dict[int, list[str]]:
    """Build a minimal chapter index from the blocked scene + the supplied
    remaining scenes. Enough for the classifier's adjacency checks."""
    all_cards = [blocked_scene, *subsequent_scenes]
    by_chapter: dict[int, list[tuple[int, str]]] = {}
    for card in all_cards:
        chapter = int(card["chapter_number"])
        scene = int(card["scene_number"])
        sid = scene_id_from_card(card)
        by_chapter.setdefault(chapter, []).append((scene, sid))
    return {
        ch: [sid for _, sid in sorted(entries)]
        for ch, entries in by_chapter.items()
    }


class StateFirewall:
    """Isolate + classify successors. See module docstring."""

    def __init__(
        self,
        *,
        project_paths: "ProjectPaths",
        story_state: "StoryState",
        classifier: SuccessorClassifier,
        ledger: "RunLedger",
        runtime_flags: dict,
    ) -> None:
        self.project_paths = project_paths
        self.story_state = story_state
        self.classifier = classifier
        self.ledger = ledger
        self.runtime_flags = runtime_flags

    def handle_blocker(
        self,
        *,
        scene_card: dict,
        prose: str,
        brief: dict | None,
        blockers: "list[Blocker]",
        subsequent_scenes: list[dict],
    ) -> FirewallDecision:
        """Handle a save-blocker: isolate, classify successors, decide continuation.

        Quarantine prose + ``blockers.json`` are assumed to be already on disk
        (written by ``write_quarantine`` before :class:`SaveBlockedError` was
        raised). This method adds the gap manifest and gap record, emits
        events, and returns the decision.
        """
        isolated_scene_id = scene_id_from_card(scene_card)
        chapter_num = int(scene_card["chapter_number"])
        scene_num = int(scene_card["scene_number"])

        blocker_dicts = [b.to_dict() for b in blockers]
        blocker_categories = sorted({b["code"] for b in blocker_dicts})

        classifier_enabled = bool(
            _get_flag(
                self.runtime_flags,
                "runtime.firewall.successor_classifier.enabled",
                False,
            )
        )

        classifier_decisions: list[SuccessorDecision] = []
        if subsequent_scenes:
            if classifier_enabled:
                chapter_index = _chapter_index_for_subsequent(
                    scene_card, subsequent_scenes,
                )
                for candidate in subsequent_scenes:
                    decision = self.classifier.classify(
                        blocked_scene=scene_card,
                        candidate_scene=candidate,
                        chapter_index=chapter_index,
                    )
                    classifier_decisions.append(decision)
            else:
                # Classifier untrusted — conservative soft-halt on every successor.
                for candidate in subsequent_scenes:
                    candidate_id = scene_id_from_card(candidate)
                    classifier_decisions.append(
                        SuccessorDecision(
                            scene_id=candidate_id,
                            class_label="parallel_weak_dependence",
                            recommendation="soft_halt",
                            reasons=["classifier disabled — conservative default"],
                            scores={"classifier_enabled": False},
                        )
                    )

        soft_halted = [
            d.scene_id for d in classifier_decisions
            if d.recommendation == "soft_halt"
        ]
        continue_with_note = [
            d.scene_id for d in classifier_decisions
            if d.recommendation != "soft_halt"
        ]
        continue_run = len(soft_halted) == 0

        gap_id = _derive_gap_id(isolated_scene_id)
        affected_scenes = [d.scene_id for d in classifier_decisions]

        gap_manifest = {
            "gap_id": gap_id,
            "isolated_scene": isolated_scene_id,
            "chapter_number": chapter_num,
            "scene_number": scene_num,
            "blocker_categories": blocker_categories,
            "blockers": blocker_dicts,
            "affected_scenes": affected_scenes,
            "successor_decisions": [
                {
                    "scene_id": d.scene_id,
                    "class_label": d.class_label,
                    "recommendation": d.recommendation,
                    "reasons": d.reasons,
                    "scores": d.scores,
                }
                for d in classifier_decisions
            ],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "brief_snapshot_available": brief is not None,
        }

        scene_dir = self._quarantine_scene_dir(chapter_num, scene_num)
        try:
            scene_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = scene_dir / "gap_manifest.json"
            manifest_path.write_text(
                json.dumps(gap_manifest, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error(
                "state_firewall could not write gap_manifest.json for %s: %s",
                isolated_scene_id, exc,
            )

        self.story_state.record_gap(
            {
                "gap_id": gap_id,
                "isolated_scene": isolated_scene_id,
                "blocker_categories": blocker_categories,
                "affected_scenes": affected_scenes,
                "created_at": gap_manifest["created_at"],
                "status": "open",
            }
        )

        self._mark_scene_quarantined(chapter_num, scene_num)

        ledger_events: list[dict] = []
        event = {
            "event_type": "scene_isolated",
            "chapter_number": chapter_num,
            "scene_number": scene_num,
            "payload": {
                "scene_id": isolated_scene_id,
                "blocker_categories": blocker_categories,
                "gap_id": gap_id,
                "continue_run": continue_run,
                "soft_halted_scenes": soft_halted,
                "continue_with_gap_note": continue_with_note,
                "classifier_enabled": classifier_enabled,
            },
        }
        self.ledger.emit_error(
            event["event_type"],
            chapter_number=chapter_num,
            scene_number=scene_num,
            payload=event["payload"],
        )
        ledger_events.append(event)

        gap_event = {
            "event_type": "gap_note_recorded",
            "chapter_number": chapter_num,
            "scene_number": scene_num,
            "payload": {
                "gap_id": gap_id,
                "isolated_scene": isolated_scene_id,
                "affected_scenes": affected_scenes,
            },
        }
        self.ledger.emit_warn(
            gap_event["event_type"],
            chapter_number=chapter_num,
            scene_number=scene_num,
            payload=gap_event["payload"],
        )
        ledger_events.append(gap_event)

        return FirewallDecision(
            isolated=True,
            gap_id=gap_id,
            continue_run=continue_run,
            soft_halted_scenes=soft_halted,
            continue_with_gap_note=continue_with_note,
            ledger_events=ledger_events,
        )

    def _quarantine_scene_dir(self, chapter_num: int, scene_num: int) -> Path:
        """Mirror the path ``write_quarantine`` uses so the manifest lands
        in the same directory as ``prose.md`` / ``blockers.json``."""
        # ProjectPaths exposes a quarantine_dir property; we fall back to a
        # reasonable default if callers pass a shim without it.
        quarantine_root = getattr(self.project_paths, "quarantine_dir", None)
        if quarantine_root is None:
            quarantine_root = Path("output/_fallback/quarantine")
        return Path(quarantine_root) / f"ch{chapter_num:02d}_sc{scene_num:02d}"

    def _mark_scene_quarantined(self, chapter_num: int, scene_num: int) -> None:
        """Flip the scene's ``revision_status`` to ``quarantined`` in
        ``scene_log``. Silent on missing row — pre-save failure can fire
        before ``scene_log`` has an entry for this scene."""
        try:
            self.story_state.conn.execute(
                """
                UPDATE scene_log
                   SET revision_status = 'quarantined',
                       revised_at = CURRENT_TIMESTAMP
                 WHERE chapter_number = ? AND scene_number = ?
                """,
                (chapter_num, scene_num),
            )
            self.story_state.conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "state_firewall could not mark scene_log row quarantined "
                "for ch%s_sc%s: %s",
                chapter_num, scene_num, exc,
            )
