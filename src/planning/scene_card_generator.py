"""Scene card auto-generation from concept seed.

Uses an OutlinePlanner agent to generate a chapter-by-chapter outline,
then converts each outline entry into a valid scene card. Optionally
validates with PhysicsEnforcer and retries failed cards.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from src.model_router import ModelRouter
    from src.planning.physics_enforcer import PhysicsEnforcer


def _jaccard_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """Compute Jaccard similarity between two token lists."""
    set_a, set_b = set(tokens_a), set(tokens_b)
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 0.0


def _estimate_scene_pressure(card: dict) -> int:
    """Heuristic pressure score (1-10) for a scene card."""
    score = 3  # baseline
    ct = card.get("conflict_type", "")
    if ct == "external":
        score += 2
    elif ct == "interpersonal":
        score += 1

    stakes = card.get("stakes", {})
    if stakes.get("external", "").strip():
        score += 2
    if stakes.get("interpersonal", "").strip():
        score += 1
    if stakes.get("personal", "").strip():
        score += 1

    return min(score, 10)


class OutlinePlanner(BaseAgent):
    """Agent that generates a chapter-by-chapter outline from a concept seed.

    Assigns structural phases (Brooks 4-part), distributes plot threads,
    assigns POV characters, and generates why_now justifications.
    """

    def __init__(self, router: "ModelRouter", role: str = "outline_planner"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        """Format concept seed into the planning prompt."""
        seed = context.get("concept_seed", {})
        meta = seed.get("meta", {})
        premise = seed.get("premise", {})
        conflict = seed.get("conflict", {})
        theme = seed.get("theme", {})
        cast = seed.get("ensemble_cast", [])
        structural = seed.get("structural_notes", {})
        target_chapters = meta.get("target_chapters", 20)

        parts = [
            "## Project Overview",
            f"Title: {meta.get('project_title', 'Untitled')}",
            f"Franchise: {meta.get('franchise', 'Original')}",
            f"Target chapters: {target_chapters}",
            f"Target word count: {meta.get('target_word_count', 75000)}",
            f"POV structure: {meta.get('pov_structure', 'single')}",
            "",
            "## Premise",
            f"What-if: {premise.get('what_if', '')}",
            f"Central question: {premise.get('central_dramatic_question', '')}",
            f"Logline: {premise.get('logline', '')}",
            "",
            "## Conflict",
            f"Antagonistic force: {json.dumps(conflict.get('primary_antagonistic_force', {}), indent=2)}",
            "",
            "## Theme",
            f"Thematic premise: {theme.get('thematic_premise', '')}",
            f"Thematic argument: {theme.get('thematic_argument', '')}",
            "",
            "## Cast",
        ]

        for char in cast:
            parts.append(f"- {char.get('name', 'Unknown')} ({char.get('role', '')})")
            dims = char.get("three_dimensions", {})
            if dims:
                parts.append(f"  Surface: {dims.get('surface', '')}")
                parts.append(f"  Inner: {dims.get('backstory_inner_demons', '')}")
            # Phase 5: Weiland arc info
            arc = char.get("weiland_arc")
            if arc:
                parts.append(f"  Lie: {arc.get('lie_believed', '')}")
                parts.append(f"  Need: {arc.get('need', '')}")
                parts.append(f"  Arc type: {arc.get('arc_type', '')}")
            parts.append("")

        if structural:
            parts.append("## Structural Notes (Brooks 4-part)")
            for phase, desc in structural.items():
                parts.append(f"- {phase}: {desc}")
            parts.append("")

        # Phase 5: Subplots (workshop-native format)
        subplots = seed.get("subplots") or []
        if subplots:
            parts.append("## Subplots")
            for sub in subplots:
                line_type = sub.get("line_type", "?")
                name = sub.get("name") or sub.get("subplot_id", "")
                purpose = sub.get("function") or sub.get("arc_summary", "")
                parts.append(f"- [{line_type}-line] {name}: {purpose}")
            parts.append("")

        # Phase 5: Hooks (workshop-native format)
        hooks = seed.get("hooks") or []
        if hooks:
            parts.append("## Hooks")
            for hook in hooks:
                # Workshop-native format: hook_type carries the priority
                # (hard/soft/series).
                priority = hook.get("hook_type", "soft")
                hook_id = hook.get("hook_id", "")
                description = hook.get("description", "")
                plant = hook.get("planted_in") or "?"
                payoff = hook.get("resolved_in") or "TBD"
                parts.append(
                    f"- [{priority}] {hook_id}: {description} "
                    f"(plant {plant}, payoff {payoff})"
                )
            parts.append("")

        # Phase 5: Revelation schedule
        revelations = seed.get("revelation_schedule", [])
        if revelations:
            parts.append("## Revelation Schedule")
            for rev in revelations:
                parts.append(
                    f"- ch{rev.get('revealed_in', rev.get('revealed_chapter', '?'))}: "
                    f"{rev.get('what', rev.get('content', ''))} "
                    f"({rev.get('significance', rev.get('impact', ''))})"
                )
            parts.append("")

        total_words = meta.get("target_word_count", 75000)
        per_chapter = total_words // target_chapters
        per_scene_target = per_chapter // 3

        # Chunked generation: chapter range and prior cards
        chapter_range = context.get("chapter_range")
        prior_summary = context.get("prior_cards_summary", "")

        if prior_summary:
            parts.append(prior_summary)
            parts.append("")

        if chapter_range:
            ch_start, ch_end = chapter_range
            range_label = f"chapters {ch_start}-{ch_end}"
            range_instruction = (
                f"Generate scene cards for {range_label} ONLY.\n"
                f"Do NOT generate scenes outside this range.\n\n"
            )
        else:
            range_label = f"all {target_chapters} chapters"
            range_instruction = ""

        parts.append(
            f"## Task\n"
            f"Generate scene cards for {range_label} with MULTIPLE SCENES PER CHAPTER.\n"
            f"{range_instruction}\n"
            f"SCENE COUNT RULES:\n"
            f"- Each chapter MUST contain 2-4 scenes (default 3).\n"
            f"- Single-scene chapters are allowed ONLY for high-impact set-piece moments "
            f"(climax, major plot points) — maximum 3 single-scene chapters in the entire novel.\n"
            f"- Per-scene target word count: ~{per_scene_target} words.\n"
            f"- Sum of scene target_word_counts per chapter must be within 90-110% "
            f"of {per_chapter} words.\n\n"
            f"OPENING ENERGY RULES:\n"
            f"- Chapter 1, Scene 1 must NOT open with the protagonist alone and thinking. "
            f"It must open in medias res, with dialogue, or with physical action.\n"
            f"- No scene's opening_hook should describe a character sitting, waiting, "
            f"or passively observing. Opening hooks must involve motion, conflict, or arrival.\n"
            f"- Each opening_hook should establish a physical situation that demands response, "
            f"not a mood or internal state.\n\n"
            f"SCENE VARIETY RULES:\n"
            f"- Alternate scene_type where possible: action -> sequel -> action.\n"
            f"- No chapter may have all scenes with the same conflict_type.\n"
            f"- Each scene MUST have a distinct mission — no two scenes in the same chapter "
            f"may have semantically equivalent missions.\n"
            f"- Each scene MUST end with a closing_hook that creates a question, complication, "
            f"or urgent decision that the next scene must address.\n"
            f"- Within a chapter, pressure must escalate or transform — the final scene "
            f"should not be the lowest-pressure scene.\n\n"
            f"Return a JSON array of scene card objects. Each object must have:\n"
            f"- chapter_number (int)\n"
            f"- scene_number (int, starting at 1 within each chapter)\n"
            f"- scene_type (one of: action, sequel)\n"
            f"- scene_role (one of: hook, escalation, reveal, decision, aftermath)\n"
            f"- structural_phase (one of: setup, first_plot_point, response, "
            f"first_pinch, midpoint, attack, second_pinch, second_plot_point, "
            f"resolution, climax)\n"
            f"- pov_character (string)\n"
            f"- mission (string, what this scene uniquely accomplishes)\n"
            f"- why_now (string, specific causal justification — no generic filler)\n"
            f"- conflict (string)\n"
            f"- conflict_type (one of: internal, interpersonal, external, environmental)\n"
            f"- dialogue_expectation (one of: dialogue_led, balanced, interior)\n"
            f"  * dialogue_led: 40-55% dialogue target, back-and-forth exchange carries the scene\n"
            f"  * balanced: no hard dialogue floor, dialogue and interiority share weight\n"
            f"  * interior: POV-isolation scene — interior monologue and observation dominate, EVEN IF other characters are physically present as background (e.g. a sparring partner in a sequel scene, a silent bystander). This is the key value to use when characters_present lists 2+ names but the scene is structurally about one POV's reflection.\n"
            f"- turning_point (string)\n"
            f"- opening_hook (string, how this scene opens with engagement)\n"
            f"- closing_hook (string, the question/complication/decision at scene end)\n"
            f"- emotional_trajectory (string)\n"
            f"- stakes (object with personal, interpersonal, external strings)\n"
            f"- characters_present (list of strings)\n"
            f"- setting (string, location and time)\n"
            f"- plot_threads_advanced (list of strings)\n"
            f"- promises_planted (list of strings)\n"
            f"- promises_paid (list of strings)\n"
            f"- canon_elements_needed (list of strings)\n"
            f"- target_word_count (int, per scene — NOT per chapter)\n"
            f"- action_beats (list of 2-4 physical actions/state changes, NOT internal thoughts — e.g. 'draws lightsaber', 'ship drops from hyperspace')\n"
            f"- active_subplots (list of subplot_ids)\n"
            f"- hook_actions (list of {{hook_id, action}} where action is plant/advance/resolve/subvert)\n"
            f"- revelations (list of revelation_ids)\n"
            f"- pov_arc_phase (current Weiland arc phase for POV character)\n"
            f"- arc_phase_transition (new phase if transition occurs, else null)\n\n"
            f"Distribute POV characters using the {meta.get('pov_structure', 'rotating')} pattern.\n"
            f"Ensure pressure escalates toward the climax.\n"
            f"Return ONLY the JSON array, no other text."
        )

        return "\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        """Parse the outline response into structured data."""
        # Try to extract JSON from response
        text = response.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            outline = json.loads(text)
            if isinstance(outline, list):
                return {"outline": outline, "scene_cards": outline}
            elif isinstance(outline, dict) and "scene_cards" in outline:
                return outline
            else:
                return {"outline": [outline], "scene_cards": [outline]}
        except json.JSONDecodeError:
            return {"outline": [], "scene_cards": [], "raw": text}


class SceneCardGenerator:
    """Generates and validates scene cards from a concept seed.

    Uses OutlinePlanner to generate scene cards, then optionally
    validates them with PhysicsEnforcer and retries failed ones.
    """

    def __init__(
        self,
        router: "ModelRouter",
        physics_enforcer: "PhysicsEnforcer | None" = None,
    ):
        self.planner = OutlinePlanner(router)
        self.physics = physics_enforcer

    async def generate(
        self, concept_seed: dict, max_retries: int = 3,
        chunk_size: int = 7,
    ) -> list[dict]:
        """Generate all scene cards for a novel in chunks.

        Splits the novel into chapter ranges (default: 7 chapters per chunk)
        to avoid LLM output token limits. Each chunk is generated in a
        separate API call with the full concept seed as context.

        Args:
            concept_seed: The concept seed dict.
            max_retries: Maximum validation retry attempts.
            chunk_size: Number of chapters per generation call.

        Returns:
            List of scene card dicts matching schemas/scene_card.json.
        """
        import logging
        logger = logging.getLogger(__name__)

        target_chapters = concept_seed.get("meta", {}).get("target_chapters", 20)
        all_cards: list[dict] = []

        # Build chapter ranges (e.g., 1-7, 8-14, 15-21, 22-28)
        ranges = []
        for start in range(1, target_chapters + 1, chunk_size):
            end = min(start + chunk_size - 1, target_chapters)
            ranges.append((start, end))

        for i, (ch_start, ch_end) in enumerate(ranges):
            label = f"chapters {ch_start}-{ch_end}"
            logger.info("Generating scene cards for %s (batch %d/%d)", label, i + 1, len(ranges))
            print(f"  Generating {label} (batch {i + 1}/{len(ranges)})...")

            chunk_cards = await self._generate_chunk(
                concept_seed, ch_start, ch_end, all_cards
            )
            if chunk_cards:
                chunk_cards = [self._ensure_defaults(card, concept_seed) for card in chunk_cards]
                all_cards.extend(chunk_cards)
            else:
                logger.warning("No cards generated for %s", label)

        # Validate chapter composition (multi-scene structure)
        composition_warnings = self._validate_chapter_composition(all_cards)
        if composition_warnings:
            for w in composition_warnings:
                logger.warning("Chapter composition: %s", w)

        # Validate: semantic completeness + physics enforcer
        all_cards = await self._validate_and_fix(
            all_cards, concept_seed, max_retries
        )

        return all_cards

    async def _generate_chunk(
        self,
        concept_seed: dict,
        ch_start: int,
        ch_end: int,
        prior_cards: list[dict],
    ) -> list[dict]:
        """Generate scene cards for a range of chapters.

        Includes a summary of prior cards so the model maintains continuity.
        """
        # Build a chunk-specific context with chapter range constraint
        context = {
            "concept_seed": concept_seed,
            "chapter_range": (ch_start, ch_end),
            "prior_cards_summary": self._summarize_prior_cards(prior_cards),
        }

        result = await self.planner.run_structured(context)
        # Result may be a list (JSON array returned directly) or a dict wrapper
        if isinstance(result, list):
            cards = result
        else:
            cards = result.get("scene_cards", result.get("outline", []))
        if not cards:
            result = await self.planner.run(context)
            if isinstance(result, list):
                cards = result
            else:
                cards = result.get("scene_cards", result.get("outline", []))

        # Filter to only the requested chapter range (model may overshoot)
        cards = [c for c in cards if ch_start <= c.get("chapter_number", 0) <= ch_end]
        return cards

    @staticmethod
    def _summarize_prior_cards(cards: list[dict]) -> str:
        """Create a compact summary of previously generated cards for continuity."""
        if not cards:
            return ""
        lines = ["## Previously Generated Scenes (for continuity)"]
        from itertools import groupby
        sorted_cards = sorted(cards, key=lambda c: (c.get("chapter_number", 0), c.get("scene_number", 0)))
        for ch_num, group in groupby(sorted_cards, key=lambda c: c.get("chapter_number", 0)):
            scenes = list(group)
            missions = [s.get("mission", "?") for s in scenes]
            hooks = scenes[-1].get("closing_hook", "")
            lines.append(
                f"- Ch{ch_num} ({len(scenes)} scene{'s' if len(scenes) > 1 else ''}): "
                f"{'; '.join(missions)}"
                + (f" -> Hook: {hooks}" if hooks else "")
            )
        return "\n".join(lines)

    async def _validate_and_fix(
        self, scene_cards: list[dict], concept_seed: dict, max_retries: int
    ) -> list[dict]:
        """Validate scene cards for semantic completeness and physics, retry failures."""
        for attempt in range(max_retries):
            failed_indices = []
            for i, card in enumerate(scene_cards):
                # Semantic completeness + scene quality checks
                warnings = self._check_semantic_completeness(card)
                warnings.extend(self._check_beat_coverage(card))
                warnings.extend(self._check_hook_requirements(card))
                warnings.extend(self._check_stakes(card))
                if warnings:
                    failed_indices.append(i)
                    continue

                # Physics validation (if enforcer available)
                if self.physics:
                    result = self.physics.validate_pre_chapter(card)
                    if not result["passed"]:
                        failed_indices.append(i)

            if not failed_indices:
                break

            # Regenerate failed cards (simplified: regenerate all and keep good ones)
            regen_result = await self.planner.run_structured(
                {"concept_seed": concept_seed}
            )
            new_cards = regen_result.get(
                "scene_cards", regen_result.get("outline", [])
            )
            new_cards = [self._ensure_defaults(c, concept_seed) for c in new_cards]

            # Replace only the failed cards if we have enough new ones
            for idx in failed_indices:
                if idx < len(new_cards):
                    scene_cards[idx] = new_cards[idx]

        return scene_cards

    # Fields that must be non-empty for a scene card to be pipeline-ready.
    _CRITICAL_FIELDS = ("mission", "conflict", "turning_point", "pov_character")

    @staticmethod
    def _check_semantic_completeness(card: dict) -> list[str]:
        """Check that critical fields have substantive (non-empty) content.

        Returns a list of warning strings for each empty critical field.
        An empty list means the card is semantically complete.
        """
        warnings = []
        for field in SceneCardGenerator._CRITICAL_FIELDS:
            value = card.get(field, "")
            if not value or not str(value).strip():
                warnings.append(
                    f"Chapter {card.get('chapter_number', '?')}, "
                    f"scene {card.get('scene_number', '?')}: "
                    f"'{field}' is empty"
                )

        if not card.get("characters_present"):
            warnings.append(
                f"Chapter {card.get('chapter_number', '?')}, "
                f"scene {card.get('scene_number', '?')}: "
                f"'characters_present' is empty"
            )

        return warnings

    @staticmethod
    def _check_beat_coverage(card: dict) -> list[str]:
        """Check that scene cards have appropriate beats for their scene_type.

        Action scenes (Bickham): require non-empty mission (goal), conflict
        (obstacle), and turning_point (outcome/setback).
        Sequel scenes: require non-empty emotional_trajectory (reaction),
        conflict (dilemma), and turning_point (decision).
        """
        warnings = []
        scene_type = card.get("scene_type", "")
        ch = card.get("chapter_number", "?")
        sc = card.get("scene_number", "?")

        if scene_type == "action":
            for field, beat in [("mission", "goal"), ("conflict", "obstacle"), ("turning_point", "outcome/setback")]:
                if not card.get(field, "").strip():
                    warnings.append(f"Ch{ch} Sc{sc}: action scene missing {beat} ('{field}' is empty)")
        elif scene_type == "sequel":
            for field, beat in [("emotional_trajectory", "reaction"), ("conflict", "dilemma"), ("turning_point", "decision")]:
                if not card.get(field, "").strip():
                    warnings.append(f"Ch{ch} Sc{sc}: sequel scene missing {beat} ('{field}' is empty)")

        return warnings

    @staticmethod
    def _check_hook_requirements(card: dict) -> list[str]:
        """Enforce hook field requirements.

        - Chapters 1-3: both opening_hook and closing_hook must be non-empty.
        - All chapters: closing_hook must be non-empty.
        """
        warnings = []
        ch = card.get("chapter_number", 0)
        sc = card.get("scene_number", "?")

        if not card.get("closing_hook", "").strip():
            warnings.append(f"Ch{ch} Sc{sc}: closing_hook is empty (required for all scenes)")

        if ch <= 3 and not card.get("opening_hook", "").strip():
            warnings.append(f"Ch{ch} Sc{sc}: opening_hook is empty (required for chapters 1-3)")

        return warnings

    @staticmethod
    def _check_stakes(card: dict) -> list[str]:
        """Require at least personal stakes plus one of interpersonal or external."""
        warnings = []
        stakes = card.get("stakes", {})
        ch = card.get("chapter_number", "?")
        sc = card.get("scene_number", "?")

        if not stakes.get("personal", "").strip():
            warnings.append(f"Ch{ch} Sc{sc}: personal stakes not defined")

        has_interpersonal = bool(stakes.get("interpersonal", "").strip())
        has_external = bool(stakes.get("external", "").strip())
        if not has_interpersonal and not has_external:
            warnings.append(f"Ch{ch} Sc{sc}: needs at least one of interpersonal or external stakes")

        return warnings

    def _ensure_defaults(self, card: dict, concept_seed: dict) -> dict:
        """Ensure a scene card has all required fields with sensible defaults."""
        meta = concept_seed.get("meta", {})
        target_chapters = meta.get("target_chapters", 20)
        total_words = meta.get("target_word_count", 75000)
        per_chapter = total_words // target_chapters

        defaults = {
            "chapter_number": 1,
            "scene_number": 1,
            "structural_phase": "setup",
            "scene_type": "action",
            "scene_role": "escalation",
            "pov_character": "",
            "mission": "",
            "why_now": "",
            "conflict": "",
            "conflict_type": "internal",
            "turning_point": "",
            "opening_hook": "",
            "closing_hook": "",
            "setting": "",
            "emotional_trajectory": "",
            "stakes": {"personal": "", "interpersonal": "", "external": ""},
            "characters_present": [],
            "plot_threads_advanced": [],
            "promises_planted": [],
            "promises_paid": [],
            "canon_elements_needed": [],
            "target_word_count": per_chapter // 3,  # Per-scene, not per-chapter
            "action_beats": [],
            "notes": "",
            # Phase 5 fields
            "active_subplots": [],
            "hook_actions": [],
            "revelations": [],
            "pov_arc_phase": None,
            "arc_phase_transition": None,
        }

        result = {**defaults, **card}
        return result

    @staticmethod
    def _validate_chapter_composition(scene_cards: list[dict]) -> list[str]:
        """Validate multi-scene chapter composition. Returns list of warnings."""
        from itertools import groupby

        warnings = []
        sorted_cards = sorted(scene_cards, key=lambda c: c.get("chapter_number", 0))

        for ch_num, group in groupby(sorted_cards, key=lambda c: c.get("chapter_number", 0)):
            scenes = list(group)

            if len(scenes) < 2:
                warnings.append(f"Chapter {ch_num}: only {len(scenes)} scene(s) — expected 2-4")
            if len(scenes) > 5:
                warnings.append(f"Chapter {ch_num}: {len(scenes)} scenes — exceeds maximum of 5")

            # Conflict variety check (for chapters with 3+ scenes)
            if len(scenes) >= 3:
                conflict_types = {s.get("conflict_type") for s in scenes}
                if len(conflict_types) < 2:
                    ct = conflict_types.pop() if conflict_types else "unknown"
                    warnings.append(
                        f"Chapter {ch_num}: all {len(scenes)} scenes have "
                        f"conflict_type '{ct}' — need variety"
                    )

            # Per-scene word count minimum check
            for s in scenes:
                wc = s.get("target_word_count", 0)
                if wc < 500:
                    warnings.append(
                        f"Chapter {ch_num} scene {s.get('scene_number', '?')}: "
                        f"target_word_count {wc} is below minimum (500)"
                    )

            # Mission uniqueness check (Jaccard similarity)
            missions = [(s.get("scene_number", 0), s.get("mission", "")) for s in scenes]
            for i, (sc_a, m_a) in enumerate(missions):
                for sc_b, m_b in missions[i + 1:]:
                    if m_a and m_b:
                        similarity = _jaccard_similarity(m_a.lower().split(), m_b.lower().split())
                        if similarity > 0.6:
                            warnings.append(
                                f"Chapter {ch_num}: scene {sc_a} and scene {sc_b} have "
                                f"similar missions (Jaccard={similarity:.2f}) — each scene "
                                f"needs a distinct mission"
                            )

            # Within-chapter pressure progression check
            if len(scenes) >= 2:
                pressure_scores = [
                    (s.get("scene_number", 0), _estimate_scene_pressure(s))
                    for s in scenes
                ]
                final_sc, final_p = pressure_scores[-1]
                min_p = min(p for _, p in pressure_scores)
                max_p = max(p for _, p in pressure_scores)
                if final_p == min_p and final_p < max_p:
                    warnings.append(
                        f"Chapter {ch_num}: final scene (scene {final_sc}) has the lowest "
                        f"pressure — chapter endings should not be the weakest moment"
                    )

        return warnings

    def save_scene_cards(
        self, scene_cards: list[dict], output_dir: str
    ) -> list[Path]:
        """Save scene cards as individual JSON files.

        Args:
            scene_cards: List of scene card dicts.
            output_dir: Directory to save files.

        Returns:
            List of paths to saved files.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        paths = []
        for card in scene_cards:
            ch = card.get("chapter_number", 1)
            sc = card.get("scene_number", 1)
            filename = f"chapter_{ch:02d}_scene_{sc:02d}.json"
            path = out / filename
            path.write_text(
                json.dumps(card, indent=2), encoding="utf-8"
            )
            paths.append(path)

        return paths
