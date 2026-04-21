"""Slice 4 ContinuityExtractor agent.

Reads saved prose + scene card and returns a list of narrow continuity
events with self-scored confidence. Output is threshold-filtered by the
orchestrator (``runtime.continuity_log.min_confidence``); rows below the
threshold are suppressed entirely \u2014 not written to the continuity log,
not surfaced in the packet, not logged as content (only a suppression
count). This prevents hallucinated facts from ever reaching the drafter.

Trust model (spec \u00a78.3): the extractor is advisory-to-trusted, threshold-
gated. Before flipping ``runtime.continuity_log.enabled`` on any book, the
eval harness in ``scripts/eval_continuity_extractor.py`` must hit
precision \u2265 0.90 (\u2265 0.95 for Ruusan) on the labeled set at
``tests/data/continuity_eval_set.json``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping, Optional

from src.agents.base_agent import BaseAgent
from src.memory.continuity_log import EVENT_TYPES
from src.model_router import ModelRouter

logger = logging.getLogger(__name__)


EXTRACTOR_VERSION = "v0.1"


class ContinuityExtractor(BaseAgent):
    """Extract narrow continuity events from saved prose.

    The agent returns a list of event dicts matching
    ``schemas/continuity_event.json`` minus ``event_id`` / ``created_at``
    (assigned by the store at append time). Bad / invalid rows are dropped
    silently with a warn log; the agent never raises from malformed LLM
    output \u2014 a scene's extractor failure must not abort the pipeline.
    """

    def __init__(self, router: ModelRouter, role: str = "continuity_extractor"):
        super().__init__(router, role)

    async def extract(
        self,
        *,
        prose: str,
        scene_card: Mapping[str, Any],
        concept_seed: Mapping[str, Any],
    ) -> list[dict]:
        """Extract and return validated events (not threshold-filtered).

        The caller applies the confidence threshold and appends passing
        events to ``ContinuityLog``. This split keeps the agent unaware of
        runtime flags so unit tests can assert extractor behavior without
        wiring the orchestrator.
        """
        context = {
            "prose": prose,
            "scene_card": dict(scene_card),
            "concept_seed": dict(concept_seed),
        }
        try:
            raw = await self.run_structured(context)
        except Exception:  # noqa: BLE001
            logger.exception("continuity_extractor router call failed")
            return []
        return self._validate_events(raw, scene_card=scene_card)

    # ------------------------------------------------------------------ agent
    def _format_context(self, context: dict) -> str:
        prose = context.get("prose", "")
        scene_card = context.get("scene_card") or {}
        concept_seed = context.get("concept_seed") or {}

        scene_id = _scene_id_from_card(scene_card)
        characters_present = scene_card.get("characters_present", [])
        revelations_planned = _planned_revelations(
            concept_seed=concept_seed, scene_card=scene_card,
        )

        scene_summary = {
            "scene_id": scene_id,
            "chapter_number": scene_card.get("chapter_number"),
            "scene_number": scene_card.get("scene_number"),
            "pov_character": scene_card.get("pov_character", ""),
            "mission": scene_card.get("mission", ""),
            "characters_present": characters_present,
            "revelations": scene_card.get("revelations", []),
            "canon_elements_needed": scene_card.get("canon_elements_needed", []),
        }

        parts = [
            f"## Scene summary\n```json\n{json.dumps(scene_summary, indent=2)}\n```",
            f"## Planned revelation IDs (only revelation events matching these are valid)\n"
            f"```json\n{json.dumps(revelations_planned, indent=2)}\n```",
            f"## Prose\n{prose}",
            "## Task\n"
            "Extract the narrow continuity events this scene establishes, per the "
            "rules in the system prompt. Return a single JSON object with an "
            "``events`` array. Self-score confidence in [0, 1]. Exclude any "
            "event whose type does not match the allowed five. Exclude "
            "interpretive, emotional, or relational events.",
        ]
        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        # Not used on the ``extract`` path (we go through ``run_structured``),
        # but BaseAgent's abstract contract requires an implementation for
        # the fallback ``run`` path.
        try:
            return json.loads(response)
        except Exception:  # noqa: BLE001
            return {"events": []}

    # ------------------------------------------------------------------ guards
    def _validate_events(
        self, raw: Any, *, scene_card: Mapping[str, Any],
    ) -> list[dict]:
        """Strip rows that don't match the closed type set or required
        details shape. Silent on bad rows \u2014 per spec \u00a78.3 the extractor is
        allowed to drop output; false positives are the cost floor."""
        events_list = _coerce_events_list(raw)
        scene_id = _scene_id_from_card(scene_card)
        out: list[dict] = []
        for raw_event in events_list:
            if not isinstance(raw_event, Mapping):
                continue
            event_type = raw_event.get("event_type")
            if event_type not in EVENT_TYPES:
                continue
            subject = raw_event.get("subject")
            if not subject or not isinstance(subject, str):
                continue
            details = raw_event.get("details")
            if not isinstance(details, Mapping):
                continue
            details_dict = dict(details)
            if not _validate_details(event_type, details_dict):
                continue
            confidence = raw_event.get("confidence")
            if not isinstance(confidence, (int, float)):
                continue
            confidence = float(confidence)
            if confidence < 0.0 or confidence > 1.0:
                continue
            out.append({
                "event_type": event_type,
                "scene_id": raw_event.get("scene_id") or scene_id,
                "subject": subject,
                "details": details_dict,
                "confidence": confidence,
                "extractor_version": EXTRACTOR_VERSION,
            })
        return out


# --------------------------------------------------------------------------- #
# Module helpers                                                              #
# --------------------------------------------------------------------------- #


_VALID_DETAILS_FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    # (required, allowed-superset-of-required)
    "location_change": (
        frozenset({"from_location", "to_location"}),
        frozenset({"from_location", "to_location"}),
    ),
    "injury_state": (
        frozenset({"severity", "body_part", "mechanism"}),
        frozenset({"severity", "body_part", "mechanism"}),
    ),
    "possession": (
        frozenset({"item", "action"}),
        frozenset({"item", "action", "counterparty"}),
    ),
    "revelation": (
        frozenset({"revelation_id", "recipient"}),
        frozenset({"revelation_id", "recipient"}),
    ),
    "status_change": (
        frozenset({"status_id", "new_value"}),
        frozenset({"status_id", "new_value"}),
    ),
}
_INJURY_SEVERITIES = frozenset({"minor", "moderate", "severe", "mortal"})
_POSSESSION_ACTIONS = frozenset({"acquired", "lost", "transferred"})


def _validate_details(event_type: str, details: Mapping[str, Any]) -> bool:
    spec = _VALID_DETAILS_FIELDS.get(event_type)
    if spec is None:
        return False
    required, allowed = spec
    for key in required:
        value = details.get(key)
        if not isinstance(value, str) or not value:
            return False
    for key in details.keys():
        if key not in allowed:
            return False
    if event_type == "injury_state" and details.get("severity") not in _INJURY_SEVERITIES:
        return False
    if event_type == "possession" and details.get("action") not in _POSSESSION_ACTIONS:
        return False
    return True


def _coerce_events_list(raw: Any) -> list:
    if isinstance(raw, Mapping) and isinstance(raw.get("events"), list):
        return list(raw["events"])
    if isinstance(raw, list):
        return raw
    # Some models return a JSON string inside a dict field.
    if isinstance(raw, Mapping) and isinstance(raw.get("response"), str):
        try:
            parsed = json.loads(raw["response"])
            if isinstance(parsed, Mapping) and isinstance(parsed.get("events"), list):
                return list(parsed["events"])
        except Exception:  # noqa: BLE001
            pass
    return []


def _scene_id_from_card(scene_card: Mapping[str, Any]) -> str:
    ch = int(scene_card.get("chapter_number") or 0)
    sn = int(scene_card.get("scene_number") or 0)
    return f"ch{ch:02d}_sc{sn:02d}"


def _planned_revelations(
    *, concept_seed: Mapping[str, Any], scene_card: Mapping[str, Any],
) -> list[str]:
    """Pull the revelation IDs planned for this scene from concept_seed."""
    ids: list[str] = []
    seen: set[str] = set()
    # Scene card's explicit revelations take priority.
    for rid in scene_card.get("revelations") or []:
        if isinstance(rid, str) and rid not in seen:
            ids.append(rid)
            seen.add(rid)
    # Fall back to the seed's revelation_map so the extractor still has a
    # universe of valid IDs even when the scene card lists none.
    physics = concept_seed.get("story_physics") or {}
    for row in physics.get("revelation_map") or []:
        if isinstance(row, Mapping):
            rid = row.get("info_id") or row.get("revelation_id")
            if isinstance(rid, str) and rid not in seen:
                ids.append(rid)
                seen.add(rid)
    schedule = concept_seed.get("revelation_schedule") or []
    for row in schedule:
        if isinstance(row, Mapping):
            rid = row.get("revelation_id") or row.get("info_id")
            if isinstance(rid, str) and rid not in seen:
                ids.append(rid)
                seen.add(rid)
    return ids


__all__ = [
    "EXTRACTOR_VERSION",
    "ContinuityExtractor",
]
