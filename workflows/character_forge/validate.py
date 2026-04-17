"""character-forge artifact validator."""

from __future__ import annotations

from workflows._shared.schema_loader import collect_errors, load_surface_schema

# Phase vocabularies per arc_type — mirrors the doc on
# concept_seed.json#/properties/ensemble_cast/items/properties/weiland_arc/properties/arc_phase_map
_ARC_PHASE_VOCAB: dict[str, set[str]] = {
    "positive_change": {
        "lie_established", "lie_reinforced", "lie_challenged",
        "moment_of_truth", "new_truth_demonstrated", "arc_resolved",
    },
    "flat": {
        "lie_established", "lie_reinforced", "lie_challenged",
        "moment_of_truth", "new_truth_demonstrated", "arc_resolved",
    },
    "corruption": {
        "lie_established", "lie_reinforced", "lie_deepened",
        "point_of_no_return", "lie_acted_upon", "lie_consequence",
        "arc_resolved_tragic",
    },
    "fall": {
        "lie_established", "lie_reinforced", "lie_deepened",
        "point_of_no_return", "lie_acted_upon", "lie_consequence",
        "arc_resolved_tragic",
    },
    "disillusionment": {
        "lie_established", "lie_reinforced", "lie_challenged",
        "truth_glimpsed", "bleaker_truth_accepted", "arc_resolved_bleak",
    },
    "negative": {
        "lie_established", "lie_reinforced", "lie_tested", "lie_unchanged",
    },
}


def validate(artifact: dict) -> list[str]:
    """Validate a character-forge artifact dict.

    Returns a list of error strings. Empty list = valid.
    """
    schema = load_surface_schema("workflows.character_forge")
    errors = collect_errors(artifact, schema)

    # Per-character semantic checks: arc_phase_map keys must be drawn from
    # the canonical vocabulary for the character's arc_type.
    for i, char in enumerate(artifact.get("ensemble_cast") or []):
        weiland = char.get("weiland_arc") or {}
        arc_type = weiland.get("arc_type")
        phase_map = weiland.get("arc_phase_map") or {}
        if not phase_map or arc_type not in _ARC_PHASE_VOCAB:
            continue
        allowed = _ARC_PHASE_VOCAB[arc_type]
        for phase in phase_map:
            if phase not in allowed:
                name = char.get("name", f"#{i}")
                errors.append(
                    f"ensemble_cast/{i}/weiland_arc/arc_phase_map: "
                    f"character {name!r} has unknown phase {phase!r} for arc_type {arc_type!r}"
                )

    return errors


def validate_arc_coverage(
    cast: list[dict], target_chapters: int | None,
) -> list[str]:
    """Optional completeness check for arc coverage across the chapter target.

    Warns when a character has weiland_arc but no arc_phase_map, or when
    arc_phase_map has fewer than 4 phases for a target_chapters >= 20 book.
    Returns warning strings (not blocking errors) — surface in compile_report
    but don't fail validation.
    """
    warnings: list[str] = []
    if not target_chapters or target_chapters < 20:
        return warnings
    for i, char in enumerate(cast):
        weiland = char.get("weiland_arc") or {}
        if not weiland:
            continue
        phase_map = weiland.get("arc_phase_map") or {}
        if not phase_map:
            warnings.append(
                f"ensemble_cast/{i} ({char.get('name', '?')}): "
                "weiland_arc present but arc_phase_map missing"
            )
            continue
        if len(phase_map) < 4:
            warnings.append(
                f"ensemble_cast/{i} ({char.get('name', '?')}): "
                f"arc_phase_map has only {len(phase_map)} phases for "
                f"{target_chapters} chapters; expected at least 4"
            )
    return warnings
