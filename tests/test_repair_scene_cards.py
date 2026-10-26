"""Tests for scene-card repair driven by the Story Brief rather than legacy files."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.repair_scene_cards import repair_cards
from src.planning import story_brief as sb


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "book"
    book.mkdir()
    (book / "concept_seed.json").write_text(json.dumps({
        "ensemble_cast": [{
            "name": "Mara Vance",
            "weiland_arc": {"arc_phase_map": {"lie": "Ch 1 (Setup)"}},
        }],
    }), encoding="utf-8")
    brief = sb.new_brief("Demo", "Original")
    sb.add_claim(brief, entity_type="character", entity_id="mara_vance",
                 field="name", value="Mara Vance")
    sb.add_claim(brief, entity_type="character", entity_id="mara_vance",
                 field="fear", value="That she is only useful when she is lying.")
    sb.add_claim(brief, entity_type="character", entity_id="mara_vance",
                 field="private_wound", value="She chose the job over her daughter.")
    sb.add_claim(brief, entity_type="character", entity_id="mara_vance",
                 field="arc_phase_map", value={"lie": "Ch 1 (Setup)"})
    path = book / "workflows" / "idea_session" / "story_brief.json"
    sb.save_brief(path, brief)
    cards = book / "scene_cards"
    cards.mkdir()
    (cards / "chapter_02_scene_01.json").write_text(json.dumps({
        "chapter_number": 2,
        "scene_number": 1,
        "pov_character": "Mara Vance",
        "stakes": {},
        "sensory_details": "",
        "turning_point": "The door opens. # Act 2 planning leak",
        "closing_hook": "She steps through. # Act 2",
    }), encoding="utf-8")
    return book


def test_repair_uses_story_brief(tmp_path: Path):
    book = _book(tmp_path)
    changed = repair_cards(book)
    assert changed == 1
    card = json.loads(
        (book / "scene_cards" / "chapter_02_scene_01.json").read_text(encoding="utf-8")
    )
    assert "Fear:" in card["stakes"]["personal"]
    assert card["pov_arc_phase"] == "Mara Vance:lie"
    assert "# Act" not in card["turning_point"]
    assert "# Act" not in card["closing_hook"]
