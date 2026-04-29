"""Tests for scripts/migrations/migrate_scene_voice_permissions.py."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.migrations import migrate_scene_voice_permissions


def test_build_scene_voice_permissions_from_legacy_fields():
    block = migrate_scene_voice_permissions.build_scene_voice_permissions({
        "notes": "Keep the scene tactile.",
        "anti_patterns": ["No exposition dump"],
        "pov_arc_phase": "lie_questioned",
        "primary_anchor": "Zahn",
        "supporting_anchor": "Luceno, Bujold",
        "stover_permitted": False,
    })

    assert block["notes"] == "Keep the scene tactile."
    assert block["anti_patterns"] == ["No exposition dump"]
    assert block["pov_arc_phase"] == "lie_questioned"
    assert block["anchor_profile"]["primary"] == "Zahn"
    assert block["anchor_profile"]["supporting"] == ["Luceno", "Bujold"]
    assert block["prohibited_modes"] == ["heightened_interiority"]


def test_build_scene_voice_permissions_preserves_existing_generic_fields():
    block = migrate_scene_voice_permissions.build_scene_voice_permissions({
        "notes": "legacy note",
        "primary_anchor": "Legacy Anchor",
        "stover_permitted": False,
        "scene_voice_permissions": {
            "notes": "generic note",
            "anchor_profile": {"primary": "Bujold"},
            "authorized_modes": ["heightened_interiority"],
        },
    })

    assert block["notes"] == "generic note"
    assert block["anchor_profile"]["primary"] == "Bujold"
    assert block["authorized_modes"] == ["heightened_interiority"]
    assert "prohibited_modes" not in block


def test_migrate_scene_card_adds_generic_block_when_missing():
    migrated, changed = migrate_scene_voice_permissions.migrate_scene_card({
        "chapter_number": 1,
        "scene_number": 1,
        "primary_anchor": "Zahn",
        "stover_permitted": True,
    })

    assert changed is True
    assert migrated["scene_voice_permissions"]["anchor_profile"]["primary"] == "Zahn"
    assert migrated["scene_voice_permissions"]["authorized_modes"] == [
        "heightened_interiority"
    ]
    assert migrated["primary_anchor"] == "Zahn"
    assert migrated["stover_permitted"] is True


def test_migrate_scene_card_is_idempotent_when_generic_block_matches():
    card = {
        "chapter_number": 1,
        "scene_number": 1,
        "primary_anchor": "Zahn",
        "stover_permitted": True,
        "scene_voice_permissions": {
            "anchor_profile": {"primary": "Zahn"},
            "authorized_modes": ["heightened_interiority"],
        },
    }
    migrated, changed = migrate_scene_voice_permissions.migrate_scene_card(card)
    assert changed is False
    assert migrated == card


def test_migrate_scene_card_is_noop_without_voice_fields():
    card = {
        "chapter_number": 1,
        "scene_number": 1,
        "mission": "m",
    }
    migrated, changed = migrate_scene_voice_permissions.migrate_scene_card(card)
    assert changed is False
    assert migrated == card
