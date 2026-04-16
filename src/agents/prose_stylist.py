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


class ProseStylist(BaseAgent):
    """Takes the typed generation brief from the Plot Architect plus
    assembled context from the ContextAssembler, and drafts scene prose."""

    def __init__(self, router, role: str = "prose_stylist"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        generation_brief = context["generation_brief"]
        assembled_context = context.get("assembled_context", "")
        negative_constraints = context.get("negative_constraints", "")
        failure_context = context.get("failure_context", "")

        parts = []

        if assembled_context:
            parts.append(assembled_context)

        # Typed brief rendered as labeled sections
        parts.append("## Generation Brief\n" + _render_brief(generation_brief))

        if negative_constraints:
            parts.append(f"## Writing Constraints\n{negative_constraints}")

        if failure_context:
            parts.append(
                f"## Revision Notes (from previous attempt)\n{failure_context}"
            )

        # Phase 5: Voice rules injection
        voice_rules = context.get("voice_rules", "")
        if voice_rules:
            parts.append(voice_rules)

        scene_card = context.get("scene_card", {})
        target_words = scene_card.get("target_word_count") or generation_brief.get("target_word_count")
        closing_hook = scene_card.get("closing_hook", "")
        characters_present = scene_card.get("characters_present", [])

        task_lines = [
            "## Task",
            "Write the complete scene prose following the typed generation brief above.",
            "Write in third-person limited POV. Focus on showing, not telling.",
            "Vary sentence length and structure. Avoid the banned phrases listed in constraints.",
            "The scene must contain the turning point specified in the brief.",
        ]
        if target_words:
            task_lines.append(
                f"Target length: approximately {target_words} words. "
                "Do not pad to reach the target — write the scene the story needs."
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
