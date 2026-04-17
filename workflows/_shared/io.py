"""JSON read/write helpers for surface artifacts.

Surfaces persist to ``data/franchises/<fr>/books/<bk>/workflows/<surface>.json``.
``write_artifact`` runs the surface validator (must return an empty list)
before writing — this prevents an invalid artifact from ever landing on
disk, so the bundle compiler can trust what it reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


class WorkflowValidationError(ValueError):
    """Raised when a surface artifact fails validation prior to write."""

    def __init__(self, surface: str, errors: list[str]):
        self.surface = surface
        self.errors = errors
        message = (
            f"{surface} artifact failed validation; refusing to write.\n  - "
            + "\n  - ".join(errors)
        )
        super().__init__(message)


def write_artifact(
    path: Path,
    artifact: dict,
    *,
    surface: str,
    validator: Callable[[dict], list[str]],
) -> Path:
    """Validate ``artifact`` then write to ``path`` as pretty JSON.

    Creates parent directories as needed. Raises ``WorkflowValidationError``
    when the validator reports any error.
    """
    errors = validator(artifact)
    if errors:
        raise WorkflowValidationError(surface, errors)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact, indent=2, ensure_ascii=False) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path


def read_artifact(path: Path) -> dict:
    """Read a surface artifact from disk. Raises FileNotFoundError if absent."""
    if not path.exists():
        raise FileNotFoundError(f"surface artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
