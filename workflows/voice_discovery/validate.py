"""voice-discovery artifact validator."""

from __future__ import annotations

from workflows._shared.schema_loader import collect_errors, load_surface_schema


def validate(artifact: dict) -> list[str]:
    """Validate a voice-discovery artifact dict.

    Returns a list of error strings. Empty list = valid.
    """
    schema = load_surface_schema("workflows.voice_discovery")
    return collect_errors(artifact, schema)
