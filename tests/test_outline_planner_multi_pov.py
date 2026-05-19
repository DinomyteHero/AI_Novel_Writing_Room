"""Tests for the multi-POV braiding additions to workflows/outline_planner.

Covers the schema additions (`pov_sequence`, `scene_briefs`) and the new
validator rules that enforce consistency between them.
"""

from __future__ import annotations

from workflows.outline_planner.validate import validate


def _baseline_artifact(outline_entry: dict) -> dict:
    return {
        "surface": "outline-planner",
        "schema_version": "1.0",
        "outline": [outline_entry],
    }


def test_single_pov_chapter_still_valid():
    """Existing single-POV chapters must continue to validate."""
    artifact = _baseline_artifact({
        "chapter_number": 1,
        "synopsis": "Ben arrives at Shedu Maad.",
        "pov_character": "Ben",
        "structural_phase": "setup",
    })
    assert validate(artifact) == []


def test_pov_sequence_only_is_valid():
    """pov_sequence without scene_briefs is valid; scene-card-authoring
    consumes it as a constraint hint when generating per-scene cards.
    """
    artifact = _baseline_artifact({
        "chapter_number": 7,
        "synopsis": "Ben chases Korda; Tess off-stage orders the cleanup.",
        "pov_character": "Ben",
        "pov_sequence": ["Ben", "Tess", "Ben"],
        "structural_phase": "first_pinch",
    })
    assert validate(artifact) == []


def test_scene_briefs_aligned_with_pov_sequence_passes():
    artifact = _baseline_artifact({
        "chapter_number": 7,
        "synopsis": "x",
        "pov_character": "Ben",
        "pov_sequence": ["Ben", "Tess", "Ben"],
        "scene_briefs": [
            {"scene_number": 1, "pov": "Ben", "thread": "Ben chase"},
            {"scene_number": 2, "pov": "Tess", "thread": "Tess board-clearing"},
            {"scene_number": 3, "pov": "Ben", "thread": "Ben chase aftermath"},
        ],
    })
    assert validate(artifact) == []


def test_scene_brief_pov_mismatch_with_pov_sequence_fails():
    artifact = _baseline_artifact({
        "chapter_number": 7,
        "synopsis": "x",
        "pov_character": "Ben",
        "pov_sequence": ["Ben", "Tess", "Ben"],
        "scene_briefs": [
            {"scene_number": 1, "pov": "Ben"},
            {"scene_number": 2, "pov": "Aevyn"},  # mismatch: expected Tess
        ],
    })
    errors = validate(artifact)
    assert any("does not match pov_sequence" in e for e in errors)


def test_scene_brief_scene_number_beyond_pov_sequence_fails():
    artifact = _baseline_artifact({
        "chapter_number": 7,
        "synopsis": "x",
        "pov_sequence": ["Ben", "Tess"],  # only 2 POVs
        "scene_briefs": [
            {"scene_number": 1, "pov": "Ben"},
            {"scene_number": 3, "pov": "Ben"},  # no third POV defined
        ],
    })
    errors = validate(artifact)
    assert any("exceeds pov_sequence length" in e for e in errors)


def test_scene_brief_without_pov_is_valid():
    """scene_briefs can omit pov when pov_sequence carries it."""
    artifact = _baseline_artifact({
        "chapter_number": 7,
        "synopsis": "x",
        "pov_sequence": ["Ben", "Tess"],
        "scene_briefs": [
            {"scene_number": 1, "thread": "Ben chase"},
            {"scene_number": 2, "thread": "Tess board-clearing"},
        ],
    })
    assert validate(artifact) == []


def test_structural_role_enum_enforced():
    artifact = _baseline_artifact({
        "chapter_number": 7,
        "synopsis": "x",
        "scene_briefs": [
            {"scene_number": 1, "structural_role": "not_a_real_role"},
        ],
    })
    errors = validate(artifact)
    # Schema-level enum check should surface the bad value.
    assert any("not_a_real_role" in e or "structural_role" in e for e in errors)
