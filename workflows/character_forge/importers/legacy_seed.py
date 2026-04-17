"""Extract a character-forge artifact from a legacy concept_seed.json.

Pulls ensemble_cast (required), referenced_characters (optional), and
relationship_arcs (optional). Raises ValueError when ensemble_cast is
missing — the surface schema requires it.
"""

from __future__ import annotations

from workflows._shared.legacy_seed_loader import pick


def import_from_seed(seed: dict) -> dict:
    """Return a character-forge artifact dict extracted from ``seed``."""
    ensemble_cast = pick(seed, "ensemble_cast")
    if not ensemble_cast:
        raise ValueError(
            "legacy seed missing ensemble_cast; cannot import character-forge slice"
        )

    artifact: dict = {
        "surface": "character-forge",
        "schema_version": "1.0",
        "ensemble_cast": ensemble_cast,
    }

    referenced = pick(seed, "referenced_characters")
    if referenced is not None:
        artifact["referenced_characters"] = referenced

    relationship_arcs = pick(seed, "relationship_arcs")
    if relationship_arcs is not None:
        artifact["relationship_arcs"] = relationship_arcs

    return artifact
