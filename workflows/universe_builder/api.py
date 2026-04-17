"""universe-builder programmatic API.

Owns ``meta`` + ``universe_meta`` for a project. The bundle compiler reads
``workflows/universe.json`` and uses ``meta`` to seed concept_seed.json's
top-level meta and ``universe_meta`` to write franchise_meta.json.

Provides ``init_from_template`` so init_project.py and any other scaffold
caller can build a baseline artifact from canon_profile + voice templates
without re-implementing meta assembly.
"""

from __future__ import annotations

from pathlib import Path

from src.project_paths import ProjectPaths
from workflows._shared.io import read_artifact, write_artifact
from workflows.universe_builder.validate import validate

ARTIFACT_NAME = "universe.json"

DEFAULT_CANON_STATUS_BY_DEPTH: dict[str, str] = {
    "fanfic_elseworlds": "AU",
    "fanfic_compliant": "canon_compliant",
    "original_deep": "original",
    "original_light": "original",
    "realistic": "original",
}


class UniverseBuilder:
    """Read/write/init the universe-builder artifact for a project."""

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
            surface="universe-builder",
            validator=validate,
        )

    @staticmethod
    def init_from_template(
        *,
        title: str,
        franchise: str,
        depth: str,
        tone: str = "heroic_with_weight",
        target_word_count: int = 100000,
        target_chapters: int | None = None,
        cosmology_id: str | None = None,
        series_id: str | None = None,
        commercial_intent: str = "fanfiction_noncommercial",
        notes: str = "",
    ) -> dict:
        """Build a baseline universe-builder artifact dict.

        Does not write to disk; callers (init_project.py, importers, tests)
        validate and persist via ``UniverseBuilder.write``.
        """
        if depth not in DEFAULT_CANON_STATUS_BY_DEPTH:
            raise ValueError(
                f"unknown depth template {depth!r}; "
                f"expected one of {sorted(DEFAULT_CANON_STATUS_BY_DEPTH)}"
            )
        canon_status = DEFAULT_CANON_STATUS_BY_DEPTH[depth]

        meta: dict = {
            "project_title": title,
            "franchise": franchise,
            "canon_status": canon_status,
            "era": "<EDIT_ME>",
            "tone": tone,
            "target_word_count": target_word_count,
        }
        if target_chapters is not None:
            meta["target_chapters"] = target_chapters
        if cosmology_id:
            meta["cosmology_id"] = cosmology_id
        if series_id:
            meta["series_id"] = series_id

        universe_meta: dict = {
            "universe_name": franchise,
            "franchise": franchise,
            "canon_status": canon_status,
            "commercial_intent": commercial_intent,
            "notes": notes,
        }
        if cosmology_id:
            universe_meta["cosmology_id"] = cosmology_id

        return {
            "surface": "universe-builder",
            "schema_version": "1.0",
            "meta": meta,
            "universe_meta": universe_meta,
        }
