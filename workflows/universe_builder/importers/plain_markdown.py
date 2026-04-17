"""Build a universe-builder artifact from a hand-written markdown file.

See ``importers/README.md`` for the expected markdown shape.
"""

from __future__ import annotations

from pathlib import Path

from workflows._shared.markdown_parser import (
    join_prose,
    parse_bullets,
    parse_kv_block,
    parse_sections,
    read_text,
)


def import_from_markdown(path: str | Path) -> dict:
    """Return a universe-builder artifact dict from a markdown file."""
    text = read_text(path)
    sections = parse_sections(text)

    project = parse_kv_block(sections.get("project", []))
    universe = parse_kv_block(sections.get("universe", []))
    premise_block = parse_kv_block(sections.get("premise", []))
    conflict_block = parse_kv_block(sections.get("conflict", []))
    theme_block = parse_kv_block(sections.get("theme", []))
    secondary_pressures = parse_bullets(sections.get("secondary_pressures", []))

    meta: dict = {}
    for src_key, dst_key in (
        ("title", "project_title"),
        ("franchise", "franchise"),
        ("canon_status", "canon_status"),
        ("era", "era"),
        ("tone", "tone"),
        ("target_word_count", "target_word_count"),
        ("target_chapters", "target_chapters"),
        ("pov_structure", "pov_structure"),
        ("project_scope", "project_scope"),
        ("series_id", "series_id"),
        ("cosmology_id", "cosmology_id"),
    ):
        if src_key in project:
            value = project[src_key]
            if dst_key in ("target_word_count", "target_chapters"):
                value = int(value)
            meta[dst_key] = value

    universe_meta: dict = {
        "universe_name": universe.get("name") or meta.get("franchise", ""),
        "franchise": universe.get("franchise") or meta.get("franchise", ""),
    }
    if "canon_status" in universe:
        universe_meta["canon_status"] = universe["canon_status"]
    elif "canon_status" in meta:
        universe_meta["canon_status"] = meta["canon_status"]
    if "commercial_intent" in universe:
        universe_meta["commercial_intent"] = universe["commercial_intent"]
    if "notes" in universe:
        universe_meta["notes"] = universe["notes"]
    if "cosmology_id" in universe:
        universe_meta["cosmology_id"] = universe["cosmology_id"]
    elif "cosmology_id" in meta:
        universe_meta["cosmology_id"] = meta["cosmology_id"]

    artifact: dict = {
        "surface": "universe-builder",
        "schema_version": "1.0",
        "meta": meta,
        "universe_meta": universe_meta,
    }

    premise: dict = {}
    if "what_if" in premise_block:
        premise["what_if"] = premise_block["what_if"]
    if "central_dramatic_question" in premise_block:
        premise["central_dramatic_question"] = premise_block["central_dramatic_question"]
    if "logline" in premise_block:
        premise["logline"] = premise_block["logline"]
    if premise:
        artifact["premise"] = premise

    conflict: dict = {}
    if any(k in conflict_block for k in ("type", "identity", "motivation", "escalation")):
        force: dict = {}
        for k in ("type", "identity", "motivation", "escalation"):
            if k in conflict_block:
                force[k] = conflict_block[k]
        conflict["primary_antagonistic_force"] = force
    if secondary_pressures:
        conflict["secondary_pressures"] = secondary_pressures
    if "lock_in_mechanism" in conflict_block:
        conflict["lock_in_mechanism"] = conflict_block["lock_in_mechanism"]
    if conflict:
        artifact["conflict"] = conflict

    theme: dict = {}
    if "thematic_premise" in theme_block:
        theme["thematic_premise"] = theme_block["thematic_premise"]
    if "thematic_argument" in theme_block:
        theme["thematic_argument"] = theme_block["thematic_argument"]
    if theme:
        artifact["theme"] = theme

    notes_lines = sections.get("notes")
    if notes_lines:
        artifact.setdefault("universe_meta", universe_meta)["notes"] = join_prose(notes_lines)

    return artifact
