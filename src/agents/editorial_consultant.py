"""Editorial Consultant agent — plan-time qualitative review.

Runs after ``PhysicsEnforcer.validate_plan`` in the compile step. Where
physics catches structural arithmetic (overdue promises, missing
why_now, causality breaks), the editorial consultant catches things no
deterministic validator can: muddled character arcs, derivative premises,
thematic arguments that never land, characters who test the theme
redundantly, convolution that will lose a genre reader by chapter 4.

Advisory only — writes a markdown report for the human author and emits
a structured verdict (``ready_to_draft`` / ``revise_plan`` /
``reconsider_premise``). The report does NOT block the compile; an
explicit ``scripts/approve_plan.py`` run is what stamps
``compile_metadata.plan_approved`` into the seed.

The agent prompt (``prompts/agent_system_prompts/editorial_consultant.md``)
owns the evaluation framework (two hats: Brooks/Weiland structural +
genre-reader). This module is plumbing: it assembles context from the
concept seed, sampled chapter blueprints, sampled scene cards, and the
physics report, then parses the LLM's markdown back into a structured
dict.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

VERDICT_VALUES = ("ready_to_draft", "revise_plan", "reconsider_premise")

# Chapter blueprint positions to sample for the review. Covers the
# Brooks structural beats we want the consultant to grade.
_SAMPLE_POSITIONS = (
    ("opening", 0.00),
    ("first_plot_point", 0.20),
    ("midpoint", 0.50),
    ("second_plot_point", 0.75),
    ("climax", 0.93),
    ("resolution", 1.00),
)


class EditorialConsultant(BaseAgent):
    """Plan-time qualitative review. Produces an advisory markdown report."""

    def __init__(self, router, role: str = "editorial_consultant"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        concept_seed = context.get("concept_seed", {}) or {}
        chapter_blueprints = context.get("chapter_blueprints", []) or []
        scene_cards = context.get("scene_cards", []) or []
        physics_report = context.get("physics_report") or {}

        meta = concept_seed.get("meta", {}) or {}
        try:
            total_chapters = int(meta.get("target_chapters") or len(chapter_blueprints) or 1)
        except (TypeError, ValueError):
            total_chapters = len(chapter_blueprints) or 1

        parts: list[str] = []

        # Reader-stance cues for Hat 2.
        parts.append("## Reader Stance")
        parts.append(json.dumps({
            "franchise": meta.get("franchise"),
            "genre": meta.get("genre"),
            "tone": meta.get("tone"),
            "era": meta.get("era"),
            "target_word_count": meta.get("target_word_count"),
            "target_chapters": total_chapters,
        }, indent=2))

        # Core seed sections — everything the consultant grades.
        seed_sections = [
            "premise", "conflict", "theme", "voice_definition",
            "canon_constraints", "canon_profile", "force_mechanics",
            "structural_notes", "ensemble_cast", "relationship_arcs",
            "referenced_characters", "subplots", "hooks",
            "revelation_schedule", "promise_payoff_ledger",
            "terminology_registry", "protagonist_arc_type",
            "arc_phase_maps",
        ]
        seed_excerpt = {
            k: concept_seed[k] for k in seed_sections if k in concept_seed
        }
        parts.append("## Concept Seed")
        parts.append("```json")
        parts.append(json.dumps(seed_excerpt, indent=2, ensure_ascii=False))
        parts.append("```")

        # Chapter blueprint samples aligned to Brooks structural beats.
        if chapter_blueprints:
            sampled = _sample_blueprints(chapter_blueprints, total_chapters)
            parts.append("## Chapter Blueprint Samples")
            for label, bp in sampled:
                ch = bp.get("chapter_number", "?")
                parts.append(f"### {label} — chapter {ch}")
                parts.append("```json")
                parts.append(json.dumps(bp, indent=2, ensure_ascii=False))
                parts.append("```")

        # Scene card samples across the book.
        if scene_cards:
            sampled_cards = _sample_scene_cards(scene_cards, total_chapters)
            parts.append("## Scene Card Samples")
            for card in sampled_cards:
                ch = card.get("chapter_number", "?")
                sn = card.get("scene_number", "?")
                parts.append(f"### chapter {ch} scene {sn}")
                parts.append("```json")
                parts.append(json.dumps(card, indent=2, ensure_ascii=False))
                parts.append("```")

        # Physics report — let the consultant skip arithmetic the
        # deterministic layer already covered.
        if physics_report:
            parts.append("## Physics Report (from compile-time validator)")
            parts.append(
                "The deterministic physics validator has already run. Do not "
                "re-audit the items below; focus on qualitative concerns the "
                "physics layer cannot catch."
            )
            parts.append("```json")
            parts.append(json.dumps({
                "passed": physics_report.get("passed"),
                "critical_count": physics_report.get("critical_count"),
                "warn_count": physics_report.get("warn_count"),
                "issues": physics_report.get("issues", [])[:20],
            }, indent=2))
            parts.append("```")

        parts.append("## Task")
        parts.append(
            "Follow the two-hat evaluation protocol from your system prompt. "
            "Produce the markdown report in the required section order and "
            "end with the single-line VERDICT marker."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        """Extract structured fields from the markdown report.

        We intentionally keep parsing shallow — the markdown is the
        human-facing artifact. The structured dict just surfaces what
        the compile needs for the report and the approval CLI.
        """
        return {
            "report_markdown": response,
            "verdict": _extract_verdict(response),
            "sections": _extract_top_sections(response),
        }


def _sample_blueprints(
    blueprints: list[dict], total_chapters: int,
) -> list[tuple[str, dict]]:
    """Return labeled (label, blueprint) pairs aligned to Brooks beats.

    Selects the blueprint whose ``chapter_number`` is closest to each
    structural-position target. De-duplicates on chapter number so an
    opening/first-plot-point pair near the beginning of a short book
    collapses to the single closest blueprint.
    """
    if not blueprints:
        return []
    by_chapter: dict[int, dict] = {}
    for bp in blueprints:
        ch = bp.get("chapter_number")
        if isinstance(ch, int):
            by_chapter[ch] = bp
    if not by_chapter:
        return []
    sampled: list[tuple[str, dict]] = []
    seen: set[int] = set()
    chapters_sorted = sorted(by_chapter)
    for label, position in _SAMPLE_POSITIONS:
        target = max(1, round(position * total_chapters))
        chosen = min(chapters_sorted, key=lambda c: abs(c - target))
        if chosen in seen:
            continue
        seen.add(chosen)
        sampled.append((label, by_chapter[chosen]))
    return sampled


def _sample_scene_cards(
    scene_cards: list[dict], total_chapters: int,
) -> list[dict]:
    """Return up to ~6 scene cards spread across the book.

    One card per sampled structural position; falls back to evenly-spaced
    if structural positions collapse in a short book.
    """
    if not scene_cards:
        return []
    by_chapter: dict[int, list[dict]] = {}
    for card in scene_cards:
        ch = card.get("chapter_number")
        if isinstance(ch, int):
            by_chapter.setdefault(ch, []).append(card)
    if not by_chapter:
        return []
    chapters_sorted = sorted(by_chapter)
    picks: list[dict] = []
    seen: set[int] = set()
    for _, position in _SAMPLE_POSITIONS:
        target = max(1, round(position * total_chapters))
        chosen_ch = min(chapters_sorted, key=lambda c: abs(c - target))
        if chosen_ch in seen:
            continue
        seen.add(chosen_ch)
        chapter_cards = sorted(
            by_chapter[chosen_ch],
            key=lambda c: c.get("scene_number", 0),
        )
        if chapter_cards:
            picks.append(chapter_cards[0])
    return picks


def _extract_verdict(response: str) -> str:
    """Find the final VERDICT: marker. Returns 'unknown' if absent."""
    match = re.search(
        r"VERDICT\s*:\s*(ready_to_draft|revise_plan|reconsider_premise)",
        response,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).lower()
    return "unknown"


def _extract_top_sections(response: str) -> dict[str, str]:
    """Pull the headed top-level sections as raw markdown blocks.

    Returns a dict keyed by normalized section name (e.g. 'strengths',
    'concerns', 'brooks_verdict'). Unknown or missing sections are
    silently omitted — the full report_markdown is always preserved.
    """
    wanted = {
        "top 3 strengths": "strengths",
        "top 5 concerns": "concerns",
        "brooks structural verdict": "brooks_verdict",
        "weiland arc verdict": "weiland_verdict",
        "convolution metrics": "convolution",
        "genre reader's gut read": "gut_read",
        "recommendations": "recommendations",
    }
    sections: dict[str, str] = {}
    # Match "## 1. Top 3 Strengths" or "## Top 3 Strengths" style headers.
    pattern = re.compile(
        r"^##+\s*(?:\d+\.\s*)?(?P<title>[^\n]+?)\s*$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(response))
    for idx, m in enumerate(matches):
        title = m.group("title").strip().lower()
        key = wanted.get(title)
        if not key:
            # Try prefix match (e.g. "Top 3 Strengths:")
            for prefix, mapped in wanted.items():
                if title.startswith(prefix):
                    key = mapped
                    break
        if not key:
            continue
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(response)
        sections[key] = response[start:end].strip()
    return sections
