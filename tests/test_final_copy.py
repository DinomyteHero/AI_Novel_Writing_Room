import json

from src.pipeline.final_copy import (
    build_continuity_lockfile,
    build_motif_ledger,
    run_copydesk_checks,
    score_read_aloud_voltage,
    validate_final_copy,
)


def _scene_card():
    return {
        "chapter_number": 5,
        "scene_number": 4,
        "pov_character": "Ben Skywalker",
        "characters_present": ["Ben Skywalker", "Desh", "Sera"],
        "mission": "Ben sends a partial report and leaves with five aboard.",
        "why_now": "The escapee has twenty-three days of head start.",
        "turning_point": "Ben sends the partial report without saying help.",
        "closing_hook": "The Steady Returns clears the atmosphere.",
        "anti_patterns": ["Do not say two months."],
    }


def _contract():
    return {
        "scene_id": "ch05_sc04",
        "speakers": ["Ben Skywalker", "Desh", "Sera"],
        "checks": [
            {
                "id": "head_start_must_be_weeks_not_months",
                "type": "global_forbidden",
                "severity": "error",
                "patterns": [r"\btwo\s+months\b"],
            },
            {
                "id": "partial_report_must_surface",
                "type": "required_patterns",
                "severity": "error",
                "patterns": [r"\bpartial\s+report\b"],
            },
        ],
    }


def test_build_continuity_lockfile_collects_high_risk_contract_inputs():
    validation = {"passed": True, "hard_failure_count": 0, "failure_count": 0}

    lockfile = build_continuity_lockfile(
        scene_card=_scene_card(),
        generation_brief={"closing_beat": "The ship lifts before Luke replies."},
        scene_contract=_contract(),
        contract_validation=validation,
        source_label="draft",
    )

    assert lockfile["scene_id"] == "ch05_sc04"
    assert lockfile["source_label"] == "draft"
    assert lockfile["pov_character"] == "Ben Skywalker"
    assert any("twenty-three days" in item["text"] for item in lockfile["timeline_claims"])
    assert any(
        item.get("check_id") == "head_start_must_be_weeks_not_months"
        for item in lockfile["forbidden_drift"]
    )
    assert lockfile["contract_status"]["passed"] is True


def test_lockfile_filters_planning_language_from_locked_facts():
    lockfile = build_continuity_lockfile(
        scene_card={
            **_scene_card(),
            "closing_hook": "Sera named the protocol. Ben supplied the frame.",
        },
        generation_brief={
            "closing_beat": "Ben supplied the word Reformations himself."
        },
    )

    locked_text = " ".join(item["text"] for item in lockfile["locked_facts"])
    assert "Ben supplied" not in locked_text
    assert "Sera named" not in locked_text


def test_motif_ledger_counts_terms_and_repetition():
    prose = (
        "The wrongness had weight. The wrongness sat in Ben's chest.\n\n"
        "Silence answered him. Silence answered him. Silence answered him."
    )

    ledger = build_motif_ledger(prose, motif_terms=["wrongness", "silence"])

    motif_counts = {item["term"]: item["count"] for item in ledger["motifs"]}
    assert motif_counts["wrongness"] == 2
    assert motif_counts["silence"] == 3
    assert "repetition" in ledger


def test_copydesk_flags_compression_and_planning_language():
    prose = "Ben supplied the public frame. " + " ".join(["word"] * 20)

    report = run_copydesk_checks(prose, source_word_count=200)

    codes = {flag["code"] for flag in report["flags"]}
    assert "compression" in codes
    assert "planning_language_leak" in codes
    assert report["passed"] is False


def test_copydesk_does_not_warn_expansion_when_final_copy_hits_target_band():
    report = run_copydesk_checks(
        " ".join(["word"] * 110),
        source_word_count=70,
        target_word_count=100,
    )

    codes = {flag["code"] for flag in report["flags"]}
    assert "expansion" not in codes


def test_copydesk_flags_lukes_order_in_ben_close_third():
    report = run_copydesk_checks(
        "Luke's Order had inherited the record.",
        scene_card=_scene_card(),
    )

    codes = {flag["code"] for flag in report["flags"]}
    assert "ben_close_third_lukes_order" in codes


def test_copydesk_does_not_treat_lowercase_named_as_planning_leak():
    report = run_copydesk_checks("The archive never named the missing chamber.")

    codes = {flag["code"] for flag in report["flags"]}
    assert "planning_language_leak" not in codes


def test_read_aloud_voltage_returns_score_shape():
    prose = (
        "Cold light moved across the viewport. Ben kept his hands still.\n\n"
        '"Partial report," Sera said.\n\n'
        '"Not help," Ben said.\n\n'
        "The Steady Returns cleared the atmosphere."
    )

    report = score_read_aloud_voltage(prose, scene_card=_scene_card())

    assert report["max_score"] == 25
    assert report["total_score"] > 0
    assert "final_line_charge" in report["ratings"]
    assert report["signals"]["speaker_count"] >= 2


def test_validate_final_copy_combines_contract_and_copydesk():
    prose = "The partial report was gone. The escapee had two months."

    report = validate_final_copy(
        prose,
        scene_contract=_contract(),
        source_word_count=8,
        scene_card=_scene_card(),
    )

    assert report["passed"] is False
    assert report["scene_contract_validation"]["passed"] is False
    assert report["scene_contract_validation"]["hard_failure_count"] == 1


def test_lockfile_is_json_serializable():
    lockfile = build_continuity_lockfile(
        scene_card=_scene_card(),
        scene_contract=_contract(),
    )

    assert json.loads(json.dumps(lockfile))["scene_id"] == "ch05_sc04"
