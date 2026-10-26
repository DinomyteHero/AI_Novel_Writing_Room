"""Tests for importing legacy character/voice artifacts into a Story Brief."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.migrate_legacy_character_data import migrate
from src.planning import story_brief as sb


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "data" / "franchises" / "original" / "books" / "demo"
    book.mkdir(parents=True)
    seed = {
        "meta": {"project_title": "Demo", "franchise": "Original"},
        "premise": {"what_if": "A spy must protect the daughter she abandoned."},
        "theme": {"thematic_premise": "Love is not a security operation."},
        "voice_definition": {
            "pov_approach": "Close third, single POV, past tense.",
            "prose_register": "Tense commercial thriller.",
            "reference_authors": ["Zahn"],
        },
        "ensemble_cast": [{
            "name": "Mara Vance",
            "role": "Protagonist",
            "weiland_arc": {
                "arc_type": "change",
                "arc_phase_map": {"lie": "Ch 1 (Setup)"},
            },
        }],
    }
    (book / "concept_seed.json").write_text(json.dumps(seed), encoding="utf-8")
    capture = book / "workflows" / "idea_session" / "capture.json"
    capture.parent.mkdir(parents=True)
    capture.write_text(json.dumps({
        "north_star": {
            "one_sentence_pitch": "A retired spy is pulled back in by her daughter.",
            "reader_promise": "A tense spy thriller with an earned ending.",
            "emotional_core": "Can you love someone without trying to save them?",
        }
    }), encoding="utf-8")
    sheets = book / "character_sheets"
    sheets.mkdir()
    (sheets / "mara_vance.json").write_text(json.dumps({
        "id": "mara_vance",
        "name": "Mara Vance",
        "role": "Protagonist",
        "arc_type": "change",
        "three_dimensions": {
            "surface": "A controlled former operative.",
            "backstory_inner_demons": "She left her daughter to finish a job.",
            "action_under_pressure": "She lies first, then moves.",
        },
        "voice_notes": "Short, dry, controlled.",
    }), encoding="utf-8")
    (book / "voice_profiles.json").write_text(json.dumps([{
        "id": "mara_vance",
        "name": "Mara Vance",
        "fields": {
            "Surface want": "To get her daughter out.",
            "Deeper want": "To stop treating love as an operation.",
            "Fear": "That she is only useful when she is lying.",
            "Private wound": "She chose the job over her daughter.",
        },
    }]), encoding="utf-8")
    return book


def test_migrate_writes_brief_and_sheets_then_removes_legacy(tmp_path: Path):
    book = _book(tmp_path)
    report = migrate(book, remove_legacy=True)

    assert report["claims_added"] > 0
    brief_path = book / "workflows" / "idea_session" / "story_brief.json"
    brief = sb.load_brief(brief_path)
    assert sb.resolve_value(brief, "character", "mara_vance", "name") == "Mara Vance"
    assert "daughter" in sb.resolve_value(brief, "character", "mara_vance", "want").lower()
    assert (brief_path.parent / "sheets" / "characters" / "mara_vance.md").exists()
    assert not (book / "character_sheets").exists()
    assert not (book / "voice_profiles.json").exists()


def test_dry_run_writes_nothing(tmp_path: Path):
    book = _book(tmp_path)
    report = migrate(book, dry_run=True, remove_legacy=True)
    assert report["dry_run"] is True
    assert not (book / "workflows" / "idea_session" / "story_brief.json").exists()
    assert (book / "character_sheets").exists()
    assert (book / "voice_profiles.json").exists()


def test_secondary_migration_does_not_duplicate(tmp_path: Path):
    book = _book(tmp_path)
    first = migrate(book)
    second = migrate(book)
    assert first["claims_added"] > 0
    assert second["claims_added"] == 0
