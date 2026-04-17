"""outline-planner programmatic API.

Owns structural_notes + chapter outline + subplots/hooks/revelations/promises
/relationship phase data. Persists to ``workflows/outline.json``.

Façade over ``src.planning.scene_card_generator.OutlinePlanner`` projecting
outline-only fields. The pipeline-side scene-card generation lives in
the scene-card-authoring surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.project_paths import ProjectPaths
from workflows._shared.io import read_artifact, write_artifact
from workflows.outline_planner.validate import validate

if TYPE_CHECKING:
    from src.model_router import ModelRouter

ARTIFACT_NAME = "outline.json"

# Fields preserved when projecting a SceneCardGenerator result down to
# outline-only entries. Anything else (mission, conflict, opening_hook,
# stakes, action_beats, etc.) belongs to scene-card-authoring.
_OUTLINE_FIELDS = (
    "chapter_number",
    "chapter_title",
    "synopsis",
    "pov_character",
    "structural_phase",
    "arc_phases_active",
    "subplot_ids",
    "estimated_word_count",
)


class OutlinePlannerSurface:
    """Read/write/generate the outline-planner artifact for a project."""

    def __init__(
        self,
        paths: ProjectPaths,
        router: "ModelRouter | None" = None,
    ):
        self.paths = paths
        self.router = router

    @property
    def artifact_path(self) -> Path:
        return self.paths.workflows_dir / ARTIFACT_NAME

    def read(self) -> dict:
        return read_artifact(self.artifact_path)

    def write(self, data: dict) -> Path:
        return write_artifact(
            self.artifact_path,
            data,
            surface="outline-planner",
            validator=validate,
        )

    @staticmethod
    def envelope(
        outline: list[dict],
        *,
        structural_notes: dict | None = None,
        subplots: list[dict] | None = None,
        hooks: list[dict] | None = None,
        revelation_schedule: list[dict] | None = None,
        promise_payoff_ledger: list[dict] | None = None,
        arc_phase_maps: dict | None = None,
    ) -> dict:
        """Wrap outline + skeletons in the surface envelope."""
        artifact: dict = {
            "surface": "outline-planner",
            "schema_version": "1.0",
            "outline": outline,
        }
        if structural_notes:
            artifact["structural_notes"] = structural_notes
        if subplots:
            artifact["subplots"] = subplots
        if hooks:
            artifact["hooks"] = hooks
        if revelation_schedule:
            artifact["revelation_schedule"] = revelation_schedule
        if promise_payoff_ledger:
            artifact["promise_payoff_ledger"] = promise_payoff_ledger
        if arc_phase_maps:
            artifact["arc_phase_maps"] = arc_phase_maps
        return artifact

    @staticmethod
    def project_to_outline(scene_cards: list[dict]) -> list[dict]:
        """Project a SceneCardGenerator output down to outline-only fields.

        Collapses multi-scene chapters into a single outline entry per
        chapter (using the first scene's POV/phase as representative) and
        drops scene-level fields (mission, conflict, etc.). The resulting
        list is what the outline-planner surface persists.
        """
        by_chapter: dict[int, dict] = {}
        for card in scene_cards:
            ch = card.get("chapter_number")
            if ch is None:
                continue
            if ch not in by_chapter:
                entry: dict = {"chapter_number": ch}
                for field in _OUTLINE_FIELDS:
                    if field in card and card[field] not in (None, "", []):
                        entry[field] = card[field]
                # Best-effort synopsis from mission + turning_point of first scene.
                if "synopsis" not in entry:
                    pieces = []
                    if card.get("mission"):
                        pieces.append(card["mission"])
                    if card.get("turning_point"):
                        pieces.append(card["turning_point"])
                    if pieces:
                        entry["synopsis"] = " — ".join(pieces)
                by_chapter[ch] = entry
        return [by_chapter[ch] for ch in sorted(by_chapter)]

    async def generate(self, concept_seed: dict) -> dict:
        """Run OutlinePlanner over a concept seed and project to outline-only.

        Requires the surface to be constructed with a router. Returns the
        envelope dict; caller must ``write()`` to persist.
        """
        if self.router is None:
            raise RuntimeError(
                "OutlinePlannerSurface.generate requires a ModelRouter; "
                "construct the surface with router=... to use generate()."
            )
        from src.planning.scene_card_generator import SceneCardGenerator

        generator = SceneCardGenerator(self.router)
        scene_cards = await generator.generate(concept_seed)
        outline = self.project_to_outline(scene_cards)
        return self.envelope(
            outline,
            structural_notes=concept_seed.get("structural_notes"),
        )
