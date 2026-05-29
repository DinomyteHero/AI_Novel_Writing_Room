"""Tests for ModelRouter prompt-cache placement.

cache_control must land on a message content block (where Anthropic honors it),
specifically the last system message, not the request top level.
"""

from src.model_router import ModelRouter


def test_apply_cache_control_marks_last_system_message():
    messages = [
        {"role": "system", "content": "json only"},
        {"role": "system", "content": "BIG STATIC PROMPT"},
        {"role": "user", "content": "draft this"},
    ]
    out = ModelRouter._apply_cache_control(messages, {"type": "ephemeral"})

    # The last system message becomes a content-block array with cache_control.
    assert out[1]["content"][0]["text"] == "BIG STATIC PROMPT"
    assert out[1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    # Other messages untouched.
    assert out[0]["content"] == "json only"
    assert out[2]["content"] == "draft this"
    # The caller's list is not mutated.
    assert messages[1]["content"] == "BIG STATIC PROMPT"


def test_apply_cache_control_noop_without_system_message():
    messages = [{"role": "user", "content": "hi"}]
    out = ModelRouter._apply_cache_control(messages, {"type": "ephemeral"})
    assert out == messages
