"""Tests for scripts/audit_phase0.py criterion evaluators and dry-run rendering.

The audit is the gate unblocking Slice 2; these tests protect the evaluators
so that future prompt-assembly changes can't silently regress the gate.
"""

import json
from pathlib import Path

import pytest

# Import the script as a module. It lives under scripts/ so add to sys.path.
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import audit_phase0 as ap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


MINIMAL_SEED = {
    "meta": {
        "project_title": "Test Book",
        "franchise": "star-wars-legends-eu",
        "era": "Legends",
        "tone": "adult",
        "pov_structure": "third-person limited",
    },
    "premise": {"what_if": "", "central_dramatic_question": ""},
    "conflict": {
        "primary_antagonistic_force": {"identity": "", "motivation": ""},
        "lock_in_mechanism": "",
    },
    "theme": {"thematic_premise": ""},
    "ensemble_cast": [
        {
            "name": "Ben",
            "role": "protagonist",
            "voice_notes": "close-third",
            "three_dimensions": {
                "surface": "calm",
                "action_under_pressure": "precise",
            },
        },
    ],
    "voice_definition": {
        "pov_approach": "close-third limited",
        "prose_register": "Adult Legends fiction. Zahn-clarity surface.",
        "reference_authors": [
            {"author": "Timothy Zahn", "what_to_emulate": "clarity"},
        ],
        "anti_slop_rules": [
            "No metaphor stacks. No 'tapestry of' constructions.",
        ],
    },
}


SCENE_CARD = {
    "chapter_number": 1,
    "scene_number": 1,
    "structural_phase": "setup",
    "pov_character": "Ben",
    "mission": "Ben loses a sparring match because of a disturbance in the Force.",
    "turning_point": "Ben stops pretending the wrongness is fatigue.",
    "characters_present": ["Ben", "Rendell"],
    "closing_hook": "Luke appears in the doorway.",
    "target_word_count": 1250,
    "action_beats": ["Spar begins", "Ben's guard drops", "Rendell lands hit"],
    "anti_patterns": ["do not infodump"],
}


# ---------------------------------------------------------------------------
# _synthesize_brief
# ---------------------------------------------------------------------------


def test_synthesize_brief_carries_scene_contract():
    brief = ap._synthesize_brief(SCENE_CARD)
    assert brief["scene_objective"] == SCENE_CARD["mission"]
    assert brief["closing_beat"] == SCENE_CARD["closing_hook"]
    assert brief["target_word_count"] == 1250
    assert brief["turning_point"]["trigger"].startswith("Ben stops")
    assert len(brief["key_beats"]) == 3


def test_synthesize_brief_handles_missing_fields():
    brief = ap._synthesize_brief({})
    assert brief["scene_objective"] == ""
    assert brief["closing_beat"] == ""
    assert brief["turning_point"] == {"trigger": "", "shift": "", "cost": ""}
    assert brief["key_beats"] == []


# ---------------------------------------------------------------------------
# _line_range
# ---------------------------------------------------------------------------


def test_line_range_returns_none_for_absent_needle():
    assert ap._line_range("line 1\nline 2", "missing") is None
    assert ap._line_range("anything", "") is None


def test_line_range_reports_single_line():
    text = "line 1\nline 2 target\nline 3"
    result = ap._line_range(text, "target")
    assert result == "L2-L2"


def test_line_range_reports_multi_line_needle():
    text = "a\nb\nmulti\nline\nthing\ne"
    result = ap._line_range(text, "multi\nline\nthing")
    assert result == "L3-L5"


# ---------------------------------------------------------------------------
# _evaluate_voice_rules
# ---------------------------------------------------------------------------


def test_evaluate_voice_rules_pass_when_register_and_authors_present(tmp_path):
    prompt = (
        "## Voice Rules (MANDATORY)\n"
        "**Register**: Adult Legends fiction. Zahn-clarity surface.\n"
        "Reference: Timothy Zahn\n"
        "- No metaphor stacks. No 'tapestry of' constructions.\n"
    )
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_voice_rules(
        prompt_path=p, prompt_text=prompt, concept_seed=MINIMAL_SEED,
    )
    assert result["pass"] is True
    assert "prose_register" in result["evidence"]
    assert "Timothy Zahn" in result["evidence"]


def test_evaluate_voice_rules_fail_when_register_absent(tmp_path):
    prompt = "Reference: Timothy Zahn\nRules: No slop"
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_voice_rules(
        prompt_path=p, prompt_text=prompt, concept_seed=MINIMAL_SEED,
    )
    assert result["pass"] is False
    assert "prose_register" in result["evidence"]


def test_evaluate_voice_rules_fail_when_authors_absent(tmp_path):
    prompt = (
        "## Voice Rules\n"
        "**Register**: Adult Legends fiction. Zahn-clarity surface.\n"
        "- No metaphor stacks. No 'tapestry of' constructions.\n"
    )
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_voice_rules(
        prompt_path=p, prompt_text=prompt, concept_seed=MINIMAL_SEED,
    )
    assert result["pass"] is False
    assert "reference_authors" in result["evidence"]


def test_evaluate_voice_rules_handles_two_tier_anti_slop(tmp_path):
    seed = dict(MINIMAL_SEED)
    seed["voice_definition"] = dict(seed["voice_definition"])
    seed["voice_definition"]["anti_slop_rules"] = {
        "description": "Two-tier",
        "derived_rules": ["Never use 'it wasnt just X it was Y' constructions."],
        "line_level_rules": ["No 'delve'."],
    }
    prompt = (
        "**Register**: Adult Legends fiction. Zahn-clarity surface.\n"
        "Author: Timothy Zahn\n"
        "Rule: Never use 'it wasnt just X it was Y' constructions.\n"
    )
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_voice_rules(
        prompt_path=p, prompt_text=prompt, concept_seed=seed,
    )
    assert result["pass"] is True


# ---------------------------------------------------------------------------
# _evaluate_scene_contract
# ---------------------------------------------------------------------------


def test_evaluate_scene_contract_pass_when_all_fields_surface(tmp_path):
    prompt = (
        f"Mission: {SCENE_CARD['mission']}\n"
        f"Turning point: {SCENE_CARD['turning_point']}\n"
        f"POV: Ben\n"
        f"Characters: Ben, Rendell\n"
        f"Closing hook: {SCENE_CARD['closing_hook']}\n"
    )
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_scene_contract(
        prompt_path=p, prompt_text=prompt, scene_card=SCENE_CARD,
    )
    assert result["pass"] is True


def test_evaluate_scene_contract_fail_when_mission_truncated(tmp_path):
    prompt = (
        "Turning point: Ben stops pretending the wrongness is fatigue.\n"
        "POV: Ben\nCharacters: Ben, Rendell\n"
        "Closing hook: Luke appears in the doorway.\n"
    )
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_scene_contract(
        prompt_path=p, prompt_text=prompt, scene_card=SCENE_CARD,
    )
    assert result["pass"] is False
    assert "mission=MISSING" in result["evidence"]


def test_evaluate_scene_contract_fail_when_character_dropped(tmp_path):
    prompt = (
        f"Mission: {SCENE_CARD['mission']}\n"
        f"Turning point: {SCENE_CARD['turning_point']}\n"
        "POV: Ben\nCharacters: Ben\n"
        f"Closing hook: {SCENE_CARD['closing_hook']}\n"
    )
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_scene_contract(
        prompt_path=p, prompt_text=prompt, scene_card=SCENE_CARD,
    )
    assert result["pass"] is False
    assert "Rendell" in result["evidence"]


# ---------------------------------------------------------------------------
# _evaluate_constraints
# ---------------------------------------------------------------------------


def test_evaluate_constraints_pass_when_most_banned_phrases_present(tmp_path):
    yaml_path = tmp_path / "neg.yaml"
    yaml_path.write_text(
        "banned_phrases:\n"
        "  ai_tells:\n"
        "    - 'delve'\n"
        "    - 'tapestry'\n"
        "    - 'testament'\n"
        "    - 'nuanced'\n"
        "    - 'landscape'\n",
        encoding="utf-8",
    )
    prompt = (
        "Banned: AVOID: delve\nAVOID: tapestry\nAVOID: testament\n"
        "AVOID: nuanced\nAVOID: landscape\n"
    )
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_constraints(
        prompt_path=p, prompt_text=prompt, negative_constraints_path=yaml_path,
    )
    assert result["pass"] is True
    assert "5/5" in result["evidence"]


def test_evaluate_constraints_fail_when_truncated(tmp_path):
    yaml_path = tmp_path / "neg.yaml"
    yaml_path.write_text(
        "banned_phrases:\n"
        "  ai_tells:\n" + "\n".join(f"    - 'phrase_{i}'" for i in range(10)) + "\n",
        encoding="utf-8",
    )
    prompt = "Banned: AVOID: phrase_0\nAVOID: phrase_1\n"
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_constraints(
        prompt_path=p, prompt_text=prompt, negative_constraints_path=yaml_path,
    )
    assert result["pass"] is False
    assert "2/10" in result["evidence"]


# ---------------------------------------------------------------------------
# _evaluate_cross_scene_feedback
# ---------------------------------------------------------------------------


def test_cross_scene_feedback_fails_with_single_scene(tmp_path):
    scene_prompts = {1: {"user": tmp_path / "sc1.txt", "system": tmp_path / "sys1.txt"}}
    scene_prompts[1]["user"].write_text("Scene 1 prompt", encoding="utf-8")
    result = ap._evaluate_cross_scene_feedback(
        scene_prompts=scene_prompts, chapter=1,
    )
    assert result["pass"] is False
    assert "need ≥2" in result["evidence"]


def test_cross_scene_feedback_pass_when_sc2_has_feedback_marker(tmp_path):
    sc1 = tmp_path / "sc1.txt"
    sc2 = tmp_path / "sc2.txt"
    sc1.write_text("Scene 1 unique content about Ben's sparring night", encoding="utf-8")
    sc2.write_text(
        "## Cross-Scene Feedback (from prior scenes in this chapter)\n"
        "Prior scene ended on: Luke appears in doorway.\n",
        encoding="utf-8",
    )
    scene_prompts = {
        1: {"user": sc1, "system": tmp_path / "sys1.txt"},
        2: {"user": sc2, "system": tmp_path / "sys2.txt"},
    }
    result = ap._evaluate_cross_scene_feedback(
        scene_prompts=scene_prompts, chapter=1,
    )
    assert result["pass"] is True
    assert "Cross-Scene Feedback" in result["evidence"]


def test_cross_scene_feedback_fails_when_no_markers_or_content_carry(tmp_path):
    sc1 = tmp_path / "sc1.txt"
    sc2 = tmp_path / "sc2.txt"
    sc1.write_text("Scene 1 content", encoding="utf-8")
    sc2.write_text("Totally independent scene 2 content.", encoding="utf-8")
    scene_prompts = {
        1: {"user": sc1, "system": tmp_path / "sys1.txt"},
        2: {"user": sc2, "system": tmp_path / "sys2.txt"},
    }
    result = ap._evaluate_cross_scene_feedback(
        scene_prompts=scene_prompts, chapter=1,
    )
    assert result["pass"] is False


# ---------------------------------------------------------------------------
# _evaluate_register_policy
# ---------------------------------------------------------------------------


def test_register_policy_pass_with_single_declaration(tmp_path):
    prompt = (
        "## Voice Rules (MANDATORY)\n"
        "**Register**: Adult Legends fiction. Zahn-clarity surface.\n"
    )
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_register_policy(
        prompt_path=p, prompt_text=prompt, concept_seed=MINIMAL_SEED,
    )
    assert result["pass"] is True
    assert "single register" in result["evidence"]


def test_register_policy_fail_with_absent_register(tmp_path):
    prompt = "## Voice Rules\n**POV**: third-person limited\n"
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_register_policy(
        prompt_path=p, prompt_text=prompt, concept_seed=MINIMAL_SEED,
    )
    assert result["pass"] is False
    assert "absent" in result["evidence"]


def test_register_policy_fail_with_multiple_declarations(tmp_path):
    prompt = (
        "**Register**: Adult Legends fiction. Zahn-clarity surface.\n"
        "**Register**: YA Fluff (contradictory).\n"
    )
    p = tmp_path / "prompt.txt"
    p.write_text(prompt, encoding="utf-8")
    result = ap._evaluate_register_policy(
        prompt_path=p, prompt_text=prompt, concept_seed=MINIMAL_SEED,
    )
    assert result["pass"] is False
    assert "2 distinct" in result["evidence"]


# ---------------------------------------------------------------------------
# End-to-end smoke: run the script on Ruusan ch01 and verify overall_pass
# ---------------------------------------------------------------------------


def _ruusan_seed() -> Path:
    return (
        Path(__file__).parent.parent
        / "data" / "franchises" / "star-wars-legends-eu"
        / "books" / "the-ruusan-atonement" / "concept_seed.json"
    )


def _betrayal_seed() -> Path:
    return (
        Path(__file__).parent.parent
        / "data" / "franchises" / "star-wars-legends-eu"
        / "books" / "legacy-of-the-force-betrayal" / "concept_seed.json"
    )


@pytest.mark.parametrize("seed_fn", [_ruusan_seed, _betrayal_seed])
def test_audit_phase0_gate_passes_for_shipping_books(seed_fn, tmp_path):
    """Slice-2 gate: the audit must pass for both Ruusan and Betrayal at HEAD.

    A failure here means prompt-assembly regressed — sc1's voice rules, scene
    contract, constraints, cross-scene feedback plumbing, or single-register
    policy can no longer be verified. Fix the regression before proceeding.
    """
    seed_path = seed_fn()
    if not seed_path.exists():
        pytest.skip(f"concept_seed not present: {seed_path}")

    # Keep the run dir in tmp_path so pytest output doesn't leak into output/.
    run_dir = tmp_path / f"phase0_pytest_{seed_path.parent.name}"

    import subprocess
    import sys
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent.parent / "scripts" / "audit_phase0.py"),
            "--concept-seed", str(seed_path),
            "--chapter", "1",
            "--run-label", f"phase0_pytest_{seed_path.parent.name}",
            "--run-dir", str(run_dir),
            "--audits-dir", str(tmp_path / "audits"),
            "--negative-constraints",
            str(Path(__file__).parent.parent / "config" / "negative_constraints.yaml"),
        ],
        cwd=str(Path(__file__).parent.parent),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"audit_phase0.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Overall pass: True" in result.stdout, (
        f"Phase 0 audit did not pass:\n{result.stdout}"
    )
