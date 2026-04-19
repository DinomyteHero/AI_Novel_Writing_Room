"""Save-blocker check for the relay pipeline (Stage 1f).

Runs after the final continuity-editor pass as the last step before file
write. Three blocker categories:

- ``CHARACTER_PRESENCE_BLOCKER``: dedicated PresenceChecker agent detects
  named characters who speak or act despite being absent from the scene
  card's characters_present list.
- ``CANON_BLOCKER``: fires when canon_expert returns ``verdict == "fail"``
  AND at least one finding has severity in ``{critical, moderate}``. Minor
  findings and ``post_divergence_drift`` are advisory only and never block.
- POV advisory: best-effort regex scan, emits a warn-level event but does
  NOT block in v1 (promoted to blocker after corpus validation).

A non-empty blocker list causes the orchestrator to write the offending
scene's prose + blocker report to the project's quarantine directory and
raise ``SaveBlockedError``, which aborts the whole run.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class Blocker:
    """One save-blocking finding.

    ``code`` is one of ``CHARACTER_PRESENCE_BLOCKER`` or ``CANON_BLOCKER``.
    Severity is always ``critical`` or ``moderate`` for blockers; lower
    severities are filtered out in ``check_save_blockers`` and emitted as
    advisories by the caller.
    """

    code: str
    severity: str
    description: str
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


class SaveBlockedError(Exception):
    """Raised when save-blockers fire. Caught by the pipeline runner to abort."""

    def __init__(
        self,
        blockers: list[Blocker],
        quarantine_path: Path,
        chapter_number: int,
        scene_number: int,
    ):
        self.blockers = blockers
        self.quarantine_path = quarantine_path
        self.chapter_number = chapter_number
        self.scene_number = scene_number
        lines = [
            f"Scene ch{chapter_number}_sc{scene_number}: "
            f"{len(blockers)} save-blocker(s) fired"
        ]
        for b in blockers:
            lines.append(f"  [{b.code}] ({b.severity}) {b.description}")
        lines.append(f"Quarantined at: {quarantine_path}")
        super().__init__("\n".join(lines))


# Heuristic POV advisory — third-person interiority verbs that suggest a
# non-POV character's internal state is being reported.
_NON_POV_INTERIORITY_VERBS = (
    "thought",
    "wondered",
    "realized",
    "remembered",
    "felt",
    "knew",
    "believed",
    "decided",
    "wished",
    "hoped",
)


async def check_save_blockers(
    prose: str,
    scene_card: dict,
    continuity_report: Optional[dict],
    presence_checker: Optional[Any],
) -> list[Blocker]:
    """Run all save-blocker checks against the final prose.

    Returns a list of ``Blocker`` objects. An empty list means the save
    proceeds.

    Parameters
    ----------
    prose:
        The final prose to evaluate (post continuity-editor).
    scene_card:
        The scene card dict (needs ``characters_present`` for presence
        context; the checker agent also consumes ``pov_character``).
    continuity_report:
        The dict returned by ``canon_expert.run()`` / ``evaluate()`` on the
        final prose. Falsy values skip the canon check.
    presence_checker:
        A ``PresenceChecker`` agent instance. ``None`` skips the presence
        check (e.g., when the agent could not be initialised).
    """
    blockers: list[Blocker] = []

    if presence_checker is not None:
        try:
            presence_result = await presence_checker.run(
                {"prose": prose, "scene_card": scene_card}
            )
        except Exception:
            # Presence-checker infra failure is advisory, not blocking.
            # The caller emits a warn-level ledger event.
            presence_result = {"violations": []}

        for v in presence_result.get("violations", []) or []:
            char = (v.get("character") or "").strip()
            if not char:
                continue
            blockers.append(
                Blocker(
                    code="CHARACTER_PRESENCE_BLOCKER",
                    severity="critical",
                    description=(
                        f"Character '{char}' speaks or acts in the scene but is "
                        f"not listed in characters_present."
                    ),
                    evidence=(v.get("evidence") or "").strip(),
                )
            )

    if continuity_report:
        verdict = continuity_report.get("verdict", "pass")
        if verdict == "fail":
            for v in continuity_report.get("violations", []) or []:
                severity = v.get("severity", "minor")
                category = v.get("category", "")
                # post_divergence_drift is always advisory (canon_expert
                # already clamps severity to "minor", but double-guard).
                if category == "post_divergence_drift":
                    continue
                if severity in ("critical", "moderate"):
                    blockers.append(
                        Blocker(
                            code="CANON_BLOCKER",
                            severity=severity,
                            description=(
                                f"{category}: {v.get('explanation', '')}".strip(": ")
                            ),
                            evidence=(v.get("text") or "").strip(),
                        )
                    )

    return blockers


def detect_pov_advisory(prose: str, scene_card: dict) -> list[dict]:
    """Detect likely non-POV interiority. Advisory-only in v1.

    Returns a list of suspected spans. Callers should emit a warn-level
    ledger event when non-empty but must NOT block saves on this signal —
    the heuristic is intentionally crude to keep false negatives rare, so
    false positives are expected.
    """
    pov = (scene_card.get("pov_character") or "").strip()
    characters_present = scene_card.get("characters_present", []) or []
    if not pov or not characters_present:
        return []

    non_pov = [c for c in characters_present if c.strip() and c.strip() != pov]
    if not non_pov:
        return []

    verb_alt = "|".join(_NON_POV_INTERIORITY_VERBS)
    hits: list[dict] = []
    for char in non_pov:
        escaped = re.escape(char)
        # "{Name} [optional short filler] {interiority verb}" — word-boundaries
        # keep the match tight. Filler cap of 20 chars avoids cross-sentence
        # false positives.
        pattern = rf"\b{escaped}\b[^.!?\n]{{0,20}}\b(?:{verb_alt})\b"
        for m in re.finditer(pattern, prose):
            hits.append(
                {
                    "character": char,
                    "span": m.group(0),
                    "offset": m.start(),
                }
            )
    return hits


def write_quarantine(
    quarantine_root: Path,
    chapter_number: int,
    scene_number: int,
    prose: str,
    blockers: list[Blocker],
    brief: Optional[dict],
    scene_card: dict,
) -> Path:
    """Write prose + blockers.json + brief.json into the quarantine folder.

    Returns the scene-specific quarantine directory
    (``<quarantine_root>/ch<NN>_sc<MM>/``).
    """
    scene_dir = quarantine_root / f"ch{chapter_number:02d}_sc{scene_number:02d}"
    scene_dir.mkdir(parents=True, exist_ok=True)

    (scene_dir / "prose.md").write_text(prose, encoding="utf-8")

    report = {
        "chapter_number": chapter_number,
        "scene_number": scene_number,
        "blockers": [b.to_dict() for b in blockers],
        "scene_card_id": scene_card.get("scene_id")
        or f"ch{chapter_number}_sc{scene_number}",
    }
    (scene_dir / "blockers.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    if brief is not None:
        (scene_dir / "brief.json").write_text(
            json.dumps(brief, indent=2), encoding="utf-8"
        )

    return scene_dir
