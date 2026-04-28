"""Tests for the IdeaSessionCapture headless api.

Covers:
- init_workspace scaffolds the expected files (capture, session, README,
  surface_handoffs/*.md).
- Repeat init is idempotent unless force=True.
- State mutation (set_north_star, add_decision, add_open_question,
  update_handoff) round-trips through capture.json.
- Save validates the schema-required envelope; broken captures raise.
- Status reports counts + ready_for_expand boolean correctly.
- expand_to_surface_drafts pre-seeds the six surface artifacts and
  refuses when the capture is not ready.
- Existing artifacts are skipped without force.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflows.idea_session_capture import IdeaSessionCapture
from workflows.idea_session_capture.api import SURFACES


@pytest.fixture
def capture(tmp_path: Path) -> IdeaSessionCapture:
    cap = IdeaSessionCapture(
        title="Test Book",
        franchise="Original",
        base_dir=str(tmp_path),
    )
    cap.init_workspace(project_scope="standalone", canon_status="original")
    return cap


def _load(capture: IdeaSessionCapture) -> dict:
    return json.loads(capture.capture_path.read_text(encoding="utf-8"))


def test_init_workspace_scaffolds_all_expected_files(tmp_path: Path) -> None:
    cap = IdeaSessionCapture(
        title="Test Book", franchise="Original", base_dir=str(tmp_path)
    )
    result = cap.init_workspace()
    paths = {p.name for p in result["written"]}
    assert "capture.json" in paths
    assert "session.md" in paths
    assert "README.md" in paths
    for surface in SURFACES:
        assert f"{surface}.md" in paths
    assert result["skipped"] == []


def test_init_is_idempotent_without_force(tmp_path: Path) -> None:
    cap = IdeaSessionCapture(
        title="Test Book", franchise="Original", base_dir=str(tmp_path)
    )
    cap.init_workspace()
    second = cap.init_workspace()
    assert second["written"] == []
    assert len(second["skipped"]) > 0


def test_init_force_overwrites(tmp_path: Path) -> None:
    cap = IdeaSessionCapture(
        title="Test Book", franchise="Original", base_dir=str(tmp_path)
    )
    cap.init_workspace()
    cap.set_north_star(one_sentence_pitch="Original pitch.")
    cap.init_workspace(force=True)
    capture = _load(cap)
    assert capture["north_star"]["one_sentence_pitch"] == ""


def test_set_north_star_round_trips(capture: IdeaSessionCapture) -> None:
    capture.set_north_star(
        one_sentence_pitch="A retired spy gets pulled back in by her own daughter.",
        reader_promise="Earned emotional ending.",
        emotional_core="reckoning with a life of lies",
        non_negotiables=["POV stays Mara"],
        avoid=["flashback open"],
    )
    data = _load(capture)
    assert "retired spy" in data["north_star"]["one_sentence_pitch"]
    assert data["north_star"]["non_negotiables"] == ["POV stays Mara"]
    assert data["north_star"]["avoid"] == ["flashback open"]


def test_add_decision_validates_confidence(capture: IdeaSessionCapture) -> None:
    capture.add_decision(
        surface="characters",
        topic="arc_type",
        decision="negative change",
        confidence="settled",
    )
    data = _load(capture)
    assert data["decisions"][0]["surface"] == "characters"
    assert data["decisions"][0]["confidence"] == "settled"


def test_save_rejects_invalid_confidence(capture: IdeaSessionCapture) -> None:
    data = _load(capture)
    data["decisions"] = [
        {
            "surface": "characters",
            "topic": "arc",
            "decision": "x",
            "confidence": "bogus_value",
        }
    ]
    with pytest.raises(ValueError):
        capture.save(data)


def test_save_rejects_missing_required_fields(capture: IdeaSessionCapture) -> None:
    data = _load(capture)
    del data["surface"]
    with pytest.raises(ValueError):
        capture.save(data)


def test_update_handoff_validates_surface(capture: IdeaSessionCapture) -> None:
    with pytest.raises(ValueError):
        capture.update_handoff("nonexistent_surface", status="seeded")


def test_update_handoff_round_trips(capture: IdeaSessionCapture) -> None:
    capture.update_handoff(
        "characters",
        status="seeded",
        settled_inputs=["Mara, 52, ex-spy"],
        questions_to_resolve=["Does she have a partner?"],
        notes="Negative change arc.",
    )
    data = _load(capture)
    block = data["surface_handoffs"]["characters"]
    assert block["status"] == "seeded"
    assert block["settled_inputs"] == ["Mara, 52, ex-spy"]
    assert block["notes"] == "Negative change arc."


def test_status_reports_ready_when_pitch_and_decision_set(
    capture: IdeaSessionCapture,
) -> None:
    snapshot = capture.status()
    assert snapshot.ready_for_expand is False
    capture.set_north_star(one_sentence_pitch="A pitch.")
    snapshot = capture.status()
    assert snapshot.ready_for_expand is False  # need a decision too
    capture.add_decision(
        surface="universe", topic="t", decision="d", confidence="settled"
    )
    snapshot = capture.status()
    assert snapshot.ready_for_expand is True
    assert snapshot.decisions_count == 1


def test_expand_refuses_when_not_ready(capture: IdeaSessionCapture) -> None:
    with pytest.raises(ValueError):
        capture.expand_to_surface_drafts()


def test_expand_seeds_six_surfaces(capture: IdeaSessionCapture) -> None:
    capture.set_north_star(
        one_sentence_pitch="A pitch.",
        reader_promise="A promise.",
        emotional_core="loneliness",
    )
    capture.add_decision(
        surface="characters",
        topic="arc",
        decision="positive change",
        confidence="settled",
    )
    result = capture.expand_to_surface_drafts()
    paths = {p.name for p in result["written"]}
    assert "universe.json" in paths
    assert "canon.json" in paths
    assert "voice.json" in paths
    assert "characters.json" in paths
    assert "outline.json" in paths
    assert "_intent.md" in paths


def test_expand_skips_existing_unless_force(capture: IdeaSessionCapture) -> None:
    capture.set_north_star(one_sentence_pitch="A pitch.")
    capture.add_decision(
        surface="universe", topic="t", decision="d", confidence="settled"
    )
    capture.expand_to_surface_drafts()
    second = capture.expand_to_surface_drafts()
    assert second["written"] == []
    assert len(second["skipped"]) == 6
    forced = capture.expand_to_surface_drafts(force=True)
    assert len(forced["written"]) == 6


def test_expand_seeded_universe_carries_north_star(
    capture: IdeaSessionCapture,
) -> None:
    capture.set_north_star(
        one_sentence_pitch="A retired spy gets pulled back in.",
        reader_promise="Earned emotional ending.",
        emotional_core="reckoning",
        non_negotiables=["POV stays Mara"],
    )
    capture.add_decision(
        surface="universe",
        topic="canon_status",
        decision="original universe",
        confidence="settled",
    )
    capture.expand_to_surface_drafts()
    universe_path = capture.paths.workflows_dir / "universe.json"
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    assert universe["surface"] == "universe-builder"
    # Schema-required blocks land
    assert universe["meta"]["project_title"] == "Test Book"
    assert universe["meta"]["franchise"] == "Original"
    assert universe["meta"]["canon_status"] == "original"
    assert universe["universe_meta"]["franchise"] == "Original"
    # Optional seeded north-star content lands in premise/theme/extended_metadata
    assert "retired spy" in universe["premise"]["logline"]
    assert universe["theme"]["thematic_premise"] == "reckoning"
    assert universe["extended_metadata"]["non_negotiables"] == ["POV stays Mara"]


def test_expand_seeded_outline_carries_brooks_skeleton(
    capture: IdeaSessionCapture,
) -> None:
    capture.set_north_star(one_sentence_pitch="A pitch.")
    capture.add_decision(
        surface="outline", topic="t", decision="d", confidence="settled"
    )
    capture.expand_to_surface_drafts()
    outline_path = capture.paths.workflows_dir / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    assert outline["surface"] == "outline-planner"
    brooks = outline["structural_notes"]["brooks_alignment"]
    # Brooks four-part keys present (for the planner to fill)
    assert "part_1_setup" in brooks
    assert "first_plot_point" in brooks
    assert "midpoint" in brooks
    assert "part_4_resolution" in brooks
    # Scene-count discipline note is preserved as a hint for the planner
    discipline = outline["structural_notes"]["_scene_count_discipline"].lower()
    assert "as many or as few scenes" in discipline
    assert "distinct turning point" in discipline


def test_expand_only_subset_of_surfaces(capture: IdeaSessionCapture) -> None:
    capture.set_north_star(one_sentence_pitch="A pitch.")
    capture.add_decision(
        surface="universe", topic="t", decision="d", confidence="settled"
    )
    result = capture.expand_to_surface_drafts(surfaces=["universe", "voice"])
    paths = {p.name for p in result["written"]}
    assert paths == {"universe.json", "voice.json"}


def test_expand_drafts_validate_against_surface_schemas(
    capture: IdeaSessionCapture,
) -> None:
    """expand_to_surface_drafts must produce skeletons that pass each
    surface's validator. Without this, Codex/Claude agents that follow
    the documented expand-then-edit-then-write workflow would write
    schema-invalid surfaces back through the surface api and trip the
    validator at write time. Schema drift in either the expand body or
    the surface schemas must fail this test.
    """
    capture.set_north_star(
        one_sentence_pitch="A drifting heir must reclaim a city she walked away from.",
        reader_promise="Hard-won emotional resolution.",
        emotional_core="cost of return",
        non_negotiables=["POV stays Mara"],
    )
    capture.add_decision(
        surface="universe",
        topic="canon_status",
        decision="original universe",
        confidence="settled",
    )
    capture.expand_to_surface_drafts()
    workflows_dir = capture.paths.workflows_dir

    surface_to_validator = {
        "universe": "workflows.universe_builder.validate",
        "canon": "workflows.canon_drafter.validate",
        "voice": "workflows.voice_discovery.validate",
        "characters": "workflows.character_forge.validate",
        "outline": "workflows.outline_planner.validate",
    }
    import importlib

    for surface, mod_name in surface_to_validator.items():
        artifact_path = workflows_dir / f"{surface}.json"
        assert artifact_path.exists(), f"{surface}.json not written by expand"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        module = importlib.import_module(mod_name)
        errors = module.validate(artifact)
        assert errors == [], (
            f"expand draft for {surface!r} failed schema validation: {errors}"
        )


def test_load_raises_when_workspace_absent(tmp_path: Path) -> None:
    cap = IdeaSessionCapture(
        title="Never Initialized", franchise="Original", base_dir=str(tmp_path)
    )
    with pytest.raises(FileNotFoundError):
        cap.load()
