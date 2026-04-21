"""Deterministic successor classifier for the state firewall (Slice 1).

When a scene is isolated by the firewall, the classifier inspects every
remaining scene in the chapter (plus the first scene of the next chapter,
since Brooks four-part transitions often carry across the boundary) and
assigns one of six labels plus a recommendation: ``soft_halt``,
``continue_cautiously``, or ``continue_with_note``.

No LLM inference in v1 — the spec (§5.3) explicitly prefers a deterministic
heuristic that is easy to validate with a hand-labeled set.

Classification rules fire in order, first match wins:

1. ``immediate_sequel`` — candidate's ``depends_on`` lists the blocked scene.
2. ``same_pov_continuation`` — same POV AND candidate is the next scene
   in the same chapter.
3. ``same_turn_escalation`` — same ``structural_phase`` AND candidate is in
   the same chapter or is the first scene of the next chapter.
4. ``transitional_with_gap`` — character-set jaccard ≥ threshold AND candidate
   is the next scene in the same chapter.
5. ``loose_downstream`` — jaccard below threshold, OR candidate is more than
   ``adjacency_max_for_continue`` scenes away.
6. ``parallel_weak_dependence`` — fallback.

Rules 1–3 recommend ``soft_halt`` (stop the run). Rule 4 recommends
``continue_cautiously`` (draft with a prompt-level gap note). Rules 5–6
recommend ``continue_with_note`` (draft and let the packet overlay carry
the gap).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


SuccessorLabel = Literal[
    "immediate_sequel",
    "same_pov_continuation",
    "same_turn_escalation",
    "transitional_with_gap",
    "loose_downstream",
    "parallel_weak_dependence",
]

Recommendation = Literal["soft_halt", "continue_cautiously", "continue_with_note"]


@dataclass(frozen=True)
class SuccessorDecision:
    scene_id: str
    class_label: SuccessorLabel
    recommendation: Recommendation
    reasons: list[str] = field(default_factory=list)
    scores: dict[str, Any] = field(default_factory=dict)


def scene_id_from_card(card: dict) -> str:
    """Canonicalize a scene card to its ``chNN_scMM`` identifier."""
    chapter = int(card["chapter_number"])
    scene = int(card["scene_number"])
    return f"ch{chapter:02d}_sc{scene:02d}"


def _normalize_cast(names: list[str] | None) -> set[str]:
    if not names:
        return set()
    return {str(n).strip().lower() for n in names if str(n).strip()}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


class SuccessorClassifier:
    """Heuristic classifier; see module docstring for the rule list."""

    def __init__(
        self,
        *,
        jaccard_threshold: float = 0.5,
        adjacency_max_for_continue: int = 1,
    ) -> None:
        if not 0.0 <= jaccard_threshold <= 1.0:
            raise ValueError(
                f"jaccard_threshold must be in [0, 1], got {jaccard_threshold}"
            )
        if adjacency_max_for_continue < 0:
            raise ValueError(
                f"adjacency_max_for_continue must be >= 0, got {adjacency_max_for_continue}"
            )
        self.jaccard_threshold = jaccard_threshold
        self.adjacency_max_for_continue = adjacency_max_for_continue

    def classify(
        self,
        *,
        blocked_scene: dict,
        candidate_scene: dict,
        chapter_index: dict[int, list[str]],
    ) -> SuccessorDecision:
        """Classify ``candidate_scene`` relative to ``blocked_scene``.

        ``chapter_index`` is ``{chapter_number: [scene_id, ...]}`` in
        narrative order. It is used to compute adjacency and to find the
        first scene of the next chapter.
        """
        blocked_id = scene_id_from_card(blocked_scene)
        candidate_id = scene_id_from_card(candidate_scene)

        blocked_chapter = int(blocked_scene["chapter_number"])
        candidate_chapter = int(candidate_scene["chapter_number"])

        same_chapter = blocked_chapter == candidate_chapter
        adjacency_distance = self._adjacency_distance(
            blocked_id, candidate_id, chapter_index,
        )
        is_next_in_chapter = same_chapter and adjacency_distance == 1
        is_first_of_next_chapter = (
            candidate_chapter == blocked_chapter + 1
            and chapter_index.get(candidate_chapter, [None])[0] == candidate_id
        )

        pov_match = self._pov_match(blocked_scene, candidate_scene)
        structural_match = self._structural_match(blocked_scene, candidate_scene)
        blocked_cast = _normalize_cast(blocked_scene.get("characters_present"))
        candidate_cast = _normalize_cast(candidate_scene.get("characters_present"))
        jaccard_score = _jaccard(blocked_cast, candidate_cast)

        scores = {
            "jaccard": round(jaccard_score, 4),
            "adjacency_distance": adjacency_distance,
            "same_chapter": same_chapter,
            "is_next_in_chapter": is_next_in_chapter,
            "is_first_of_next_chapter": is_first_of_next_chapter,
            "pov_match": pov_match,
            "structural_match": structural_match,
            "jaccard_threshold": self.jaccard_threshold,
        }

        depends_on = [
            str(x).strip() for x in candidate_scene.get("depends_on") or []
        ]
        if blocked_id in depends_on:
            return SuccessorDecision(
                scene_id=candidate_id,
                class_label="immediate_sequel",
                recommendation="soft_halt",
                reasons=[f"candidate.depends_on includes {blocked_id}"],
                scores=scores,
            )

        if pov_match and is_next_in_chapter:
            return SuccessorDecision(
                scene_id=candidate_id,
                class_label="same_pov_continuation",
                recommendation="soft_halt",
                reasons=[
                    "same pov_character",
                    "next scene in same chapter",
                ],
                scores=scores,
            )

        if structural_match and (same_chapter or is_first_of_next_chapter):
            return SuccessorDecision(
                scene_id=candidate_id,
                class_label="same_turn_escalation",
                recommendation="soft_halt",
                reasons=[
                    f"same structural_phase={blocked_scene.get('structural_phase')!r}",
                    "same chapter" if same_chapter else "first scene of next chapter",
                ],
                scores=scores,
            )

        if jaccard_score >= self.jaccard_threshold and is_next_in_chapter:
            return SuccessorDecision(
                scene_id=candidate_id,
                class_label="transitional_with_gap",
                recommendation="continue_cautiously",
                reasons=[
                    f"character-set jaccard={jaccard_score:.2f} >= threshold={self.jaccard_threshold}",
                    "next scene in same chapter",
                ],
                scores=scores,
            )

        if (
            jaccard_score < self.jaccard_threshold
            or adjacency_distance > self.adjacency_max_for_continue
        ):
            reasons = []
            if jaccard_score < self.jaccard_threshold:
                reasons.append(
                    f"character-set jaccard={jaccard_score:.2f} < threshold={self.jaccard_threshold}",
                )
            if adjacency_distance > self.adjacency_max_for_continue:
                reasons.append(
                    f"adjacency_distance={adjacency_distance} > {self.adjacency_max_for_continue}",
                )
            return SuccessorDecision(
                scene_id=candidate_id,
                class_label="loose_downstream",
                recommendation="continue_with_note",
                reasons=reasons,
                scores=scores,
            )

        return SuccessorDecision(
            scene_id=candidate_id,
            class_label="parallel_weak_dependence",
            recommendation="continue_with_note",
            reasons=["no stronger rule matched"],
            scores=scores,
        )

    @staticmethod
    def _pov_match(blocked: dict, candidate: dict) -> bool:
        a = str(blocked.get("pov_character") or "").strip().lower()
        b = str(candidate.get("pov_character") or "").strip().lower()
        return bool(a) and a == b

    @staticmethod
    def _structural_match(blocked: dict, candidate: dict) -> bool:
        a = str(blocked.get("structural_phase") or "").strip().lower()
        b = str(candidate.get("structural_phase") or "").strip().lower()
        return bool(a) and a == b

    @staticmethod
    def _adjacency_distance(
        blocked_id: str,
        candidate_id: str,
        chapter_index: dict[int, list[str]],
    ) -> int:
        """Signed distance (always >= 0 here) between blocked and candidate.

        Within the same chapter, counts index positions. Across chapters,
        counts scene-steps as ``(remaining in blocked's chapter) + sum of
        full intervening chapters + position in candidate's chapter``.
        Returns a large sentinel when the candidate cannot be found.
        """
        ordered_chapters = sorted(chapter_index.keys())
        flat: list[tuple[int, str]] = []
        for ch in ordered_chapters:
            for sid in chapter_index[ch]:
                flat.append((ch, sid))
        positions = {sid: i for i, (_, sid) in enumerate(flat)}
        if blocked_id not in positions or candidate_id not in positions:
            return 10**6  # sentinel: can't compute
        return abs(positions[candidate_id] - positions[blocked_id])


def build_chapter_index(scene_cards: list[dict]) -> dict[int, list[str]]:
    """Build the ``{chapter: [scene_id, ...]}`` index from a flat list of cards.

    Sorts by ``chapter_number`` then ``scene_number`` within chapter.
    """
    by_chapter: dict[int, list[tuple[int, str]]] = {}
    for card in scene_cards:
        chapter = int(card["chapter_number"])
        scene = int(card["scene_number"])
        sid = scene_id_from_card(card)
        by_chapter.setdefault(chapter, []).append((scene, sid))
    return {
        ch: [sid for _, sid in sorted(entries)]
        for ch, entries in by_chapter.items()
    }
