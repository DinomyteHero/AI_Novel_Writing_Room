"""Tests for the Slice 1 successor classifier.

Covers each of the six classification rules and the agreement check against
the hand-labeled set at ``tests/data/successor_classifier_labels.json``.
Until that file reaches 30 labels, the agreement check asserts each pair
individually instead of enforcing the ≥ 27 / 30 gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline.successor_classifier import (
    SuccessorClassifier,
    SuccessorDecision,
    build_chapter_index,
    scene_id_from_card,
)


def _cards_to_index(cards: list[dict]) -> dict[int, list[str]]:
    return build_chapter_index(cards)


def test_scene_id_formatting():
    assert scene_id_from_card({"chapter_number": 4, "scene_number": 7}) == "ch04_sc07"
    assert scene_id_from_card({"chapter_number": 12, "scene_number": 3}) == "ch12_sc03"


def test_rule1_immediate_sequel_wins_over_everything():
    blocked = {
        "chapter_number": 4, "scene_number": 7,
        "pov_character": "Hunter", "structural_phase": "midpoint",
        "characters_present": ["Hunter"],
    }
    candidate = {
        "chapter_number": 9, "scene_number": 3,
        "pov_character": "Leia", "structural_phase": "attack",
        "characters_present": ["Leia"],
        "depends_on": ["ch04_sc07"],
    }
    idx = _cards_to_index([blocked, candidate])
    d = SuccessorClassifier().classify(
        blocked_scene=blocked, candidate_scene=candidate, chapter_index=idx,
    )
    assert d.class_label == "immediate_sequel"
    assert d.recommendation == "soft_halt"


def test_rule2_same_pov_continuation():
    blocked = {
        "chapter_number": 1, "scene_number": 1,
        "pov_character": "Ben Skywalker", "structural_phase": "setup",
        "characters_present": ["Ben Skywalker", "Luke Skywalker"],
    }
    candidate = {
        "chapter_number": 1, "scene_number": 2,
        "pov_character": "Ben Skywalker", "structural_phase": "setup",
        "characters_present": ["Ben Skywalker", "Desh Rolan"],
    }
    idx = _cards_to_index([blocked, candidate])
    d = SuccessorClassifier().classify(
        blocked_scene=blocked, candidate_scene=candidate, chapter_index=idx,
    )
    assert d.class_label == "same_pov_continuation"
    assert d.recommendation == "soft_halt"


def test_rule3_same_turn_escalation_across_chapter_boundary():
    blocked = {
        "chapter_number": 1, "scene_number": 2,
        "pov_character": "Jacen Solo", "structural_phase": "setup",
        "characters_present": ["Jacen Solo", "Ben Skywalker"],
    }
    candidate = {
        "chapter_number": 2, "scene_number": 1,
        "pov_character": "Jacen Solo", "structural_phase": "setup",
        "characters_present": ["Jacen Solo", "Nelani Dinn"],
    }
    idx = _cards_to_index([blocked, candidate])
    d = SuccessorClassifier().classify(
        blocked_scene=blocked, candidate_scene=candidate, chapter_index=idx,
    )
    # Rule 2 doesn't fire (not same chapter); rule 3 fires (same phase, first
    # scene of next chapter).
    assert d.class_label == "same_turn_escalation"
    assert d.recommendation == "soft_halt"


def test_rule4_transitional_with_gap_is_cautious():
    blocked = {
        "chapter_number": 2, "scene_number": 1,
        "pov_character": "A", "structural_phase": "setup",
        "characters_present": ["Alice", "Bob", "Carol"],
    }
    candidate = {
        "chapter_number": 2, "scene_number": 2,
        "pov_character": "B",  # different POV
        "structural_phase": "first_plot_point",  # different phase
        "characters_present": ["Alice", "Bob", "Dan"],
    }
    idx = _cards_to_index([blocked, candidate])
    d = SuccessorClassifier(jaccard_threshold=0.5).classify(
        blocked_scene=blocked, candidate_scene=candidate, chapter_index=idx,
    )
    # jaccard = |{alice, bob}| / |{alice, bob, carol, dan}| = 2/4 = 0.5 >= threshold, adjacent
    assert d.class_label == "transitional_with_gap"
    assert d.recommendation == "continue_cautiously"


def test_rule5_loose_downstream_fires_on_distance_or_low_jaccard():
    blocked = {
        "chapter_number": 1, "scene_number": 1,
        "pov_character": "Luke Skywalker", "structural_phase": "climax",
        "characters_present": ["Luke Skywalker"],
    }
    # far scene + disjoint cast + different POV + different phase
    candidate = {
        "chapter_number": 2, "scene_number": 2,
        "pov_character": "Han Solo", "structural_phase": "response",
        "characters_present": ["Han Solo", "Chewbacca"],
    }
    cards = [
        blocked,
        {"chapter_number": 1, "scene_number": 2, "pov_character": "X",
         "structural_phase": "setup", "characters_present": []},
        {"chapter_number": 2, "scene_number": 1, "pov_character": "Y",
         "structural_phase": "setup", "characters_present": []},
        candidate,
    ]
    idx = _cards_to_index(cards)
    d = SuccessorClassifier().classify(
        blocked_scene=blocked, candidate_scene=candidate, chapter_index=idx,
    )
    assert d.class_label == "loose_downstream"
    assert d.recommendation == "continue_with_note"


def test_missing_scene_in_index_returns_large_distance():
    blocked = {
        "chapter_number": 1, "scene_number": 1,
        "pov_character": "A", "structural_phase": "setup",
        "characters_present": ["A"],
    }
    candidate = {
        "chapter_number": 9, "scene_number": 9,
        "pov_character": "B", "structural_phase": "resolution",
        "characters_present": ["B"],
    }
    # Index covers only the blocked scene — candidate is "unknown".
    idx = _cards_to_index([blocked])
    d = SuccessorClassifier().classify(
        blocked_scene=blocked, candidate_scene=candidate, chapter_index=idx,
    )
    # Adjacency distance should be the sentinel (very large), so rule 5 fires
    # via the "far" branch regardless of jaccard.
    assert d.class_label == "loose_downstream"
    assert d.recommendation == "continue_with_note"


def test_constructor_rejects_bad_threshold():
    with pytest.raises(ValueError):
        SuccessorClassifier(jaccard_threshold=1.5)
    with pytest.raises(ValueError):
        SuccessorClassifier(adjacency_max_for_continue=-1)


def test_depends_on_with_missing_field_is_tolerated():
    blocked = {
        "chapter_number": 1, "scene_number": 1,
        "pov_character": "A", "structural_phase": "setup",
        "characters_present": ["A"],
    }
    candidate = {
        "chapter_number": 1, "scene_number": 2,
        "pov_character": "A", "structural_phase": "setup",
        "characters_present": ["A"],
        # no depends_on
    }
    idx = _cards_to_index([blocked, candidate])
    d = SuccessorClassifier().classify(
        blocked_scene=blocked, candidate_scene=candidate, chapter_index=idx,
    )
    # Should fall through to rule 2 (same POV continuation).
    assert d.class_label == "same_pov_continuation"


# --- Hand-labeled set agreement ------------------------------------------

LABELS_PATH = Path(__file__).parent / "data" / "successor_classifier_labels.json"


def _load_labels() -> list[dict]:
    if not LABELS_PATH.exists():
        return []
    with LABELS_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("labels") or []


@pytest.mark.parametrize("label", _load_labels(), ids=lambda L: (
    f"{L['blocked']['chapter_number']:02d}-{L['blocked']['scene_number']:02d}"
    f"__to__{L['candidate']['chapter_number']:02d}-{L['candidate']['scene_number']:02d}"
    f"__{L['expected_class']}"
))
def test_hand_labeled_pair(label: dict):
    """Each seed label must match the classifier's output. Once the label set
    grows past 30 pairs, the ≥ 27/30 agreement gate in
    ``test_classifier_agreement_gate`` is authoritative and individual
    failures are allowed to slip (per spec §5.3.4). Until then, every seed
    label is a hard assertion — they're all objectively clear-cut."""
    clf = SuccessorClassifier(jaccard_threshold=0.5)
    cards = [label["blocked"], label["candidate"]]
    idx = _cards_to_index(cards)
    d = clf.classify(
        blocked_scene=label["blocked"],
        candidate_scene=label["candidate"],
        chapter_index=idx,
    )
    assert d.class_label == label["expected_class"], (
        f"class mismatch: got {d.class_label!r}, expected {label['expected_class']!r}, "
        f"reasons={d.reasons}, scores={d.scores}"
    )
    assert d.recommendation == label["expected_recommendation"]


def test_classifier_agreement_gate():
    """Informational: reports agreement against the labeled set. Enforces the
    90 % floor only once the labeled set has reached 30 pairs, per spec §5.3.4.
    While the set is partial, this test just reports and passes."""
    labels = _load_labels()
    if len(labels) < 30:
        pytest.skip(
            f"labeled set has {len(labels)} pairs; full 30-pair gate inactive. "
            "Author tests/data/successor_classifier_labels.json to ≥ 30 pairs."
        )

    clf = SuccessorClassifier(jaccard_threshold=0.5)
    matches = 0
    for label in labels:
        idx = _cards_to_index([label["blocked"], label["candidate"]])
        d = clf.classify(
            blocked_scene=label["blocked"],
            candidate_scene=label["candidate"],
            chapter_index=idx,
        )
        if (
            d.class_label == label["expected_class"]
            and d.recommendation == label["expected_recommendation"]
        ):
            matches += 1

    agreement = matches / len(labels)
    assert agreement >= 0.90, (
        f"agreement {agreement:.2%} below the 90% gate "
        f"({matches}/{len(labels)}). Classifier must be retuned before "
        "flipping runtime.firewall.successor_classifier.enabled on."
    )
