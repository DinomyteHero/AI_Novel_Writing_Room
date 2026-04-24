"""Deterministic scene-contract validation for generated prose.

This module enforces executable, scene-specific constraints after drafting.
It is intentionally narrow: it catches high-risk continuity and beat-ownership
failures cheaply before any LLM judge or line editor spends tokens.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


_QUOTE_RE = re.compile(r'["\u201c](.+?)["\u201d]', re.DOTALL)
_DEFAULT_SPEECH_VERBS = (
    "said",
    "asked",
    "answered",
    "replied",
    "murmured",
    "whispered",
    "called",
    "said quietly",
    "said at last",
    "corrected",
    "snorted",
    "muttered",
)


@dataclass(frozen=True)
class DialogueLine:
    speaker: str | None
    text: str
    line: int
    excerpt: str


def load_contract(path: str | Path) -> dict[str, Any]:
    """Load a JSON scene contract."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_prose_contract(
    prose: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate prose against a scene contract.

    Supported check types:
    - ``global_forbidden``: fail when any regex appears anywhere in prose.
    - ``required_patterns``: fail when any required regex is absent globally.
    - ``speaker_forbidden``: fail when listed speakers say matching terms.
    - ``speaker_required``: fail when a speaker has no dialogue matching any
      listed regex.
    - ``character_required``: fail when no paragraph window around a named
      character matches any listed regex.
    """

    failures: list[dict[str, Any]] = []
    dialogue = extract_dialogue(prose, contract.get("speakers") or [])

    for check in contract.get("checks") or []:
        check_type = check.get("type")
        if check_type == "global_forbidden":
            failures.extend(_check_global_forbidden(prose, check))
        elif check_type == "required_patterns":
            failures.extend(_check_required_patterns(prose, check))
        elif check_type == "speaker_forbidden":
            failures.extend(_check_speaker_forbidden(dialogue, check))
        elif check_type == "speaker_required":
            failures.extend(_check_speaker_required(dialogue, check))
        elif check_type == "character_required":
            failures.extend(_check_character_required(prose, check))
        else:
            failures.append({
                "check_id": check.get("id", "unknown"),
                "severity": check.get("severity", "error"),
                "message": f"Unknown scene contract check type: {check_type!r}",
            })

    hard_failures = [f for f in failures if f.get("severity", "error") == "error"]
    return {
        "scene_id": contract.get("scene_id"),
        "passed": not hard_failures,
        "failure_count": len(failures),
        "hard_failure_count": len(hard_failures),
        "failures": failures,
        "dialogue_lines": [
            {
                "speaker": line.speaker,
                "line": line.line,
                "text": line.text,
            }
            for line in dialogue
        ],
    }


def validate_prose_file(
    prose_path: str | Path,
    contract_path: str | Path,
) -> dict[str, Any]:
    """Load prose and contract paths, then validate."""

    prose = Path(prose_path).read_text(encoding="utf-8")
    contract = load_contract(contract_path)
    return validate_prose_contract(prose, contract)


def extract_dialogue(prose: str, speakers: Iterable[str]) -> list[DialogueLine]:
    """Extract quoted dialogue and infer a likely speaker.

    This is deliberately heuristic. It catches common manuscript attributions
    cheaply enough for a deterministic gate:
    - ``"Text," Sera said.``
    - ``Sera said, "Text."``
    - ``Sera's head lifted. "Text."``
    """

    speaker_names = list(speakers)
    lines: list[DialogueLine] = []

    for match in _QUOTE_RE.finditer(prose):
        text = _normalize_space(match.group(1))
        if not text:
            continue
        start = match.start()
        end = match.end()
        speaker = _infer_speaker(prose, start, end, speaker_names)
        line = prose.count("\n", 0, start) + 1
        excerpt = _line_excerpt(prose, start)
        lines.append(DialogueLine(speaker=speaker, text=text, line=line, excerpt=excerpt))

    return lines


def _infer_speaker(
    prose: str,
    quote_start: int,
    quote_end: int,
    speakers: list[str],
) -> str | None:
    before_break = prose.rfind("\n\n", 0, quote_start)
    before_para_start = 0 if before_break == -1 else before_break + 2
    before = prose[before_para_start:quote_start]
    after_para_end = prose.find("\n\n", quote_end)
    if after_para_end == -1:
        after_para_end = min(len(prose), quote_end + 220)
    after_para = prose[quote_end:after_para_end]

    after_hit = _speaker_after_quote(after_para, speakers)
    if after_hit:
        return after_hit

    before_hit = _speaker_before_quote(before, speakers)
    if before_hit:
        return before_hit

    paragraph = before + after_para
    mentioned = _mentioned_speakers(paragraph, speakers)
    if len(mentioned) == 1:
        return mentioned[0]

    return None


def _speaker_after_quote(after: str, speakers: list[str]) -> str | None:
    window = after[:160]
    lower_window = window.lower()
    if not any(verb in lower_window for verb in _DEFAULT_SPEECH_VERBS):
        return None

    best: tuple[int, str] | None = None
    for speaker in speakers:
        match = re.search(r"\b" + re.escape(speaker) + r"\b", window)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), speaker)
    return best[1] if best else None


def _speaker_before_quote(before: str, speakers: list[str]) -> str | None:
    lower_before = before.lower()
    if not before.strip():
        return None

    best: tuple[int, str] | None = None
    for speaker in speakers:
        for match in re.finditer(r"\b" + re.escape(speaker) + r"(?:'s|\u2019s)?\b", before):
            if best is None or match.start() > best[0]:
                best = (match.start(), speaker)

    leading = _leading_speaker(before, speakers)
    if best is None:
        return leading

    tail = lower_before[best[0]:]
    if any(verb in tail for verb in _DEFAULT_SPEECH_VERBS):
        return best[1]
    if leading:
        return leading
    mentioned = _mentioned_speakers(before, speakers)
    if len(mentioned) == 1:
        return mentioned[0]
    return None


def _leading_speaker(text: str, speakers: list[str]) -> str | None:
    stripped = text.lstrip()
    for speaker in speakers:
        if re.match(r"\b" + re.escape(speaker) + r"(?:'s|\u2019s)?\b", stripped):
            return speaker
    return None


def _mentioned_speakers(text: str, speakers: list[str]) -> list[str]:
    found = []
    for speaker in speakers:
        if re.search(r"\b" + re.escape(speaker) + r"(?:'s|\u2019s)?\b", text):
            found.append(speaker)
    return found


def _check_global_forbidden(prose: str, check: Mapping[str, Any]) -> list[dict[str, Any]]:
    failures = []
    for pattern in check.get("patterns") or []:
        for match in _finditer(pattern, prose):
            failures.append(_failure(
                check,
                f"Forbidden prose pattern matched: {pattern}",
                line=prose.count("\n", 0, match.start()) + 1,
                excerpt=_line_excerpt(prose, match.start()),
                pattern=pattern,
            ))
    return failures


def _check_required_patterns(prose: str, check: Mapping[str, Any]) -> list[dict[str, Any]]:
    failures = []
    for pattern in check.get("patterns") or []:
        if not _search(pattern, prose):
            failures.append(_failure(
                check,
                f"Required prose pattern missing: {pattern}",
                pattern=pattern,
            ))
    return failures


def _check_speaker_forbidden(
    dialogue: list[DialogueLine],
    check: Mapping[str, Any],
) -> list[dict[str, Any]]:
    failures = []
    speakers = set(check.get("speakers") or [])
    for line in dialogue:
        if line.speaker not in speakers:
            continue
        for pattern in check.get("patterns") or []:
            if _search(pattern, line.text):
                failures.append(_failure(
                    check,
                    f"{line.speaker} dialogue matched forbidden pattern: {pattern}",
                    speaker=line.speaker,
                    line=line.line,
                    excerpt=line.excerpt,
                    pattern=pattern,
                ))
    return failures


def _check_speaker_required(
    dialogue: list[DialogueLine],
    check: Mapping[str, Any],
) -> list[dict[str, Any]]:
    speaker = check.get("speaker")
    patterns = check.get("patterns") or []
    for line in dialogue:
        if line.speaker != speaker:
            continue
        if any(_search(pattern, line.text) for pattern in patterns):
            return []

    return [_failure(
        check,
        f"{speaker} has no dialogue matching any required pattern.",
        speaker=speaker,
    )]


def _check_character_required(prose: str, check: Mapping[str, Any]) -> list[dict[str, Any]]:
    character = check.get("character")
    patterns = check.get("patterns") or []
    window_size = int(check.get("window_paragraphs", 2))
    paragraphs = re.split(r"\n\s*\n", prose)

    for idx, paragraph in enumerate(paragraphs):
        if not character or not re.search(r"\b" + re.escape(character) + r"\b", paragraph):
            continue
        window = "\n\n".join(paragraphs[idx:idx + window_size + 1])
        if any(_search(pattern, window) for pattern in patterns):
            return []

    return [_failure(
        check,
        f"{character} has no nearby text matching any required pattern.",
        speaker=character,
    )]


def _failure(
    check: Mapping[str, Any],
    message: str,
    *,
    speaker: str | None = None,
    line: int | None = None,
    excerpt: str | None = None,
    pattern: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "check_id": check.get("id", "unknown"),
        "severity": check.get("severity", "error"),
        "message": message,
    }
    if speaker:
        item["speaker"] = speaker
    if line is not None:
        item["line"] = line
    if excerpt:
        item["excerpt"] = excerpt
    if pattern:
        item["pattern"] = pattern
    return item


def _search(pattern: str, text: str) -> re.Match[str] | None:
    return re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)


def _finditer(pattern: str, text: str) -> Iterable[re.Match[str]]:
    return re.finditer(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _line_excerpt(prose: str, pos: int) -> str:
    line_start = prose.rfind("\n", 0, pos) + 1
    line_end = prose.find("\n", pos)
    if line_end == -1:
        line_end = len(prose)
    return prose[line_start:line_end].strip()
