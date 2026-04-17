"""universe-builder artifact validator."""

from __future__ import annotations

from workflows._shared.schema_loader import collect_errors, load_surface_schema


def validate(artifact: dict) -> list[str]:
    """Validate a universe-builder artifact dict.

    Returns a list of error strings. Empty list = valid.
    """
    schema = load_surface_schema("workflows.universe_builder")
    errors = collect_errors(artifact, schema)

    meta = artifact.get("meta", {}) or {}
    universe_meta = artifact.get("universe_meta", {}) or {}

    # Cross-field semantic check: meta.franchise should match universe_meta.franchise.
    meta_franchise = meta.get("franchise")
    um_franchise = universe_meta.get("franchise")
    if meta_franchise and um_franchise and meta_franchise != um_franchise:
        errors.append(
            "meta.franchise != universe_meta.franchise "
            f"({meta_franchise!r} vs {um_franchise!r}); they must agree."
        )

    # Cross-field semantic check: meta.canon_status should match universe_meta.canon_status when both set.
    meta_canon = meta.get("canon_status")
    um_canon = universe_meta.get("canon_status")
    if meta_canon and um_canon and meta_canon != um_canon:
        errors.append(
            "meta.canon_status != universe_meta.canon_status "
            f"({meta_canon!r} vs {um_canon!r}); they must agree."
        )

    return errors
