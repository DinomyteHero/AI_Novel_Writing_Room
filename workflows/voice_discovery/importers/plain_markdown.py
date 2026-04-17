"""Build a voice-discovery artifact from a hand-written markdown file."""

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
    """Return a voice-discovery artifact dict from a markdown file."""
    text = read_text(path)
    sections = parse_sections(text)

    voice_kv = parse_kv_block(sections.get("voice", []))
    voice_def: dict = {
        "pov_approach": voice_kv.get("pov_approach", "<EDIT_ME>"),
        "prose_register": voice_kv.get("prose_register", "<EDIT_ME>"),
    }
    for key in (
        "force_description_guidelines",
        "pacing_feel",
        "narrative_voice_notes",
    ):
        if key in voice_kv:
            voice_def[key] = voice_kv[key]

    anti_slop = parse_bullets(sections.get("anti_slop_rules", []))
    if anti_slop:
        voice_def["anti_slop_rules"] = anti_slop

    anti_patterns = parse_bullets(sections.get("anti_patterns", []))
    if anti_patterns:
        voice_def["anti_patterns"] = anti_patterns

    # Reference authors come as `### Author: <Name>` subsections.
    sub3 = parse_sections(text, level=3)
    authors = []
    for title, lines in sub3.items():
        if not title.startswith("author_"):
            continue
        kv = parse_kv_block(lines)
        if "author" not in kv and "name" not in kv:
            continue
        entry: dict = {"author": kv.get("author") or kv.get("name", "")}
        for k in ("what_to_emulate", "what_to_avoid"):
            if k in kv:
                entry[k] = kv[k]
        authors.append(entry)
    if authors:
        voice_def["reference_authors"] = authors

    char_voices_kv = parse_kv_block(sections.get("character_voices", []))
    if char_voices_kv:
        voice_def["character_voices"] = char_voices_kv

    notes = sections.get("narrative_voice_notes")
    if notes and "narrative_voice_notes" not in voice_def:
        voice_def["narrative_voice_notes"] = join_prose(notes)

    return {
        "surface": "voice-discovery",
        "schema_version": "1.0",
        "voice_definition": voice_def,
    }
