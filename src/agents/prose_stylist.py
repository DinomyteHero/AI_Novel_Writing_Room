"""Prose Stylist agent — takes a typed generation brief and drafts scene prose.

Consumes `generation_brief` as a dict matching `schemas/generation_brief.json`.
Surfaces typed fields as labeled markdown sections in the user prompt so the
drafter sees structured, high-salience guidance instead of a prose blob.
"""

from src.agents.base_agent import BaseAgent


def _render_brief(brief: dict) -> str:
    """Render a typed generation brief as labeled markdown sections.

    Required fields render unconditionally; optional fields render only when
    present and non-empty. Missing required fields render as an explicit
    "(unspecified)" placeholder so the drafter is aware — the Plot Architect's
    semantic check already logged a warning if any were missing.
    """
    lines: list[str] = []

    lines.append("## Scene Objective")
    lines.append(brief.get("scene_objective", "(unspecified)"))

    opening_mode = brief.get("opening_mode")
    if opening_mode:
        lines.append("")
        lines.append("## Opening Mode")
        lines.append(opening_mode)

    key_beats = brief.get("key_beats") or []
    if key_beats:
        lines.append("")
        lines.append("## Key Beats")
        for i, beat in enumerate(key_beats, 1):
            desc = beat.get("beat_description", "")
            state = beat.get("state_change", "")
            reaction = beat.get("pov_reaction", "")
            lines.append(f"{i}. {desc}")
            if state:
                lines.append(f"   - State change: {state}")
            if reaction:
                lines.append(f"   - POV reaction: {reaction}")

    tp = brief.get("turning_point") or {}
    lines.append("")
    lines.append("## Turning Point")
    if tp:
        lines.append(f"- Trigger: {tp.get('trigger', '(unspecified)')}")
        lines.append(f"- Shift: {tp.get('shift', '(unspecified)')}")
        lines.append(f"- Cost: {tp.get('cost', '(unspecified)')}")
    else:
        lines.append("(unspecified)")

    lines.append("")
    lines.append("## Closing Beat")
    lines.append(brief.get("closing_beat", "(unspecified)"))

    ea = brief.get("emotional_arc") or {}
    lines.append("")
    lines.append("## Emotional Arc")
    if ea:
        lines.append(
            f"{ea.get('start', '(unspecified)')} -> "
            f"{ea.get('shift', '(unspecified)')} -> "
            f"{ea.get('end', '(unspecified)')}"
        )
    else:
        lines.append("(unspecified)")

    voice = brief.get("voice_guidance")
    if voice:
        lines.append("")
        lines.append("## Voice Guidance")
        lines.append(voice)

    delivery = brief.get("delivery_preferences") or {}
    if delivery:
        rendered = []
        if delivery.get("reveal_mode"):
            rendered.append(f"- Reveal mode: {delivery['reveal_mode']}")
        if delivery.get("exposition_budget"):
            rendered.append(f"- Exposition budget: {delivery['exposition_budget']}")
        if delivery.get("register_override"):
            rendered.append(f"- Register override: {delivery['register_override']}")
        if rendered:
            lines.append("")
            lines.append("## Delivery Preferences")
            lines.extend(rendered)

    required_hooks = brief.get("required_hooks") or []
    if required_hooks:
        lines.append("")
        lines.append("## Required Hooks")
        lines.extend(f"- {h}" for h in required_hooks)

    required_subplots = brief.get("required_subplots") or []
    if required_subplots:
        lines.append("")
        lines.append("## Required Subplots")
        lines.extend(f"- {s}" for s in required_subplots)

    required_revelations = brief.get("required_revelations") or []
    if required_revelations:
        lines.append("")
        lines.append("## Required Revelations")
        lines.extend(f"- {r}" for r in required_revelations)

    forbidden = brief.get("forbidden_moves") or []
    if forbidden:
        lines.append("")
        lines.append("## Forbidden Moves (do not write)")
        lines.extend(f"- {m}" for m in forbidden)

    anti_patterns = brief.get("anti_patterns") or []
    if anti_patterns:
        lines.append("")
        lines.append("## Anti-Patterns (extracted from scene card notes — do NOT do these)")
        lines.extend(f"- {a}" for a in anti_patterns)

    return "\n".join(lines)


_PART_1_PHASES = frozenset({"lie_established", "lie_reinforced"})
_PART_2_3_PHASES = frozenset({
    "lie_questioned", "lie_cracking", "lie_deepened", "point_of_no_return",
})
_PART_3_4_PHASES = frozenset({
    "lie_confronted", "truth_accepted", "truth_rejected",
    "lie_acted_upon", "lie_consequence",
    "truth_tested", "truth_pressured", "truth_reaffirmed",
    "truth_glimpsed", "disillusionment_accepted",
})


def _register_guidance_for_phase(phase: str) -> str:
    if phase in _PART_1_PHASES:
        return (
            "Part 1 register — reactive, tactile, sensory. Character feels "
            "problems before naming them. No clinical articulation."
        )
    if phase in _PART_2_3_PHASES:
        return (
            "Part 2-3 register — interior tension permitted, but still grounded "
            "in sensation. No mission-debrief sentences."
        )
    if phase in _PART_3_4_PHASES:
        return (
            "Part 3-4 register — analytical precision permitted where earned. "
            "Character may articulate what they now understand."
        )
    return "Honor the scene-card notes above for voice register."


def _scene_voice_contract(scene_card: dict) -> str:
    """Render the top-of-prompt Scene Voice Contract block.

    Returns an empty string when the scene card has nothing to surface.
    """
    notes = (scene_card.get("notes") or "").strip()
    raw_anti_patterns = scene_card.get("anti_patterns") or []
    anti_patterns = [str(a).strip() for a in raw_anti_patterns if str(a).strip()]
    pov_arc_phase = (scene_card.get("pov_arc_phase") or "").strip()

    if not notes and not anti_patterns and not pov_arc_phase:
        return ""

    lines: list[str] = ["## Scene Voice Contract (READ FIRST — ABSOLUTE)"]
    if notes:
        lines.append(notes)
    if anti_patterns:
        lines.append("")
        lines.append("### Anti-Patterns (from scene card)")
        lines.extend(f"- {a}" for a in anti_patterns)
    if pov_arc_phase:
        lines.append("")
        lines.append("### POV Arc Phase")
        lines.append(
            f"{pov_arc_phase} — {_register_guidance_for_phase(pov_arc_phase)}"
        )
    return "\n".join(lines)


class ProseStylist(BaseAgent):
    """Takes the typed generation brief from the Plot Architect plus
    assembled context from the ContextAssembler, and drafts scene prose."""

    def __init__(self, router, role: str = "prose_stylist"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        generation_brief = context["generation_brief"]
        assembled_context = context.get("assembled_context", "")
        dynamic_feedback = context.get("dynamic_feedback", "")
        failure_context = context.get("failure_context", "")
        # Slice 2: when the orchestrator resolves ``runtime.chapter_packet.enabled``
        # to true, it passes a rendered packet here. The packet renderer embeds
        # a flat-context snapshot so every token the legacy flat path produced
        # is still present (parity-enforced in tests/test_packet_parity.py).
        chapter_packet = context.get("chapter_packet")
        scene_card = context.get("scene_card", {}) or {}

        parts = []

        # The Scene Voice Contract is the drafter's highest-salience per-scene
        # instruction block — hoisted to the top of the user prompt so the
        # scene-card notes and anti-patterns do not sit buried inside the
        # scene-card JSON blob or the assembled context's mid-prompt position.
        voice_contract = _scene_voice_contract(scene_card)
        if voice_contract:
            parts.append(voice_contract)

        # When a packet is supplied, it is the drafter's single inspectable
        # runtime contract and replaces the flat assembled_context in the
        # rendered prompt. assembled_context is still kept around by the
        # orchestrator as the ``runtime.chapter_packet.fallback_on_error``
        # escape hatch; it is not re-appended here to avoid duplicate scene
        # card / voice-rules sections.
        if chapter_packet is not None:
            rendered_packet = chapter_packet.get("rendered_markdown") if isinstance(chapter_packet, dict) else ""
            if not rendered_packet and hasattr(chapter_packet, "render_markdown"):
                rendered_packet = chapter_packet.render_markdown()
            if rendered_packet:
                parts.append(rendered_packet)
        elif assembled_context:
            # assembled_context already includes the "## Writing Constraints" block
            # produced by ContextAssembler (the base banned-phrase list from
            # config/negative_constraints.yaml). The orchestrator may add
            # cross-scene dynamic feedback (overused words, description ratio
            # trends) via dynamic_feedback — that stays in its own section.
            parts.append(assembled_context)

        # Typed brief rendered as labeled sections
        parts.append("## Generation Brief\n" + _render_brief(generation_brief))

        if dynamic_feedback:
            parts.append(
                f"## Cross-Scene Feedback (from prior scenes in this chapter)\n{dynamic_feedback}"
            )

        if failure_context:
            parts.append(
                f"## Revision Notes (from previous attempt)\n{failure_context}"
            )

        # Phase 5: Voice rules injection
        voice_rules = context.get("voice_rules", "")
        if voice_rules:
            parts.append(voice_rules)

        target_words = scene_card.get("target_word_count") or generation_brief.get("target_word_count")
        closing_hook = scene_card.get("closing_hook", "")
        characters_present = scene_card.get("characters_present", [])
        pov_approach = context.get("pov_approach") or "third-person limited"

        task_lines = [
            "## Task",
            "Write the complete scene prose following the typed generation brief above.",
            f"Write in {pov_approach} POV. Focus on showing, not telling.",
            "Vary sentence length and structure. Avoid the banned phrases listed in constraints.",
            "The scene must contain the turning point specified in the brief.",
        ]
        if target_words:
            floor = int(target_words * 0.90)
            ceiling = int(target_words * 1.10)
            task_lines.append(
                f"Target length: {target_words} words. "
                f"Aim to land within {floor}–{ceiling} words (±10% of target). "
                "Treat the target as a soft floor, not a ceiling: if your "
                "first full pass through the brief's beats is coming in short, "
                "add the scene depth the beats actually need — room for the "
                "dialogue to breathe, for physical actions to land, for "
                "interior reactions to register — rather than compressing each "
                "beat to a sentence. If you significantly exceed the ceiling, "
                "check that every paragraph is earning its length; the "
                "downstream pipeline does not hard-reject off-target scenes "
                "but consistent undershoot is a quality signal."
            )
        if closing_hook:
            task_lines.append(
                f"SCENE BOUNDARY: The scene ENDS at the closing hook: \"{closing_hook}\". "
                "Do not write any content beyond this moment. Do not advance into "
                "the next scene's territory."
            )
        if characters_present:
            task_lines.append(
                "CHARACTERS PRESENT: Only the following characters may have dialogue "
                f"or significant action in this scene: {', '.join(characters_present)}. "
                "Characters not in this list may only appear in the closing hook "
                "if specified there."
            )

        parts.append("\n".join(task_lines))

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {
            "prose": response,
            "scene_card": context.get("scene_card", {}),
        }
