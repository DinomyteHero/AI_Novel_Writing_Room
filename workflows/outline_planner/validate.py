"""outline-planner artifact validator."""

from __future__ import annotations

from workflows._shared.schema_loader import collect_errors, load_surface_schema


def validate(artifact: dict) -> list[str]:
    """Validate an outline-planner artifact dict.

    Returns a list of error strings. Empty list = valid.
    """
    schema = load_surface_schema("workflows.outline_planner")
    errors = collect_errors(artifact, schema)

    outline = artifact.get("outline") or []
    seen_chapters: set[int] = set()
    for i, entry in enumerate(outline):
        chapter = entry.get("chapter_number")
        if chapter is None:
            continue
        if chapter in seen_chapters:
            errors.append(
                f"outline/{i}: duplicate chapter_number {chapter}"
            )
        seen_chapters.add(chapter)

    # Subplot cross-references in outline entries should point to known
    # subplot_ids when subplots[] is populated.
    subplot_ids = {sp.get("subplot_id") for sp in artifact.get("subplots") or []}
    if subplot_ids:
        for i, entry in enumerate(outline):
            for ref in entry.get("subplot_ids") or []:
                if ref not in subplot_ids:
                    errors.append(
                        f"outline/{i}/subplot_ids: unknown subplot_id {ref!r}"
                    )

    return errors
