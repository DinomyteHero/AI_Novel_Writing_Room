import json
from pathlib import Path

from src.quality.scene_contract_validator import validate_prose_contract


ROOT = Path(__file__).resolve().parents[1]


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


def test_scene_contract_carries_speaker_through_pronoun_action_beat():
    prose = (
        'Torin studied the heading. "I remember this index."\n\n'
        'He tapped the display. "Not the public settlement. The private one."\n\n'
        'Kael watched in silence.'
    )

    result = validate_prose_contract(prose, _contract())

    assert not result["passed"]
    assert any(
        failure["check_id"] == "survivor_later_frame"
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


def _load_ruusan_contract(name: str):
    path = (
        ROOT
        / "data"
        / "franchises"
        / "star-wars-legends-eu"
        / "books"
        / "the-ruusan-atonement"
        / "scene_contracts"
        / name
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_ch05_sc02_contract_blocks_plain_reformations_in_survivor_dialogue():
    contract = _load_ruusan_contract("ch05_sc02.json")
    prose = (
        'Torin studied the display. "The Reformations. You will know this part."\n\n'
        'Kael reached past him. "Not architect. Custodian."\n\n'
        "Twelve chamber-bound anchors surrounded Gavran as central keystone."
    )

    result = validate_prose_contract(prose, contract)

    assert not result["passed"]
    assert any(
        failure["check_id"] == "survivors_cannot_carry_public_reformations_frame"
        and failure.get("speaker") == "Torin"
        for failure in result["failures"]
    )


def test_ch05_sc02_contract_blocks_survivor_public_frame_paraphrases():
    contract = _load_ruusan_contract("ch05_sc02.json")
    prose = (
        'Sera studied the display. "Gavran built this before the official settlement. '
        'The later records never named it."\n\n'
        'Torin folded his arms. "Not the version the Order published afterward. '
        'The private one."\n\n'
        'Kael reached past him. "Not architect. Custodian."\n\n'
        "Twelve chamber-bound anchors surrounded Gavran as central keystone."
    )

    result = validate_prose_contract(prose, contract)

    assert not result["passed"]
    assert sum(
        1
        for failure in result["failures"]
        if failure["check_id"] == "survivors_cannot_carry_public_reformations_frame"
    ) >= 3


def test_ch05_sc02_contract_blocks_decentralized_public_reforms():
    contract = _load_ruusan_contract("ch05_sc02.json")
    prose = (
        'Ben checked the index. "The public settlement decentralized the Order."\n\n'
        'Sera said, "Private penance-and-containment."\n\n'
        'Kael reached past her. "Not architect. Custodian."\n\n'
        "Twelve chamber-bound anchors surrounded Gavran as central keystone."
    )

    result = validate_prose_contract(prose, contract)

    assert not result["passed"]
    assert any(
        failure["check_id"] == "public_reformations_must_not_decentralize_order"
        for failure in result["failures"]
    )


def test_ch04_sc03_contract_requires_8_3_1_stasis_math():
    contract = _load_ruusan_contract("ch04_sc03.json")
    prose = (
        "Around the ring were twelve chambers.\n\n"
        "Nine dark chambers lined the wall.\n\n"
        "Three chambers were still lit.\n\n"
        "The twelfth chamber was broken open from inside.\n\n"
        "The breach had been logged twenty-three standard days ago."
    )

    result = validate_prose_contract(prose, contract)

    assert not result["passed"]
    assert any(
        failure["check_id"] == "stasis_ring_inventory_must_be_8_3_1"
        for failure in result["failures"]
    )
    assert any(
        failure["check_id"] == "stasis_ring_inventory_must_not_be_9_3_1"
        for failure in result["failures"]
    )


def test_ch05_sc04_contract_blocks_two_month_head_start():
    contract = _load_ruusan_contract("ch05_sc04.json")
    prose = (
        "The report to Luke was already open. Survey complete. Continuing investigation.\n\n"
        "The report did not mention the survivors. It did not mention the seal. "
        "It did not say help.\n\n"
        "The escapee had two months of head start.\n\n"
        "The Steady Returns lifted from the plateau."
    )

    result = validate_prose_contract(prose, contract)

    assert not result["passed"]
    assert any(
        failure["check_id"] == "head_start_must_be_weeks_not_months"
        for failure in result["failures"]
    )
