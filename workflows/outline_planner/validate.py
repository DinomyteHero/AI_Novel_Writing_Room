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

    # Multi-POV braiding consistency. When both pov_sequence and scene_briefs
    # are present, each scene_brief's pov must match the corresponding
    # pov_sequence entry. When pov_sequence is present alone, scene-card
    # authoring will derive scenes from it, so we only validate the join when
    # both fields are present.
    for i, entry in enumerate(outline):
        pov_sequence = entry.get("pov_sequence") or []
        scene_briefs = entry.get("scene_briefs") or []
        if not (pov_sequence and scene_briefs):
            continue
        for brief in scene_briefs:
            scene_num = brief.get("scene_number")
            if scene_num is None or scene_num < 1:
                continue
            if scene_num > len(pov_sequence):
                errors.append(
                    f"outline/{i}/scene_briefs: scene_number {scene_num} "
                    f"exceeds pov_sequence length {len(pov_sequence)}"
                )
                continue
            expected_pov = pov_sequence[scene_num - 1]
            actual_pov = brief.get("pov")
            if actual_pov and actual_pov != expected_pov:
                errors.append(
                    f"outline/{i}/scene_briefs/scene_{scene_num}: "
                    f"pov {actual_pov!r} does not match pov_sequence "
                    f"entry {expected_pov!r}"
                )

    # When pov_sequence is set but pov_character is not, derive a soft
    # warning - pov_character should be the framing POV, defaulting to the
    # first entry in pov_sequence when omitted.
    for i, entry in enumerate(outline):
        pov_sequence = entry.get("pov_sequence") or []
        if pov_sequence and not entry.get("pov_character"):
            # Not an error - the bundle compiler can derive pov_character
            # from pov_sequence[0] - but worth flagging so authors are
            # explicit about which POV frames the chapter.
            pass

    return errors
