"""Shared test fixtures."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def no_provider_keys(monkeypatch):
    """Tests never call real models, and a key or library in the shell mustn't
    change which provider a role uses or where books are."""
    for env in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                "WRITERS_ROOM_LIBRARY"):
        monkeypatch.delenv(env, raising=False)


@pytest.fixture
def temp_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def settings_yaml(temp_dir):
    """A temporary settings.yaml in local mode with one cloud-routed role."""
    import yaml

    config_dir = Path(temp_dir) / "config"
    config_dir.mkdir()
    settings = {
        "deployment_mode": "local",
        "models": {
            "local": {
                "inference_backend": "llama-server",
                "base_url": "http://localhost:8080/v1",
                "timeout_seconds": 300,
                "models": {"primary_moe": "test-model"},
                "default_params": {"primary_moe": {"temperature": 0.7}},
            },
            "cloud": {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
                "timeout_seconds": 300,
                "models": {"primary": "anthropic/claude-sonnet-4-20250514"},
                "default_params": {"primary": {"temperature": 0.7, "max_tokens": 4096}},
            },
        },
        "agent_routing": {
            "planner": {"backend": "local", "model": "primary_moe", "params": {"temperature": 0.4}},
            "studio_writer": {
                "backend": "local", "model": "primary_moe", "params": {"temperature": 0.9}
            },
            "studio_reader": {"backend": "cloud", "model": "primary", "params": {"temperature": 0.3}},
        },
    }
    config_path = config_dir / "settings.yaml"
    config_path.write_text(yaml.dump(settings), encoding="utf-8")
    return str(config_path)


OUTLINE = """# Outline

Intro text that isn't a chapter.

## Chapter 1: The Storm
- Mara finds the lighthouse dark.
- Words: 2,500

## Chapter 2
- The keeper is missing.

### chapter 3 — Low Tide
- She finds the boat.
- **Length:** ~1800
"""


@pytest.fixture
def library(tmp_path):
    from src.studio.project import Library

    return Library(tmp_path / "library")


@pytest.fixture
def book(library):
    book, _ = library.new_book("The Dark Lighthouse")
    book.bible_path.write_text(
        "# The Dark Lighthouse\n\nMara is a lighthouse keeper's niece.\n", encoding="utf-8"
    )
    book.characters_path.write_text(
        '## Mara\n- **How she talks:** dry\n  - "Nineteen years to ask."\n', encoding="utf-8"
    )
    book.outline_path.write_text(OUTLINE, encoding="utf-8")
    return book
