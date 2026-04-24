from src.quality.scene_contract_validator import validate_prose_contract


def _contract():
    return {
        "scene_id": "test_scene",
        "speakers": ["Ben", "Desh", "Sera", "Torin", "Kael"],
        "checks": [
            {
                "id": "survivor_later_frame",
                "type": "speaker_forbidden",
                "severity": "error",
                "speakers": ["Sera", "Torin", "Kael"],
                "patterns": [r"\bpublic\s+settlement\b"],
            },
            {
                "id": "kael_owns_correction",
                "type": "speaker_forbidden",
                "severity": "error",
                "speakers": ["Sera", "Torin"],
                "patterns": [r"\bnot\s+(?:the\s+)?architect\b", r"\bcustodian\b"],
            },
            {
                "id": "kael_required",
                "type": "character_required",
                "severity": "error",
                "character": "Kael",
                "window_paragraphs": 2,
                "patterns": [r"\bcustodian\b", r"\barchitect\b"],
            },
        ],
    }


def test_scene_contract_detects_survivor_later_frame_dialogue():
    prose = (
        'Sera looked at the display. "It predates the public settlement. Yes."\n\n'
        'Kael touched the title. "Custodian."'
    )

    result = validate_prose_contract(prose, _contract())

    assert not result["passed"]
    assert any(
        failure["check_id"] == "survivor_later_frame"
        and failure.get("speaker") == "Sera"
        for failure in result["failures"]
    )


def test_scene_contract_detects_wrong_gavran_correction_owner():
    prose = (
        'Torin studied the heading. "Not architect. Custodian."\n\n'
        'Kael watched in silence.'
    )

    result = validate_prose_contract(prose, _contract())

    assert not result["passed"]
    assert any(
        failure["check_id"] == "kael_owns_correction"
        and failure.get("speaker") == "Torin"
        for failure in result["failures"]
    )


def test_scene_contract_passes_when_ben_owns_frame_and_kael_correction():
    prose = (
        'Ben checked his datapad. "The public settlement was real."\n\n'
        'Sera did not soften her voice. "Private penance-and-containment."\n\n'
        'Kael reached past her. "Not architect. Custodian."'
    )

    result = validate_prose_contract(prose, _contract())

    assert result["passed"]
    assert result["hard_failure_count"] == 0


def test_scene_contract_does_not_steal_speaker_from_next_paragraph():
    prose = (
        "Ben's mind moved toward the timeline.\n\n"
        '"Veranthos predates the public settlement," he said. '
        '"This was written before that."\n\n'
        '"Yes," Torin said quietly.\n\n'
        'Kael reached past them. "Custodian."'
    )

    result = validate_prose_contract(prose, _contract())

    public_settlement_failures = [
        failure for failure in result["failures"]
        if failure["check_id"] == "survivor_later_frame"
    ]
    assert public_settlement_failures == []
