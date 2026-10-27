"""Tests for ModelRouter prompt-cache placement.

cache_control must land on a message content block (where Anthropic honors it):
the last system message, and the end of the stable parts of a user message.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx

from src.model_router import ModelRouter
from src.studio import prompts


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


def _caching_router(settings_yaml):
    router = ModelRouter(settings_yaml)
    router.mode = "hybrid"  # each role uses its own backend
    router.config["pipeline"] = {"prompt_caching": {"enabled": True, "anthropic_ttl": "1h"}}
    router.config["models"]["anthropic"] = {"api": "anthropic", "models": {"opus": "claude-test"}}
    router.config["agent_routing"]["studio_critic"] = {"backend": "anthropic", "model": "opus"}
    return router


def _draft(book, number, written):
    plan = book.read_plan()
    return prompts.draft_messages(plan, plan.chapters()[number], written, 2000)


WRITTEN = {1: "# Chapter 1\n\nOne.", 2: "# Chapter 2\n\nTwo."}


def test_each_chapter_call_starts_with_the_last_ones_cached_parts(book):
    second = _draft(book, 2, WRITTEN)[1]
    third = _draft(book, 3, WRITTEN)[1]
    assert second["content"] == "\n\n".join(second["parts"])
    assert third["cache_upto"] == len(third["parts"]) - 1
    assert third["parts"][-1].startswith("# Task")
    # Chapter 3's call begins with every part chapter 2's call cached, so a
    # provider caching at part boundaries reads the book from cache.
    cached = second["parts"][: second["cache_upto"]]
    assert third["parts"][: len(cached)] == cached


async def test_anthropic_marks_the_system_prompt_and_the_end_of_the_book(book, settings_yaml):
    from types import SimpleNamespace

    message = SimpleNamespace(content=[SimpleNamespace(type="text", text="Notes.")], stop_reason="end_turn",
                              usage=SimpleNamespace(input_tokens=10, output_tokens=3,
                                                    cache_read_input_tokens=900, cache_creation_input_tokens=50))
    stream = SimpleNamespace(get_final_message=AsyncMock(return_value=message))
    context = MagicMock(__aenter__=AsyncMock(return_value=stream), __aexit__=AsyncMock(return_value=None))
    client = MagicMock()
    client.beta.messages.stream.return_value = context
    router = _caching_router(settings_yaml)
    router._get_anthropic_client = lambda backend: client

    assert await router.complete("studio_critic", _draft(book, 3, WRITTEN)) == "Notes."
    sent = client.beta.messages.stream.call_args.kwargs
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    [user] = sent["messages"]
    marks = [block.get("cache_control") for block in user["content"]]
    assert marks[-2] == {"type": "ephemeral", "ttl": "1h"} and marks.count(None) == len(marks) - 1
    assert router.usage_log[-1]["cached_tokens"] == 900
    assert router.usage_log[-1]["cache_write_tokens"] == 50


async def test_openrouter_marks_claude_and_sends_other_models_plain_text(book, settings_yaml):
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    router = _caching_router(settings_yaml)
    for name in ("_cloud_client", "_local_client"):
        setattr(router, name, httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(respond)))
    try:
        await router.complete("studio_reader", _draft(book, 3, WRITTEN))  # anthropic/... via OpenRouter
        await router.complete("studio_writer", _draft(book, 3, WRITTEN))  # a local model
        await router.chat("studio_reader", "System", [{"role": "user", "content": "Hi", "parts": ["Hi"]}], [])
    finally:
        await router.close()

    claude, local, chat = payloads
    blocks = claude["messages"][1]["content"]
    assert blocks[-2]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "parts" not in claude["messages"][1]
    assert isinstance(local["messages"][1]["content"], str)
    assert set(local["messages"][1]) == {"role", "content"}
    # A chat turn's steps are seconds apart: its marker uses the 5-minute entry.
    assert chat["messages"][1]["content"] == [{"type": "text", "text": "Hi", "cache_control": {"type": "ephemeral"}}]
