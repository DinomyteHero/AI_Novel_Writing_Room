"""Final-copy helpers for contract-clean prose.

This module owns the deterministic half of the final literary copy pipeline:
continuity lockfiles, motif ledgers, copy-desk checks, read-aloud voltage, and
post-polish validation. The LLM-facing literary polish agent consumes these
artifacts, but the artifacts themselves stay cheap and inspectable.
"""

from __future__ import annotations

import re
import json
from collections import Counter
from typing import Any, Iterable, Mapping

from src.quality.repetition_detector import RepetitionDetector
from src.quality.scene_contract_validator import (
    extract_dialogue,
    validate_prose_contract,
)


DEFAULT_MOTIF_TERMS = (
    "wrongness",
    "pressure",
    "silence",
    "cold",
    "flat",
    "note",
    "chest",
    "weight",
    "wound",
    "seal",
)

_TIMELINE_RE = re.compile(
    r"\b(?:day|days|week|weeks|month|months|year|years|"
    r"twenty-three|aboard|head start|until)\b",
    re.IGNORECASE,
)
_WITHHOLDING_RE = re.compile(
    r"\b(?:withhold|withholding|does not mention|did not mention|"
    r"do not reveal|hold back|unnamed|deferred|not yet|without naming)\b",
    re.IGNORECASE,
)
_SUMMARY_LEAK_PATTERNS = (
    (r"\b[A-Z][a-z]+\s+(?:supplied|named|framed|registered)\b", 0),
    (
        r"\b(?:scene card|anti-pattern|turning point detail|beat description)\b",
        re.IGNORECASE,
    ),
    (
        r"\b(?:the scene|this scene)\s+(?:establishes|shows|reveals|pivots)\b",
        re.IGNORECASE,
    ),
)
_FILLER_PATTERNS = (
    "in that moment",
    "for a long moment",
    "without hesitation",
    "despite everything",
    "something shifted",
    "with a sense of",
    "it was as if",
    "there was something about",
    "couldn't help but",
    "found himself",
    "found herself",
    "braced for what came next",
)


def scene_label(scene_card: Mapping[str, Any]) -> str:
    """Return a stable chNN_scMM label for a scene card."""

    chapter = int(scene_card.get("chapter_number", 0) or 0)
    scene = int(scene_card.get("scene_number", 1) or 1)
    return f"ch{chapter:02d}_sc{scene:02d}"


def build_continuity_lockfile(
    *,
    scene_card: Mapping[str, Any],
    generation_brief: Mapping[str, Any] | None = None,
    scene_contract: Mapping[str, Any] | None = None,
    contract_validation: Mapping[str, Any] | None = None,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Build a compact fact lockfile for final literary polish.

    The lockfile intentionally favors provenance over clever extraction. It
    gathers the high-risk facts and prohibitions already present in planning
    artifacts, then presents them as a JSON contract the polish pass must not
    alter.
    """

    generation_brief = generation_brief or {}
    scene_contract = scene_contract or {}
    label = (
        scene_contract.get("scene_id")
        or scene_card.get("scene_id")
        or scene_label(scene_card)
    )

    locked_facts = _compact_truths(
        (
            ("mission", scene_card.get("mission")),
            ("why_now", scene_card.get("why_now")),
            ("conflict", scene_card.get("conflict")),
            ("turning_point", scene_card.get("turning_point")),
            ("opening_hook", scene_card.get("opening_hook")),
            ("closing_hook", scene_card.get("closing_hook")),
            ("brief_objective", generation_brief.get("scene_objective")),
            ("brief_closing_beat", generation_brief.get("closing_beat")),
        )
    )

    turning_point_detail = scene_card.get("turning_point_detail")
    if isinstance(turning_point_detail, Mapping):
        locked_facts.extend(_compact_truths(
            (
                ("turning_point_trigger", turning_point_detail.get("trigger")),
                ("turning_point_shift", turning_point_detail.get("shift")),
                ("turning_point_cost", turning_point_detail.get("cost")),
            )
        ))

    contract_checks = [
        {
            "id": check.get("id"),
            "type": check.get("type"),
            "severity": check.get("severity", "error"),
        }
        for check in scene_contract.get("checks", []) or []
        if isinstance(check, Mapping)
    ]

    return {
        "schema_version": 1,
        "scene_id": label,
        "source_label": source_label,
        "pov_character": scene_card.get("pov_character"),
        "characters_present": list(scene_card.get("characters_present", []) or []),
        "locked_facts": locked_facts,
        "timeline_claims": _collect_matching_strings(
            [scene_card, generation_brief],
            _TIMELINE_RE,
            limit=12,
        ),
        "withheld_information": _collect_matching_strings(
            [scene_card, generation_brief],
            _WITHHOLDING_RE,
            limit=12,
        ),
        "speaker_ownership": _speaker_ownership(scene_card, scene_contract),
        "forbidden_drift": _forbidden_drift(scene_card, generation_brief, scene_contract),
        "contract_status": {
            "loaded": bool(scene_contract),
            "passed": None if contract_validation is None else bool(
                contract_validation.get("passed")
            ),
            "hard_failure_count": (
                None
                if contract_validation is None
                else int(contract_validation.get("hard_failure_count", 0))
            ),
            "failure_count": (
                None
                if contract_validation is None
                else int(contract_validation.get("failure_count", 0))
            ),
            "checks": contract_checks,
        },
    }


def build_motif_ledger(
    prose: str,
    *,
    motif_terms: Iterable[str] | None = None,
    character_names: list[str] | None = None,
) -> dict[str, Any]:
    """Count motif terms and repeated phrases for final-copy awareness."""

    terms = [t.lower() for t in (motif_terms or DEFAULT_MOTIF_TERMS)]
    paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
    word_count = len(prose.split())
    motifs = []
    for term in terms:
        pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        para_hits = [
            idx for idx, para in enumerate(paragraphs) if pattern.search(para)
        ]
        count = len(pattern.findall(prose))
        if count == 0:
            continue
        density = (count / max(word_count, 1)) * 1000
        motifs.append({
            "term": term,
            "count": count,
            "paragraph_indices": para_hits,
            "density_per_1k": round(density, 2),
            "over_budget": count > max(3, word_count // 450),
        })

    repetition = RepetitionDetector().analyze(
        prose,
        character_names=character_names,
    )
    return {
        "word_count": word_count,
        "motifs": motifs,
        "repetition": {
            "score": repetition.get("repetition_score"),
            "flagged_words": repetition.get("flagged_words", [])[:12],
            "repeated_ngrams": repetition.get("repeated_ngrams", [])[:12],
            "opener_violations": repetition.get("opener_violations", [])[:8],
        },
    }


def run_copydesk_checks(
    prose: str,
    *,
    source_word_count: int | None = None,
    target_word_count: int | None = None,
    scene_card: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run deterministic final-copy lint checks.

    These checks are advisory except for obvious damaged-output cases. They
    tell the copy desk what to inspect after the literary polish pass.
    """

    words = prose.split()
    word_count = len(words)
    sentences = _split_sentences(prose)
    paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
    flags: list[dict[str, Any]] = []

    source_ratio = None
    if source_word_count:
        source_ratio = word_count / max(source_word_count, 1)
        if source_ratio < 0.8:
            flags.append(_flag(
                "error",
                "compression",
                f"Final copy is {source_ratio:.0%} of source length.",
            ))
        elif source_ratio > 1.25 and not _within_target_band(
            word_count,
            target_word_count,
        ):
            flags.append(_flag(
                "warn",
                "expansion",
                f"Final copy is {source_ratio:.0%} of source length.",
            ))

    em_dash_count = prose.count("\u2014")
    if word_count and em_dash_count / word_count > 0.012:
        flags.append(_flag(
            "warn",
            "em_dash_density",
            f"{em_dash_count} em dashes across {word_count} words.",
        ))

    for pattern, regex_flags in _SUMMARY_LEAK_PATTERNS:
        for match in re.finditer(pattern, prose, flags=regex_flags):
            flags.append(_flag(
                "warn",
                "planning_language_leak",
                f"Planning-language pattern matched: {match.group(0)}",
                line=_line_for_offset(prose, match.start()),
            ))

    lower = prose.lower()
    for phrase in _FILLER_PATTERNS:
        pos = lower.find(phrase)
        if pos != -1:
            flags.append(_flag(
                "warn",
                "filler_phrase",
                f"Filler phrase present: {phrase}",
                line=_line_for_offset(prose, pos),
            ))

    if _ben_close_third_lukes_order_leak(prose, scene_card):
        flags.append(_flag(
            "warn",
            "ben_close_third_lukes_order",
            "Ben close-third narration uses Luke's Order; prefer his father's Order, his Order, or the Jedi Order.",
        ))

    long_sentences = [
        {"index": idx, "word_count": len(sentence.split())}
        for idx, sentence in enumerate(sentences)
        if len(sentence.split()) > 45
    ]
    if long_sentences:
        flags.append(_flag(
            "info",
            "long_sentence_cluster",
            f"{len(long_sentences)} sentence(s) exceed 45 words.",
            samples=long_sentences[:5],
        ))

    long_paragraphs = [
        {"index": idx, "word_count": len(paragraph.split())}
        for idx, paragraph in enumerate(paragraphs)
        if len(paragraph.split()) > 180
    ]
    if long_paragraphs:
        flags.append(_flag(
            "warn",
            "long_paragraph",
            f"{len(long_paragraphs)} paragraph(s) exceed 180 words.",
            samples=long_paragraphs[:5],
        ))

    opener_counts = Counter(
        " ".join(sentence.lower().split()[:3])
        for sentence in sentences
        if sentence.split()
    )
    repeated_openers = [
        {"opener": opener, "count": count}
        for opener, count in opener_counts.most_common()
        if count >= 3 and opener
    ]
    if repeated_openers:
        flags.append(_flag(
            "info",
            "repeated_sentence_openers",
            "Some sentence openings repeat three or more times.",
            samples=repeated_openers[:8],
        ))

    hard_flags = [f for f in flags if f["severity"] == "error"]
    return {
        "word_count": word_count,
        "source_word_count": source_word_count,
        "target_word_count": target_word_count,
        "source_ratio": None if source_ratio is None else round(source_ratio, 3),
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "em_dash_count": em_dash_count,
        "flags": flags,
        "needs_attention": bool(flags),
        "passed": not hard_flags,
    }


def score_read_aloud_voltage(
    prose: str,
    *,
    scene_card: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score scene-level read-aloud pressure using cheap heuristics."""

    scene_card = scene_card or {}
    sentences = _split_sentences(prose)
    paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
    dialogue = extract_dialogue(prose, _speaker_aliases(scene_card))
    speaker_count = len({line.speaker for line in dialogue if line.speaker})
    sentence_lengths = [len(s.split()) for s in sentences if s.split()]
    final_sentence = sentences[-1].strip() if sentences else ""

    opening_score = _opening_pull_score(paragraphs[0] if paragraphs else "")
    rhythm_score = _rhythm_score(sentence_lengths)
    dialogue_score = 5 if speaker_count >= 2 else 3 if dialogue else 2
    emotional_score = _emotional_turn_score(prose, scene_card)
    final_score = _final_line_score(final_sentence)
    total = opening_score + rhythm_score + dialogue_score + emotional_score + final_score

    return {
        "total_score": total,
        "max_score": 25,
        "ratings": {
            "opening_pull": opening_score,
            "paragraph_music": rhythm_score,
            "dialogue_separability": dialogue_score,
            "emotional_turn": emotional_score,
            "final_line_charge": final_score,
        },
        "signals": {
            "dialogue_line_count": len(dialogue),
            "speaker_count": speaker_count,
            "sentence_count": len(sentences),
            "paragraph_count": len(paragraphs),
            "final_sentence": final_sentence,
        },
        "needs_human_read_aloud": total < 18,
    }


def validate_final_copy(
    prose: str,
    *,
    scene_contract: Mapping[str, Any] | None = None,
    source_word_count: int | None = None,
    scene_card: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run post-polish validation and final-copy diagnostics."""

    contract_validation = None
    if scene_contract:
        contract_validation = validate_prose_contract(prose, scene_contract)
    copydesk = run_copydesk_checks(
        prose,
        source_word_count=source_word_count,
        target_word_count=(
            int(scene_card.get("target_word_count"))
            if scene_card and scene_card.get("target_word_count")
            else None
        ),
        scene_card=scene_card,
    )
    voltage = score_read_aloud_voltage(prose, scene_card=scene_card)
    hard_contract_passed = (
        True if contract_validation is None else bool(contract_validation.get("passed"))
    )
    return {
        "passed": hard_contract_passed and bool(copydesk.get("passed")),
        "scene_contract_validation": contract_validation,
        "copydesk": copydesk,
        "read_aloud_voltage": voltage,
    }


def _speaker_ownership(
    scene_card: Mapping[str, Any],
    scene_contract: Mapping[str, Any],
) -> dict[str, Any]:
    voice = scene_card.get("scene_voice_permissions") or {}
    speaker_checks = [
        {
            "id": check.get("id"),
            "type": check.get("type"),
            "speaker": check.get("speaker"),
            "speakers": check.get("speakers"),
        }
        for check in scene_contract.get("checks", []) or []
        if isinstance(check, Mapping)
        and check.get("type") in {"speaker_required", "speaker_forbidden"}
    ]
    return {
        "pov_character": scene_card.get("pov_character"),
        "characters_present": list(scene_card.get("characters_present", []) or []),
        "voice_guidance": scene_card.get("voice_guidance")
        or scene_card.get("dialogue_guidance"),
        "scene_voice_permissions": voice,
        "contract_speaker_checks": speaker_checks,
    }


def _forbidden_drift(
    scene_card: Mapping[str, Any],
    generation_brief: Mapping[str, Any],
    scene_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        key = str(item.get("text") or jsonish_key(item))
        if key in seen:
            return
        seen.add(key)
        items.append(item)

    for key in ("anti_patterns", "forbidden_moves", "do_not_include"):
        for value in _as_list(scene_card.get(key)) + _as_list(generation_brief.get(key)):
            add({"source": key, "text": _squash(str(value), limit=420)})
    for check in scene_contract.get("checks", []) or []:
        if not isinstance(check, Mapping):
            continue
        if check.get("type") in {"global_forbidden", "speaker_forbidden"}:
            add({
                "source": "scene_contract",
                "check_id": check.get("id"),
                "type": check.get("type"),
                "severity": check.get("severity", "error"),
            })
    return items[:35]


def _collect_matching_strings(
    roots: Iterable[Any],
    pattern: re.Pattern[str],
    *,
    limit: int,
) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for root in roots:
        for path, value in _walk_strings(root):
            if pattern.search(value):
                hits.append({"path": path, "text": _squash(value)})
                if len(hits) >= limit:
                    return hits
    return hits


def _walk_strings(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, child in value.items():
            yield from _walk_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _walk_strings(child, f"{path}[{idx}]")


def _compact_truths(items: Iterable[tuple[str, Any]]) -> list[dict[str, str]]:
    truths = []
    for key, value in items:
        if isinstance(value, str) and value.strip():
            text = _squash(value)
            if not _looks_like_planning_language(text):
                truths.append({"id": key, "text": text})
    return truths


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def jsonish_key(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _squash(value: str, *, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _looks_like_planning_language(text: str) -> bool:
    return any(
        re.search(pattern, text, flags=regex_flags)
        for pattern, regex_flags in _SUMMARY_LEAK_PATTERNS
    )


def _split_sentences(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    return [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", cleaned)
        if s.strip()
    ]


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _within_target_band(word_count: int, target_word_count: int | None) -> bool:
    if not target_word_count or target_word_count <= 0:
        return False
    return 0.85 * target_word_count <= word_count <= 1.15 * target_word_count


def _ben_close_third_lukes_order_leak(
    prose: str,
    scene_card: Mapping[str, Any] | None,
) -> bool:
    if not scene_card or scene_card.get("pov_character") != "Ben Skywalker":
        return False
    return bool(re.search(r"\bLuke[’']s\s+Order\b", prose))


def _speaker_aliases(scene_card: Mapping[str, Any]) -> list[str]:
    names = list(scene_card.get("characters_present", []) or [])
    aliases: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not name.strip():
            continue
        for alias in (name.strip(), name.strip().split()[0]):
            if alias and alias not in seen:
                seen.add(alias)
                aliases.append(alias)
    return aliases


def _flag(
    severity: str,
    code: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    item = {"severity": severity, "code": code, "message": message}
    item.update(extra)
    return item


def _opening_pull_score(first_paragraph: str) -> int:
    if not first_paragraph:
        return 0
    words = first_paragraph.split()
    score = 3
    if len(words) <= 120:
        score += 1
    if re.search(r"\b(?:cold|light|sound|smell|breath|hand|door|ship|voice)\b", first_paragraph, re.I):
        score += 1
    if re.match(r"^(?:The|A|An)\s+\w+\s+was\b", first_paragraph):
        score -= 1
    return max(0, min(5, score))


def _rhythm_score(sentence_lengths: list[int]) -> int:
    if len(sentence_lengths) < 3:
        return 3
    avg = sum(sentence_lengths) / len(sentence_lengths)
    if avg == 0:
        return 0
    variance = sum((length - avg) ** 2 for length in sentence_lengths) / len(sentence_lengths)
    cv = (variance ** 0.5) / avg
    if cv >= 0.55:
        return 5
    if cv >= 0.4:
        return 4
    if cv >= 0.28:
        return 3
    return 2


def _emotional_turn_score(prose: str, scene_card: Mapping[str, Any]) -> int:
    closing = str(scene_card.get("closing_hook", "") or "")
    turning = str(scene_card.get("turning_point", "") or "")
    text = prose.lower()
    score = 3
    if closing and any(word.lower() in text for word in _key_terms(closing)):
        score += 1
    if turning and any(word.lower() in text for word in _key_terms(turning)):
        score += 1
    return max(0, min(5, score))


def _final_line_score(final_sentence: str) -> int:
    if not final_sentence:
        return 0
    words = final_sentence.split()
    score = 3
    if len(words) <= 24:
        score += 1
    if re.search(r"\b(?:out|gone|silence|dark|door|name|signal|report|help|there)\b", final_sentence, re.I):
        score += 1
    if re.search(r"\b(?:realized|understood|knew|felt)\b", final_sentence, re.I):
        score -= 1
    return max(0, min(5, score))


def _key_terms(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text)
    stop = {"that", "with", "from", "into", "this", "they", "have", "will", "scene"}
    return [word for word in words if word.lower() not in stop][:12]
