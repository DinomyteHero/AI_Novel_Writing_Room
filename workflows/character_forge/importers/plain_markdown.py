"""Build a character-forge artifact from a hand-written markdown file."""

from __future__ import annotations

from pathlib import Path

from workflows._shared.markdown_parser import (
    parse_bullets,
    parse_kv_block,
    parse_sections,
    read_text,
)


def import_from_markdown(path: str | Path) -> dict:
    """Return a character-forge artifact dict from a markdown file."""
    text = read_text(path)
    sections = parse_sections(text)

    cast: list[dict] = []
    for title, lines in sections.items():
        if not title.startswith("character_"):
            continue
        kv = parse_kv_block(lines)
        if "name" not in kv:
            continue
        char: dict = {
            "name": kv["name"],
            "role": kv.get("role", "<EDIT_ME>"),
            "three_dimensions": {
                "surface": kv.get("surface", "<EDIT_ME>"),
                "backstory_inner_demons": kv.get("backstory_inner_demons", "<EDIT_ME>"),
                "action_under_pressure": kv.get("action_under_pressure", "<EDIT_ME>"),
            },
        }
        for k in ("age", "force_status", "voice_notes"):
            if k in kv:
                char[k] = kv[k]
        weiland: dict = {}
        for k in ("lie_believed", "ghost", "want", "need", "arc_type", "arc_summary", "initial_phase"):
            if k in kv:
                weiland[k] = kv[k]
        if weiland:
            char["weiland_arc"] = weiland
        cast.append(char)

    if not cast:
        raise ValueError(
            f"no '## Character: <Name>' sections found in {path}; "
            "character-forge import requires at least 2 characters"
        )

    artifact: dict = {
        "surface": "character-forge",
        "schema_version": "1.0",
        "ensemble_cast": cast,
    }

    referenced = parse_bullets(sections.get("referenced_characters", []))
    if referenced:
        artifact["referenced_characters"] = [{"name": name} for name in referenced]

    return artifact
