"""Tests for src/agents/rhythm_editor.py.

Covers two surfaces:
- The LLM-facing agent (prompt building, response parsing, normalization).
- The deterministic apply path (safety caps applied regardless of model output).
"""

from __future__ import annotations

import pytest

from src.agents.rhythm_editor import RhythmEditor, apply_rhythm_edits


# --- normalization ---------------------------------------------------------


def test_normalize_drops_unknown_issue_codes():
    raw = {
        "summary": "test",
        "edits": [
            {
                "fix_for_issue_code": "rhythm.em_dash_overuse",
                "pattern": "a",
                "replacement": "b",
                "reason": "x",
            },
            {
                "fix_for_issue_code": "rhythm.dialogue_starved",  # not in scope
                "pattern": "c",
                "replacement": "d",
            },
            {
                "fix_for_issue_code": "not.a.real.code",
                "pattern": "e",
                "replacement": "f",
            },
        ],
    }
    result = RhythmEditor._normalize_result(raw)
    assert len(result["edits"]) == 1
    assert result["edits"][0]["fix_for_issue_code"] == "rhythm.em_dash_overuse"


def test_normalize_drops_noop_edits():
    raw = {
        "summary": "x",
        "edits": [
            {"fix_for_issue_code": "rhythm.em_dash_overuse",
             "pattern": "same", "replacement": "same"},
        ],
    }
    result = RhythmEditor._normalize_result(raw)
    assert result["edits"] == []


def test_normalize_drops_empty_pattern():
    raw = {
        "summary": "x",
        "edits": [
            {"fix_for_issue_code": "rhythm.em_dash_overuse",
             "pattern": "", "replacement": "b"},
        ],
    }
    result = RhythmEditor._normalize_result(raw)
    assert result["edits"] == []


def test_normalize_coerces_missing_replacement_to_empty_string():
    raw = {
        "summary": "x",
        "edits": [
            {"fix_for_issue_code": "rhythm.em_dash_overuse",
             "pattern": "abc"},
        ],
    }
    result = RhythmEditor._normalize_result(raw)
    assert result["edits"][0]["replacement"] == ""


# --- response parsing ------------------------------------------------------


def test_parse_response_handles_fenced_json():
    editor = RhythmEditor.__new__(RhythmEditor)  # skip __init__ for unit test
    raw = '```json\n{"summary": "ok", "edits": []}\n```'
    parsed = editor._parse_response(raw, {})
    assert parsed == {"summary": "ok", "edits": []}


def test_parse_response_handles_trailing_text():
    editor = RhythmEditor.__new__(RhythmEditor)
    raw = 'Sure, here is the JSON:\n{"summary": "ok", "edits": []}\nLet me know!'
    parsed = editor._parse_response(raw, {})
    assert parsed["summary"] == "ok"


def test_parse_response_returns_empty_on_garbage():
    editor = RhythmEditor.__new__(RhythmEditor)
    parsed = editor._parse_response("this is not JSON at all", {})
    assert parsed == {"summary": "", "edits": []}


# --- apply path: success cases ---------------------------------------------


def test_apply_single_edit():
    prose = "She turned — slowly — and looked at him."
    edits = [{
        "fix_for_issue_code": "rhythm.em_dash_overuse",
        "pattern": "She turned — slowly — and looked",
        "replacement": "She turned slowly and looked",
        "reason": "cut em-dashes",
    }]
    patched, audit = apply_rhythm_edits(prose, edits)
    assert "—" not in patched
    assert sum(1 for a in audit if a["action"] == "applied") == 1


def test_apply_multiple_edits_under_cap():
    prose = (
        "He moved — quickly — toward the door. "
        "She watched — patient — from the corner."
    )
    edits = [
        {"fix_for_issue_code": "rhythm.em_dash_overuse",
         "pattern": "He moved — quickly — toward",
         "replacement": "He moved quickly toward"},
        {"fix_for_issue_code": "rhythm.em_dash_overuse",
         "pattern": "She watched — patient — from",
         "replacement": "She watched, patient, from"},
    ]
    patched, audit = apply_rhythm_edits(prose, edits)
    assert "He moved quickly toward" in patched
    assert "She watched, patient, from" in patched
    applied = [a for a in audit if a["action"] == "applied"]
    assert len(applied) == 2


# --- apply path: safety caps ------------------------------------------------


def test_apply_rejects_pattern_not_in_prose():
    prose = "She turned slowly."
    edits = [{
        "fix_for_issue_code": "rhythm.em_dash_overuse",
        "pattern": "He moved quickly",
        "replacement": "x",
    }]
    patched, audit = apply_rhythm_edits(prose, edits)
    assert patched == prose
    assert audit[0]["action"] == "rejected"
    assert audit[0]["reason"] == "pattern_not_in_prose"


def test_apply_rejects_ambiguous_pattern():
    prose = "He moved. He moved again. He moved a third time."
    edits = [{
        "fix_for_issue_code": "rhythm.em_dash_overuse",
        "pattern": "He moved",
        "replacement": "He paused",
    }]
    patched, audit = apply_rhythm_edits(prose, edits)
    assert patched == prose
    assert audit[0]["reason"] == "ambiguous_pattern_occurrences"
    assert audit[0]["occurrences"] == 3


def test_apply_rejects_duplicate_pattern():
    prose = "She walked to the door."
    edits = [
        {"fix_for_issue_code": "rhythm.em_dash_overuse",
         "pattern": "She walked", "replacement": "She strode"},
        {"fix_for_issue_code": "rhythm.em_dash_overuse",
         "pattern": "She walked", "replacement": "She marched"},
    ]
    patched, audit = apply_rhythm_edits(prose, edits)
    assert "She strode" in patched
    rejected = [a for a in audit if a["action"] == "rejected"]
    assert any(r["reason"] == "duplicate_pattern" for r in rejected)


def test_apply_enforces_max_edits_cap():
    # Build 10 distinct edits with unambiguous (non-overlapping) patterns,
    # cap at 3.
    tokens = ["alpha", "bravo", "charlie", "delta", "echo",
              "foxtrot", "golf", "hotel", "india", "juliet"]
    prose = " ".join(tokens)
    edits = [
        {"fix_for_issue_code": "rhythm.em_dash_overuse",
         "pattern": tok, "replacement": tok.upper()}
        for tok in tokens
    ]
    patched, audit = apply_rhythm_edits(prose, edits, max_edits=3)
    applied = [a for a in audit if a["action"] == "applied"]
    rejected = [a for a in audit if a["action"] == "rejected"
                and a["reason"] == "max_edits_exceeded"]
    assert len(applied) == 3
    assert len(rejected) == 7


def test_apply_enforces_changed_char_budget():
    prose = "abc def ghi"
    edits = [
        {"fix_for_issue_code": "rhythm.em_dash_overuse",
         "pattern": "abc", "replacement": "A" * 1000},
    ]
    patched, audit = apply_rhythm_edits(
        prose, edits, max_total_changed_chars=50,
    )
    assert patched == prose
    assert audit[0]["reason"] == "changed_char_budget_exceeded"


def test_apply_enforces_changed_ratio_ceiling():
    prose = "abc def"  # 7 chars
    edits = [
        {"fix_for_issue_code": "rhythm.em_dash_overuse",
         "pattern": "abc", "replacement": "longer replacement text"},
    ]
    patched, audit = apply_rhythm_edits(
        prose, edits, max_changed_ratio=0.1,
    )
    assert patched == prose
    assert audit[0]["reason"] == "changed_ratio_exceeded"


# --- defensive cases --------------------------------------------------------


def test_apply_handles_empty_prose():
    patched, audit = apply_rhythm_edits("", [{"pattern": "x", "replacement": "y"}])
    assert patched == ""


def test_apply_handles_non_list_edits():
    patched, audit = apply_rhythm_edits("abc", "not a list")
    assert patched == "abc"
    assert audit == []


def test_apply_handles_non_dict_edit_entry():
    patched, audit = apply_rhythm_edits("abc", ["not a dict", None, 42])
    assert patched == "abc"


def test_apply_handles_non_string_replacement():
    edits = [{"fix_for_issue_code": "rhythm.em_dash_overuse",
              "pattern": "abc", "replacement": 42}]
    patched, audit = apply_rhythm_edits("abc def", edits)
    assert patched == "abc def"
    assert audit[0]["reason"] == "non_string_replacement"
