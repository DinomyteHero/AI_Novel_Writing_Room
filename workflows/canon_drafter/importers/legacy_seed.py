"""Extract a canon-drafter artifact from a legacy concept_seed.json.

Pulls canon_profile, canon_constraints, force_mechanics, and
terminology_registry slices verbatim. Each slice is optional except
canon_constraints (the schema requires it); when canon_constraints is
absent in the seed, the importer raises ValueError so the operator
notices rather than silently producing an invalid artifact.
"""

from __future__ import annotations

from workflows._shared.legacy_seed_loader import pick


def import_from_seed(seed: dict) -> dict:
    """Return a canon-drafter artifact dict extracted from ``seed``."""
    canon_constraints = pick(seed, "canon_constraints")
    if canon_constraints is None:
        raise ValueError(
            "legacy seed missing required canon_constraints; "
            "cannot import canon-drafter slice"
        )

    artifact: dict = {
        "surface": "canon-drafter",
        "schema_version": "1.0",
        "canon_constraints": canon_constraints,
    }

    canon_profile = pick(seed, "canon_profile")
    if canon_profile is not None:
        artifact["canon_profile"] = canon_profile

    force_mechanics = pick(seed, "force_mechanics")
    if force_mechanics is not None:
        artifact["force_mechanics"] = force_mechanics

    terminology = pick(seed, "terminology_registry")
    if terminology is not None:
        artifact["terminology_registry"] = terminology

    return artifact
