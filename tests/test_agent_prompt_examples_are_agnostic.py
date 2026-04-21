"""Guardrails against project-specific example leakage in generic agent prompts."""

from pathlib import Path


PROMPTS_DIR = (
    Path(__file__).resolve().parent.parent / "prompts" / "agent_system_prompts"
)

BANNED_TOKENS = (
    "Ben Skywalker",
    "ben_skywalker",
    "Master Skywalker",
    "Ruusan",
    "Coruscant",
    "force_wrongness",
    "Luke validates Ben",
    "Luke's survey assignment",
)


def test_generic_agent_prompts_avoid_project_specific_examples():
    for prompt_path in PROMPTS_DIR.glob("*.md"):
        text = prompt_path.read_text(encoding="utf-8")
        for token in BANNED_TOKENS:
            assert token not in text, (
                f"{prompt_path.name} still contains project-specific token: {token}"
            )
