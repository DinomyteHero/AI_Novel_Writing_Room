"""Unit tests for shared scene-level voice-permission helpers."""

from src.prompting.scene_voice_permissions import (
    normalize_scene_voice_permissions,
    render_canon_voice_permissions,
    render_scene_voice_contract,
)


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


def test_render_canon_voice_permissions_only_surfaces_true_stover_flag():
    rendered = render_canon_voice_permissions({
        "notes": "Use one consistent metaphor.",
        "anti_patterns": ["No exposition dump"],
        "stover_permitted": True,
    })

    assert "Scene-Level Voice Permissions" in rendered
    assert "Use one consistent metaphor." in rendered
    assert "stover_permitted: true" in rendered
    assert "Stover-style prose intensity" in rendered
    assert "- No exposition dump" in rendered


def test_render_canon_voice_permissions_supports_generic_authorized_mode():
    rendered = render_canon_voice_permissions({
        "scene_voice_permissions": {
            "notes": "Sharper inward pressure is allowed here.",
            "authorized_modes": ["heightened_interiority"],
        }
    })

    assert "authorized_modes: heightened_interiority" in rendered
    assert "heightened interior density" in rendered
    assert "Stover-style" not in rendered


def test_render_canon_voice_permissions_omits_section_for_false_only():
    rendered = render_canon_voice_permissions({"stover_permitted": False})
    assert rendered == ""
