"""Static canon-guidance sidecars for scene-card enrichment.

The canon scout is a planning-time helper, not a drafting-time dependency.
This module keeps its output deterministic and cacheable: each scene gets a
sidecar JSON file keyed by a hash of the inputs that should affect guidance.
Runtime packet compilation only injects fresh sidecars.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PROMPT_VERSION = "canon_scout_v1"
SCHEMA_VERSION = 1

GUIDANCE_LIST_FIELDS = (
    "hard_constraints",
    "canon_risks",
    "legends_continuity_notes",
    "possible_disney_bleed",
    "required_context_for_drafter",
    "allowed_au_divergences",
    "open_questions",
)

REVIEW_STATUSES = {"unreviewed", "accepted", "rejected", "needs_source"}


def scene_id_from_card(scene_card: Mapping[str, Any]) -> str:
    """Return the canonical chNN_scMM identifier for a scene card."""
    chapter_number = int(scene_card.get("chapter_number") or 0)
    scene_number = int(scene_card.get("scene_number") or 1)
    if chapter_number < 1 or scene_number < 1:
        raise ValueError("scene card must include positive chapter_number/scene_number")
    return f"ch{chapter_number:02d}_sc{scene_number:02d}"


def estimate_tokens(text: str) -> int:
    """Cheap token estimate for dry-run costing.

    Uses a conservative 0.75 words/token approximation, rounded up by integer
    arithmetic so estimates do not undercount tiny prompts.
    """
    words = len(text.split())
    return max(1, int(words / 0.75) + 1) if text.strip() else 0


def build_concept_seed_canon_slice(concept_seed: Mapping[str, Any]) -> dict:
    """Extract the seed fields the Canon Scout should see.

    The full concept seed is too broad for every scene. This slice keeps the
    explicit continuity contract, terminology, force mechanics, and relevant
    cast/relationship surfaces while avoiding unrelated compile metadata.
    """
    keys = (
        "meta",
        "premise",
        "conflict",
        "canon_profile",
        "canon_constraints",
        "force_mechanics",
        "terminology_registry",
        "referenced_characters",
        "relationship_arcs",
        "ensemble_cast",
    )
    return {key: concept_seed.get(key) for key in keys if key in concept_seed}


def compute_input_hash(
    *,
    concept_seed: Mapping[str, Any],
    chapter_blueprint: Mapping[str, Any] | None,
    scene_card: Mapping[str, Any],
    canon_contract_text: str,
    prompt_version: str = PROMPT_VERSION,
) -> str:
    """Hash every stable input that should invalidate canon guidance."""
    payload = {
        "prompt_version": prompt_version,
        "concept_seed_canon_slice": build_concept_seed_canon_slice(concept_seed),
        "chapter_blueprint": dict(chapter_blueprint or {}),
        "scene_card": dict(scene_card),
        "canon_contract_text": canon_contract_text,
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GuidanceFreshness:
    scene_id: str
    status: str
    path: Path
    expected_hash: str
    actual_hash: str = ""
    reason: str = ""

    @property
    def is_fresh(self) -> bool:
        return self.status == "fresh"


@dataclass(frozen=True)
class GuidanceCoverage:
    """Freshness rollup for a set of scene cards."""

    total: int
    fresh: int
    missing: int
    stale: int
    invalid: int
    details: tuple[GuidanceFreshness, ...]

    @property
    def complete(self) -> bool:
        return self.total > 0 and self.fresh == self.total

    @property
    def incomplete(self) -> tuple[GuidanceFreshness, ...]:
        return tuple(item for item in self.details if not item.is_fresh)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "fresh": self.fresh,
            "missing": self.missing,
            "stale": self.stale,
            "invalid": self.invalid,
            "complete": self.complete,
            "details": [
                {
                    "scene_id": item.scene_id,
                    "status": item.status,
                    "path": str(item.path),
                    "expected_hash": item.expected_hash,
                    "actual_hash": item.actual_hash,
                    "reason": item.reason,
                }
                for item in self.details
            ],
        }


class CanonGuidanceStore:
    """Read/write static canon-guidance sidecars for a book."""

    def __init__(
        self,
        root_dir: str | Path,
        *,
        canon_contract_path: str | Path | None = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.canon_contract_path = Path(canon_contract_path) if canon_contract_path else None
        self.prompt_version = prompt_version

    def contract_text(self) -> str:
        if self.canon_contract_path and self.canon_contract_path.exists():
            return self.canon_contract_path.read_text(encoding="utf-8")
        return ""

    def path_for_scene(self, scene_card_or_id: Mapping[str, Any] | str) -> Path:
        if isinstance(scene_card_or_id, str):
            sid = scene_card_or_id
        else:
            sid = scene_id_from_card(scene_card_or_id)
        return self.root_dir / f"{sid}.json"

    def expected_hash(
        self,
        *,
        concept_seed: Mapping[str, Any],
        chapter_blueprint: Mapping[str, Any] | None,
        scene_card: Mapping[str, Any],
    ) -> str:
        return compute_input_hash(
            concept_seed=concept_seed,
            chapter_blueprint=chapter_blueprint,
            scene_card=scene_card,
            canon_contract_text=self.contract_text(),
            prompt_version=self.prompt_version,
        )

    def freshness(
        self,
        *,
        concept_seed: Mapping[str, Any],
        chapter_blueprint: Mapping[str, Any] | None,
        scene_card: Mapping[str, Any],
    ) -> GuidanceFreshness:
        sid = scene_id_from_card(scene_card)
        path = self.path_for_scene(sid)
        expected = self.expected_hash(
            concept_seed=concept_seed,
            chapter_blueprint=chapter_blueprint,
            scene_card=scene_card,
        )
        if not path.exists():
            return GuidanceFreshness(sid, "missing", path, expected, reason="no sidecar")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return GuidanceFreshness(
                sid, "invalid", path, expected, reason=f"{type(exc).__name__}: {exc}"
            )
        actual = str(payload.get("input_hash") or "")
        if actual != expected:
            return GuidanceFreshness(sid, "stale", path, expected, actual)
        if not self._is_guidance_payload(payload):
            return GuidanceFreshness(sid, "invalid", path, expected, actual, "schema")
        return GuidanceFreshness(sid, "fresh", path, expected, actual)

    def load_fresh(
        self,
        *,
        concept_seed: Mapping[str, Any],
        chapter_blueprint: Mapping[str, Any] | None,
        scene_card: Mapping[str, Any],
    ) -> dict | None:
        freshness = self.freshness(
            concept_seed=concept_seed,
            chapter_blueprint=chapter_blueprint,
            scene_card=scene_card,
        )
        if not freshness.is_fresh:
            return None
        try:
            return json.loads(freshness.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def coverage(
        self,
        *,
        concept_seed: Mapping[str, Any],
        blueprints: Mapping[int, Mapping[str, Any]],
        scene_cards: list[Mapping[str, Any]],
    ) -> GuidanceCoverage:
        """Return freshness coverage for the selected scene cards."""
        details: list[GuidanceFreshness] = []
        for card in scene_cards:
            chapter = int(card.get("chapter_number") or 0)
            details.append(
                self.freshness(
                    concept_seed=concept_seed,
                    chapter_blueprint=blueprints.get(chapter, {}),
                    scene_card=card,
                )
            )
        counts = {"fresh": 0, "missing": 0, "stale": 0, "invalid": 0}
        for item in details:
            if item.status in counts:
                counts[item.status] += 1
        return GuidanceCoverage(
            total=len(details),
            fresh=counts["fresh"],
            missing=counts["missing"],
            stale=counts["stale"],
            invalid=counts["invalid"],
            details=tuple(details),
        )

    def prepare_payload(
        self,
        *,
        model_output: Mapping[str, Any],
        model: str,
        concept_seed: Mapping[str, Any],
        chapter_blueprint: Mapping[str, Any] | None,
        scene_card: Mapping[str, Any],
    ) -> dict:
        """Normalize model output and attach cache metadata."""
        sid = scene_id_from_card(scene_card)
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "scene_id": sid,
            "chapter_number": int(scene_card.get("chapter_number") or 0),
            "scene_number": int(scene_card.get("scene_number") or 1),
            "model": model,
            "prompt_version": self.prompt_version,
            "input_hash": self.expected_hash(
                concept_seed=concept_seed,
                chapter_blueprint=chapter_blueprint,
                scene_card=scene_card,
            ),
            "review_status": str(model_output.get("review_status") or "unreviewed"),
            "confidence": _coerce_confidence(model_output.get("confidence")),
        }
        if payload["review_status"] not in REVIEW_STATUSES:
            payload["review_status"] = "unreviewed"
        for field in GUIDANCE_LIST_FIELDS:
            payload[field] = _coerce_string_list(model_output.get(field))
        return payload

    def write(self, payload: Mapping[str, Any]) -> Path:
        if not self._is_guidance_payload(payload):
            raise ValueError("invalid canon guidance payload")
        self.root_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for_scene(str(payload["scene_id"]))
        path.write_text(
            json.dumps(dict(payload), ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _is_guidance_payload(payload: Mapping[str, Any]) -> bool:
        if int(payload.get("schema_version") or 0) != SCHEMA_VERSION:
            return False
        for key in ("scene_id", "model", "prompt_version", "input_hash", "review_status"):
            if not isinstance(payload.get(key), str) or not payload.get(key):
                return False
        if payload.get("review_status") not in REVIEW_STATUSES:
            return False
        if not isinstance(payload.get("chapter_number"), int):
            return False
        if not isinstance(payload.get("scene_number"), int):
            return False
        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            return False
        return all(isinstance(payload.get(field), list) for field in GUIDANCE_LIST_FIELDS)


def render_guidance_for_packet(guidance: Mapping[str, Any]) -> str:
    """Render fresh canon guidance for the drafter packet."""
    lines: list[str] = []
    status = guidance.get("review_status", "unreviewed")
    confidence = guidance.get("confidence", 0)
    lines.append(f"- Review status: {status}")
    lines.append(f"- Scout confidence: {confidence}")

    headings = (
        ("hard_constraints", "Hard Constraints"),
        ("required_context_for_drafter", "Required Context For Drafter"),
        ("legends_continuity_notes", "Legends Continuity Notes"),
        ("allowed_au_divergences", "Allowed AU Divergences"),
        ("possible_disney_bleed", "Possible Disney Canon Bleed"),
        ("canon_risks", "Canon Risks"),
        ("open_questions", "Open Questions"),
    )
    for field, heading in headings:
        values = [str(v).strip() for v in guidance.get(field, []) if str(v).strip()]
        if not values:
            continue
        lines.append("")
        lines.append(f"#### {heading}")
        for value in values:
            lines.append(f"- {value}")
    return "\n".join(lines)


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                text = item.get("note") or item.get("summary") or item.get("description")
                if text:
                    out.append(str(text).strip())
            elif item is not None:
                text = str(item).strip()
                if text:
                    out.append(text)
        return out
    return [str(value).strip()] if str(value).strip() else []


def _coerce_confidence(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"high", "strong"}:
            return 0.85
        if lowered in {"medium", "moderate"}:
            return 0.6
        if lowered in {"low", "weak"}:
            return 0.3
        try:
            return max(0.0, min(1.0, float(lowered)))
        except ValueError:
            return 0.5
    return 0.5


__all__ = [
    "CanonGuidanceStore",
    "GUIDANCE_LIST_FIELDS",
    "GuidanceFreshness",
    "PROMPT_VERSION",
    "SCHEMA_VERSION",
    "build_concept_seed_canon_slice",
    "compute_input_hash",
    "estimate_tokens",
    "render_guidance_for_packet",
    "scene_id_from_card",
]
