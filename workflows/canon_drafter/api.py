"""canon-drafter programmatic API.

Owns canon_profile + canon_constraints + terminology_registry +
force_mechanics. Persists to ``workflows/canon.json``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from src.project_paths import ProjectPaths
from workflows._shared.io import read_artifact, write_artifact
from workflows.canon_drafter.validate import validate

ARTIFACT_NAME = "canon.json"

REPO_ROOT = Path(__file__).resolve().parents[2]
CANON_PROFILE_TEMPLATES_DIR = REPO_ROOT / "templates" / "canon_profile"


class CanonDrafter:
    """Read/write/edit the canon-drafter artifact for a project."""

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
            surface="canon-drafter",
            validator=validate,
        )

    @staticmethod
    def apply_template(
        template_name: str,
        *,
        canon_constraints: dict | None = None,
    ) -> dict:
        """Build a baseline canon-drafter artifact from a canon_profile template.

        ``template_name`` matches the file stem under templates/canon_profile/
        (e.g. 'fanfic_elseworlds', 'original_deep'). The returned artifact
        always carries a non-empty canon_constraints (the schema requires it);
        callers can override via the ``canon_constraints`` kwarg.
        """
        template_path = CANON_PROFILE_TEMPLATES_DIR / f"{template_name}.json"
        if not template_path.exists():
            available = sorted(p.stem for p in CANON_PROFILE_TEMPLATES_DIR.glob("*.json"))
            raise FileNotFoundError(
                f"canon_profile template not found: {template_name!r} "
                f"(available: {available})"
            )
        canon_profile = json.loads(template_path.read_text(encoding="utf-8"))
        canon_profile.pop("_template_notes", None)

        return {
            "surface": "canon-drafter",
            "schema_version": "1.0",
            "canon_profile": canon_profile,
            "canon_constraints": copy.deepcopy(canon_constraints) if canon_constraints else {
                "continuity": "<EDIT_ME>",
                "canon_preserved": [],
                "style_constraints": [],
            },
        }

    def add_term(self, term: dict) -> dict:
        """Append a term to the artifact's terminology_registry, then write."""
        artifact = self.read()
        registry = artifact.setdefault("terminology_registry", [])
        registry.append(copy.deepcopy(term))
        self.write(artifact)
        return artifact
