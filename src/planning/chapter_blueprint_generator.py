"""Chapter Blueprint Generator — derives chapter_blueprint.json files from scene cards.

Hybrid generator: deterministic rollup of ID lists / counts / scene-plan scaffold
from scene cards, plus an LLM ``ChapterBlueprintSynthesizer`` agent for the
narrative fields (chapter_mission, chapter_turn, per-scene purpose, pacing_curve,
exit_vector, relationship_turns, notes).

The deterministic half preserves ID fidelity (no hallucinated revelation/hook
IDs); the LLM half produces narrative-quality sentences matching the texture
of hand-authored blueprints.

Hand-authored blueprints at the canonical save path always take precedence —
``save_blueprints`` skips existing files unless ``force=True``.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING

from src.agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from src.model_router import ModelRouter

logger = logging.getLogger(__name__)


_PACING_CURVE_VALUES = {"rising", "falling", "steady", "mixed"}
_STRUCTURAL_PHASES = {
    "setup", "first_plot_point", "response", "first_pinch", "midpoint",
    "attack", "second_pinch", "second_plot_point", "resolution", "climax",
}
_SCENE_ROLES = {"hook", "escalation", "reveal", "decision", "aftermath"}


# --------------------------------------------------------------------------- #
# Deterministic rollup helpers                                                 #
# --------------------------------------------------------------------------- #

def _compute_pov_allocation(cards: list[dict]) -> list[str]:
    """Ordered unique pov_character per appearance."""
    seen = OrderedDict()
    for card in cards:
        pov = card.get("pov_character", "")
        if pov and pov not in seen:
            seen[pov] = None
    return list(seen.keys())


def _compute_scene_plan_skeleton(cards: list[dict]) -> list[dict]:
    """Per-scene skeleton with role, dialogue_expectation, target_word_count.

    Pulled verbatim from each card. ``purpose`` is left empty here — the
    synthesizer fills it. Scene roles fall back to a sane default if a card
    doesn't carry one (the blueprint schema requires ``role``).
    """
    skeleton = []
    for card in cards:
        scene_number = card.get("scene_number", 1)
        role = card.get("scene_role") or "escalation"
        if role not in _SCENE_ROLES:
            role = "escalation"

        entry = {
            "scene_number": scene_number,
            "role": role,
            "target_word_count": card.get("target_word_count", 1000),
            "purpose": "",
        }
        # dialogue_expectation is optional in the blueprint schema; only emit
        # it when the card supplies one, to match the hand-authored pattern
        # of always-present-when-known.
        dialogue = card.get("dialogue_expectation")
        if dialogue:
            entry["dialogue_expectation"] = dialogue
        skeleton.append(entry)
    return skeleton


def _compute_chapter_word_target(cards: list[dict]) -> int:
    """Sum of per-scene target_word_count."""
    return sum(int(card.get("target_word_count", 0) or 0) for card in cards)


def _compute_reveal_payload(cards: list[dict]) -> list[str]:
    """Sorted union of revelation IDs from each card's ``revelations``."""
    ids: set[str] = set()
    for card in cards:
        for rid in card.get("revelations", []) or []:
            if isinstance(rid, str) and rid:
                ids.add(rid)
    return sorted(ids)


def _compute_hook_movements(cards: list[dict]) -> dict:
    """Aggregate hook_actions into {planted, advanced, resolved} buckets.

    Action verbs map: plant -> planted, advance -> advanced,
    resolve -> resolved, subvert -> resolved (subversion is a form of
    resolution). Unknown actions are silently skipped. Within each bucket,
    IDs are de-duplicated and sorted.
    """
    bucket_map = {
        "plant": "planted",
        "advance": "advanced",
        "resolve": "resolved",
        "subvert": "resolved",
    }
    buckets: dict[str, set[str]] = {"planted": set(), "advanced": set(), "resolved": set()}
    for card in cards:
        for entry in card.get("hook_actions", []) or []:
            if not isinstance(entry, dict):
                continue
            hook_id = entry.get("hook_id")
            action = entry.get("action")
            bucket = bucket_map.get(action)
            if hook_id and bucket:
                buckets[bucket].add(hook_id)
    return {key: sorted(values) for key, values in buckets.items()}


def _compute_subplot_obligations(cards: list[dict]) -> list[str]:
    """Sorted union of active_subplots IDs across all cards."""
    ids: set[str] = set()
    for card in cards:
        for sid in card.get("active_subplots", []) or []:
            if isinstance(sid, str) and sid:
                ids.add(sid)
    return sorted(ids)


def _compute_structural_phase(cards: list[dict]) -> str:
    """Return the last scene's structural_phase (chapter belongs where it lands)."""
    if not cards:
        return "setup"
    last_phase = cards[-1].get("structural_phase") or "setup"
    if last_phase not in _STRUCTURAL_PHASES:
        return "setup"
    return last_phase


def _build_deterministic_rollup(chapter_number: int, cards: list[dict]) -> dict:
    """Compute all deterministic blueprint fields for a chapter."""
    return {
        "chapter_number": chapter_number,
        "structural_phase": _compute_structural_phase(cards),
        "pov_allocation": _compute_pov_allocation(cards),
        "scene_count": len(cards),
        "scene_plan": _compute_scene_plan_skeleton(cards),
        "reveal_payload": _compute_reveal_payload(cards),
        "hook_movements": _compute_hook_movements(cards),
        "subplot_obligations": _compute_subplot_obligations(cards),
        "chapter_word_target": _compute_chapter_word_target(cards),
    }


# --------------------------------------------------------------------------- #
# Synthesizer agent (LLM half)                                                 #
# --------------------------------------------------------------------------- #


class ChapterBlueprintSynthesizer(BaseAgent):
    """LLM agent that writes the narrative-quality fields of a chapter blueprint.

    Receives scene cards (filtered to relevant fields) plus a concept-seed
    excerpt and the deterministic rollup. Returns a dict with chapter_mission,
    chapter_turn, scene_purposes, pacing_curve, exit_vector, relationship_turns,
    notes.
    """

    def __init__(self, router: "ModelRouter", role: str = "chapter_blueprint_synthesizer"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        chapter_number = context["chapter_number"]
        cards = context["scene_cards"]
        rollup = context["deterministic_rollup"]
        concept_excerpt = context.get("concept_excerpt", {})

        filtered_cards = [_filter_scene_card_for_synthesizer(c) for c in cards]

        parts = [
            f"## Chapter {chapter_number} — Blueprint Synthesis",
            "",
            "## Deterministic rollup (already computed — do NOT modify)",
            "These are facts your narrative writing must reference. You do NOT invent new IDs.",
            f"```json\n{json.dumps(rollup, indent=2)}\n```",
            "",
            "## Scene cards (full content for each scene in this chapter)",
            f"```json\n{json.dumps(filtered_cards, indent=2)}\n```",
            "",
            "## Concept-seed excerpt (for ID -> label mapping)",
            f"```json\n{json.dumps(concept_excerpt, indent=2)}\n```",
            "",
            "## Task",
            (
                "Write the narrative-quality blueprint fields for this chapter. "
                "Return ONLY a JSON object with the keys specified in your system prompt: "
                "chapter_mission, chapter_turn, scene_purposes (one per scene_number), "
                "pacing_curve, exit_vector, relationship_turns (may be []), notes (may be \"\")."
            ),
        ]
        return "\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        # Not used — run() overrides to call complete_structured directly
        return {}

    async def run(self, context: dict) -> dict:
        """Synthesize narrative blueprint fields, with graceful degradation.

        On parse error or schema-shape failure, returns a fallback dict with
        empty narrative fields and a notes line describing the failure. The
        deterministic rollup remains valid even if synthesis fails, so the
        caller can still produce a schema-valid blueprint.
        """
        messages = self._build_messages(context)
        try:
            result = await self.router.complete_structured(self.role, messages)
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning(
                "ChapterBlueprintSynthesizer: parse failure for chapter %s (%s) — "
                "falling back to empty narrative fields",
                context.get("chapter_number"), exc,
            )
            return _empty_synthesizer_output(
                context["scene_cards"],
                f"Synthesizer parse failure: {exc}",
            )

        if not isinstance(result, dict):
            logger.warning(
                "ChapterBlueprintSynthesizer: non-dict result for chapter %s — "
                "falling back to empty narrative fields",
                context.get("chapter_number"),
            )
            return _empty_synthesizer_output(
                context["scene_cards"],
                "Synthesizer returned non-dict response.",
            )

        return result


_SYNTH_RELEVANT_CARD_FIELDS = (
    "chapter_number", "scene_number", "scene_role", "scene_type",
    "dialogue_expectation", "structural_phase", "pov_character",
    "characters_present", "mission", "why_now", "conflict", "conflict_type",
    "turning_point", "opening_hook", "closing_hook", "emotional_trajectory",
    "stakes", "setting", "target_word_count", "active_subplots",
    "hook_actions", "revelations", "pov_arc_phase",
)


def _filter_scene_card_for_synthesizer(card: dict) -> dict:
    """Project a scene card to fields the synthesizer needs.

    Drops voice/draft-specific fields (e.g., sensory_details, action_beats,
    canon_elements_needed, notes) to reduce token footprint without losing
    the narrative signal the synthesizer reads.
    """
    return {key: card[key] for key in _SYNTH_RELEVANT_CARD_FIELDS if key in card}


def _empty_synthesizer_output(cards: list[dict], note: str) -> dict:
    """Fallback synthesis output preserving schema validity."""
    return {
        "chapter_mission": "",
        "chapter_turn": "",
        "scene_purposes": [
            {"scene_number": c.get("scene_number", i + 1), "purpose": ""}
            for i, c in enumerate(cards)
        ],
        "pacing_curve": "mixed",
        "exit_vector": "",
        "relationship_turns": [],
        "notes": note,
    }


# --------------------------------------------------------------------------- #
# Top-level generator                                                          #
# --------------------------------------------------------------------------- #


_CONCEPT_EXCERPT_KEYS = ("revelations", "hooks", "subplots", "ensemble_cast", "theme", "premise")


def _build_concept_excerpt(concept_seed: dict) -> dict:
    """Pick the concept-seed sections the synthesizer needs for label mapping."""
    return {key: concept_seed[key] for key in _CONCEPT_EXCERPT_KEYS if key in concept_seed}


def _merge_synthesis_into_blueprint(rollup: dict, synthesis: dict) -> dict:
    """Merge LLM-produced narrative fields into the deterministic rollup.

    Scene-level ``purpose`` strings are zipped into the scene_plan skeleton
    by scene_number. Missing or extra synthesis entries are tolerated —
    the rollup's scene_plan structure is the source of truth for which
    scenes exist.
    """
    blueprint = dict(rollup)
    blueprint["chapter_mission"] = synthesis.get("chapter_mission", "")
    blueprint["chapter_turn"] = synthesis.get("chapter_turn", "")
    pacing = synthesis.get("pacing_curve")
    if pacing in _PACING_CURVE_VALUES:
        blueprint["pacing_curve"] = pacing
    elif pacing:
        # Unknown value — fall back to mixed rather than dropping the field
        blueprint["pacing_curve"] = "mixed"
    blueprint["exit_vector"] = synthesis.get("exit_vector", "")

    purposes_by_scene = {
        item.get("scene_number"): item.get("purpose", "")
        for item in (synthesis.get("scene_purposes") or [])
        if isinstance(item, dict)
    }
    for scene in blueprint["scene_plan"]:
        scene["purpose"] = purposes_by_scene.get(scene["scene_number"], "")

    relationship_turns = synthesis.get("relationship_turns") or []
    if isinstance(relationship_turns, list):
        # Validate and keep only well-shaped entries
        filtered = [
            rt for rt in relationship_turns
            if isinstance(rt, dict) and rt.get("dyad") and rt.get("from") and rt.get("to")
        ]
        blueprint["relationship_turns"] = filtered

    notes = synthesis.get("notes", "")
    if notes:
        blueprint["notes"] = notes

    return blueprint


class ChapterBlueprintGenerator:
    """Generates chapter blueprints from a concept seed + scene cards.

    Hybrid: deterministic rollup of ID/count/skeleton fields, LLM synthesis
    for narrative fields. Output dicts conform to schemas/chapter_blueprint.json.
    """

    def __init__(self, router: "ModelRouter"):
        self.router = router
        self.synthesizer = ChapterBlueprintSynthesizer(router)

    async def generate(
        self, concept_seed: dict, scene_cards: list[dict],
    ) -> list[dict]:
        """Generate a blueprint per distinct chapter_number in scene_cards.

        Cards are grouped by chapter_number and sorted by scene_number within
        each chapter. Returns blueprints sorted by chapter_number.
        """
        if not scene_cards:
            return []

        sorted_cards = sorted(
            scene_cards,
            key=lambda c: (c.get("chapter_number", 0), c.get("scene_number", 0)),
        )
        concept_excerpt = _build_concept_excerpt(concept_seed)

        blueprints: list[dict] = []
        for chapter_number, group in groupby(
            sorted_cards, key=lambda c: c.get("chapter_number", 0),
        ):
            cards = list(group)
            blueprint = await self._generate_one(chapter_number, cards, concept_excerpt)
            blueprints.append(blueprint)
        return blueprints

    async def _generate_one(
        self, chapter_number: int, cards: list[dict], concept_excerpt: dict,
    ) -> dict:
        rollup = _build_deterministic_rollup(chapter_number, cards)
        synthesis = await self.synthesizer.run({
            "chapter_number": chapter_number,
            "scene_cards": cards,
            "deterministic_rollup": rollup,
            "concept_excerpt": concept_excerpt,
        })
        return _merge_synthesis_into_blueprint(rollup, synthesis)


# --------------------------------------------------------------------------- #
# Persistence                                                                  #
# --------------------------------------------------------------------------- #


def _blueprint_path(
    franchise_slug: str, book_slug: str, chapter_number: int, base_dir: str = ".",
) -> Path:
    """Canonical path the chapter packet compiler loads blueprints from."""
    return (
        Path(base_dir)
        / "data"
        / "franchises"
        / franchise_slug
        / "books"
        / book_slug
        / "chapter_blueprints"
        / f"chapter_{int(chapter_number):02d}.json"
    )


def save_blueprints(
    blueprints: list[dict],
    franchise_slug: str,
    book_slug: str,
    base_dir: str = ".",
    force: bool = False,
) -> list[Path]:
    """Persist blueprints to the canonical chapter_blueprints directory.

    Hand-authored blueprints take precedence: existing files are preserved
    unless ``force=True``. Returns paths of files actually written.
    """
    written: list[Path] = []
    for blueprint in blueprints:
        chapter_number = blueprint.get("chapter_number")
        if chapter_number is None:
            logger.warning("save_blueprints: blueprint missing chapter_number — skipping")
            continue
        path = _blueprint_path(franchise_slug, book_slug, chapter_number, base_dir)
        if path.exists() and not force:
            logger.info(
                "save_blueprints: chapter %s blueprint already exists at %s — skipped (hand-authored precedence)",
                chapter_number, path,
            )
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(blueprint, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    return written
