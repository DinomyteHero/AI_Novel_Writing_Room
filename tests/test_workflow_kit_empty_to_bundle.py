"""Phase 4 acceptance gate #1 — empty directory → compiled bundle.

Drives all six surface api.py modules to author a minimal-but-complete
project from an empty tmp tree, then runs the bundle compiler and
asserts the plumbing works end-to-end:

- Each surface artifact validates against its own schema.
- The bundle compiler's schema validation against the canonical
  ``concept_seed.json`` schema reports zero errors.
- The compiled scene_cards/ tree contains the expected count.
- ``compile_report.json`` is well-formed.

Note: this test is about *plumbing*, not editorial content. The minimal
stubs intentionally satisfy the schema's minLength constraints but won't
necessarily pass the compliance validator's full structural assessment
(which checks for things like coherent canon_preserved arrays). The
Ruusan equivalence test (``test_compile_bundle_ruusan_equivalence``)
exercises real content.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.compile_bundle import compile_bundle
from src.project_paths import ProjectPaths
from workflows.canon_drafter.api import CanonDrafter
from workflows.character_forge.api import CharacterForge
from workflows.outline_planner.api import OutlinePlannerSurface
from workflows.scene_card_authoring.api import SceneCardAuthoring
from workflows.universe_builder.api import UniverseBuilder
from workflows.voice_discovery.api import VoiceDiscovery, write_voice


_HINT_50 = "EDIT ME — at least fifty characters of placeholder content here please."
_HINT_100 = (
    "EDIT ME — at least one hundred characters of placeholder content here, "
    "padded so schema validation passes the minimum-length checks cleanly."
)
_HINT_30 = "EDIT ME — at least thirty characters here."
_HINT_20 = "EDIT ME — at least twenty chars."


def _stub_character(role: str) -> dict:
    return {
        "name": f"<EDIT_ME> {role} name",
        "role": role,
        "three_dimensions": {
            "surface": _HINT_50,
            "backstory_inner_demons": _HINT_50,
            "action_under_pressure": _HINT_50,
        },
        "weiland_arc": {
            "lie_believed": _HINT_30,
            "ghost": _HINT_30,
            "want": _HINT_20,
            "need": _HINT_20,
            "arc_type": "positive_change",
        },
    }


def _drive_surfaces(paths: ProjectPaths) -> None:
    """Build a minimal-but-valid artifact for each surface."""
    paths.workflows_dir.mkdir(parents=True, exist_ok=True)

    # universe-builder — meta + universe_meta + premise/conflict/theme.
    ub = UniverseBuilder(paths)
    universe = UniverseBuilder.init_from_template(
        title="Test Project",
        franchise="Test Franchise",
        depth="original_light",
        target_chapters=20,
    )
    universe["premise"] = {
        "what_if": _HINT_50,
        "central_dramatic_question": "<EDIT_ME>",
        "logline": "<EDIT_ME>",
    }
    universe["conflict"] = {
        "primary_antagonistic_force": {
            "type": "<EDIT_ME>",
            "motivation": _HINT_50,
            "escalation": _HINT_100,
        },
        "secondary_pressures": [_HINT_30],
        "lock_in_mechanism": _HINT_30,
    }
    universe["theme"] = {
        "thematic_premise": "<EDIT_ME>",
        "thematic_argument": _HINT_100,
        "how_each_arc_tests_theme": {},
    }
    ub.write(universe)

    # canon-drafter — apply a template.
    cd = CanonDrafter(paths)
    canon = CanonDrafter.apply_template("original_light")
    cd.write(canon)

    # voice-discovery — build voice_definition via the helper.
    vd = VoiceDiscovery()
    voice_def = vd.build_voice_definition(
        pov_approach="single close third",
        prose_register="literary",
    )
    write_voice(paths, voice_def)

    # character-forge — minimum 2 characters.
    cf = CharacterForge(paths)
    cast = [_stub_character("protagonist"), _stub_character("antagonist")]
    cf.write(CharacterForge.envelope(cast))

    # outline-planner — minimum one chapter.
    op = OutlinePlannerSurface(paths)
    outline = [
        {"chapter_number": i, "synopsis": f"Chapter {i} placeholder synopsis."}
        for i in range(1, 6)
    ]
    op.write(OutlinePlannerSurface.envelope(outline))

    # scene-card-authoring — one stub card so the compiler emits one file.
    sca = SceneCardAuthoring(paths)
    cards = [
        {
            "chapter_number": 1,
            "scene_number": 1,
            "pov_character": "<EDIT_ME> protagonist name",
            "mission": "Stub mission for plumbing test.",
            "why_now": "Stub why-now justification.",
            "conflict": "Stub conflict.",
            "turning_point": "Stub turning point.",
        }
    ]
    sca.write(SceneCardAuthoring.envelope(cards))


def test_empty_to_bundle_plumbing(tmp_path):
    """An empty tmp tree, driven through six api.py modules, compiles."""
    paths = ProjectPaths(
        "test-project", base_dir=str(tmp_path),
        franchise_slug="test-franchise",
    )
    paths.ensure_dirs()
    assert not paths.workflows_dir.exists() or not any(paths.workflows_dir.iterdir())

    _drive_surfaces(paths)

    # All six surface artifacts present.
    for artifact_name in ("universe.json", "canon.json", "voice.json", "characters.json", "outline.json", "scene_cards.json"):
        assert (paths.workflows_dir / artifact_name).exists()

    report = compile_bundle(
        franchise_slug="test-franchise",
        book_slug="test-project",
        base_dir=str(tmp_path),
    )

    # Plumbing assertions: no missing surfaces, no schema errors at the
    # bundle level, scene cards extracted, report file written.
    assert report.surfaces_missing == []
    assert report.schema_errors == [], (
        f"bundle schema errors: {report.schema_errors}"
    )
    assert report.scene_card_errors == []
    assert report.scene_card_count == 1

    seed_path = paths.concept_seed_path
    assert seed_path.exists()
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    assert seed["meta"]["project_title"] == "Test Project"
    assert len(seed["ensemble_cast"]) == 2

    extracted = sorted(paths.scene_cards_dir.glob("chapter_*_scene_*.json"))
    assert len(extracted) == 1

    report_path = paths.book_dir / "compile_report.json"
    assert report_path.exists()
    report_dict = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_dict["franchise"] == "test-franchise"
    assert report_dict["book"] == "test-project"
    assert report_dict["scene_card_count"] == 1


def test_compile_with_missing_required_surface_reports_clearly(tmp_path):
    """Bundle compile with a missing required surface fails cleanly."""
    paths = ProjectPaths(
        "test-project", base_dir=str(tmp_path),
        franchise_slug="test-franchise",
    )
    paths.ensure_dirs()
    paths.workflows_dir.mkdir(parents=True, exist_ok=True)

    # Write only universe.json; everything else is missing.
    UniverseBuilder(paths).write(UniverseBuilder.init_from_template(
        title="X", franchise="Y", depth="original_light",
    ))

    report = compile_bundle(
        franchise_slug="test-franchise",
        book_slug="test-project",
        base_dir=str(tmp_path),
    )
    assert "canon" in report.surfaces_missing
    assert "voice" in report.surfaces_missing
    assert "characters" in report.surfaces_missing
    assert "outline" in report.surfaces_missing
    # When surfaces are missing the compiler short-circuits before
    # building a seed, so concept_seed.json is not written.
    assert not paths.concept_seed_path.exists()


def test_compile_without_scene_cards_warns_but_succeeds(tmp_path):
    """When workflows/scene_cards.json is absent, compile warns (default) but emits a seed."""
    paths = ProjectPaths(
        "test-project", base_dir=str(tmp_path),
        franchise_slug="test-franchise",
    )
    paths.ensure_dirs()
    _drive_surfaces(paths)

    # Remove the scene_cards envelope so the compiler hits the no-cards path.
    (paths.workflows_dir / "scene_cards.json").unlink()

    report = compile_bundle(
        franchise_slug="test-franchise",
        book_slug="test-project",
        base_dir=str(tmp_path),
    )
    assert report.scene_card_count == 0
    assert any("scene cards" in w.lower() for w in report.warnings)
    # Seed still written; pipeline downstream auto-generates cards.
    assert paths.concept_seed_path.exists()
