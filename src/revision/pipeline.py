"""Three-band revision pipeline orchestrator.

Runs structural, scene/emotion, and line/copy revision passes sequentially.
Each band emits revision_band_start/revision_band_complete events to the ledger.
"""

import time
from typing import TYPE_CHECKING

from src.revision.line_copy import LineCopyEditor
from src.revision.scene_emotion import SceneEmotionReviewer
from src.revision.structural_continuity import StructuralContinuityReviewer

if TYPE_CHECKING:
    from src.model_router import ModelRouter
    from src.run_ledger import RunLedger


class RevisionPipeline:
    """Three-band sequential revision pipeline.

    Band 1: Structural/Continuity — fix plot holes, arc issues, timeline
    Band 2: Scene/Emotion — improve conflict, turning points, show-don't-tell
    Band 3: Line/Copy — prose polish, AI-tell removal, rhythm
    """

    def __init__(self, router: "ModelRouter", ledger: "RunLedger"):
        self.router = router
        self.ledger = ledger
        self.band1 = StructuralContinuityReviewer(router)
        self.band2 = SceneEmotionReviewer(router)
        self.band3 = LineCopyEditor(router)

    async def run(self, prose: str, context: dict) -> dict:
        """Run all three revision bands sequentially.

        Args:
            prose: The prose to revise (typically CraftEditor output)
            context: Dict with scene_card, story_state_summary,
                     prior_chapter_summary, character_voices,
                     negative_constraints, quality_flags

        Returns:
            {
                "prose": str,           # Final revised prose
                "bands_applied": list,  # Names of bands that ran
                "band_results": list,   # Per-band metadata
            }
        """
        chapter_num = context.get("scene_card", {}).get("chapter_number")
        scene_num = context.get("scene_card", {}).get("scene_number", 1)
        bands_applied = []
        band_results = []
        current_prose = prose

        # Band 1: Structural/Continuity
        current_prose, band_meta = await self._run_band(
            band=self.band1,
            band_name="structural_continuity",
            prose=current_prose,
            context=context,
            chapter_num=chapter_num,
            scene_num=scene_num,
        )
        bands_applied.append("structural_continuity")
        band_results.append(band_meta)

        # Band 2: Scene/Emotion
        current_prose, band_meta = await self._run_band(
            band=self.band2,
            band_name="scene_emotion",
            prose=current_prose,
            context=context,
            chapter_num=chapter_num,
            scene_num=scene_num,
        )
        bands_applied.append("scene_emotion")
        band_results.append(band_meta)

        # Band 3: Line/Copy
        current_prose, band_meta = await self._run_band(
            band=self.band3,
            band_name="line_copy",
            prose=current_prose,
            context=context,
            chapter_num=chapter_num,
            scene_num=scene_num,
        )
        bands_applied.append("line_copy")
        band_results.append(band_meta)

        return {
            "prose": current_prose,
            "bands_applied": bands_applied,
            "band_results": band_results,
        }

    async def _run_band(
        self,
        band,
        band_name: str,
        prose: str,
        context: dict,
        chapter_num: int | None,
        scene_num: int | None,
    ) -> tuple[str, dict]:
        """Run a single revision band with ledger events."""
        self.ledger.emit(
            "revision_band_start",
            chapter_number=chapter_num,
            scene_number=scene_num,
            agent_role=band.role,
            payload={"band_name": band_name},
        )

        start = time.time()

        # Build band-specific context with current prose
        band_context = {**context, "prose": prose}
        result = await band.run(band_context)
        revised_prose = result.get("prose", prose)

        duration_ms = int((time.time() - start) * 1000)

        self.ledger.emit(
            "revision_band_complete",
            chapter_number=chapter_num,
            scene_number=scene_num,
            agent_role=band.role,
            payload={
                "band_name": band_name,
                "duration_ms": duration_ms,
                "input_words": len(prose.split()),
                "output_words": len(revised_prose.split()),
            },
        )

        band_meta = {
            "band_name": band_name,
            "duration_ms": duration_ms,
            "input_words": len(prose.split()),
            "output_words": len(revised_prose.split()),
        }

        return revised_prose, band_meta
