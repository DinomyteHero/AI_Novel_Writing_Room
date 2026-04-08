"""Tests for voice rule injection in ContextAssembler."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.memory.context_assembler import ContextAssembler


@pytest.fixture
def seed_with_voice(tmp_path):
    """Create a concept seed with voice_definition."""
    seed = {
        "meta": {"project_title": "Test", "franchise": "Original", "era": "Modern",
                 "tone": "dark_gritty", "target_word_count": 80000, "target_chapters": 20},
        "premise": {"what_if": "x" * 60, "central_dramatic_question": "CDQ", "logline": "Log"},
        "conflict": {"primary_antagonistic_force": {"type": "x", "motivation": "x" * 60,
                     "escalation": "x" * 110}, "lock_in_mechanism": "x" * 40},
        "theme": {"thematic_premise": "x", "thematic_argument": "x" * 110,
                  "how_each_arc_tests_theme": {}},
        "ensemble_cast": [{"name": "Hero", "role": "Protagonist",
                           "three_dimensions": {"surface": "x" * 60,
                                                "backstory_inner_demons": "x" * 60,
                                                "action_under_pressure": "x" * 60},
                           "voice_notes": "x" * 40}],
        "canon_constraints": {"continuity": "x", "canon_preserved": [], "style_constraints": []},
        "voice_definition": {
            "pov_approach": "close third-person limited",
            "prose_register": "commercial",
            "anti_slop": {
                "banned_words": ["delve", "tapestry", "nuanced"],
                "banned_phrases": ["It wasn't just X, it was Y", "A testament to"],
            },
            "anti_patterns": ["Every chapter opening with weather description"],
            "narrative_voice_notes": "Keep it punchy and direct.",
        },
    }
    path = tmp_path / "concept_seed.json"
    with open(path, "w") as f:
        json.dump(seed, f)
    return str(path)


class TestVoiceRulesAssembly:
    """Tests that voice rules appear in assembled context."""

    def test_voice_rules_in_assembled_output(self, seed_with_voice, tmp_path):
        """Voice definition rules appear in the Phase 2 assembled context."""
        constraints_path = str(tmp_path / "neg.yaml")
        with open(constraints_path, "w") as f:
            f.write("banned_phrases:\n  ai_tells:\n    - delve\n")

        assembler = ContextAssembler(
            concept_seed_path=seed_with_voice,
            negative_constraints_path=constraints_path,
            manuscripts_dir=str(tmp_path / "manuscripts"),
        )
        # Test the voice rules method directly
        voice_rules = assembler._assemble_voice_rules()
        assert "Voice Rules (MANDATORY)" in voice_rules
        assert "delve" in voice_rules
        assert "tapestry" in voice_rules
        assert "close third-person limited" in voice_rules
        assert "commercial" in voice_rules
        assert "weather description" in voice_rules
        assert "punchy and direct" in voice_rules

    def test_no_voice_definition_returns_empty(self, tmp_path):
        """Without voice_definition, _assemble_voice_rules returns empty string."""
        seed = {
            "meta": {"project_title": "Test", "franchise": "X", "era": "X",
                     "tone": "dark_gritty", "target_word_count": 80000},
            "premise": {"what_if": "x" * 60, "central_dramatic_question": "x", "logline": "x"},
            "conflict": {"primary_antagonistic_force": {"type": "x", "motivation": "x" * 60,
                         "escalation": "x" * 110}, "lock_in_mechanism": "x" * 40},
            "theme": {"thematic_premise": "x", "thematic_argument": "x" * 110,
                      "how_each_arc_tests_theme": {}},
            "ensemble_cast": [{"name": "H", "role": "P",
                               "three_dimensions": {"surface": "x" * 60,
                                                    "backstory_inner_demons": "x" * 60,
                                                    "action_under_pressure": "x" * 60},
                               "voice_notes": "x" * 40}],
            "canon_constraints": {"continuity": "x", "canon_preserved": [], "style_constraints": []},
        }
        path = tmp_path / "seed_no_voice.json"
        with open(path, "w") as f:
            json.dump(seed, f)

        constraints_path = str(tmp_path / "neg.yaml")
        with open(constraints_path, "w") as f:
            f.write("banned_phrases:\n  ai_tells: []\n")

        assembler = ContextAssembler(
            concept_seed_path=str(path),
            negative_constraints_path=constraints_path,
        )
        assert assembler._assemble_voice_rules() == ""
