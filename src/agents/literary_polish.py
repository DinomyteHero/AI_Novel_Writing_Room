"""LiteraryPolish agent - final taste pass for contract-clean prose."""

from __future__ import annotations

import json
import re

from src.agents.base_agent import BaseAgent


class LiteraryPolish(BaseAgent):
    """Final literary copy pass.

    This agent is deliberately distinct from QualityPolish. QualityPolish is a
    bounded copy editor used inside the normal relay. LiteraryPolish is the
    final taste pass for prose that already passed hard scene contracts.
    """

    def __init__(self, router, role: str = "literary_polish"):
        super().__init__(router, role)

    async def run(self, context: dict) -> dict:
        messages = self._build_messages(context)
        raw = await self.router.complete(self.role, messages)
        return self._parse_response(raw, context)

    def _format_context(self, context: dict) -> str:
        source_prose = context.get("source_prose", "")
        scene_card = context.get("scene_card", {}) or {}
        generation_brief = context.get("generation_brief", {}) or {}
        continuity_lockfile = context.get("continuity_lockfile", {}) or {}
        motif_ledger = context.get("motif_ledger", {}) or {}
        copydesk_report = context.get("copydesk_report", {}) or {}
        voltage_report = context.get("voltage_report", {}) or {}
        scene_contract_validation = context.get("scene_contract_validation")
        scene_contract = context.get("scene_contract")

        parts = [
            "## Final-Copy Principle",
            (
                "Deepen the prose without inventing. The scene is already "
                "contract-clean; your job is literary inevitability, not new plot."
            ),
            "## Continuity Lockfile (hard constraint)",
            f"```json\n{json.dumps(continuity_lockfile, indent=2, ensure_ascii=False)}\n```",
            "## Scene Card (reference, not permission to add new beats)",
            f"```json\n{json.dumps(scene_card, indent=2, ensure_ascii=False)}\n```",
        ]

        if generation_brief:
            parts.extend([
                "## Generation Brief (structural reference)",
                f"```json\n{json.dumps(generation_brief, indent=2, ensure_ascii=False)}\n```",
            ])
        if scene_contract:
            parts.extend([
                "## Scene Contract (must still pass after polish)",
                f"```json\n{json.dumps(scene_contract, indent=2, ensure_ascii=False)}\n```",
            ])
        if scene_contract_validation:
            parts.extend([
                "## Current Contract Validation",
                f"```json\n{json.dumps(scene_contract_validation, indent=2, ensure_ascii=False)}\n```",
            ])

        parts.extend([
            "## Motif Ledger",
            f"```json\n{json.dumps(motif_ledger, indent=2, ensure_ascii=False)}\n```",
            "## Copy Desk Diagnostics",
            f"```json\n{json.dumps(copydesk_report, indent=2, ensure_ascii=False)}\n```",
            "## Read-Aloud Voltage Diagnostics",
            f"```json\n{json.dumps(voltage_report, indent=2, ensure_ascii=False)}\n```",
            "## Source Prose",
            source_prose,
            "## Task",
            (
                "Return a complete final literary copy of the scene. Preserve "
                "every plot fact, timeline claim, character present, POV boundary, "
                "speaker ownership rule, withheld-information rule, and closing "
                "boundary from the continuity lockfile and scene contract."
            ),
            "Allowed improvements:",
            "- sentence rhythm and paragraph music",
            "- image freshness and sensory precision",
            "- dialogue subtext and beat timing",
            "- cleaner transitions between action, speech, and interiority",
            "- stronger scene ending pressure",
            "- reduced motif repetition without erasing required motifs",
            "",
            "Forbidden changes:",
            "- no new lore, names, locations, mechanics, or exposition",
            "- no reassigned dialogue ownership",
            "- no changed chronology, counts, ship roster, or report content",
            "- no solving mysteries the source keeps withheld",
            "- no content past the closing hook",
            "- no summary of your edits, no markdown fences, no notes",
        ])

        return "\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {
            "prose": _strip_wrapping(response),
            "scene_card": context.get("scene_card", {}),
            "was_literary_polished": True,
        }


def _strip_wrapping(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"^```\s*\w*\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()
