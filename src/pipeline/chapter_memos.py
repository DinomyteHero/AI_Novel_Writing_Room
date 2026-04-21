"""Slice 2 chapter-close and milestone memos.

Synthesizes the revision-debt store, gap-note table, and (later) promise
ledger + quality telemetry into a per-chapter or cross-chapter memo that a
human uses to prioritize manual review. Memos are pure data \u2014 the generator
never mutates state.

Persistence is the orchestrator's job (spec \u00a76.3.2): memos land at
``output/<franchise>/<book>/runs/<run_id>/memos/``. This module builds the
structured dict + markdown render; ``ChapterCloseMemoGenerator.write(...)`` is
a convenience helper for the orchestrator + CLI.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.memory.story_state import StoryState
    from src.pipeline.revision_debt import RevisionDebtStore


# ---------------------------------------------------------------------------
# Internals shared by both generators
# ---------------------------------------------------------------------------


def _counts_by(rows: Iterable[Mapping[str, Any]], field_name: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field_name, "unknown"))
        out[key] = out.get(key, 0) + 1
    return out


def _open_ids(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    return [row["debt_id"] for row in rows if row.get("status") == "open"]


def _gap_summary(gaps: Iterable[Mapping[str, Any]]) -> list[dict]:
    out: list[dict] = []
    for g in gaps:
        out.append({
            "gap_id": g.get("gap_id"),
            "isolated_scene": g.get("isolated_scene"),
            "blocker_categories": list(g.get("blocker_categories") or []),
            "affected_scenes": list(g.get("affected_scenes") or []),
            "status": g.get("status"),
        })
    return out


def _count_by_category(rows: Iterable[Mapping[str, Any]], category: str) -> int:
    return sum(1 for r in rows if r.get("category") == category)


def _synthesize_attention_items(
    *, rows: list[dict], gaps: list[dict], pending_promises: list[dict],
) -> list[str]:
    items: list[str] = []
    by_sev = _counts_by(rows, "severity")
    if by_sev.get("high", 0):
        items.append(
            f"**{by_sev['high']}** high-severity debt row(s) open \u2014 review before next chapter."
        )
    if by_sev.get("medium", 0):
        items.append(
            f"{by_sev['medium']} medium-severity debt row(s) \u2014 triage at milestone memo."
        )
    open_gaps = [g for g in gaps if g.get("status") == "open"]
    if open_gaps:
        items.append(
            f"{len(open_gaps)} open gap-note(s) \u2014 resolve via patch workflow before manuscript export."
        )
    if pending_promises:
        items.append(
            f"{len(pending_promises)} promise(s) planted but not yet paid."
        )
    by_cat = _counts_by(rows, "category")
    if by_cat.get("canon"):
        items.append(
            f"{by_cat['canon']} canon advisory row(s) \u2014 verify franchise terminology."
        )
    if by_cat.get("presence_near_miss"):
        items.append(
            f"{by_cat['presence_near_miss']} presence near-miss(es) \u2014 review character presence."
        )
    if by_cat.get("wordcount_drift"):
        items.append(
            f"{by_cat['wordcount_drift']} word-count drift event(s)."
        )
    if by_cat.get("compression_advisory"):
        items.append(
            f"{by_cat['compression_advisory']} compression advisory(ies) \u2014 polish shrank prose."
        )
    if not items:
        items.append("No advisories open for this chapter.")
    return items


def _render_markdown(memo: Mapping[str, Any]) -> str:
    parts: list[str] = []
    kind = memo.get("kind", "chapter_close")
    if kind == "chapter_close":
        parts.append(f"# Chapter {memo.get('chapter_number')} \u2014 Close Memo")
    else:
        parts.append(f"# Milestone Memo (through chapter {memo.get('through_chapter')})")
    parts.append(f"_Generated: {memo.get('generated_at')}_")
    parts.append("")

    parts.append("## Debt Summary")
    debt_summary = memo.get("debt_summary", {})
    counts_cat = debt_summary.get("counts_by_category", {})
    counts_sev = debt_summary.get("counts_by_severity", {})
    if counts_cat:
        parts.append("**By category:**")
        for cat, n in sorted(counts_cat.items()):
            parts.append(f"- {cat}: {n}")
    if counts_sev:
        parts.append("")
        parts.append("**By severity:**")
        for sev, n in sorted(counts_sev.items()):
            parts.append(f"- {sev}: {n}")
    open_ids = debt_summary.get("open_debt_ids", [])
    if open_ids:
        parts.append("")
        parts.append(f"**Open debt ids ({len(open_ids)}):**")
        for did in open_ids:
            parts.append(f"- {did}")

    gap_notes = memo.get("gap_notes") or []
    if gap_notes:
        parts.append("")
        parts.append("## Gap Notes")
        for gap in gap_notes:
            cats = ", ".join(gap.get("blocker_categories") or []) or "(no categories)"
            parts.append(
                f"- **{gap.get('gap_id', '?')}** \u2014 {gap.get('isolated_scene', '?')} [{cats}] ({gap.get('status')})"
            )

    if memo.get("pending_promises"):
        parts.append("")
        parts.append("## Pending Promises")
        for p in memo["pending_promises"]:
            parts.append(f"- {p}")

    if memo.get("debt_trend"):
        parts.append("")
        parts.append("## Debt Trend (by chapter)")
        for row in memo["debt_trend"]:
            sev = row.get("counts_by_severity", {})
            label = ", ".join(f"{k}={v}" for k, v in sorted(sev.items()))
            parts.append(f"- Chapter {row.get('chapter_number')}: {label}")

    if memo.get("recommended_review_chapters"):
        parts.append("")
        parts.append("## Recommended Review Chapters")
        parts.append(", ".join(str(c) for c in memo["recommended_review_chapters"]))

    parts.append("")
    parts.append("## Human Attention")
    for item in memo.get("human_attention_items") or []:
        parts.append(f"- {item}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Chapter-close memo
# ---------------------------------------------------------------------------


class ChapterCloseMemoGenerator:
    def __init__(
        self,
        *,
        debt_store: Optional["RevisionDebtStore"],
        story_state: Optional["StoryState"] = None,
        promise_ledger=None,
    ) -> None:
        self.debt_store = debt_store
        self.story_state = story_state
        self.promise_ledger = promise_ledger

    def generate(self, *, chapter_number: int) -> dict:
        debt_rows = (
            self.debt_store.list_for_chapter(chapter_number)
            if self.debt_store is not None
            else []
        )
        gap_rows: list[dict] = []
        if self.story_state is not None:
            try:
                gap_rows = self.story_state.list_open_gaps(chapter_number=chapter_number)
            except Exception:  # noqa: BLE001
                logger.exception("list_open_gaps failed for chapter %s", chapter_number)
        pending_promises = self._pending_promises(chapter_number)

        presence_near_misses = _count_by_category(debt_rows, "presence_near_miss")
        compression_events = _count_by_category(debt_rows, "compression_advisory")
        wc_events = [r for r in debt_rows if r.get("category") == "wordcount_drift"]
        max_abs_pct = 0.0
        for r in wc_events:
            pct = float((r.get("details") or {}).get("pct_drift") or 0.0)
            if abs(pct) > max_abs_pct:
                max_abs_pct = abs(pct)

        memo = {
            "kind": "chapter_close",
            "chapter_number": chapter_number,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "debt_summary": {
                "counts_by_category": _counts_by(debt_rows, "category"),
                "counts_by_severity": _counts_by(debt_rows, "severity"),
                "open_debt_ids": _open_ids(debt_rows),
            },
            "gap_notes": _gap_summary(gap_rows),
            "open_gap_count": sum(1 for g in gap_rows if g.get("status") == "open"),
            "pending_promises": pending_promises,
            "presence_near_misses": presence_near_misses,
            "compression_events": compression_events,
            "word_count_drift": {
                "events": len(wc_events),
                "max_abs_pct": max_abs_pct,
            },
            "human_attention_items": _synthesize_attention_items(
                rows=debt_rows, gaps=gap_rows, pending_promises=pending_promises,
            ),
        }
        return memo

    def render_markdown(self, memo: Mapping[str, Any]) -> str:
        return _render_markdown(memo)

    def write(self, memo: Mapping[str, Any], *, memos_dir: Path) -> Path:
        memos_dir = Path(memos_dir)
        memos_dir.mkdir(parents=True, exist_ok=True)
        stem = f"chapter_{int(memo['chapter_number']):02d}_close_memo"
        json_path = memos_dir / f"{stem}.json"
        md_path = memos_dir / f"{stem}.md"
        json_path.write_text(json.dumps(memo, indent=2), encoding="utf-8")
        md_path.write_text(self.render_markdown(memo), encoding="utf-8")
        return md_path

    def _pending_promises(self, chapter_number: int) -> list[dict]:
        if self.promise_ledger is None:
            return []
        try:
            return list(self.promise_ledger.pending_as_of_chapter(chapter_number))
        except Exception:  # noqa: BLE001
            logger.exception("promise_ledger.pending_as_of_chapter failed")
            return []


# ---------------------------------------------------------------------------
# Milestone memo
# ---------------------------------------------------------------------------


class MilestoneMemoGenerator:
    def __init__(
        self,
        *,
        debt_store: Optional["RevisionDebtStore"],
        story_state: Optional["StoryState"] = None,
        promise_ledger=None,
    ) -> None:
        self.debt_store = debt_store
        self.story_state = story_state
        self.promise_ledger = promise_ledger

    def generate(self, *, through_chapter: int) -> dict:
        all_rows = self.debt_store.list_all() if self.debt_store is not None else []
        per_chapter: list[dict] = []
        for ch in range(1, through_chapter + 1):
            rows_ch = [
                r for r in all_rows
                if (r.get("scope") or {}).get("chapter_number") == ch
            ]
            per_chapter.append({
                "chapter_number": ch,
                "counts_by_severity": _counts_by(rows_ch, "severity"),
            })

        gap_rows: list[dict] = []
        if self.story_state is not None:
            try:
                # No chapter filter \u2014 pull everything and aggregate.
                gap_rows = self.story_state.list_open_gaps()
            except Exception:  # noqa: BLE001
                logger.exception("list_open_gaps failed for milestone memo")

        resolved = sum(1 for g in gap_rows if g.get("status") in ("resolved", "overruled"))
        total = len(gap_rows)
        resolution_rate = resolved / total if total else 1.0
        open_count = sum(1 for g in gap_rows if g.get("status") == "open")

        # Recommend any chapter with a high-severity or canon debt row.
        recommended = sorted({
            (r.get("scope") or {}).get("chapter_number")
            for r in all_rows
            if r.get("severity") == "high" or r.get("category") == "canon"
        } - {None})

        pending_promises = self._pending_promises(through_chapter)

        memo = {
            "kind": "milestone",
            "through_chapter": through_chapter,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "debt_summary": {
                "counts_by_category": _counts_by(all_rows, "category"),
                "counts_by_severity": _counts_by(all_rows, "severity"),
                "open_debt_ids": _open_ids(all_rows),
            },
            "debt_trend": per_chapter,
            "gap_notes": _gap_summary(gap_rows),
            "gap_resolution_rate": resolution_rate,
            "open_gap_count": open_count,
            "pending_promises": pending_promises,
            "presence_near_misses": _count_by_category(all_rows, "presence_near_miss"),
            "compression_events": _count_by_category(all_rows, "compression_advisory"),
            "word_count_drift": {
                "events": _count_by_category(all_rows, "wordcount_drift"),
                "max_abs_pct": 0.0,
            },
            "recommended_review_chapters": list(recommended),
            "human_attention_items": _synthesize_attention_items(
                rows=all_rows, gaps=gap_rows, pending_promises=pending_promises,
            ),
        }
        return memo

    def render_markdown(self, memo: Mapping[str, Any]) -> str:
        return _render_markdown(memo)

    def write(self, memo: Mapping[str, Any], *, memos_dir: Path) -> Path:
        memos_dir = Path(memos_dir)
        memos_dir.mkdir(parents=True, exist_ok=True)
        stem = f"milestone_through_chapter_{int(memo['through_chapter']):02d}_memo"
        json_path = memos_dir / f"{stem}.json"
        md_path = memos_dir / f"{stem}.md"
        json_path.write_text(json.dumps(memo, indent=2), encoding="utf-8")
        md_path.write_text(self.render_markdown(memo), encoding="utf-8")
        return md_path

    def _pending_promises(self, through_chapter: int) -> list[dict]:
        if self.promise_ledger is None:
            return []
        try:
            return list(self.promise_ledger.pending_as_of_chapter(through_chapter))
        except Exception:  # noqa: BLE001
            logger.exception("promise_ledger.pending_as_of_chapter failed")
            return []


__all__ = [
    "ChapterCloseMemoGenerator",
    "MilestoneMemoGenerator",
]
