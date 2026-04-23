from __future__ import annotations

import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from src.pipeline.canon_guidance import CanonGuidanceStore
from src.pipeline.run_preflight import validate_current_run
from src.project_paths import ProjectPaths


LONG = (
    "This deliberately long fixture sentence provides enough descriptive "
    "content for schema minimum lengths while staying irrelevant to the test. "
)


@contextmanager
def _workspace_tmp():
    path = Path(f"codex_test_run_preflight_{uuid.uuid4().hex}")
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _seed() -> dict:
    return {
        "meta": {
            "project_title": "Preflight Test Book",
            "franchise": "Preflight Franchise",
            "canon_status": "AU",
            "era": "test era",
            "tone": "heroic_with_weight",
            "target_word_count": 50000,
        },
        "premise": {
            "what_if": LONG,
            "central_dramatic_question": "Will the preflight catch missing sidecars?",
            "logline": "A test book validates pre-run architecture.",
        },
        "conflict": {
            "primary_antagonistic_force": {
                "type": "system",
                "motivation": LONG,
                "escalation": LONG + LONG,
            },
            "lock_in_mechanism": LONG,
        },
        "theme": {
            "thematic_premise": "Preparation matters.",
            "thematic_argument": LONG + LONG,
            "how_each_arc_tests_theme": {"A": "A tests the theme."},
        },
        "ensemble_cast": [
            {
                "name": "A",
                "role": "lead",
                "three_dimensions": {
                    "surface": LONG,
                    "backstory_inner_demons": LONG,
                    "action_under_pressure": LONG,
                },
            },
            {
                "name": "B",
                "role": "support",
                "three_dimensions": {
                    "surface": LONG,
                    "backstory_inner_demons": LONG,
                    "action_under_pressure": LONG,
                },
            },
        ],
        "canon_constraints": {
            "continuity": "test continuity",
            "canon_preserved": ["A remains A."],
            "style_constraints": ["No crossover bleed."],
        },
        "compile_metadata": {"plan_approved": True},
    }


def _scene_card() -> dict:
    return {
        "chapter_number": 1,
        "scene_number": 1,
        "structural_phase": "setup",
        "pov_character": "A",
        "mission": "A finds the test problem.",
        "conflict": "The sidecar is missing.",
        "turning_point": "A decides to stop the run.",
        "characters_present": ["A"],
    }


def _blueprint() -> dict:
    return {
        "chapter_number": 1,
        "chapter_mission": "Catch missing architecture before the run.",
        "chapter_turn": "Unchecked plan becomes checked plan.",
        "scene_plan": [{"scene_number": 1, "role": "hook", "purpose": "test"}],
    }


def _write_project(tmp_path):
    paths = ProjectPaths(
        "preflight-test-book",
        base_dir=str(tmp_path),
        franchise_slug="preflight-franchise",
    )
    paths.ensure_dirs()
    paths.chapter_blueprints_dir.mkdir(parents=True, exist_ok=True)
    paths.concept_seed_path.write_text(json.dumps(_seed()), encoding="utf-8")
    (paths.scene_cards_dir / "chapter_01_scene_01.json").write_text(
        json.dumps(_scene_card()),
        encoding="utf-8",
    )
    (paths.chapter_blueprints_dir / "chapter_01.json").write_text(
        json.dumps(_blueprint()),
        encoding="utf-8",
    )
    paths.canon_contract_path.write_text("Use the test canon.", encoding="utf-8")
    return paths


def test_preflight_fails_when_required_canon_guidance_is_missing():
    with _workspace_tmp() as tmp_path:
        _write_project(tmp_path)

        report = validate_current_run(
            franchise_slug="preflight-franchise",
            book_slug="preflight-test-book",
            base_dir=str(tmp_path),
            chapter=1,
        )

    assert report.passed is False
    assert any(issue.category == "canon_guidance" for issue in report.errors)
    assert report.canon_guidance["missing"] == 1


def test_preflight_passes_after_sidecar_is_generated():
    with _workspace_tmp() as tmp_path:
        paths = _write_project(tmp_path)
        store = CanonGuidanceStore(
            paths.canon_guidance_dir,
            canon_contract_path=paths.canon_contract_path,
        )
        store.write(
            store.prepare_payload(
                model_output={"confidence": 0.8},
                model="x-ai/grok-4.1-fast",
                concept_seed=_seed(),
                chapter_blueprint=_blueprint(),
                scene_card=_scene_card(),
            )
        )

        report = validate_current_run(
            franchise_slug="preflight-franchise",
            book_slug="preflight-test-book",
            base_dir=str(tmp_path),
            chapter=1,
        )

    assert report.passed is True
    assert report.packet_count == 1
    assert report.canon_guidance["fresh"] == 1
