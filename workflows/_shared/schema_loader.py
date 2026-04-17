"""Schema loading + validation helpers shared across workflow surfaces.

Each surface ships a ``schema.json`` next to its ``api.py``. The
``validate.py`` modules load that schema once and run ``jsonschema.validate``
against the artifact dict. ``collect_errors`` returns all errors at once
rather than raising on the first one — surface validators want to surface
the full list to the operator (or to the bundle compiler).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import jsonschema


@lru_cache(maxsize=None)
def load_surface_schema(surface_pkg: str) -> dict:
    """Load the schema.json sitting next to a surface's api.py.

    ``surface_pkg`` is the import path of the surface package, e.g.
    ``workflows.universe_builder``. Cached so repeated validations within
    one process don't re-parse the same JSON.
    """
    parts = surface_pkg.split(".")
    schema_path = Path(__file__).resolve().parent.parent
    for part in parts[1:]:  # drop the leading 'workflows'
        schema_path = schema_path / part
    schema_path = schema_path / "schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def collect_errors(artifact: dict, schema: dict) -> list[str]:
    """Run jsonschema.validate against ``artifact`` and return all errors.

    Returns an empty list when the artifact validates. Each error string
    is formatted as ``"<json-path>: <message>"`` so callers can render
    them line-by-line in compile reports.
    """
    validator = jsonschema.Draft7Validator(schema)
    errors: list[str] = []
    for err in validator.iter_errors(artifact):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{path}: {err.message}")
    return errors
