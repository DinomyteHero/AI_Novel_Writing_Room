"""Manuscript Reviewer agent — dual-persona full-manuscript evaluation.

Applies two complementary lenses to review a manuscript or manuscript portion:
1. Literary Critic — evaluates craft, voice, emotional resonance
2. Structural Editor — evaluates pacing, arcs, promise fulfillment, coherence

Returns a structured JSON review with categorized issues, an overall
assessment, and a recommendation (approve / revise_specific_chapters /
major_revision_needed).
"""

import json

from src.agents.base_agent import BaseAgent


# Issue severity levels
SEVERITY_LEVELS = {"critical", "major", "minor", "suggestion"}

# Issue categories
ISSUE_CATEGORIES = {
    # Literary Critic categories
    "craft",
    "voice",
    "emotional_impact",
    "prose_quality",
    "dialogue",
    "imagery",
    # Structural Editor categories
    "pacing",
    "arc_coherence",
    "promise_fulfillment",
    "plot_logic",
    "continuity",
    "chapter_transitions",
    "subplot_integration",
    "hook_management",
}

# Valid recommendation values
VALID_RECOMMENDATIONS = {
    "approve",
    "revise_specific_chapters",
    "major_revision_needed",
}


class ManuscriptReviewer(BaseAgent):
    """Dual-persona manuscript evaluator. Combines a Literary Critic lens
    (craft, voice, emotional impact) with a Structural Editor lens (pacing,
    arcs, promises, coherence) to produce a comprehensive review."""

    def __init__(self, router, role: str = "manuscript_reviewer"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        chapter_summaries = context.get("chapter_summaries", [])
        hooks = context.get("hooks", [])
        subplots = context.get("subplots", [])
        character_arcs = context.get("character_arcs", [])

        parts = []

        # Chapter summaries
        if chapter_summaries:
            parts.append("## Chapter Summaries")
            for i, summary in enumerate(chapter_summaries, 1):
                if isinstance(summary, dict):
                    title = summary.get("title", f"Chapter {i}")
                    text = summary.get("summary", "")
                    parts.append(f"### {title}\n{text}")
                else:
                    parts.append(f"### Chapter {i}\n{summary}")
            parts.append("")

        # Hooks
        if hooks:
            parts.append(
                f"## Hooks\n```json\n{json.dumps(hooks, indent=2)}\n```"
            )

        # Subplots
        if subplots:
            parts.append(
                f"## Subplots\n```json\n{json.dumps(subplots, indent=2)}\n```"
            )

        # Character arcs
        if character_arcs:
            parts.append(
                f"## Character Arcs\n```json\n{json.dumps(character_arcs, indent=2)}\n```"
            )

        # Manuscript prose
        parts.append(f"## Manuscript\n{prose}")

        # Task instruction
        parts.append(
            "## Task\n"
            "Review this manuscript through two complementary lenses:\n\n"
            "**Persona 1 — Literary Critic:** Evaluate craft, voice, emotional "
            "impact, prose quality, dialogue authenticity, and imagery.\n\n"
            "**Persona 2 — Structural Editor:** Evaluate pacing, arc coherence, "
            "promise fulfillment (hooks planted vs. resolved), plot logic, "
            "continuity, chapter transitions, subplot integration, and hook management.\n\n"
            "Return a JSON object with the following structure:\n"
            "```json\n"
            "{\n"
            '  "review_persona": {\n'
            '    "literary_critic": "brief summary of craft/voice findings",\n'
            '    "structural_editor": "brief summary of structure/pacing findings"\n'
            "  },\n"
            '  "issues": [\n'
            "    {\n"
            '      "severity": "critical | major | minor | suggestion",\n'
            '      "category": "craft | voice | emotional_impact | prose_quality | '
            "dialogue | imagery | pacing | arc_coherence | promise_fulfillment | "
            "plot_logic | continuity | chapter_transitions | subplot_integration | "
            'hook_management",\n'
            '      "description": "specific, actionable description of the issue",\n'
            '      "affected_chapters": [1, 2],\n'
            '      "suggested_fix": "concrete direction for improvement"\n'
            "    }\n"
            "  ],\n"
            '  "overall_assessment": "holistic summary of manuscript quality",\n'
            '  "recommendation": "approve | revise_specific_chapters | major_revision_needed"\n'
            "}\n"
            "```\n\n"
            "Guidelines:\n"
            "1. Be specific — reference chapter numbers, character names, and "
            "concrete examples from the text.\n"
            "2. Issues should be actionable — vague criticism is not useful.\n"
            "3. Check every planted hook against the hook ledger for resolution status.\n"
            "4. Verify each character arc progresses through its expected phases.\n"
            "5. Evaluate subplot threads for integration and satisfying resolution.\n"
            "6. Recommendation should reflect the most severe issues found:\n"
            '   - "approve" — no critical or major issues remain\n'
            '   - "revise_specific_chapters" — issues are localized to specific chapters\n'
            '   - "major_revision_needed" — systemic issues across the manuscript\n'
        )

        return "\n\n".join(parts)

    async def run(self, context: dict) -> dict:
        """Run the manuscript reviewer and return structured evaluation."""
        messages = self._build_messages(context)
        result = await self.router.complete_structured(self.role, messages)

        # Normalize the result
        issues = result.get("issues", [])
        review_persona = result.get("review_persona", {})
        overall_assessment = result.get("overall_assessment", "")
        recommendation = result.get("recommendation", "major_revision_needed")

        # Validate and normalize each issue
        normalized_issues = []
        for issue in issues:
            severity = issue.get("severity", "minor")
            if severity not in SEVERITY_LEVELS:
                severity = "minor"

            category = issue.get("category", "craft")
            if category not in ISSUE_CATEGORIES:
                category = "craft"

            affected_chapters = issue.get("affected_chapters", [])
            if not isinstance(affected_chapters, list):
                affected_chapters = [affected_chapters] if affected_chapters else []

            normalized_issues.append({
                "severity": severity,
                "category": category,
                "description": issue.get("description", ""),
                "affected_chapters": affected_chapters,
                "suggested_fix": issue.get("suggested_fix", ""),
            })

        # Derive recommendation from issues if not valid
        if recommendation not in VALID_RECOMMENDATIONS:
            recommendation = self._derive_recommendation(normalized_issues)

        # Ensure review_persona has both keys
        if not isinstance(review_persona, dict):
            review_persona = {}
        review_persona.setdefault("literary_critic", "")
        review_persona.setdefault("structural_editor", "")

        return {
            "review_persona": review_persona,
            "issues": normalized_issues,
            "overall_assessment": overall_assessment,
            "recommendation": recommendation,
        }

    def _derive_recommendation(self, issues: list[dict]) -> str:
        """Derive a recommendation from the issue list when the LLM
        returns an invalid or missing recommendation value."""
        if not issues:
            return "approve"

        severities = {issue["severity"] for issue in issues}

        if "critical" in severities:
            # Check whether critical issues span many chapters
            critical_chapters = set()
            for issue in issues:
                if issue["severity"] == "critical":
                    critical_chapters.update(issue.get("affected_chapters", []))
            if len(critical_chapters) > 3:
                return "major_revision_needed"
            return "revise_specific_chapters"

        if "major" in severities:
            return "revise_specific_chapters"

        return "approve"

    def _parse_response(self, response: str, context: dict) -> dict:
        # Not used — run() overrides the flow to use complete_structured
        return {}
