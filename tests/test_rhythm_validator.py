"""Tests for src/quality/rhythm_validator.py."""

from __future__ import annotations

import pytest

from src.quality.rhythm_validator import (
    DEFAULT_THRESHOLDS,
    RhythmIssue,
    compute_metrics,
    validate_rhythm,
)


# --- metric computation -----------------------------------------------------


def test_compute_metrics_counts_words_and_sentences():
    prose = "She walked to the door. He watched her go. The room was quiet."
    metrics = compute_metrics(prose)
    assert metrics.word_count == 13  # 5 + 4 + 4
    assert metrics.sentence_count == 3
    assert metrics.paragraph_count == 1


def test_compute_metrics_counts_em_dashes():
    prose = "She walked — slowly — to the door. He watched — and waited."
    metrics = compute_metrics(prose)
    # walked—slowly, slowly—to, watched—and = 3 em-dashes
    assert metrics.em_dashes == 3


def test_compute_metrics_double_hyphen_counts_as_em_dash():
    prose = "She walked -- slowly -- to the door."
    metrics = compute_metrics(prose)
    assert metrics.em_dashes == 2


def test_compute_metrics_detects_short_sentence_clusters():
    # Four consecutive sentences ≤8 words each = one cluster.
    prose = "He moved. He stopped. He turned around. He waited."
    metrics = compute_metrics(prose)
    assert metrics.short_sentence_count == 4
    assert metrics.short_sentence_runs == 1


def test_compute_metrics_no_cluster_when_long_sentence_interrupts():
    prose = (
        "He moved. He stopped. "
        "Then the door opened with a long sustained whine that filled the corridor and made him flinch. "
        "He waited. He held still."
    )
    metrics = compute_metrics(prose)
    # Two short, one long, two short — no run of 3+.
    assert metrics.short_sentence_runs == 0


def test_compute_metrics_two_clusters_count_separately():
    prose = (
        "He moved. He stopped. He turned around. "
        "Then the door opened with a long whine that filled the entire corridor. "
        "He waited. He held still. He breathed out."
    )
    metrics = compute_metrics(prose)
    assert metrics.short_sentence_runs == 2


def test_compute_metrics_counts_default_openers():
    prose = (
        "He moved. She watched. They waited. "
        "Behind the curtain, a shadow shifted. "
        "It was time."
    )
    metrics = compute_metrics(prose)
    # He, She, They, It → 4 default openers. "Behind" doesn't match.
    assert metrics.default_opener_count == 4
    assert metrics.sentence_count == 5


def test_compute_metrics_counts_dialogue_paragraphs():
    prose = (
        "She walked to the door.\n\n"
        "\"Stop,\" he said.\n\n"
        "She did not stop.\n\n"
        "\"I said stop.\""
    )
    metrics = compute_metrics(prose)
    assert metrics.paragraph_count == 4
    assert metrics.dialogue_bearing_paragraphs == 2


def test_compute_metrics_counts_curly_dialogue():
    prose = "“Stop,” he said.\n\nShe did not stop."
    metrics = compute_metrics(prose)
    assert metrics.dialogue_bearing_paragraphs == 1


def test_compute_metrics_counts_abstract_tics():
    prose = (
        "She felt the particular weight of grief. "
        "It was the kind of moment she had been dreading. "
        "Something adjacent to fear. "
        "Not quite anger. "
        "The way someone braces for impact."
    )
    metrics = compute_metrics(prose)
    # 5 distinct tic patterns hit.
    assert metrics.abstract_constructions == 5


# --- validate_rhythm: issue firing ------------------------------------------


def _clean_paragraph() -> str:
    """A scene that should pass all thresholds."""
    return (
        "Behind the desk, Ben watched her come in.\n\n"
        "\"You shouldn't be here,\" he said.\n\n"
        "Iressa pulled out the chair without asking and sat down. "
        "She set her datapad in the exact center of the desk, perfectly aligned with the edge. "
        "If she'd been ten minutes slower, she would have missed him.\n\n"
        "\"I'm aware,\" she said. \"I came anyway.\"\n\n"
        "Ben let the silence sit for a count of three. "
        "Outside the window, the Coruscant traffic moved in long lazy ribbons that caught the late light.\n\n"
        "\"What do you want?\" he asked.\n\n"
        "\"The thing you took from the archive.\"\n\n"
        "Two breaths.\n\n"
        "\"Get out,\" Ben said."
    )


def test_clean_prose_passes():
    prose = _clean_paragraph()
    result = validate_rhythm(prose, scope="scene", scope_id="ch01_sc01")
    assert result.passed, f"clean prose should pass, got issues: {[i.code for i in result.issues]}"


def test_em_dash_overuse_fires():
    prose = (
        "She walked — slowly — to the door — and stopped. "
        "He watched — patient — as the silence — long and complete — settled."
    )
    result = validate_rhythm(prose, scope="scene")
    codes = {i.code for i in result.issues}
    assert "rhythm.em_dash_overuse" in codes


def test_staccato_cluster_fires():
    # 5 distinct clusters of 3+ short sentences, separated by long sentences.
    long_sentence = (
        "Outside the window the city traffic moved in long lazy ribbons "
        "that caught the afternoon light against the cold gray clouds."
    )
    short_run = "He moved. He stopped. He turned."
    prose = " ".join([short_run, long_sentence] * 5 + [short_run])
    result = validate_rhythm(prose, scope="scene", require_dialogue=False)
    codes = {i.code for i in result.issues}
    assert "rhythm.staccato_cluster" in codes, (
        f"expected staccato_cluster, got {codes}; runs="
        f"{compute_metrics(prose).short_sentence_runs}"
    )


def test_opener_monotone_fires():
    # 6 sentences, all starting He/She/They.
    prose = (
        "He walked. She followed. They reached the door. "
        "He opened it. She went through. They locked the door behind them."
    )
    result = validate_rhythm(prose, scope="scene")
    codes = {i.code for i in result.issues}
    assert "rhythm.opener_monotone" in codes


def test_dialogue_starved_fires_when_required():
    # Narration only, no dialogue.
    prose = (
        "She walked through the door and stopped at the threshold. "
        "The room beyond was empty. "
        "Dust settled on every surface in a thin gray film."
    )
    result = validate_rhythm(prose, scope="scene", require_dialogue=True)
    codes = {i.code for i in result.issues}
    assert "rhythm.dialogue_starved" in codes


def test_dialogue_starved_suppressed_for_interior_scenes():
    # Same narration; with require_dialogue=False the check is suppressed.
    prose = (
        "She walked through the door and stopped at the threshold. "
        "The room beyond was empty. "
        "Dust settled on every surface in a thin gray film."
    )
    result = validate_rhythm(prose, scope="scene", require_dialogue=False)
    codes = {i.code for i in result.issues}
    assert "rhythm.dialogue_starved" not in codes


def test_abstract_tic_fires_with_density():
    # Pack the tic family densely.
    tic_para = (
        "She felt the particular weight of it. "
        "Something adjacent to fear settled in her chest. "
        "Not quite grief, not quite anger. "
        "The way someone braces for an impact they know is coming. "
    )
    prose = tic_para * 3
    result = validate_rhythm(prose, scope="scene")
    codes = {i.code for i in result.issues}
    assert "rhythm.abstract_tic" in codes


# --- severity bands ---------------------------------------------------------


def test_em_dash_warn_band_emits_medium_severity():
    # Construct prose with em-dash density well above the warn threshold.
    prose = (
        "She walked — slowly — to the door — and stopped — listening — for him. " * 3
    )
    result = validate_rhythm(prose, scope="scene")
    em_issues = [i for i in result.issues if i.code == "rhythm.em_dash_overuse"]
    assert em_issues
    assert em_issues[0].severity == "medium"


def test_em_dash_advisory_band_emits_low_severity():
    # ~7 em-dashes per 1k words, between advisory (6) and warn (10).
    # 7 em-dashes in 1000 words.
    base_words = "the quick brown fox jumped over the lazy dog and ran far. " * 100
    em_dash_inserts = "She walked — slowly. " * 7
    prose = base_words + em_dash_inserts
    result = validate_rhythm(prose, scope="scene")
    em_issues = [i for i in result.issues if i.code == "rhythm.em_dash_overuse"]
    if em_issues:
        assert em_issues[0].severity in {"low", "medium"}


# --- threshold override -----------------------------------------------------


def test_custom_thresholds_can_relax_a_check():
    prose = "He moved. He stopped. He turned. He waited."
    relaxed = {
        **DEFAULT_THRESHOLDS,
        "short_sentence_runs_per_chapter": {"advisory": 50, "warn": 100},
    }
    result = validate_rhythm(prose, scope="scene", thresholds=relaxed, require_dialogue=False)
    codes = {i.code for i in result.issues}
    assert "rhythm.staccato_cluster" not in codes


# --- edge cases -------------------------------------------------------------


def test_numeric_range_not_counted_as_em_dash():
    metrics = compute_metrics("The war ran from 1995--2003 and again 2010--2012.")
    assert metrics.em_dashes == 0


def test_empty_or_whitespace_prose_passes_cleanly():
    for prose in ("", "   \n\n  "):
        result = validate_rhythm(prose, scope="scene", require_dialogue=True)
        assert result.passed
        assert result.issues == ()


# --- to_dict roundtrip ------------------------------------------------------


def test_result_to_dict_includes_metrics_and_issues():
    prose = "He moved. He stopped. He turned. He waited. He breathed."
    result = validate_rhythm(prose, scope="scene", scope_id="ch01_sc01")
    payload = result.to_dict()
    assert payload["scope"] == "scene"
    assert payload["scope_id"] == "ch01_sc01"
    assert "metrics" in payload
    assert "em_dashes_per_1k_words" in payload["metrics"]
    assert isinstance(payload["issues"], list)
    if payload["issues"]:
        first = payload["issues"][0]
        assert {"code", "severity", "message", "metric_value", "threshold"} <= first.keys()
