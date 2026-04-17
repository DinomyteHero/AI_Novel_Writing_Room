"""Extract a voice-discovery artifact from a legacy concept_seed.json.

Pulls the voice_definition slice verbatim. Raises ValueError when the
seed has no voice_definition — voice is required for the bundle to
compile (the pipeline depends on it).
"""

from __future__ import annotations

from workflows._shared.legacy_seed_loader import pick


def import_from_seed(seed: dict) -> dict:
    """Return a voice-discovery artifact dict extracted from ``seed``."""
    voice_definition = pick(seed, "voice_definition")
    if voice_definition is None:
        raise ValueError(
            "legacy seed missing voice_definition; cannot import voice-discovery slice"
        )

    return {
        "surface": "voice-discovery",
        "schema_version": "1.0",
        "voice_definition": voice_definition,
    }
