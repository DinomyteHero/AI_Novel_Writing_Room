"""Build a scene-card-authoring artifact from a hand-written markdown file."""

from __future__ import annotations

import re
from pathlib import Path

from workflows._shared.markdown_parser import (
    parse_kv_block,
    parse_sections,
    read_text,
)

_SCENE_TITLE = re.compile(r"^chapter_(\d+)_scene_(\d+)(?:_.*)?$")


def import_from_markdown(path: str | Path) -> dict:
    """Return a scene-card-authoring artifact dict from a markdown file."""
    text = read_text(path)
    sections = parse_sections(text)

    scene_cards: list[dict] = []
    for title, lines in sections.items():
        match = _SCENE_TITLE.match(title)
        if not match:
            continue
        ch = int(match.group(1))
        sn = int(match.group(2))
        kv = parse_kv_block(lines)
        card: dict = {
            "chapter_number": ch,
            "scene_number": sn,
            "pov_character": kv.get("pov_character", "<EDIT_ME>"),
        }
        for k in (
            "structural_phase", "scene_type", "scene_role",
            "mission", "scene_goal", "why_now",
            "conflict", "scene_conflict", "conflict_type",
            "dialogue_expectation", "turning_point",
            "opening_hook", "closing_hook",
            "setting", "location", "sensory_details",
            "emotional_trajectory", "pov_arc_phase", "arc_phase",
            "thematic_beat", "scene_outcome", "notes",
        ):
            if k in kv:
                card[k] = kv[k]
        if "target_word_count" in kv:
            try:
                card["target_word_count"] = int(kv["target_word_count"])
            except ValueError:
                pass
        scene_cards.append(card)

    scene_cards.sort(key=lambda c: (c["chapter_number"], c["scene_number"]))

    return {
        "surface": "scene-card-authoring",
        "schema_version": "1.0",
        "scene_cards": scene_cards,
    }
