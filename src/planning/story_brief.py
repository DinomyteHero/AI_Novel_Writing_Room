"""Canonical Story Brief and claim ledger for author-led planning.

The brief is deliberately claim-based instead of a mutable character blob:
every fact is a claim with an origin, confidence, status, and optional source
quote. Character, location, theme, plot, and voice sheets are projections of
the confirmed claims. Inferred or delegated values stay visible and reversible.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

ENTITY_TYPES = (
    "intent",
    "character",
    "location",
    "theme",
    "plot",
    "world",
    "voice",
    "relationship",
)

ORIGINS = ("author", "inferred", "delegated", "import")
CONFIDENCES = ("explicit", "inferred", "uncertain")
STATUSES = ("proposed", "confirmed", "rejected", "superseded")
IMPACTS = ("blocking", "strong", "texture")

_HIGH_IMPACT_FIELDS = frozenset({
    "one_sentence_pitch", "reader_promise", "emotional_core",
    "premise", "want", "need", "lie_believed", "question",
    "pov", "register", "rule", "ending",
})
_TEXTURE_FIELDS = frozenset({
    "name", "age", "appearance", "sensory", "sensory_palette",
    "alias", "epithet", "motif", "color", "sound",
})

DEFAULT_ENTITY_IDS = {
    "intent": "book",
    "plot": "main",
    "theme": "main",
    "voice": "book",
    "world": "world",
}

GLOBAL_REQUIREMENTS: tuple[tuple[str, str, str, str], ...] = (
    ("intent", "one_sentence_pitch", "essential", "What is the book in one sentence?"),
    ("intent", "reader_promise", "essential", "What experience is the reader buying?"),
    ("intent", "emotional_core", "essential", "What should the reader feel at the end that they did not feel at the start?"),
    ("plot", "premise", "essential", "Who wants what, why now, and what stands in the way?"),
    ("plot", "inciting_incident", "recommended", "What breaks the ordinary world and forces the story to start?"),
    ("plot", "midpoint", "recommended", "What reverses the protagonist's approach at the midpoint?"),
    ("plot", "climax", "recommended", "What is the worst decision or confrontation the story is building toward?"),
    ("plot", "resolution", "recommended", "What changes after the climax, and at what cost?"),
    ("theme", "question", "essential", "What question should the reader sit with after the last page?"),
    ("voice", "pov", "essential", "Who tells the story, from where, and in what tense?"),
    ("voice", "register", "recommended", "What should the prose feel like on the page?"),
    ("world", "rule", "recommended", "What rule, cost, or limit does the world impose on the protagonist?"),
)

_CHARACTER_FIELDS = (
    ("role", "essential", "What is {name}'s role in the story?"),
    ("want", "essential", "What does {name} want, concretely?"),
    ("need", "essential", "What does {name} need that they do not know they need?"),
    ("lie_believed", "recommended", "What does {name} believe that is wrong?"),
    ("ghost", "recommended", "What wound or event made that belief necessary?"),
    ("arc_type", "recommended", "What kind of change does {name} undergo?"),
    ("voice", "recommended", "How does {name} sound when they speak or think?"),
)

_LOCATION_FIELDS = (
    ("function", "essential", "What happens in {name} that cannot happen anywhere else?"),
    ("control", "recommended", "Who controls {name}, and what does it cost to enter or leave?"),
    ("sensory", "recommended", "What does {name} look, sound, and smell like?"),
    ("rules", "recommended", "What special rule or danger applies in {name}?"),
)

_THEME_FIELDS = (
    ("question", "essential", "What question does this theme ask?"),
    ("answers", "recommended", "Which characters answer that question differently?"),
    ("motifs", "recommended", "What image or motif carries this theme without stating it?"),
)

_FIELD_PROMPTS = {
    "role": "What is {name}'s role in the story?",
    "want": "What does {name} want, concretely?",
    "need": "What does {name} need that they do not know they need?",
    "lie_believed": "What does {name} believe that is wrong?",
    "ghost": "What wound or event made that belief necessary?",
    "arc_type": "What kind of change does {name} undergo?",
    "voice": "How does {name} sound when they speak or think?",
    "function": "What happens in {name} that cannot happen anywhere else?",
    "control": "Who controls {name}, and what does it cost to enter or leave?",
    "sensory": "What does {name} look, sound, and smell like?",
    "rules": "What special rule or danger applies in {name}?",
    "question": "What question does this theme ask?",
    "answers": "Which characters answer that question differently?",
    "motifs": "What image or motif carries this theme without stating it?",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "unknown"


def new_brief(title: str, franchise: str) -> dict[str, Any]:
    """Create an empty Story Brief."""
    now = _utc_now()
    return {
        "schema_version": "1.0",
        "project": {"title": title, "franchise": franchise},
        "claims": [],
        "questions": [],
        "created_at": now,
        "updated_at": now,
    }


def load_brief(path: str | Path) -> dict[str, Any]:
    import json

    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_brief(path: str | Path, brief: dict[str, Any]) -> None:
    import json

    brief["updated_at"] = _utc_now()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(brief, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def default_impact(entity_type: str, field: str) -> str:
    if field in _HIGH_IMPACT_FIELDS:
        return "blocking"
    if field in _TEXTURE_FIELDS:
        return "texture"
    if entity_type in ("character", "plot", "theme", "voice"):
        return "strong"
    return "strong"


def _claim_key(claim: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(claim.get("entity_type")),
        str(claim.get("entity_id")),
        str(claim.get("field")),
    )


def add_claim(
    brief: dict[str, Any],
    *,
    entity_type: str,
    field: str,
    value: Any,
    entity_id: str | None = None,
    origin: str = "author",
    confidence: str | None = None,
    status: str | None = None,
    source_quote: str = "",
    impact: str | None = None,
) -> dict[str, Any]:
    """Append a claim and supersede older confirmed values for the same field."""
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown entity_type: {entity_type!r}")
    if origin not in ORIGINS:
        raise ValueError(f"unknown origin: {origin!r}")
    if not field:
        raise ValueError("claim field is required")
    if value is None or value == "":
        raise ValueError("claim value is required")

    if entity_id is None:
        entity_id = DEFAULT_ENTITY_IDS.get(entity_type)
    if not entity_id:
        raise ValueError(f"entity_id is required for {entity_type}")
    entity_id = _slug(entity_id)

    if confidence is None:
        confidence = "explicit" if origin in ("author", "import") else "inferred"
    if confidence not in CONFIDENCES:
        raise ValueError(f"unknown confidence: {confidence!r}")
    if status is None:
        status = (
            "confirmed"
            if origin in ("author", "import", "delegated")
            else "proposed"
        )
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    if impact is None:
        impact = default_impact(entity_type, field)
    if impact not in IMPACTS:
        raise ValueError(f"unknown impact: {impact!r}")

    existing = brief.setdefault("claims", [])
    new_claim = {
        "claim_id": f"clm_{len(existing) + 1:04d}",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "field": field,
        "value": value,
        "origin": origin,
        "confidence": confidence,
        "status": status,
        "impact": impact,
        "source_quote": source_quote,
        "created_at": _utc_now(),
    }
    if status == "confirmed":
        for claim in existing:
            if _claim_key(claim) == _claim_key(new_claim) and claim.get("status") == "confirmed":
                claim["status"] = "superseded"
                claim["superseded_by"] = new_claim["claim_id"]
    existing.append(new_claim)
    brief["updated_at"] = _utc_now()
    return new_claim


def get_claim(brief: Mapping[str, Any], claim_id: str) -> dict[str, Any]:
    for claim in brief.get("claims") or []:
        if claim.get("claim_id") == claim_id:
            return claim
    raise KeyError(f"unknown claim_id: {claim_id}")


def _supersede_other_confirmed(brief: dict[str, Any], claim: dict[str, Any]) -> None:
    for other in brief.get("claims") or []:
        if other is claim:
            continue
        if (
            _claim_key(other) == _claim_key(claim)
            and other.get("status") == "confirmed"
        ):
            other["status"] = "superseded"
            other["superseded_by"] = claim["claim_id"]


def confirm_claim(brief: dict[str, Any], claim_id: str) -> dict[str, Any]:
    claim = get_claim(brief, claim_id)
    if claim.get("status") == "rejected":
        raise ValueError("cannot confirm a rejected claim")
    claim["status"] = "confirmed"
    claim["confidence"] = "explicit"
    _supersede_other_confirmed(brief, claim)
    brief["updated_at"] = _utc_now()
    return claim


def reject_claim(brief: dict[str, Any], claim_id: str) -> dict[str, Any]:
    claim = get_claim(brief, claim_id)
    claim["status"] = "rejected"
    brief["updated_at"] = _utc_now()
    return claim


def delegate_claim(
    brief: dict[str, Any],
    claim_id: str,
    *,
    rationale: str = "",
) -> dict[str, Any]:
    claim = get_claim(brief, claim_id)
    claim["origin"] = "delegated"
    claim["status"] = "confirmed"
    claim["confidence"] = "inferred"
    claim["delegated_rationale"] = rationale
    _supersede_other_confirmed(brief, claim)
    brief["updated_at"] = _utc_now()
    return claim


def add_question(
    brief: dict[str, Any],
    *,
    entity_type: str,
    field: str,
    question: str,
    entity_id: str | None = None,
    why_it_matters: str = "",
    blocking: bool = False,
) -> dict[str, Any]:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown entity_type: {entity_type!r}")
    entity_id = _slug(entity_id or DEFAULT_ENTITY_IDS.get(entity_type, "book"))
    questions = brief.setdefault("questions", [])
    item = {
        "question_id": f"q_{len(questions) + 1:04d}",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "field": field,
        "question": question,
        "why_it_matters": why_it_matters,
        "blocking": bool(blocking),
        "status": "open",
        "created_at": _utc_now(),
    }
    questions.append(item)
    brief["updated_at"] = _utc_now()
    return item


def resolve_claim(
    brief: Mapping[str, Any],
    entity_type: str,
    entity_id: str,
    field: str,
) -> dict[str, Any] | None:
    entity_id = _slug(entity_id)
    found = [
        claim for claim in (brief.get("claims") or [])
        if claim.get("entity_type") == entity_type
        and claim.get("entity_id") == entity_id
        and claim.get("field") == field
        and claim.get("status") == "confirmed"
    ]
    return found[-1] if found else None


def resolve_value(
    brief: Mapping[str, Any],
    entity_type: str,
    entity_id: str,
    field: str,
    default: Any = None,
) -> Any:
    claim = resolve_claim(brief, entity_type, entity_id, field)
    return claim.get("value") if claim else default


def entity_values(
    brief: Mapping[str, Any],
    entity_type: str,
    entity_id: str,
    *,
    include_proposed: bool = False,
) -> dict[str, Any]:
    allowed = {"confirmed"} | ({"proposed"} if include_proposed else set())
    entity_id = _slug(entity_id)
    values: dict[str, Any] = {}
    for claim in brief.get("claims") or []:
        if (
            claim.get("entity_type") == entity_type
            and claim.get("entity_id") == entity_id
            and claim.get("status") in allowed
        ):
            values[str(claim.get("field"))] = claim.get("value")
    values.setdefault("id", entity_id)
    return values


def entity_ids(brief: Mapping[str, Any], entity_type: str) -> list[str]:
    return sorted({
        str(claim.get("entity_id"))
        for claim in (brief.get("claims") or [])
        if claim.get("entity_type") == entity_type
        and claim.get("status") in ("confirmed", "proposed")
    })


def entity_name(
    brief: Mapping[str, Any],
    entity_type: str,
    entity_id: str,
) -> str:
    return str(
        resolve_value(brief, entity_type, entity_id, "name")
        or entity_id.replace("_", " ").title()
    )


def _gap(
    *,
    entity_type: str,
    entity_id: str,
    field: str,
    importance: str,
    prompt: str,
    action: str,
) -> dict[str, Any]:
    return {
        "gap_id": f"{entity_type}:{entity_id}:{field}",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "field": field,
        "importance": importance,
        "prompt": prompt,
        "action": action,
        "impact": "blocking" if importance == "essential" else "strong",
    }


def _has_value(brief: Mapping[str, Any], entity_type: str, entity_id: str, field: str) -> bool:
    return resolve_claim(brief, entity_type, entity_id, field) is not None


def gap_action(importance: str, entity_type: str, field: str) -> str:
    """Return ask/propose/scaffold/defer for a gap."""
    if importance == "essential" and entity_type in ("character", "theme", "plot"):
        return "ask"
    if importance == "essential":
        return "propose"
    if field in _TEXTURE_FIELDS:
        return "scaffold"
    if importance == "recommended":
        return "propose"
    return "defer"


def detect_gaps(brief: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return missing values that still change the book, sorted by leverage."""
    gaps: list[dict[str, Any]] = []
    for entity_type, field, importance, prompt in GLOBAL_REQUIREMENTS:
        entity_id = DEFAULT_ENTITY_IDS.get(entity_type, entity_type)
        if not _has_value(brief, entity_type, entity_id, field):
            gaps.append(_gap(
                entity_type=entity_type,
                entity_id=entity_id,
                field=field,
                importance=importance,
                prompt=prompt,
                action=gap_action(importance, entity_type, field),
            ))

    character_ids = entity_ids(brief, "character")
    if not character_ids:
        gaps.append(_gap(
            entity_type="character",
            entity_id="protagonist",
            field="name",
            importance="essential",
            prompt="Who is the protagonist, and what do they want?",
            action="ask",
        ))
    for char_id in character_ids:
        name = entity_name(brief, "character", char_id)
        tier = str(resolve_value(brief, "character", char_id, "tier", "principal"))
        required = _CHARACTER_FIELDS
        if tier == "supporting":
            required = tuple(item for item in required if item[0] in ("role", "want", "voice"))
        for field, importance, prompt in required:
            if _has_value(brief, "character", char_id, field):
                continue
            gaps.append(_gap(
                entity_type="character",
                entity_id=char_id,
                field=field,
                importance=importance,
                prompt=prompt.format(name=name),
                action=gap_action(importance, "character", field),
            ))

    location_ids = entity_ids(brief, "location")
    if not location_ids:
        gaps.append(_gap(
            entity_type="location",
            entity_id="primary",
            field="function",
            importance="recommended",
            prompt="What is one place where the story's pressure becomes physical?",
            action="propose",
        ))
    for loc_id in location_ids:
        name = entity_name(brief, "location", loc_id)
        for field, importance, prompt in _LOCATION_FIELDS:
            if not _has_value(brief, "location", loc_id, field):
                gaps.append(_gap(
                    entity_type="location",
                    entity_id=loc_id,
                    field=field,
                    importance=importance,
                    prompt=prompt.format(name=name),
                    action=gap_action(importance, "location", field),
                ))

    for theme_id in entity_ids(brief, "theme"):
        for field, importance, prompt in _THEME_FIELDS:
            if not _has_value(brief, "theme", theme_id, field):
                gaps.append(_gap(
                    entity_type="theme",
                    entity_id=theme_id,
                    field=field,
                    importance=importance,
                    prompt=prompt.format(name=entity_name(brief, "theme", theme_id)),
                    action=gap_action(importance, "theme", field),
                ))

    for question in brief.get("questions") or []:
        if question.get("status") == "open":
            gaps.append({
                "gap_id": f"question:{question.get('question_id')}",
                "entity_type": question.get("entity_type"),
                "entity_id": question.get("entity_id"),
                "field": question.get("field"),
                "importance": "essential" if question.get("blocking") else "recommended",
                "prompt": question.get("question", ""),
                "action": "ask",
                "impact": "blocking" if question.get("blocking") else "strong",
                "question_id": question.get("question_id"),
            })

    deduped: dict[str, dict[str, Any]] = {}
    for gap in gaps:
        deduped.setdefault(gap["gap_id"], gap)
    ordered = sorted(
        deduped.values(),
        key=lambda g: (0 if g["importance"] == "essential" else 1, g["gap_id"]),
    )
    return ordered


def coverage(brief: Mapping[str, Any]) -> dict[str, Any]:
    gaps = detect_gaps(brief)
    confirmed = [c for c in brief.get("claims") or [] if c.get("status") == "confirmed"]
    proposed = [c for c in brief.get("claims") or [] if c.get("status") == "proposed"]
    essential = [g for g in gaps if g["importance"] == "essential"]
    recommended = [g for g in gaps if g["importance"] == "recommended"]
    return {
        "claims_confirmed": len(confirmed),
        "claims_proposed": len(proposed),
        "entities": {
            entity_type: len(entity_ids(brief, entity_type))
            for entity_type in ("character", "location", "theme")
        },
        "gaps_essential": len(essential),
        "gaps_recommended": len(recommended),
        "open_blocking_questions": sum(
            1 for q in brief.get("questions") or []
            if q.get("status") == "open" and q.get("blocking")
        ),
        "ready_for_sheets": not essential,
        "ready_for_expand": not essential,
        "next_gaps": gaps[:5],
    }


def next_questions(brief: Mapping[str, Any], n: int = 3) -> list[dict[str, Any]]:
    return detect_gaps(brief)[:n]


def confirmed_claims(
    brief: Mapping[str, Any],
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        c for c in brief.get("claims") or []
        if c.get("status") == "confirmed"
        and (entity_type is None or c.get("entity_type") == entity_type)
        and (entity_id is None or c.get("entity_id") == _slug(entity_id))
    ]


def proposed_claims(
    brief: Mapping[str, Any],
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        c for c in brief.get("claims") or []
        if c.get("status") == "proposed"
        and (entity_type is None or c.get("entity_type") == entity_type)
        and (entity_id is None or c.get("entity_id") == _slug(entity_id))
    ]


# ---------------------------------------------------------------------------
# Reviewable sheets
# ---------------------------------------------------------------------------


def _frontmatter(meta: Mapping[str, Any]) -> str:
    return "---\n" + yaml.safe_dump(dict(meta), sort_keys=False).strip() + "\n---\n"


def _section(title: str, value: Any) -> str:
    if value is None or value == "" or value == []:
        return ""
    if isinstance(value, list):
        body = "\n".join(f"- {item}" for item in value)
    elif isinstance(value, dict):
        body = "\n".join(f"- **{k}**: {v}" for k, v in value.items())
    else:
        body = str(value)
    return f"\n## {title}\n{body}\n"


def _review_block(brief: Mapping[str, Any], entity_type: str, entity_id: str) -> str:
    proposed = proposed_claims(brief, entity_type, entity_id)
    sourced = [
        c for c in confirmed_claims(brief, entity_type, entity_id)
        if c.get("source_quote")
    ]
    gaps = [
        g for g in detect_gaps(brief)
        if g.get("entity_type") == entity_type and g.get("entity_id") == entity_id
    ]
    out = ""
    if proposed:
        out += "\n## Assumptions To Review\n"
        out += "\n".join(
            f"- `{c['claim_id']}` **{c['field']}**: {c['value']} "
            f"(origin={c['origin']}, confidence={c['confidence']})"
            for c in proposed
        ) + "\n"
    if sourced:
        out += "\n## Provenance\n"
        out += "\n".join(
            f"- **{c['field']}**: “{c['source_quote']}” "
            f"({c['origin']}, `{c['claim_id']}`)"
            for c in sourced
        ) + "\n"
    if gaps:
        out += "\n## Open Gaps\n"
        out += "\n".join(f"- **{g['field']}** ({g['action']}): {g['prompt']}" for g in gaps) + "\n"
    return out


def render_character_sheet(brief: Mapping[str, Any], entity_id: str) -> str:
    entity_id = _slug(entity_id)
    values = entity_values(brief, "character", entity_id)
    name = entity_name(brief, "character", entity_id)
    has_proposed = bool(proposed_claims(brief, "character", entity_id))
    gaps = [
        g for g in detect_gaps(brief)
        if g.get("entity_type") == "character" and g.get("entity_id") == entity_id
    ]
    status = "draft" if has_proposed or gaps else "approved"
    meta = {
        "id": entity_id,
        "name": name,
        "type": "character",
        "tier": values.get("tier", "principal"),
        "status": status,
        "claim_ids": [c["claim_id"] for c in confirmed_claims(brief, "character", entity_id)],
    }
    parts = [
        _frontmatter(meta),
        f"# {name}\n",
        _section("Role", values.get("role")),
        _section("Want", values.get("want")),
        _section("Need", values.get("need")),
        _section("Lie Believed", values.get("lie_believed")),
        _section("Ghost", values.get("ghost")),
        _section("Arc", values.get("arc_type")),
        _section("Voice", values.get("voice")),
        _section("Relationships", values.get("relationships")),
        _review_block(brief, "character", entity_id),
    ]
    return "".join(part for part in parts if part)


def render_location_sheet(brief: Mapping[str, Any], entity_id: str) -> str:
    entity_id = _slug(entity_id)
    values = entity_values(brief, "location", entity_id)
    name = entity_name(brief, "location", entity_id)
    gaps = [
        g for g in detect_gaps(brief)
        if g.get("entity_type") == "location" and g.get("entity_id") == entity_id
    ]
    status = "draft" if proposed_claims(brief, "location", entity_id) or gaps else "approved"
    meta = {
        "id": entity_id,
        "name": name,
        "type": "location",
        "tier": values.get("tier", "primary"),
        "status": status,
    }
    return "".join([
        _frontmatter(meta),
        f"# {name}\n",
        _section("Story Function", values.get("function")),
        _section("Control And Access", values.get("control")),
        _section("Sensory Palette", values.get("sensory")),
        _section("Rules And Dangers", values.get("rules")),
        _review_block(brief, "location", entity_id),
    ])


def render_theme_sheet(brief: Mapping[str, Any], entity_id: str = "main") -> str:
    entity_id = _slug(entity_id)
    values = entity_values(brief, "theme", entity_id)
    name = entity_name(brief, "theme", entity_id)
    gaps = [
        g for g in detect_gaps(brief)
        if g.get("entity_type") == "theme" and g.get("entity_id") == entity_id
    ]
    meta = {
        "id": entity_id,
        "name": name,
        "type": "theme",
        "status": "draft" if proposed_claims(brief, "theme", entity_id) or gaps else "approved",
    }
    return "".join([
        _frontmatter(meta),
        f"# {name}\n",
        _section("Question", values.get("question")),
        _section("Competing Answers", values.get("answers")),
        _section("Motifs", values.get("motifs")),
        _review_block(brief, "theme", entity_id),
    ])


def render_plot_sheet(brief: Mapping[str, Any]) -> str:
    values = entity_values(brief, "plot", "main")
    gaps = [
        g for g in detect_gaps(brief)
        if g.get("entity_type") == "plot" and g.get("entity_id") == "main"
    ]
    meta = {
        "id": "main",
        "type": "plot",
        "status": "draft" if proposed_claims(brief, "plot", "main") or gaps else "approved",
    }
    return "".join([
        _frontmatter(meta),
        "# Plot Spine\n",
        _section("Premise", values.get("premise")),
        _section("Inciting Incident", values.get("inciting_incident")),
        _section("Midpoint", values.get("midpoint")),
        _section("Crisis", values.get("crisis")),
        _section("Climax", values.get("climax")),
        _section("Resolution", values.get("resolution")),
        _section("Promises", values.get("promises")),
        _review_block(brief, "plot", "main"),
    ])


def render_world_sheet(brief: Mapping[str, Any]) -> str:
    values = entity_values(brief, "world", "world")
    gaps = [
        g for g in detect_gaps(brief)
        if g.get("entity_type") == "world" and g.get("entity_id") == "world"
    ]
    meta = {
        "id": "world",
        "type": "world",
        "status": "draft" if proposed_claims(brief, "world", "world") or gaps else "approved",
    }
    return "".join([
        _frontmatter(meta),
        "# World And Canon\n",
        _section("Central Rule", values.get("rule")),
        _section("Cost Or Limit", values.get("cost")),
        _section("Factions", values.get("factions")),
        _section("History", values.get("history")),
        _section("Terminology", values.get("terminology")),
        _review_block(brief, "world", "world"),
    ])


def render_review_index(brief: Mapping[str, Any]) -> str:
    cov = coverage(brief)
    gaps = detect_gaps(brief)
    proposed = proposed_claims(brief)
    meta = {
        "type": "review",
        "status": "approved" if cov["ready_for_expand"] else "draft",
        "ready_for_expand": cov["ready_for_expand"],
    }
    out = [
        _frontmatter(meta),
        "# Story Brief Review\n",
        f"- Confirmed claims: {cov['claims_confirmed']}\n",
        f"- Proposed claims: {cov['claims_proposed']}\n",
        f"- Essential gaps: {cov['gaps_essential']}\n",
        f"- Recommended gaps: {cov['gaps_recommended']}\n",
        f"- Open blocking questions: {cov['open_blocking_questions']}\n",
    ]
    if proposed:
        out.append("\n## Proposed Claims\n")
        out.append("\n".join(
            f"- `{c['claim_id']}` **{c['entity_type']}/{c['entity_id']}.{c['field']}**: "
            f"{c['value']} (origin={c['origin']})"
            for c in proposed
        ) + "\n")
    if gaps:
        out.append("\n## Open Gaps\n")
        out.append("\n".join(
            f"- `{g['gap_id']}` ({g['importance']}, {g['action']}): {g['prompt']}"
            for g in gaps
        ) + "\n")
    return "".join(out)


def write_sheets(
    brief: Mapping[str, Any],
    root: str | Path,
) -> list[Path]:
    """Write reviewable Markdown projections under ``root``."""
    out_root = Path(root)
    written: list[Path] = []

    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)

    for char_id in entity_ids(brief, "character"):
        write(out_root / "characters" / f"{char_id}.md", render_character_sheet(brief, char_id))
    for loc_id in entity_ids(brief, "location"):
        write(out_root / "locations" / f"{loc_id}.md", render_location_sheet(brief, loc_id))
    for theme_id in entity_ids(brief, "theme"):
        write(out_root / "themes" / f"{theme_id}.md", render_theme_sheet(brief, theme_id))
    write(out_root / "plot.md", render_plot_sheet(brief))
    write(out_root / "world.md", render_world_sheet(brief))
    write(out_root / "review.md", render_review_index(brief))
    return written


__all__ = [
    "ENTITY_TYPES",
    "ORIGINS",
    "CONFIDENCES",
    "STATUSES",
    "IMPACTS",
    "new_brief",
    "load_brief",
    "save_brief",
    "add_claim",
    "confirm_claim",
    "reject_claim",
    "delegate_claim",
    "add_question",
    "resolve_claim",
    "resolve_value",
    "entity_values",
    "entity_ids",
    "entity_name",
    "detect_gaps",
    "coverage",
    "next_questions",
    "confirmed_claims",
    "proposed_claims",
    "render_character_sheet",
    "render_location_sheet",
    "render_theme_sheet",
    "render_plot_sheet",
    "render_world_sheet",
    "render_review_index",
    "write_sheets",
]
