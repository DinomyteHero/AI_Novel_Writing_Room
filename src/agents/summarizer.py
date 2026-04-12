"""Summarizer agent — compresses chapter prose into summaries and state diffs.

Produces both a natural language summary (~200-400 tokens) for ChromaDB storage
and a structured state diff (JSON) for updating the story state database.
"""

import json

from src.agents.base_agent import BaseAgent


class Summarizer(BaseAgent):
    """Compresses chapter prose into summaries and structured state diffs.

    Uses the utility model (low temperature) for consistent, factual output.
    Output is a JSON object with 'summary' and 'state_diff' keys.
    """

    def __init__(self, router, role: str = "summarizer"):
        super().__init__(router, role)

    async def run(self, context: dict) -> dict:
        """Run the summarizer, expecting structured JSON output."""
        messages = self._build_messages(context)
        try:
            result = await self.router.complete_structured(self.role, messages)
        except (json.JSONDecodeError, KeyError):
            # Fallback: try plain completion and parse
            raw = await self.router.complete(self.role, messages)
            result = self._parse_response(raw, context)
        return self._normalize_result(result)

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context.get("scene_card", {})

        parts = [
            "## Scene Card",
            json.dumps(scene_card, indent=2),
            "",
        ]

        # Inject current story state snapshot so LLM can produce accurate old_value fields
        state_snapshot = context.get("state_snapshot")
        if state_snapshot:
            parts.append("## Current Story State")
            parts.append("Use these EXACT values as old_value in your state diff entries.")
            parts.append("")
            parts.append("### Characters")
            for c in state_snapshot.get("characters", []):
                arc_info = ""
                if c.get("arc"):
                    arc_info = f" | arc_type={c['arc']['arc_type']}, phase={c['arc']['current_phase']}"
                parts.append(
                    f"- {c['id']}: location={c.get('current_location', 'unknown')}, "
                    f"emotional_state={c.get('emotional_state', 'unknown')}{arc_info}"
                )
            parts.append("")
            parts.append("### Subplots")
            for s in state_snapshot.get("subplots", []):
                parts.append(f"- {s['subplot_id']} [{s['line_type']}-line]: status={s['current_status']}")
            parts.append("")
            parts.append("### Hooks")
            for h in state_snapshot.get("hooks", []):
                parts.append(f"- {h['hook_id']} ({h['priority']}): status={h['current_status']}")
            parts.append("")

        parts.extend([
            "## Chapter Prose",
            prose,
            "",
            "## Task",
            "Analyze the chapter prose above and produce a JSON object with exactly two keys:",
            "",
            '1. "summary": A natural language summary (200-400 tokens) capturing:',
            "   - Key events that occurred",
            "   - Character state changes (emotional shifts, decisions made)",
            "   - Plot threads advanced or introduced",
            "   - The emotional arc of the scene",
            "",
            '2. "state_diff": A structured diff object with:',
            '   - "chapter_number": integer',
            '   - "changes": object containing:',
            '     - "character_updates": array of {character_id, field, old_value, new_value}',
            '     - "plot_thread_updates": array of {thread_id, field, old_value, new_value}',
            '     - "new_knowledge": array of {character_id, fact, source}',
            "",
            "For character_id values, use lowercase underscore format (e.g., 'ben_skywalker').",
            "For plot_thread_updates, track status changes (planted/active/escalating/resolving/resolved).",
            "For new_knowledge, record what characters learned and how (witnessed/told/inferred).",
            "",
            "Phase 5 additional change types (include when applicable):",
            '     - "subplot_updates": array of {subplot_id, field, old_value, new_value}',
            '     - "hook_updates": array of {hook_id, field, old_value, new_value}',
            '     - "arc_phase_updates": array of {character_id, old_phase, new_phase, evidence}',
            '     - "terminology_updates": array of {term, definition, category}',
            "",
            "For arc_phase_updates, old_value must state what you believe the current phase is.",
            "If you are unsure whether a state change occurred, DO NOT include it.",
            "False positives are worse than false negatives.",
        ])

        return "\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        """Parse raw text response into structured output."""
        # Try to extract JSON from the response
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Return a safe fallback
            chapter_num = context.get("scene_card", {}).get("chapter_number", 0)
            return {
                "summary": response[:1000],
                "state_diff": {
                    "chapter_number": chapter_num,
                    "changes": {
                        "character_updates": [],
                        "plot_thread_updates": [],
                        "new_knowledge": [],
                    },
                },
            }

    def _normalize_result(self, result: dict) -> dict:
        """Ensure the result has the expected structure."""
        if "summary" not in result:
            result["summary"] = ""
        if "state_diff" not in result:
            result["state_diff"] = {
                "chapter_number": 0,
                "changes": {
                    "character_updates": [],
                    "plot_thread_updates": [],
                    "new_knowledge": [],
                },
            }
        # Ensure changes sub-object exists
        changes = result["state_diff"].setdefault("changes", {})
        changes.setdefault("character_updates", [])
        changes.setdefault("plot_thread_updates", [])
        changes.setdefault("new_knowledge", [])
        # Phase 5 change types
        changes.setdefault("subplot_updates", [])
        changes.setdefault("hook_updates", [])
        changes.setdefault("arc_phase_updates", [])
        changes.setdefault("terminology_updates", [])
        return result
