from __future__ import annotations

import json
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.pipeline.canon_guidance import CanonGuidanceStore
from src.pipeline.chapter_packet import ChapterPacketCompiler


@contextmanager
def _workspace_tmp():
    path = Path(f"codex_test_canon_guidance_{uuid.uuid4().hex}")
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _seed() -> dict:
    return {
        "meta": {
            "project_title": "The Ruusan Atonement",
            "franchise": "Star Wars Legends EU",
            "era": "47 ABY",
        },
        "canon_profile": {
            "continuity": "Legends",
            "cross_continuity_violations": ["World Between Worlds"],
        },
    }


def _blueprint() -> dict:
    return {
        "chapter_number": 1,
        "chapter_mission": "Test mission",
        "chapter_turn": "Test turn",
        "scene_plan": [{"scene_number": 1, "role": "hook"}],
    }


def _scene_card() -> dict:
    return {
        "chapter_number": 1,
        "scene_number": 1,
        "pov_character": "Ben Skywalker",
        "summary": "Ben checks a Sith ruin for post-FOTJ fallout.",
    }


def test_canon_guidance_store_marks_fresh_and_stale():
    with _workspace_tmp() as tmp_path:
        contract = tmp_path / "canon_contract.md"
        contract.write_text("Use Legends. Avoid Disney-only concepts.", encoding="utf-8")
        store = CanonGuidanceStore(tmp_path / "canon_guidance", canon_contract_path=contract)

        payload = store.prepare_payload(
            model_output={
                "hard_constraints": ["Use Legends continuity."],
                "required_context_for_drafter": ["Ben is post-FOTJ."],
                "confidence": 0.8,
            },
            model="x-ai/grok-4.1-fast",
            concept_seed=_seed(),
            chapter_blueprint=_blueprint(),
            scene_card=_scene_card(),
        )
        path = store.write(payload)

        assert path.exists()
        freshness = store.freshness(
            concept_seed=_seed(),
            chapter_blueprint=_blueprint(),
            scene_card=_scene_card(),
        )
        assert freshness.status == "fresh"
        assert store.load_fresh(
            concept_seed=_seed(),
            chapter_blueprint=_blueprint(),
            scene_card=_scene_card(),
        )["required_context_for_drafter"] == ["Ben is post-FOTJ."]

        changed_card = {**_scene_card(), "summary": "A changed scene plan."}
        assert store.freshness(
            concept_seed=_seed(),
            chapter_blueprint=_blueprint(),
            scene_card=changed_card,
        ).status == "stale"
        assert store.load_fresh(
            concept_seed=_seed(),
            chapter_blueprint=_blueprint(),
            scene_card=changed_card,
        ) is None


def test_canon_guidance_coverage_rolls_up_freshness():
    with _workspace_tmp() as tmp_path:
        store = CanonGuidanceStore(tmp_path / "canon_guidance")
        scene_one = _scene_card()
        scene_two = {**_scene_card(), "scene_number": 2}
        payload = store.prepare_payload(
            model_output={"confidence": 0.7},
            model="x-ai/grok-4.1-fast",
            concept_seed=_seed(),
            chapter_blueprint=_blueprint(),
            scene_card=scene_one,
        )
        store.write(payload)

        coverage = store.coverage(
            concept_seed=_seed(),
            blueprints={1: _blueprint()},
            scene_cards=[scene_one, scene_two],
        )

        assert coverage.total == 2
        assert coverage.fresh == 1
        assert coverage.missing == 1
        assert coverage.complete is False
        assert [item.scene_id for item in coverage.incomplete] == ["ch01_sc02"]


def test_chapter_packet_injects_fresh_canon_guidance():
    with _workspace_tmp() as tmp_path:
        contract = tmp_path / "canon_contract.md"
        contract.write_text("Use Legends.", encoding="utf-8")
        store = CanonGuidanceStore(tmp_path / "canon_guidance", canon_contract_path=contract)
        payload = store.prepare_payload(
            model_output={
                "hard_constraints": ["No World Between Worlds."],
                "legends_continuity_notes": ["Post-FOTJ branch."],
                "confidence": "high",
            },
            model="x-ai/grok-4.1-fast",
            concept_seed=_seed(),
            chapter_blueprint=_blueprint(),
            scene_card=_scene_card(),
        )
        store.write(payload)

        compiler = ChapterPacketCompiler(
            concept_seed=_seed(),
            blueprints={1: _blueprint()},
            canon_guidance_store=store,
        )
        base = compiler.compile_base(chapter_number=1)
        overlay = compiler.compile_overlay(base=base, scene_card=_scene_card())

        assert overlay.canon_guidance["hard_constraints"] == ["No World Between Worlds."]
        assert "Static Canon Guidance" in overlay.rendered_markdown
        assert "Post-FOTJ branch." in overlay.rendered_markdown


def test_canon_guidance_schema_validates_payload():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(Path("schemas/canon_guidance.json").read_text(encoding="utf-8"))
    with _workspace_tmp() as tmp_path:
        store = CanonGuidanceStore(tmp_path / "canon_guidance")
        payload = store.prepare_payload(
            model_output={"confidence": 0.5},
            model="x-ai/grok-4.1-fast",
            concept_seed=_seed(),
            chapter_blueprint=_blueprint(),
            scene_card=_scene_card(),
        )
        jsonschema.validate(instance=payload, schema=schema)
