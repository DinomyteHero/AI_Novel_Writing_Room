"""Chapter-level word-count telemetry (Stage 1h of the relay refactor).

Word count leaves the scene-level gate taxonomy entirely and becomes a
chapter-close telemetry signal. The pipeline never blocks a save on word
count — this module just emits info/warn/error level ledger events so
humans can spot drift.

Thresholds, on chapter total versus blueprint-declared target:

- |drift| <= 15%              -> ``emit_info``   (OK)
- 15% < |drift| <= 30%        -> ``emit_warn``  (notable drift)
- |drift| > 30%               -> ``emit_error`` (significant drift)

When no blueprint / target is available, a single ``emit_info`` event
records the actual total with a missing-target flag.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


def _blueprint_target_words(blueprint: dict) -> Optional[int]:
    """Sum target_word_count across the blueprint's scene_plan."""
    if not isinstance(blueprint, dict):
        return None
    plan = blueprint.get("scene_plan") or []
    total = 0
    seen_any = False
    for scene in plan:
        if not isinstance(scene, dict):
            continue
        t = scene.get("target_word_count")
        if isinstance(t, (int, float)) and t > 0:
            total += int(t)
            seen_any = True
    return total if seen_any else None


def _actual_words(chapter_results: Iterable[dict]) -> int:
    """Sum ``word_count`` across scene result dicts."""
    return sum(
        int(r.get("word_count") or 0)
        for r in chapter_results
        if isinstance(r, dict)
    )


def _resolve_blueprint_path(
    franchise_slug: Optional[str],
    book_slug: Optional[str],
    chapter_number: int,
    base_dir: Path = Path("."),
) -> Optional[Path]:
    if not franchise_slug or not book_slug:
        return None
    return (
        base_dir
        / "data"
        / "franchises"
        / franchise_slug
        / "books"
        / book_slug
        / "chapter_blueprints"
        / f"chapter_{int(chapter_number):02d}.json"
    )


def load_blueprint(
    franchise_slug: Optional[str],
    book_slug: Optional[str],
    chapter_number: int,
    base_dir: Path = Path("."),
) -> Optional[dict]:
    """Load the chapter blueprint JSON, or return None if missing/broken."""
    path = _resolve_blueprint_path(
        franchise_slug, book_slug, chapter_number, base_dir=base_dir
    )
    if path is None or not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "word_count_telemetry: could not load blueprint %s (%s)", path, exc
        )
        return None


def classify_drift(actual: int, target: int) -> tuple[str, float]:
    """Return ``(level, drift_fraction)`` for a total vs target.

    ``level`` is one of ``"info"``, ``"warn"``, ``"error"``. ``drift_fraction``
    is a signed fraction (actual-target)/target — positive if over, negative
    if under.
    """
    if target <= 0:
        return "info", 0.0
    drift = (actual - target) / target
    mag = abs(drift)
    if mag <= 0.15:
        level = "info"
    elif mag <= 0.30:
        level = "warn"
    else:
        level = "error"
    return level, drift


def emit_chapter_word_count_telemetry(
    ledger: Any,
    *,
    chapter_number: int,
    chapter_results: list[dict],
    blueprint: Optional[dict] = None,
    franchise_slug: Optional[str] = None,
    book_slug: Optional[str] = None,
    base_dir: Path = Path("."),
) -> dict:
    """Emit chapter-level word-count telemetry to the ledger.

    Returns a dict with the computed numbers and the emitted level. The
    caller can attach this to a chapter-result record if desired.

    ``ledger`` is expected to have ``emit_info``, ``emit_warn``, and
    ``emit_error`` helpers; ``RunLedger`` provides these as of Stage 1i.
    """
    actual = _actual_words(chapter_results)

    if blueprint is None:
        blueprint = load_blueprint(
            franchise_slug, book_slug, chapter_number, base_dir=base_dir
        )

    target = _blueprint_target_words(blueprint) if blueprint else None

    payload: dict[str, Any] = {
        "chapter_number": chapter_number,
        "actual_word_count": actual,
        "target_word_count": target,
    }

    if target is None or target <= 0:
        payload["drift_fraction"] = None
        payload["level"] = "info"
        payload["reason"] = "no_target_available"
        _emit(ledger, "info", chapter_number=chapter_number, payload=payload)
        return payload

    level, drift = classify_drift(actual, target)
    payload["drift_fraction"] = drift
    payload["level"] = level
    _emit(ledger, level, chapter_number=chapter_number, payload=payload)
    return payload


def _emit(
    ledger: Any,
    level: str,
    *,
    chapter_number: int,
    payload: dict,
) -> None:
    """Dispatch to the appropriate emit_* helper; fall back to emit."""
    event_type = "chapter_word_count_telemetry"
    method = getattr(ledger, f"emit_{level}", None)
    if method is not None:
        method(event_type, chapter_number=chapter_number, payload=payload)
        return
    # Fallback for older ledger instances without level helpers.
    emit = getattr(ledger, "emit", None)
    if emit is not None:
        payload_with_level = dict(payload)
        payload_with_level.setdefault("level", level)
        emit(event_type, chapter_number=chapter_number, payload=payload_with_level)
