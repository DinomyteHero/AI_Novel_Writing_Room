"""Quality Polish agent — single bounded polisher replacing Craft Editor + 3 revision bands.

The Quality Polish pass is the only post-gate stage that touches prose. It applies
expression-level edits (show-don't-tell, word choice, AI-tell removal, sentence
rhythm, grammar) within an explicit contract: it CANNOT add or remove beats,
characters, or story content.

Under the forward-only relay, Final Gate and the compression advisory both run
downstream of polish as telemetry only — they log advisory events but never
revert the polish. The save-blocker layer (character presence, canon verdict
at critical/moderate severity) is the sole hard-failure path. Polish output
is always saved otherwise.

Replaces: craft_editor, revision/pipeline (3 bands: structural_continuity,
scene_emotion, line_copy).
"""

import json

from src.agents.base_agent import BaseAgent


class QualityPolish(BaseAgent):
    """Single bounded polish pass. Expression-only edits; structure untouched.

    Receives gate-passed prose plus scene card hard constraints, quality metric
    flags, and an explicit 80% word-count floor as an instructed target to the
    model. Under the forward-only relay, the floor is advisory: the runtime
    compression guard emits a warn-level `compression_guard_fired` event when
    polish cuts below 60% of pre-polish word count, but the polished output is
    always kept. Final Gate runs afterwards as telemetry and never reverts.
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
            f"instead. Polish that compresses aggressively (below 60% of pre-polish) "
            f"fires an advisory event for human review — polish is still saved, but "
            f"aggressive compression is flagged as quality risk."
        )

        # Quality metric flags drive the polish agenda — what actually needs fixing.
        flags = quality_metrics.get("flags", []) if quality_metrics else []
        if flags:
            parts.append("## Quality Metric Flags (what to target)\n- " + "\n- ".join(flags[:15]))

        # Overused words from repetition detector — include paragraph
        # indices when available so the model can target specific paragraphs
        # rather than scanning the whole scene.
        per_scene = quality_metrics.get("per_scene", []) if quality_metrics else []
        overused_entries: list[str] = []
        seen_words: set[str] = set()
        for s in per_scene:
            rep = s.get("repetition", {})
            for w in rep.get("flagged_words", []):
                if isinstance(w, dict):
                    word = w.get("word")
                    paragraphs = w.get("paragraph_indices") or []
                else:
                    word = str(w)
                    paragraphs = []
                if not word or word in seen_words:
                    continue
                seen_words.add(word)
                if paragraphs:
                    paras_str = ", ".join(f"¶{i}" for i in paragraphs)
                    overused_entries.append(f"{word} ({paras_str})")
                else:
                    overused_entries.append(word)
        if overused_entries:
            parts.append(
                "## Overused Words (vary, don't delete; ¶N = zero-indexed paragraph)\n"
                f"{', '.join(overused_entries[:20])}"
            )

        # Show-don't-tell violations from slop detector
        slop_violations: list[str] = []
        for s in per_scene:
            slop = s.get("slop", {})
            for v in slop.get("show_dont_tell_violations", []) or slop.get("tell_not_show", []):
                if isinstance(v, dict):
                    text = v.get("text") or v.get("phrase")
                    paragraph = v.get("paragraph")
                    if text and paragraph is not None:
                        slop_violations.append(f"{text} (¶{paragraph})")
                    elif text:
                        slop_violations.append(text)
                elif v:
                    slop_violations.append(str(v))
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
