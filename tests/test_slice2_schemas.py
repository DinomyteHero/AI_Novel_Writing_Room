"""JSON-schema validation tests for Slice 2 artifacts.

Checks:
- ``schemas/chapter_packet.json`` validates a real packet dict produced by
  ``ChapterPacketCompiler``.
- ``schemas/revision_debt.json`` validates a real debt row.
- ``schemas/chapter_memo.json`` validates both chapter-close and milestone
  memos.
- Known-bad examples fail (closed category enum, required-field check).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from src.memory.story_state import StoryState
from src.pipeline.chapter_memos import (
    ChapterCloseMemoGenerator,
    MilestoneMemoGenerator,
)
from src.pipeline.chapter_packet import ChapterPacketCompiler
from src.pipeline.revision_debt import RevisionDebtStore


SCHEMA_DIR = Path("schemas")


def _load_schema(name: str) -> dict:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------- chapter_packet


def _blueprint() -> dict:
    return {
        "chapter_number": 1,
        "chapter_mission": "Mission",
        "chapter_turn": "Turn",
        "pov_allocation": ["Ben"],
        "scene_plan": [
            {"scene_number": 1, "role": "hook"},
        ],
    }


def test_chapter_packet_schema_validates_base():
    schema = _load_schema("chapter_packet.json")
    compiler = ChapterPacketCompiler(
        concept_seed={"meta": {"project_title": "t", "franchise": "f"}},
        blueprints={1: _blueprint()},
    )
    base = compiler.compile_base(chapter_number=1)
    jsonschema.validate(instance=base.to_json(), schema=schema)


def test_chapter_packet_schema_validates_overlay():
    schema = _load_schema("chapter_packet.json")
    compiler = ChapterPacketCompiler(
        concept_seed={"meta": {"project_title": "t", "franchise": "f"}},
        blueprints={1: _blueprint()},
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 1, "pov_character": "Ben"},
    )
    jsonschema.validate(instance=overlay.to_json(), schema=schema)


def test_chapter_packet_schema_rejects_missing_required():
    schema = _load_schema("chapter_packet.json")
    bad = {"overlay_version": 0}  # missing chapter_number/mission/chapter_turn
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


# --------------------------------------------------------------- revision_debt


def test_revision_debt_schema_validates_row():
    schema = _load_schema("revision_debt.json")
    store = RevisionDebtStore(db_path=":memory:")
    debt_id = store.add({
        "producer": "canon_expert",
        "scope": {"level": "scene", "chapter_number": 1, "scene_number": 1},
        "category": "canon",
        "severity": "medium",
        "summary": "t",
        "details": {"code": "CANON_X"},
    })
    row = store.get(debt_id)
    # Store returns owner_or_reviewer_notes as NULL (None); the schema allows
    # omission, so drop None-valued optional fields for validation.
    cleaned = {k: v for k, v in row.items() if v is not None}
    jsonschema.validate(instance=cleaned, schema=schema)


def test_revision_debt_schema_rejects_unknown_category():
    schema = _load_schema("revision_debt.json")
    bad = {
        "debt_id": "d1",
        "created_at": "2026-04-20T00:00:00+00:00",
        "producer": "x",
        "scope": {"level": "scene"},
        "category": "not_a_category",
        "severity": "low",
        "status": "open",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_revision_debt_schema_rejects_bad_severity():
    schema = _load_schema("revision_debt.json")
    bad = {
        "debt_id": "d1",
        "created_at": "2026-04-20T00:00:00+00:00",
        "producer": "x",
        "scope": {"level": "scene"},
        "category": "canon",
        "severity": "catastrophic",
        "status": "open",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


# --------------------------------------------------------------- chapter_memo


def test_chapter_close_memo_schema_validates():
    schema = _load_schema("chapter_memo.json")
    store = RevisionDebtStore(db_path=":memory:")
    store.add({
        "producer": "canon_expert",
        "scope": {"level": "scene", "chapter_number": 1},
        "category": "canon",
        "severity": "high",
        "summary": "s",
    })
    gen = ChapterCloseMemoGenerator(debt_store=store)
    memo = gen.generate(chapter_number=1)
    jsonschema.validate(instance=memo, schema=schema)


def test_milestone_memo_schema_validates():
    schema = _load_schema("chapter_memo.json")
    store = RevisionDebtStore(db_path=":memory:")
    store.add({
        "producer": "canon_expert",
        "scope": {"level": "scene", "chapter_number": 1},
        "category": "canon",
        "severity": "medium",
        "summary": "s",
    })
    gen = MilestoneMemoGenerator(debt_store=store)
    memo = gen.generate(through_chapter=3)
    jsonschema.validate(instance=memo, schema=schema)


def test_chapter_memo_rejects_bad_kind():
    schema = _load_schema("chapter_memo.json")
    bad = {
        "kind": "unknown",
        "generated_at": "2026-04-20T00:00:00+00:00",
        "debt_summary": {
            "counts_by_category": {},
            "counts_by_severity": {},
            "open_debt_ids": [],
        },
        "human_attention_items": [],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)
