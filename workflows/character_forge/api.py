"""character-forge programmatic API.

Owns the ensemble_cast slice (plus optional referenced_characters and
relationship_arcs). Persists to ``workflows/characters.json``.
"""

from __future__ import annotations

import copy
from pathlib import Path

from src.project_paths import ProjectPaths
from workflows._shared.io import read_artifact, write_artifact
from workflows.character_forge.validate import validate, validate_arc_coverage

ARTIFACT_NAME = "characters.json"


class CharacterForge:
    """Read/write/edit the character-forge artifact for a project."""

    def __init__(self, paths: ProjectPaths):
        self.paths = paths

    @property
    def artifact_path(self) -> Path:
        return self.paths.workflows_dir / ARTIFACT_NAME

    def read(self) -> dict:
        return read_artifact(self.artifact_path)

    def write(self, data: dict) -> Path:
        return write_artifact(
            self.artifact_path,
            data,
            surface="character-forge",
            validator=validate,
        )

    @staticmethod
    def envelope(
        ensemble_cast: list[dict],
        *,
        referenced_characters: list[dict] | None = None,
        relationship_arcs: list[dict] | None = None,
    ) -> dict:
        """Wrap an ensemble_cast list in the surface envelope."""
        artifact: dict = {
            "surface": "character-forge",
            "schema_version": "1.0",
            "ensemble_cast": copy.deepcopy(ensemble_cast),
        }
        if referenced_characters:
            artifact["referenced_characters"] = copy.deepcopy(referenced_characters)
        if relationship_arcs:
            artifact["relationship_arcs"] = copy.deepcopy(relationship_arcs)
        return artifact

    def add_character(self, character: dict) -> dict:
        """Append a character to the artifact's ensemble_cast, then write."""
        artifact = self.read()
        cast = artifact.setdefault("ensemble_cast", [])
        cast.append(copy.deepcopy(character))
        self.write(artifact)
        return artifact

    @staticmethod
    def validate_arc_coverage(
        cast: list[dict], target_chapters: int | None,
    ) -> list[str]:
        """Wrapper around the validate.py helper for surface-level use."""
        return validate_arc_coverage(cast, target_chapters)
