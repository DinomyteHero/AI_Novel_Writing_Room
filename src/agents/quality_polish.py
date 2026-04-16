"""Quality Polish agent — single bounded polisher replacing Craft Editor + 3 revision bands.

The Quality Polish pass is the only post-gate stage that touches prose. It applies
expression-level edits (show-don't-tell, word choice, AI-tell removal, sentence
rhythm, grammar) within an explicit contract: it CANNOT add or remove beats,
characters, or story content. The Final Gate validates the polish output and
rejects it if the contract is violated.

Replaces: craft_editor, revision/pipeline (3 bands: structural_continuity,
scene_emotion, line_copy).
"""

import json

from src.agents.base_agent import BaseAgent


class QualityPolish(BaseAgent):
    """Single bounded polish pass. Expression-only edits; structure untouched.

    Receives gate-passed prose plus scene card hard constraints, quality metric
    flags, and an explicit word-count floor (polished text must not drop below
    80% of pre-polish count). The Final Gate verifies the contract on output.
    """

    def __init__(self, router, role: str = "quality_polish"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context["scene_card"]
        quality_metrics = context.get("quality_metrics") or {}
        negative_constraints = context.get("negative_constraints", "")
        canon_notes = context.get("canon_notes", "")

        # Pre-polish word count drives the minimum floor for the polish output.
        pre_polish_wc = len(prose.split())
        target_wc = scene_card.get("target_word_count", 0)
        min_floor = int(pre_polish_wc * 0.80)

        # Scene card hard constraints (characters_present, closing_hook) surface
        # at the top of the prompt so the model sees them before the prose.
        hard_constraints = {
            "characters_present": scene_card.get("characters_present", []),
            "closing_hook": scene_card.get("closing_hook", ""),
            "target_word_count": target_wc,
        }

        parts = []
        parts.append(
            f"## Scene Hard Constraints (DO NOT VIOLATE)\n"
            f"```json\n{json.dumps(hard_constraints, indent=2)}\n```"
        )
        parts.append(f"## Scene Card (reference)\n```json\n{json.dumps(scene_card, indent=2)}\n```")
        parts.append(
            f"## Word Count Contract\n"
            f"Pre-polish word count: {pre_polish_wc}\n"
            f"Minimum floor (80%): {min_floor}\n"
            f"Target: {target_wc}\n"
            f"**Your polished output MUST be >= {min_floor} words.** "
            f"If you would cut below the floor, stop cutting and rewrite in place "
            f"instead. A compression guard will reject polish output below the floor."
        )

        # Quality metric flags drive the polish agenda — what actually needs fixing.
        flags = quality_metrics.get("flags", []) if quality_metrics else []
        if flags:
            parts.append("## Quality Metric Flags (what to target)\n- " + "\n- ".join(flags[:15]))

        # Overused words from repetition detector
        per_scene = quality_metrics.get("per_scene", []) if quality_metrics else []
        overused: list[str] = []
        for s in per_scene:
            rep = s.get("repetition", {})
            for w in rep.get("flagged_words", []):
                word = w.get("word") if isinstance(w, dict) else str(w)
                if word and word not in overused:
                    overused.append(word)
        if overused:
            parts.append(
                "## Overused Words (vary, don't delete)\n"
                f"{', '.join(overused[:20])}"
            )

        # Show-don't-tell violations from slop detector
        slop_violations: list[str] = []
        for s in per_scene:
            slop = s.get("slop", {})
            for v in slop.get("show_dont_tell_violations", []):
                text = v.get("text") if isinstance(v, dict) else str(v)
                if text:
                    slop_violations.append(text)
        if slop_violations:
            parts.append(
                "## Show-Don't-Tell Violations (rewrite as demonstrated emotion)\n- "
                + "\n- ".join(slop_violations[:10])
            )

        if negative_constraints:
            parts.append(f"## Style Constraints (AI-tells to eliminate)\n{negative_constraints}")

        if canon_notes:
            parts.append(
                f"## Canon Notes (HARD CONSTRAINT — preserve corrections)\n{canon_notes}"
            )

        parts.append(f"## Prose to Polish\n{prose}")

        parts.append(
            "## Task\n"
            "Apply a single bounded polish pass. This is expression-level editing only.\n\n"
            "**You CAN:**\n"
            "- Fix show-don't-tell violations (rewrite told emotions as demonstrated)\n"
            "- Improve word choice precision (vague -> specific)\n"
            "- Remove AI-tell phrases and cliches from the constraints list\n"
            "- Vary sentence length and paragraph rhythm\n"
            "- Fix typos, grammar, dangling modifiers, pronoun ambiguity\n"
            "- Improve dialogue tags (adverb-heavy -> action beats)\n"
            "- Rewrite for sentence variety WITHOUT cutting total length\n\n"
            "**You CANNOT:**\n"
            "- Add or remove story beats\n"
            "- Add or remove characters (only those in characters_present may speak or act)\n"
            "- Change the turning point or its execution\n"
            "- Alter the scene's structural arc\n"
            "- Extend content past the closing_hook boundary\n"
            "- Introduce information not in the scene card or prose\n"
            "- Cut below the 80% word-count floor stated above\n\n"
            "**Canon compliance is a HARD CONSTRAINT.** If Canon Notes are present, "
            "every correction must be preserved. Do not revert corrected terminology.\n\n"
            "Return the COMPLETE polished prose text. No commentary, no notes, no "
            "before/after markup. Just the improved prose."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {
            "prose": response.strip(),
            "scene_card": context["scene_card"],
            "was_polished": True,
        }
