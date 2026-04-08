"""Tests for the gold evaluation corpus.

Verifies that reference chapters meet the quality rubric,
serving as a calibration test for the quality metrics system.
"""

import json
from pathlib import Path

import pytest

from src.quality.metrics_dashboard import MetricsDashboard
from src.rag.embedding import MockEmbeddingFunction


EVAL_DIR = Path(__file__).parent.parent / "data" / "eval_corpus"
RUBRIC_PATH = EVAL_DIR / "eval_rubric.json"


@pytest.fixture
def eval_rubric():
    """Load the evaluation rubric."""
    if not RUBRIC_PATH.exists():
        pytest.skip("Evaluation rubric not found")
    with open(RUBRIC_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def eval_dashboard():
    """MetricsDashboard configured for evaluation.

    Uses embedding_function=None because MockEmbeddingFunction produces
    hash-based vectors that don't reflect real semantic similarity.
    Paragraph similarity checks are skipped; the other three repetition
    sub-checks still run.
    """
    return MetricsDashboard(
        negative_constraints_path=str(
            Path(__file__).parent.parent / "config" / "negative_constraints.yaml"
        ),
        embedding_function=None,
    )


def _load_reference_chapter(filename: str) -> str:
    """Load a reference chapter from the eval corpus."""
    path = EVAL_DIR / filename
    if not path.exists():
        pytest.skip(f"Reference chapter not found: {filename}")
    return path.read_text(encoding="utf-8")


def _make_scene_card(chapter_num: int, structural_phase: str) -> dict:
    """Create a minimal scene card for eval testing."""
    return {
        "chapter_number": chapter_num,
        "scene_number": 1,
        "structural_phase": structural_phase,
        "pov_character": "Ben Skywalker",
        "characters_present": [
            "Ben Skywalker", "Luke Skywalker", "Kaia Rensh",
            "Dex Vorn", "Yara Tann",
        ],
        "emotional_trajectory": "Cautious skepticism -> reluctant acceptance",
    }


class TestEvalCorpus:
    """Verify reference chapters meet quality rubric targets."""

    def test_rubric_exists(self, eval_rubric):
        """Ensure the rubric has the expected structure."""
        assert "metrics" in eval_rubric
        assert "zero_tolerance" in eval_rubric

    @pytest.mark.parametrize("chapter_info", [
        {"file": "chapter_01_reference.md", "phase": "setup", "num": 1},
        {"file": "chapter_02_reference.md", "phase": "response", "num": 2},
        {"file": "chapter_03_reference.md", "phase": "midpoint", "num": 3},
    ])
    def test_reference_chapter_overall_score(
        self, eval_dashboard, eval_rubric, chapter_info
    ):
        """Each reference chapter should meet the overall score target."""
        prose = _load_reference_chapter(chapter_info["file"])
        scene_card = _make_scene_card(chapter_info["num"], chapter_info["phase"])

        result = eval_dashboard.analyze_chapter(prose, scene_card)

        target = eval_rubric["metrics"]["overall_score_target"]
        assert result["overall_score"] >= target["min"], (
            f"Chapter {chapter_info['num']} overall score {result['overall_score']:.3f} "
            f"below minimum {target['min']}"
        )

    @pytest.mark.parametrize("chapter_info", [
        {"file": "chapter_01_reference.md", "phase": "setup", "num": 1},
        {"file": "chapter_02_reference.md", "phase": "response", "num": 2},
        {"file": "chapter_03_reference.md", "phase": "midpoint", "num": 3},
    ])
    def test_reference_chapter_no_ai_tells(
        self, eval_dashboard, eval_rubric, chapter_info
    ):
        """Reference chapters should have zero AI-tell words."""
        prose = _load_reference_chapter(chapter_info["file"])
        scene_card = _make_scene_card(chapter_info["num"], chapter_info["phase"])

        result = eval_dashboard.analyze_chapter(prose, scene_card)
        ai_tells = result["slop"]["ai_tells_found"]
        assert len(ai_tells) == 0, (
            f"Chapter {chapter_info['num']} has AI-tells: "
            f"{[t['word'] for t in ai_tells]}"
        )

    @pytest.mark.parametrize("chapter_info", [
        {"file": "chapter_01_reference.md", "phase": "setup", "num": 1},
        {"file": "chapter_02_reference.md", "phase": "response", "num": 2},
        {"file": "chapter_03_reference.md", "phase": "midpoint", "num": 3},
    ])
    def test_reference_chapter_no_banned_phrases(
        self, eval_dashboard, eval_rubric, chapter_info
    ):
        """Reference chapters should have zero banned phrases."""
        prose = _load_reference_chapter(chapter_info["file"])
        scene_card = _make_scene_card(chapter_info["num"], chapter_info["phase"])

        result = eval_dashboard.analyze_chapter(prose, scene_card)
        banned = result["voice"]["banned_phrases_found"]
        assert len(banned) == 0, (
            f"Chapter {chapter_info['num']} has banned phrases: "
            f"{[b['phrase'] for b in banned]}"
        )

    @pytest.mark.parametrize("chapter_info", [
        {"file": "chapter_01_reference.md", "phase": "setup", "num": 1},
        {"file": "chapter_02_reference.md", "phase": "response", "num": 2},
        {"file": "chapter_03_reference.md", "phase": "midpoint", "num": 3},
    ])
    def test_reference_chapter_repetition_score(
        self, eval_dashboard, eval_rubric, chapter_info
    ):
        """Reference chapters should meet repetition score target."""
        prose = _load_reference_chapter(chapter_info["file"])
        scene_card = _make_scene_card(chapter_info["num"], chapter_info["phase"])

        result = eval_dashboard.analyze_chapter(prose, scene_card)
        target = eval_rubric["metrics"]["repetition_score_target"]
        score = result["repetition"]["repetition_score"]
        assert score >= target["min"], (
            f"Chapter {chapter_info['num']} repetition score {score:.3f} "
            f"below minimum {target['min']}"
        )

    @pytest.mark.parametrize("chapter_info", [
        {"file": "chapter_01_reference.md", "phase": "setup", "num": 1},
        {"file": "chapter_02_reference.md", "phase": "response", "num": 2},
        {"file": "chapter_03_reference.md", "phase": "midpoint", "num": 3},
    ])
    def test_reference_chapter_slop_score(
        self, eval_dashboard, eval_rubric, chapter_info
    ):
        """Reference chapters should meet slop score target."""
        prose = _load_reference_chapter(chapter_info["file"])
        scene_card = _make_scene_card(chapter_info["num"], chapter_info["phase"])

        result = eval_dashboard.analyze_chapter(prose, scene_card)
        target = eval_rubric["metrics"]["slop_score_target"]
        score = result["slop"]["slop_score"]
        assert score >= target["min"], (
            f"Chapter {chapter_info['num']} slop score {score:.3f} "
            f"below minimum {target['min']}"
        )

    def test_reference_chapters_word_count(self, eval_rubric):
        """Reference chapters should be approximately target word count."""
        for ch_info in eval_rubric.get("reference_chapters", []):
            prose = _load_reference_chapter(ch_info["file"])
            word_count = len(prose.split())
            target = ch_info.get("target_words", 3000)
            # Allow 50% variance from target
            assert word_count >= target * 0.3, (
                f"{ch_info['file']} has only {word_count} words "
                f"(target: {target})"
            )
