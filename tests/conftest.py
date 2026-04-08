"""Shared test fixtures."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_concept_seed():
    """Load the Beyond the Veil concept seed."""
    seed_path = Path(__file__).parent.parent / "data" / "story_bibles" / "beyond_the_veil" / "concept_seed.json"
    with open(seed_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_scene_card():
    """Load the Chapter 1 Scene 1 card."""
    card_path = (
        Path(__file__).parent.parent
        / "data" / "story_bibles" / "beyond_the_veil" / "scene_cards"
        / "chapter_01_scene_01.json"
    )
    with open(card_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_router():
    """Create a mock ModelRouter that returns predictable responses."""
    router = MagicMock()
    router.mode = "local"
    router.complete = AsyncMock(return_value="Mock LLM response")
    router.complete_structured = AsyncMock(return_value={
        "verdict": "pass",
        "failure_codes": [],
        "severity": "non_blocking",
        "route_to": None,
        "structural_score": 0.85,
        "voice_score": 0.80,
        "polish_score": 0.75,
    })
    router.close = AsyncMock()
    return router


@pytest.fixture
def settings_yaml(temp_dir):
    """Create a temporary settings.yaml for testing."""
    config_dir = Path(temp_dir) / "config"
    config_dir.mkdir()
    settings = {
        "deployment_mode": "local",
        "models": {
            "local": {
                "inference_backend": "llama-server",
                "base_url": "http://localhost:8080/v1",
                "models": {
                    "primary_moe": "test-model",
                    "fast_moe": "test-fast-model",
                    "utility": "test-utility-model",
                },
                "default_params": {
                    "primary_moe": {"temperature": 0.7},
                },
            },
            "cloud": {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "models": {
                    "primary": "anthropic/claude-sonnet-4-20250514",
                },
                "default_params": {
                    "primary": {"temperature": 0.7, "max_tokens": 4096},
                },
            },
        },
        "agent_routing": {
            "plot_architect": {"backend": "local", "model": "primary_moe", "params": {"temperature": 0.4}},
            "prose_stylist": {"backend": "local", "model": "primary_moe", "params": {"temperature": 0.9}},
            "gate_critic": {"backend": "local", "model": "primary_moe", "params": {"temperature": 0.3}},
            "craft_editor": {"backend": "local", "model": "primary_moe", "params": {"temperature": 0.4}},
            "voice_checker": {"backend": "cloud", "model": "primary", "params": {"temperature": 0.3}},
        },
        "pipeline": {
            "max_structural_retries": 3,
            "max_voice_retries": 2,
            "chapter_output_dir": "data/manuscripts",
            "run_ledger_path": "data/run_ledger.db",
        },
    }

    import yaml
    config_path = config_dir / "settings.yaml"
    with open(config_path, "w") as f:
        yaml.dump(settings, f)

    return str(config_path)


@pytest.fixture
def story_state(temp_dir):
    """Create a StoryState with temp SQLite."""
    from src.memory.story_state import StoryState
    state = StoryState(db_path=str(Path(temp_dir) / "test_state.db"))
    yield state
    state.close()


@pytest.fixture
def story_state_initialized(story_state, sample_concept_seed):
    """StoryState pre-populated from concept seed."""
    story_state.init_from_concept_seed(sample_concept_seed)
    return story_state


@pytest.fixture
def knowledge_layers(story_state_initialized):
    """KnowledgeLayers wrapping an initialized StoryState."""
    from src.memory.knowledge_layers import KnowledgeLayers
    return KnowledgeLayers(story_state_initialized)


@pytest.fixture
def mock_embedding_function():
    """Deterministic mock embedding function for ChromaDB tests."""
    from src.rag.embedding import MockEmbeddingFunction
    return MockEmbeddingFunction(dimension=384)


@pytest.fixture
def chapter_memory(tmp_path, mock_embedding_function):
    """ChapterMemory with mock embedding in temp directory.

    Uses tmp_path (pytest built-in) instead of temp_dir to avoid Windows
    file locking issues — tmp_path is cleaned up at session end, not
    immediately after the test, so ChromaDB's SQLite file isn't held open.
    """
    from src.memory.chapter_memory import ChapterMemory
    return ChapterMemory(
        persist_directory=str(tmp_path / "test_chapter_memory"),
        embedding_function=mock_embedding_function,
    )


@pytest.fixture
def negative_constraints():
    """Load negative constraints config."""
    import yaml
    with open(Path(__file__).parent.parent / "config" / "negative_constraints.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def metrics_dashboard(mock_embedding_function):
    """MetricsDashboard with mock embedding."""
    from src.quality.metrics_dashboard import MetricsDashboard
    return MetricsDashboard(
        negative_constraints_path=str(
            Path(__file__).parent.parent / "config" / "negative_constraints.yaml"
        ),
        embedding_function=mock_embedding_function,
    )


@pytest.fixture
def sample_prose():
    """Clean prose for quality testing — no AI-tells or banned phrases."""
    return (
        'Ben stared at the holographic star chart, its blue-white glow '
        'painting shadows across Luke\'s study. The wound regions pulsed '
        'like infected wounds in the fabric of the galaxy.\n\n'
        '"Three expeditions in the last eighteen months," Luke said, not '
        'looking up. "All lost contact within seventy-two hours."\n\n'
        '"And you want to send a fourth." Ben studied the markers. They '
        'formed an arc, curving away from charted space.\n\n'
        'He turned to the viewport. Coruscant\'s evening traffic wove '
        'patterns of light against the darkening sky. A dozen levels down, '
        'someone was cooking something with too much jogan spice.'
    )


@pytest.fixture
def sloppy_prose():
    """Prose deliberately loaded with AI-tells and bad patterns."""
    return (
        'In that moment, Ben delved into the nuanced tapestry of the Force. '
        'He felt a shiver run down his spine. The landscape of his mind '
        'was multifaceted and straightforward at the same time.\n\n'
        'In that moment, he realized that it was more than just a mission. '
        'It was a testament to their resolve. Without hesitation, he '
        'knew that something had fundamentally shifted.\n\n'
        'In that moment, the smell of ozone filled the air. He quietly '
        'orchestrated his thoughts, remarkably calm despite everything. '
        'A symphony of emotions played through him.\n\n'
        'In that moment, he noticed the tapestry of stars above. It was '
        'more than he could have imagined. He felt his jaw tightened with '
        'resolve as he seemingly understood the vital truth.'
    )
