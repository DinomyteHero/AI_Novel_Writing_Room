"""Deterministic prose-rhythm validator.

Catches the four mechanical patterns that make AI-drafted prose feel hard to
read even when its Flesch score looks fine:

- em-dash overuse (Zahn ~3/1k words; AI drafts hit 10+)
- consecutive short-sentence clusters (Zahn rarely runs 3+ in a row; AI drafts
  do it constantly, creating staccato)
- monotonous sentence openings (Zahn varies; AI drafts default to
  He/She/They/Name/The/It/There for ~half of all sentences)
- abstract-construction tics ("the particular X", "something adjacent", etc.)

Pure detection. No LLM. Returns a structured result the orchestrator can
either log as telemetry or convert into revision-debt rows. Thresholds derived
from a Scoundrels (Zahn, 2013) corpus baseline:

    Metric                         | Zahn baseline | Default advisory | Default warn
    em_dashes_per_1k_words         | 3.1           | >6               | >10
    short_sentence_runs_per_chapter| ~1.3          | >4               | >8
    default_opener_pct             | 24%           | >35%             | >45%
    dialogue_bearing_paragraph_pct | 67%           | <55%             | <45%
    abstract_constructions_per_1k  | 0.2           | >0.6             | >1.5

Severity rules:

- `low`    : metric is in the advisory band
- `medium` : metric is in the warn band
- `high`   : reserved for callers; this module emits low/medium only

Callers (orchestrator, final_copy diagnostics, bench harness) decide whether
to escalate to a hard fail. The validator itself never blocks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping


# Regex anchors --------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z]+(?:[''’][A-Za-z]+)*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'“‘])")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_DIALOGUE_QUOTE_RE = re.compile(r"[\"“”]")
# ``--`` as an em-dash substitute, but NOT inside a numeric range (1995--2003)
# or a markdown horizontal rule (---).
_DASH_DASH_EM_RE = re.compile(r"(?<![\d-])--(?![\d-])")

# Sentence-opener classes that, when used too often, flatten the prose rhythm.
# Conservative — only the four big default-opener buckets, not every pronoun.
_DEFAULT_OPENER_RE = re.compile(
    r"^(He|She|They|It|The|There)\b",
)

# Abstract-construction tic family. Each phrase, used once or twice in a
# manuscript, is fine; used dozens of times it becomes the most visible AI
# tell. Match case-insensitively because narrator-vs-character voice doesn't
# matter for the tic count.
_TIC_PATTERNS = (
    re.compile(r"\bthe particular\b", re.IGNORECASE),
    re.compile(r"\bthe kind of\b", re.IGNORECASE),
    re.compile(r"\bthe sort of\b", re.IGNORECASE),
    re.compile(r"\bthe way (?:of )?(?:someone|a person|of a person)\b", re.IGNORECASE),
    re.compile(r"\bsomething (?:like|adjacent)\b", re.IGNORECASE),
    re.compile(r"\bnot (?:quite|entirely)\b", re.IGNORECASE),
)

# Default thresholds. Callers can override via the `thresholds` arg.
DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "em_dashes_per_1k_words": {"advisory": 6.0, "warn": 10.0},
    "short_sentence_runs_per_chapter": {"advisory": 4, "warn": 8},
    "default_opener_pct": {"advisory": 35.0, "warn": 45.0},
    "dialogue_bearing_paragraph_pct_floor": {"advisory": 55.0, "warn": 45.0},
    "abstract_constructions_per_1k_words": {"advisory": 0.6, "warn": 1.5},
}


# Result containers ----------------------------------------------------------


@dataclass(frozen=True)
class RhythmIssue:
    """One detected rhythm problem."""

    code: str
    severity: str  # "low" or "medium"
    message: str
    metric_value: float
    threshold: float


@dataclass(frozen=True)
class RhythmMetrics:
    """Raw per-prose measurements. Useful as telemetry on every run."""

    word_count: int
    sentence_count: int
    paragraph_count: int
    em_dashes: int
    em_dashes_per_1k_words: float
    short_sentence_count: int
    short_sentence_runs: int
    default_opener_count: int
    default_opener_pct: float
    dialogue_bearing_paragraphs: int
    dialogue_bearing_paragraph_pct: float
    abstract_constructions: int
    abstract_constructions_per_1k_words: float


@dataclass(frozen=True)
class RhythmResult:
    """Validator output. `passed` is true when no issues fired."""

    scope: str  # "scene" or "chapter"
    scope_id: str | None
    passed: bool
    metrics: RhythmMetrics
    issues: tuple[RhythmIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "passed": self.passed,
            "metrics": {
                "word_count": self.metrics.word_count,
                "sentence_count": self.metrics.sentence_count,
                "paragraph_count": self.metrics.paragraph_count,
                "em_dashes": self.metrics.em_dashes,
                "em_dashes_per_1k_words": round(self.metrics.em_dashes_per_1k_words, 2),
                "short_sentence_count": self.metrics.short_sentence_count,
                "short_sentence_runs": self.metrics.short_sentence_runs,
                "default_opener_count": self.metrics.default_opener_count,
                "default_opener_pct": round(self.metrics.default_opener_pct, 1),
                "dialogue_bearing_paragraphs": self.metrics.dialogue_bearing_paragraphs,
                "dialogue_bearing_paragraph_pct": round(
                    self.metrics.dialogue_bearing_paragraph_pct, 1
                ),
                "abstract_constructions": self.metrics.abstract_constructions,
                "abstract_constructions_per_1k_words": round(
                    self.metrics.abstract_constructions_per_1k_words, 2
                ),
            },
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                    "metric_value": round(issue.metric_value, 2),
                    "threshold": issue.threshold,
                }
                for issue in self.issues
            ],
        }


# Core analyzer --------------------------------------------------------------


def compute_metrics(prose: str) -> RhythmMetrics:
    """Pure measurement. No thresholds applied.

    Caller is responsible for normalising prose to plain text (strip headers,
    scene-card frontmatter, etc.). The validator does not try to be clever
    about markdown.
    """
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(prose) if p.strip()]
    full_text = "\n".join(paragraphs)
    all_words = _WORD_RE.findall(full_text)
    word_count = len(all_words)

    sentences = [
        s.strip()
        for s in _SENTENCE_SPLIT_RE.split(full_text)
        if s.strip() and len(_WORD_RE.findall(s)) >= 2
    ]
    sentence_count = len(sentences)

    em_dashes = full_text.count("—") + len(_DASH_DASH_EM_RE.findall(full_text))

    sentence_lens = [len(_WORD_RE.findall(s)) for s in sentences]
    short_sentence_count = sum(1 for length in sentence_lens if length <= 8)

    short_runs = 0
    current_run = 0
    for length in sentence_lens:
        if length <= 8:
            current_run += 1
        else:
            if current_run >= 3:
                short_runs += 1
            current_run = 0
    if current_run >= 3:
        short_runs += 1

    default_opener_count = sum(
        1 for s in sentences if _DEFAULT_OPENER_RE.match(s)
    )

    dialogue_paragraphs = sum(
        1 for p in paragraphs if _DIALOGUE_QUOTE_RE.search(p)
    )

    abstract_constructions = sum(
        len(pat.findall(full_text)) for pat in _TIC_PATTERNS
    )

    per_1k = lambda n: (1000.0 * n / word_count) if word_count else 0.0
    pct = lambda n, d: (100.0 * n / d) if d else 0.0

    return RhythmMetrics(
        word_count=word_count,
        sentence_count=sentence_count,
        paragraph_count=len(paragraphs),
        em_dashes=em_dashes,
        em_dashes_per_1k_words=per_1k(em_dashes),
        short_sentence_count=short_sentence_count,
        short_sentence_runs=short_runs,
        default_opener_count=default_opener_count,
        default_opener_pct=pct(default_opener_count, sentence_count),
        dialogue_bearing_paragraphs=dialogue_paragraphs,
        dialogue_bearing_paragraph_pct=pct(dialogue_paragraphs, len(paragraphs)),
        abstract_constructions=abstract_constructions,
        abstract_constructions_per_1k_words=per_1k(abstract_constructions),
    )


def validate_rhythm(
    prose: str,
    *,
    scope: str = "scene",
    scope_id: str | None = None,
    thresholds: Mapping[str, Mapping[str, float]] | None = None,
    require_dialogue: bool = True,
) -> RhythmResult:
    """Compute metrics and emit issues for any metric in advisory/warn bands.

    ``require_dialogue`` should be False for scenes flagged as interior /
    POV-isolation (the dialogue-density check would otherwise fire on every
    contemplative scene). Defaults to True because most scenes have a second
    character present and should carry dialogue.
    """
    caller_overrode_thresholds = thresholds is not None
    thresholds = dict(thresholds or DEFAULT_THRESHOLDS)

    metrics = compute_metrics(prose)
    # Empty / whitespace-only prose has no rhythm to measure; every metric is 0,
    # which would otherwise trip the dialogue-starved floor. Pass cleanly.
    if metrics.word_count == 0 or metrics.paragraph_count == 0:
        return RhythmResult(
            scope=scope, scope_id=scope_id, passed=True,
            metrics=metrics, issues=(),
        )
    issues: list[RhythmIssue] = []

    def _band(metric_value: float, *, advisory: float, warn: float, higher_is_worse: bool) -> str | None:
        if higher_is_worse:
            if metric_value > warn:
                return "medium"
            if metric_value > advisory:
                return "low"
        else:
            if metric_value < warn:
                return "medium"
            if metric_value < advisory:
                return "low"
        return None

    # 1. em-dash density
    em_dash_thresh = thresholds["em_dashes_per_1k_words"]
    severity = _band(
        metrics.em_dashes_per_1k_words,
        advisory=em_dash_thresh["advisory"],
        warn=em_dash_thresh["warn"],
        higher_is_worse=True,
    )
    if severity:
        issues.append(RhythmIssue(
            code="rhythm.em_dash_overuse",
            severity=severity,
            message=(
                f"em-dash density {metrics.em_dashes_per_1k_words:.1f}/1k words "
                f"exceeds {em_dash_thresh['advisory']:.0f} (Zahn baseline ~3)"
            ),
            metric_value=metrics.em_dashes_per_1k_words,
            threshold=em_dash_thresh["advisory"],
        ))

    # 2. consecutive short-sentence runs
    runs_thresh = thresholds["short_sentence_runs_per_chapter"]
    if scope == "scene" and not caller_overrode_thresholds:
        # The per-chapter calibration (4/8) never fires on a single ~1.5k-word
        # scene; scale to the scene grain so staccato is actually detectable.
        runs_thresh = {"advisory": 2, "warn": 4}
    severity = _band(
        metrics.short_sentence_runs,
        advisory=runs_thresh["advisory"],
        warn=runs_thresh["warn"],
        higher_is_worse=True,
    )
    if severity:
        issues.append(RhythmIssue(
            code="rhythm.staccato_cluster",
            severity=severity,
            message=(
                f"{metrics.short_sentence_runs} clusters of 3+ consecutive short "
                f"sentences exceeds {runs_thresh['advisory']} (creates staccato rhythm)"
            ),
            metric_value=metrics.short_sentence_runs,
            threshold=runs_thresh["advisory"],
        ))

    # 3. default-opener monotony
    opener_thresh = thresholds["default_opener_pct"]
    severity = _band(
        metrics.default_opener_pct,
        advisory=opener_thresh["advisory"],
        warn=opener_thresh["warn"],
        higher_is_worse=True,
    )
    if severity:
        issues.append(RhythmIssue(
            code="rhythm.opener_monotone",
            severity=severity,
            message=(
                f"{metrics.default_opener_pct:.1f}% of sentences start with "
                f"He/She/They/It/The/There; exceeds {opener_thresh['advisory']:.0f}% "
                f"(Zahn baseline ~24%)"
            ),
            metric_value=metrics.default_opener_pct,
            threshold=opener_thresh["advisory"],
        ))

    # 4. dialogue-bearing paragraph floor (only if scene expects dialogue)
    if require_dialogue:
        dialogue_thresh = thresholds["dialogue_bearing_paragraph_pct_floor"]
        severity = _band(
            metrics.dialogue_bearing_paragraph_pct,
            advisory=dialogue_thresh["advisory"],
            warn=dialogue_thresh["warn"],
            higher_is_worse=False,
        )
        if severity:
            issues.append(RhythmIssue(
                code="rhythm.dialogue_starved",
                severity=severity,
                message=(
                    f"only {metrics.dialogue_bearing_paragraph_pct:.1f}% of paragraphs "
                    f"contain dialogue; below {dialogue_thresh['advisory']:.0f}% floor "
                    f"(Zahn baseline ~67%)"
                ),
                metric_value=metrics.dialogue_bearing_paragraph_pct,
                threshold=dialogue_thresh["advisory"],
            ))

    # 5. abstract-construction tic family
    tic_thresh = thresholds["abstract_constructions_per_1k_words"]
    severity = _band(
        metrics.abstract_constructions_per_1k_words,
        advisory=tic_thresh["advisory"],
        warn=tic_thresh["warn"],
        higher_is_worse=True,
    )
    if severity:
        issues.append(RhythmIssue(
            code="rhythm.abstract_tic",
            severity=severity,
            message=(
                f"abstract-construction density "
                f"{metrics.abstract_constructions_per_1k_words:.2f}/1k words exceeds "
                f"{tic_thresh['advisory']:.2f} (\"the particular X\" tic family)"
            ),
            metric_value=metrics.abstract_constructions_per_1k_words,
            threshold=tic_thresh["advisory"],
        ))

    return RhythmResult(
        scope=scope,
        scope_id=scope_id,
        passed=not issues,
        metrics=metrics,
        issues=tuple(issues),
    )
