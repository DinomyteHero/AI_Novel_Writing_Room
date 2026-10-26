"""Turn free-form author chat into proposed Story Brief claims.

Extraction is intentionally proposal-only: the extractor never writes to the
brief and never confirms a claim. The caller persists returned claims as
``origin=inferred`` / ``status=proposed`` so the author can review them.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

_ALLOWED_ENTITY_TYPES = {
    "intent", "character", "location", "theme", "plot", "world", "voice",
    "relationship",
}
_ALLOWED_CONFIDENCE = {"explicit", "inferred", "uncertain"}


def _brief_digest(brief: Mapping[str, Any], limit: int = 4000) -> str:
    claims = [
        {
            "entity_type": c.get("entity_type"),
            "entity_id": c.get("entity_id"),
            "field": c.get("field"),
            "value": c.get("value"),
            "status": c.get("status"),
        }
        for c in (brief.get("claims") or [])
        if c.get("status") in ("confirmed", "proposed")
    ]
    return json.dumps(
        {
            "title": (brief.get("project") or {}).get("title"),
            "claims": claims,
            "open_questions": [
                q.get("question") for q in (brief.get("questions") or [])
                if q.get("status") == "open"
            ],
        },
        ensure_ascii=False,
    )[:limit]


async def extract_claims(
    router: Any,
    turn_text: str,
    brief: Mapping[str, Any],
    *,
    max_claims: int = 8,
) -> list[dict[str, Any]]:
    """Return candidate claims from one author turn, or [] on model failure."""
    if not turn_text.strip():
        return []
    prompt = (
        "Extract planning claims from this author turn. Return JSON only:\n"
        '{"claims": [{"entity_type": "...", "entity_id": "...", '
        '"field": "...", "value": "...", "confidence": "explicit|inferred|uncertain", '
        '"source_quote": "..."}]}\n\n'
        f"Current brief: {_brief_digest(brief)}\n\n"
        f"Author turn:\n{turn_text}\n\n"
        "Rules: only extract what the author actually said or clearly implied. "
        "Do not invent proper nouns or plot facts. Use entity_type one of: "
        "intent, character, location, theme, plot, world, voice, relationship. "
        "Use stable snake_case entity_id values (for example mara_vance). "
        "For intent/voice use entity_id 'book'; for plot/theme use 'main'; "
        "for world use 'world'. If the author rejects an idea, phrase the "
        "claim as the positive constraint they chose. Return at most "
        f"{max_claims} claims."
    )
    try:
        result = await router.complete_structured(
            "story_brief_extractor",
            [
                {
                    "role": "system",
                    "content": (
                        "You extract candidate planning claims. The author "
                        "decides; never mark a claim confirmed."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
    except Exception:
        return []
    if not isinstance(result, dict):
        return []
    raw_claims = result.get("claims")
    if not isinstance(raw_claims, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in raw_claims[:max_claims]:
        if not isinstance(item, dict):
            continue
        entity_type = str(item.get("entity_type") or "")
        field = str(item.get("field") or "").strip()
        value = item.get("value")
        if entity_type not in _ALLOWED_ENTITY_TYPES or not field:
            continue
        if value is None or value == "":
            continue
        confidence = str(item.get("confidence") or "inferred")
        if confidence not in _ALLOWED_CONFIDENCE:
            confidence = "inferred"
        cleaned.append({
            "entity_type": entity_type,
            "entity_id": item.get("entity_id"),
            "field": field,
            "value": value,
            "confidence": confidence,
            "source_quote": str(item.get("source_quote") or ""),
        })
    return cleaned


__all__ = ["extract_claims"]
