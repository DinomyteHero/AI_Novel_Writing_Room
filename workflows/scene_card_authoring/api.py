"""scene-card-authoring programmatic API.

Owns the per-scene cards. Persists each card as
``workflows/scene_cards/chapter_NN_scene_NN.json`` on write. Façade over
``src.planning.scene_card_generator.SceneCardGenerator`` for generate()
and ``workflows._shared.scene_card_translator.translate_scene_card`` for
translate().
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.project_paths import ProjectPaths
from workflows._shared.io import WorkflowValidationError, read_artifact, write_artifact
from workflows._shared.scene_card_translator import translate_scene_card
from workflows.scene_card_authoring.validate import validate

if TYPE_CHECKING:
    from src.model_router import ModelRouter
    from src.planning.physics_enforcer import PhysicsEnforcer

ENVELOPE_NAME = "scene_cards.json"
CARDS_SUBDIR = "scene_cards"


class SceneCardAuthoring:
    """Read/write/generate the scene-card-authoring artifact for a project."""

    def __init__(
        self,
        paths: ProjectPaths,
        router: "ModelRouter | None" = None,
        physics_enforcer: "PhysicsEnforcer | None" = None,
    ):
        self.paths = paths
        self.router = router
        self.physics_enforcer = physics_enforcer

    @property
    def envelope_path(self) -> Path:
        """Single-file envelope path. Holds the canonical card list as
        emitted by importers / generators before per-card extraction."""
        return self.paths.workflows_dir / ENVELOPE_NAME

    @property
    def cards_dir(self) -> Path:
        """Per-card directory (one file per scene). Mirrors
        ``schemas/scene_card.json`` shape via the translator."""
        return self.paths.workflows_dir / CARDS_SUBDIR

    @staticmethod
    def envelope(
        scene_cards: list[dict],
        *,
        structural_overrides: dict | None = None,
    ) -> dict:
        """Wrap a card list in the surface envelope."""
        artifact: dict = {
            "surface": "scene-card-authoring",
            "schema_version": "1.0",
            "scene_cards": scene_cards,
        }
        if structural_overrides:
            artifact["structural_overrides"] = structural_overrides
        return artifact

    def read(self) -> dict:
        """Read the single-file envelope. Raises FileNotFoundError if absent."""
        return read_artifact(self.envelope_path)

    def write(self, data: dict) -> Path:
        """Write the envelope file (validating first)."""
        return write_artifact(
            self.envelope_path,
            data,
            surface="scene-card-authoring",
            validator=validate,
        )

    def write_per_card(
        self,
        cards: list[dict],
        *,
        structural_overrides: dict | None = None,
    ) -> list[Path]:
        """Translate each card and write one file per (chapter, scene).

        Mirrors ``scripts/install_seed.py`` extraction behaviour: each card
        passes through ``translate_scene_card`` (canonical-first /
        workshop-fallback merging) before being written. The bundle compiler
        reuses this method for the canonical scene_cards/ tree at the book
        root.
        """
        # Validate the envelope shape before writing anything to disk.
        envelope_errors = validate(self.envelope(cards, structural_overrides=structural_overrides))
        if envelope_errors:
            raise WorkflowValidationError("scene-card-authoring", envelope_errors)

        self.cards_dir.mkdir(parents=True, exist_ok=True)
        out_paths: list[Path] = []
        for card in cards:
            translated = translate_scene_card(
                card, structural_overrides=structural_overrides
            )
            ch = translated["chapter_number"]
            sn = translated["scene_number"]
            filename = f"chapter_{ch:02d}_scene_{sn:02d}.json"
            path = self.cards_dir / filename
            path.write_text(
                json.dumps(translated, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            out_paths.append(path)
        return out_paths

    def read_per_card(self) -> list[dict]:
        """Read all per-card files in sorted order. Returns empty list if
        the directory is absent or empty."""
        if not self.cards_dir.exists():
            return []
        cards: list[dict] = []
        for path in sorted(self.cards_dir.glob("chapter_*_scene_*.json")):
            cards.append(json.loads(path.read_text(encoding="utf-8")))
        return cards

    def translate(
        self,
        raw_cards: list[dict],
        *,
        structural_overrides: dict | None = None,
    ) -> list[dict]:
        """Pass-through to the shared scene_card_translator."""
        return [
            translate_scene_card(card, structural_overrides=structural_overrides)
            for card in raw_cards
        ]

    async def generate(
        self, concept_seed: dict, *, max_retries: int = 3, chunk_size: int = 7,
    ) -> list[dict]:
        """Run SceneCardGenerator and return the card list (no write)."""
        if self.router is None:
            raise RuntimeError(
                "SceneCardAuthoring.generate requires a ModelRouter; "
                "construct the surface with router=... to use generate()."
            )
        from src.planning.scene_card_generator import SceneCardGenerator

        generator = SceneCardGenerator(self.router, self.physics_enforcer)
        return await generator.generate(
            concept_seed, max_retries=max_retries, chunk_size=chunk_size,
        )
