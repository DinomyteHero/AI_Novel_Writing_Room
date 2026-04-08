"""Five-band adaptive revision pipeline.

Extends the base RevisionPipeline with two conditional bands:
  Band 4: Dialogue Polish (runs when dialogue-heavy + low voice score)
  Band 5: Worldbuilding Coherence (runs when canon elements present + issues)
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING

from src.agents.base_agent import BaseAgent
from src.revision.pipeline import RevisionPipeline

if TYPE_CHECKING:
    from src.model_router import ModelRouter
    from src.run_ledger import RunLedger


class DialoguePolishEditor(BaseAgent):
    """Band 4 revision agent for dialogue quality.

    Focuses on tag variety, subtext, character voice differentiation,
    and exposition-in-dialogue reduction.
    """

    def __init__(self, router: "ModelRouter", role: str = "dialogue_polish_editor"):
        super().__init__(router, role)

    def _load_system_prompt(self) -> str:
        """Load from revision_prompts directory."""
        prompt_path = Path("prompts/revision_prompts/dialogue_polish.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return f"You are the {self.role} agent."

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        character_voices = context.get("character_voices", "")
        quality_flags = context.get("quality_flags", [])

        parts = []

        if character_voices:
            parts.append(f"## Character Voice Profiles\n{character_voices}")

        if quality_flags:
            parts.append("## Quality Issues to Address")
            for flag in quality_flags:
                parts.append(f"- {flag}")
            parts.append("")

        parts.append(f"## Current Prose\n{prose}")

        parts.append(
            "## Task\n"
            "Polish all dialogue in this prose. Focus on:\n"
            "- Tag variety — reduce over-reliance on 'said', use action beats\n"
            "- Subtext — ensure characters imply rather than state feelings\n"
            "- Voice differentiation — each character should sound distinct\n"
            "- Exposition removal — cut info-dumps disguised as dialogue\n"
            "- Natural rhythm — dialogue should feel like real speech\n\n"
            "Return ONLY the complete revised prose. Preserve plot, structure, "
            "and non-dialogue content."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {"prose": response.strip()}


class WorldbuildingCoherenceReviewer(BaseAgent):
    """Band 5 revision agent for worldbuilding consistency.

    Ensures world-building details are consistent: technology levels,
    geography, cultural references, franchise-specific terminology.
    """

    def __init__(
        self, router: "ModelRouter", role: str = "worldbuilding_coherence_reviewer"
    ):
        super().__init__(router, role)

    def _load_system_prompt(self) -> str:
        """Load from revision_prompts directory."""
        prompt_path = Path("prompts/revision_prompts/worldbuilding_coherence.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return f"You are the {self.role} agent."

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context.get("scene_card", {})
        canon_elements = scene_card.get("canon_elements_needed", [])
        quality_flags = context.get("quality_flags", [])

        parts = []

        if canon_elements:
            parts.append("## Canon Elements Required")
            for element in canon_elements:
                parts.append(f"- {element}")
            parts.append("")

        if quality_flags:
            parts.append("## Quality Issues to Address")
            for flag in quality_flags:
                parts.append(f"- {flag}")
            parts.append("")

        parts.append(f"## Current Prose\n{prose}")

        parts.append(
            "## Task\n"
            "Review and fix worldbuilding coherence. Check:\n"
            "- Technology consistency — tech level matches the setting\n"
            "- Geography accuracy — locations and distances are consistent\n"
            "- Cultural references — customs, language, traditions are correct\n"
            "- Franchise terminology — proper nouns, titles, species names\n"
            "- Internal consistency — facts match earlier chapters\n\n"
            "Return ONLY the complete revised prose. Preserve plot, characters, "
            "and structure. Only fix worldbuilding inconsistencies."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {"prose": response.strip()}


class AdaptiveRevisionPipeline(RevisionPipeline):
    """Five-band revision pipeline with conditional Band 4 and Band 5.

    Bands 1-3 always run (structural, emotion, line).
    Band 4 (dialogue polish) runs when dialogue is heavy and voice score is low.
    Band 5 (worldbuilding) runs when canon elements are present and flagged.
    """

    def __init__(
        self,
        router: "ModelRouter",
        ledger: "RunLedger",
        metrics_dashboard=None,
    ):
        super().__init__(router, ledger)
        self.band4 = DialoguePolishEditor(router)
        self.band5 = WorldbuildingCoherenceReviewer(router)
        self.metrics = metrics_dashboard

    async def run(self, prose: str, context: dict) -> dict:
        """Run 3 mandatory bands, then conditionally bands 4 and 5.

        Args:
            prose: The prose to revise.
            context: Dict with scene_card, quality metrics, etc.

        Returns:
            {prose, bands_applied, band_results}
        """
        # Evaluate band 4/5 conditions on ORIGINAL prose (before revision)
        quality_metrics = context.get("quality_metrics")
        run_band4 = self._should_run_band4(prose, quality_metrics)
        run_band5 = self._should_run_band5(context, quality_metrics)

        # Run bands 1-3 via parent
        result = await super().run(prose, context)
        current_prose = result["prose"]
        bands_applied = result["bands_applied"]
        band_results = result["band_results"]

        chapter_num = context.get("scene_card", {}).get("chapter_number")
        scene_num = context.get("scene_card", {}).get("scene_number", 1)

        # Conditional Band 4: Dialogue Polish
        if run_band4:
            current_prose, band_meta = await self._run_band(
                band=self.band4,
                band_name="dialogue_polish",
                prose=current_prose,
                context=context,
                chapter_num=chapter_num,
                scene_num=scene_num,
            )
            bands_applied.append("dialogue_polish")
            band_results.append(band_meta)

        # Conditional Band 5: Worldbuilding Coherence
        if run_band5:
            current_prose, band_meta = await self._run_band(
                band=self.band5,
                band_name="worldbuilding_coherence",
                prose=current_prose,
                context=context,
                chapter_num=chapter_num,
                scene_num=scene_num,
            )
            bands_applied.append("worldbuilding_coherence")
            band_results.append(band_meta)

        return {
            "prose": current_prose,
            "bands_applied": bands_applied,
            "band_results": band_results,
        }

    def _should_run_band4(
        self, prose: str, quality_metrics: dict = None
    ) -> bool:
        """Determine if dialogue polish band should run.

        Runs when:
        - Dialogue ratio > 0.25 (scene has significant dialogue)
        - AND voice fidelity score < 0.8
        """
        # Compute dialogue ratio
        lines = [l.strip() for l in prose.split("\n") if l.strip()]
        if not lines:
            return False

        dialogue_lines = sum(
            1 for l in lines
            if l.startswith('"') or l.startswith('\u201c')  # " or left double quote
            or '" ' in l[:20]  # dialogue tag near start
        )
        dialogue_ratio = dialogue_lines / len(lines) if lines else 0

        if dialogue_ratio <= 0.25:
            return False

        # Check voice fidelity if metrics available
        if quality_metrics:
            voice = quality_metrics.get("voice", {})
            fidelity = voice.get("voice_fidelity_score", 1.0)
            return fidelity < 0.8

        # If no metrics, run when dialogue-heavy
        return True

    def _should_run_band5(
        self, context: dict, quality_metrics: dict = None
    ) -> bool:
        """Determine if worldbuilding coherence band should run.

        Runs when:
        - Scene card has canon_elements_needed entries
        - AND quality flags include canon/character issues
        """
        scene_card = context.get("scene_card", {})
        canon_elements = scene_card.get("canon_elements_needed", [])

        if not canon_elements:
            return False

        # Check quality flags for canon/character issues
        if quality_metrics:
            flags = quality_metrics.get("flags", [])
            has_issues = any(
                "canon" in f.lower() or "character" in f.lower()
                for f in flags
            )
            return has_issues

        # If no metrics but canon elements present, run
        return True
