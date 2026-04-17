"""scene-card-authoring artifact validator."""

from __future__ import annotations

from workflows._shared.schema_loader import collect_errors, load_surface_schema


def validate(artifact: dict) -> list[str]:
    """Validate a scene-card-authoring artifact dict.

    Note: cards are validated against the surface schema (which is more
    permissive than schemas/scene_card.json since the translator fills in
    canonical fields from workshop ones). The bundle compiler runs the
    stricter scene_card.json validation against the translated output.
    """
    schema = load_surface_schema("workflows.scene_card_authoring")
    errors = collect_errors(artifact, schema)

    # Cross-card semantic check: chapter+scene number pairs must be unique.
    seen: set[tuple[int, int]] = set()
    for i, card in enumerate(artifact.get("scene_cards") or []):
        ch = card.get("chapter_number")
        sn = card.get("scene_number")
        if ch is None or sn is None:
            continue
        key = (ch, sn)
        if key in seen:
            errors.append(
                f"scene_cards/{i}: duplicate (chapter={ch}, scene={sn}) pair"
            )
        seen.add(key)

    return errors
