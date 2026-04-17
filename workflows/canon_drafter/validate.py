"""canon-drafter artifact validator."""

from __future__ import annotations

from workflows._shared.schema_loader import collect_errors, load_surface_schema


def validate(artifact: dict) -> list[str]:
    """Validate a canon-drafter artifact dict.

    Returns a list of error strings. Empty list = valid.
    """
    schema = load_surface_schema("workflows.canon_drafter")
    errors = collect_errors(artifact, schema)

    # Each terminology_registry entry must supply either ``term`` or
    # ``canonical_form`` (the schema accepts either; semantic check enforces
    # at least one is present).
    for i, entry in enumerate(artifact.get("terminology_registry") or []):
        if not entry.get("term") and not entry.get("canonical_form"):
            errors.append(
                f"terminology_registry/{i}: must supply either 'term' or 'canonical_form'"
            )

    return errors
