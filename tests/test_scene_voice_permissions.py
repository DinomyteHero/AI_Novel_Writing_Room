"""Unit tests for shared scene-level voice-permission helpers."""

from src.prompting.scene_voice_permissions import (
    detect_legacy_voice_fields,
    normalize_scene_voice_permissions,
    render_scene_voice_contract,
)


def test_detect_legacy_voice_fields_returns_empty_for_canonical_card():
    assert detect_legacy_voice_fields({
        "scene_voice_permissions": {"anchor_profile": {"primary": "Bujold"}},
    }) == []


def test_detect_legacy_voice_fields_lists_present_legacy_fields():
    assert detect_legacy_voice_fields({
        "primary_anchor": "Zahn",
        "stover_permitted": True,
    }) == ["primary_anchor", "stover_permitted"]


def test_detect_legacy_voice_fields_handles_none_card():
    assert detect_legacy_voice_fields(None) == []


def test_detect_legacy_voice_fields_coexists_with_new_block():
    # A card mid-migration carries both; the helper still surfaces the legacy
    # fields so the operator knows to finish the move.
    legacy = detect_legacy_voice_fields({
        "primary_anchor": "Zahn",
        "scene_voice_permissions": {"notes": "migrated notes"},
    })
    assert legacy == ["primary_anchor"]


def test_normalize_scene_voice_permissions_reads_legacy_fields():
    permissions = normalize_scene_voice_permissions({
        "notes": "Keep the scene tactile.",
        "anti_patterns": ["No exposition dump", "Avoid clinical phrasing"],
        "pov_arc_phase": "lie_questioned",
        "primary_anchor": "Zahn",
        "supporting_anchor": "Luceno, Bujold",
        "stover_permitted": False,
    })

    assert permissions.notes == "Keep the scene tactile."
    assert permissions.anti_patterns == (
        "No exposition dump",
        "Avoid clinical phrasing",
    )
    assert permissions.pov_arc_phase == "lie_questioned"
    assert permissions.primary_anchor == "Zahn"
    assert permissions.supporting_anchors == ("Luceno", "Bujold")
    assert permissions.has_stover_permission is True
    assert permissions.stover_permitted is False
    assert permissions.prohibited_modes == ("heightened_interiority",)


def test_normalize_scene_voice_permissions_prefers_generic_block():
    permissions = normalize_scene_voice_permissions({
        "notes": "legacy note",
        "primary_anchor": "Legacy Anchor",
        "stover_permitted": False,
        "scene_voice_permissions": {
            "notes": "Keep the language close to the body.",
            "anti_patterns": ["No lecture cadence"],
            "pov_arc_phase": "truth_tested",
            "anchor_profile": {
                "primary": "Bujold",
                "supporting": ["Le Guin", "Cherryh"],
            },
            "authorized_modes": ["heightened_interiority"],
        },
    })

    assert permissions.notes == "Keep the language close to the body."
    assert permissions.anti_patterns == ("No lecture cadence",)
    assert permissions.pov_arc_phase == "truth_tested"
    assert permissions.primary_anchor == "Bujold"
    assert permissions.supporting_anchors == ("Le Guin", "Cherryh")
    assert permissions.authorized_modes == ("heightened_interiority",)
    assert permissions.prohibited_modes == ()
    assert permissions.stover_permitted is True
    assert permissions.uses_legacy_stover_guidance is False


def test_render_scene_voice_contract_preserves_false_permission_signal():
    rendered = render_scene_voice_contract({
        "primary_anchor": "Zahn",
        "supporting_anchor": ["Luceno", "Bujold"],
        "stover_permitted": False,
    })

    assert "## Scene Voice Contract" in rendered
    assert "### Scene Anchor Profile" in rendered
    assert "Primary anchor: Zahn" in rendered
    assert "Supporting anchors: Luceno, Bujold" in rendered
    assert "### Stover Permission" in rendered
    assert "is not permitted in this scene" in rendered


def test_render_scene_voice_contract_uses_generic_permission_copy():
    rendered = render_scene_voice_contract({
        "scene_voice_permissions": {
            "anchor_profile": {
                "primary": "Bujold",
                "supporting": ["Cherryh"],
            },
            "prohibited_modes": ["heightened_interiority"],
        }
    })

    assert "### Heightened Interiority Permission" in rendered
    assert "Heightened interior density is not permitted in this scene" in rendered
    assert "Stover" not in rendered
