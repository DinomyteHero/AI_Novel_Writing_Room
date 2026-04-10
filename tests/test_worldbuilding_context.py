"""Tests for worldbuilding integration with the ContextAssembler."""

import json
from pathlib import Path

import pytest

from src.memory.context_assembler import ContextAssembler, TOKEN_BUDGETS
from src.rag.embedding import MockEmbeddingFunction
from src.worldbuilding.worldbuilding_db import WorldbuildingDB
from src.worldbuilding.lore_vectorstore import LoreVectorStore
from src.worldbuilding.lore_service import LoreService


@pytest.fixture
def concept_seed_path(tmp_path):
    seed = {
        "meta": {
            "project_title": "Test Novel",
            "franchise": "star_wars",
            "era": "Old Republic",
            "tone": "dark",
            "pov_structure": "third_person_limited",
        },
        "premise": {
            "what_if": "What if the Sith won?",
            "central_dramatic_question": "Can one person resist?",
        },
        "conflict": {
            "primary_antagonistic_force": {"identity": "The Empire", "motivation": "Control"},
            "lock_in_mechanism": "Conscription",
        },
        "theme": {"thematic_premise": "Freedom vs security"},
        "ensemble_cast": [
            {
                "name": "Ben Skywalker",
                "role": "Protagonist",
                "voice_notes": "Earnest, blunt",
                "three_dimensions": {
                    "surface": "A young Jedi padawan",
                    "backstory_inner_demons": "Haunted by failure",
                    "action_under_pressure": "Acts decisively",
                },
            }
        ],
    }
    path = tmp_path / "concept_seed.json"
    path.write_text(json.dumps(seed))
    return str(path)


@pytest.fixture
def constraints_path(tmp_path):
    import yaml
    constraints = {"banned_phrases": {"test": ["avoid this"]}, "structural_rules": {}}
    path = tmp_path / "constraints.yaml"
    path.write_text(yaml.dump(constraints))
    return str(path)


@pytest.fixture
def lore_service(tmp_path):
    db = WorldbuildingDB(db_path=str(tmp_path / "wb.db"))
    vs = LoreVectorStore(
        persist_directory=str(tmp_path / "wb_vectors"),
        embedding_function=MockEmbeddingFunction(),
    )
    svc = LoreService(db=db, vectorstore=vs)

    # Set up universe with entries
    svc.create_universe("test_au", "Test AU", franchise="star_wars")
    svc.create_lore_entry(
        universe_id="test_au", category="faction",
        title="Draleth Hegemony",
        content="A declining imperial power in the Outer Rim",
        thematic_notes="Late-stage decline",
        speech_patterns="Formal, no contractions",
    )
    svc.create_lore_entry(
        universe_id="test_au", category="terminology",
        title="Hegemon", content="Supreme ruler title in the Hegemony",
    )
    svc.create_lore_entry(
        universe_id="test_au", category="terminology",
        title="Tribute Tithe", content="Annual tax to the Hegemony",
    )
    return svc


class TestWorldbuildingInAssembly:
    def test_includes_worldbuilding_when_service_present(
        self, concept_seed_path, constraints_path, lore_service, tmp_path
    ):
        assembler = ContextAssembler(
            concept_seed_path=concept_seed_path,
            negative_constraints_path=constraints_path,
            manuscripts_dir=str(tmp_path / "manuscripts"),
            lore_service=lore_service,
            universe_id="test_au",
        )
        scene_card = {
            "chapter_number": 1,
            "location": "Outer Rim Draleth sector",
            "characters_present": ["Ben Skywalker"],
            "task": "Infiltrate the Hegemony",
        }
        result = assembler.assemble(scene_card)
        assert "Worldbuilding Lore" in result

    def test_includes_terminology_glossary(
        self, concept_seed_path, constraints_path, lore_service, tmp_path
    ):
        assembler = ContextAssembler(
            concept_seed_path=concept_seed_path,
            negative_constraints_path=constraints_path,
            manuscripts_dir=str(tmp_path / "manuscripts"),
            lore_service=lore_service,
            universe_id="test_au",
        )
        scene_card = {
            "chapter_number": 1,
            "characters_present": ["Ben Skywalker"],
        }
        result = assembler.assemble(scene_card)
        assert "Worldbuilding Terminology" in result
        assert "Hegemon" in result

    def test_skips_worldbuilding_when_no_service(
        self, concept_seed_path, constraints_path, tmp_path
    ):
        assembler = ContextAssembler(
            concept_seed_path=concept_seed_path,
            negative_constraints_path=constraints_path,
            manuscripts_dir=str(tmp_path / "manuscripts"),
        )
        scene_card = {
            "chapter_number": 1,
            "characters_present": ["Ben Skywalker"],
        }
        result = assembler.assemble(scene_card)
        assert "Worldbuilding Lore" not in result
        assert "Worldbuilding Terminology" not in result

    def test_skips_worldbuilding_when_no_universe_id(
        self, concept_seed_path, constraints_path, lore_service, tmp_path
    ):
        assembler = ContextAssembler(
            concept_seed_path=concept_seed_path,
            negative_constraints_path=constraints_path,
            manuscripts_dir=str(tmp_path / "manuscripts"),
            lore_service=lore_service,
            universe_id=None,
        )
        scene_card = {
            "chapter_number": 1,
            "characters_present": ["Ben Skywalker"],
        }
        result = assembler.assemble(scene_card)
        assert "Worldbuilding Lore" not in result

    def test_phase2_enabled_with_only_lore_service(
        self, concept_seed_path, constraints_path, lore_service, tmp_path
    ):
        assembler = ContextAssembler(
            concept_seed_path=concept_seed_path,
            negative_constraints_path=constraints_path,
            manuscripts_dir=str(tmp_path / "manuscripts"),
            lore_service=lore_service,
            universe_id="test_au",
        )
        assert assembler._phase2_enabled is True


class TestTokenBudgets:
    def test_worldbuilding_budgets_exist(self):
        assert "worldbuilding_lore" in TOKEN_BUDGETS
        assert "worldbuilding_terminology" in TOKEN_BUDGETS
        assert "worldbuilding_dialogue" in TOKEN_BUDGETS

    def test_budgets_are_positive(self):
        assert TOKEN_BUDGETS["worldbuilding_lore"] > 0
        assert TOKEN_BUDGETS["worldbuilding_terminology"] > 0
        assert TOKEN_BUDGETS["worldbuilding_dialogue"] > 0
