"""Tests for ModelRouter."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from src import model_catalog
from src.model_router import ModelRouter, load_config
from tests.fakes import CATALOG, CATALOG_NOW, DAY


class TestModelRouterRouting:
    """Test routing logic for different deployment modes."""

    def test_local_mode_routes_to_local(self, settings_yaml):
        router = ModelRouter(settings_yaml)
        routing = router._get_routing("planner")
        assert routing["backend"] == "local"

    def test_local_mode_uses_agent_params(self, settings_yaml):
        router = ModelRouter(settings_yaml)
        routing = router._get_routing("planner")
        assert routing["params"]["temperature"] == 0.4

    def test_unknown_agent_gets_default(self, settings_yaml):
        router = ModelRouter(settings_yaml)
        routing = router._get_routing("unknown_agent")
        assert routing["backend"] == "local"
        assert routing["model"] == "primary_moe"

    def test_resolve_model_name(self, settings_yaml):
        router = ModelRouter(settings_yaml)
        routing = {"backend": "local", "model": "primary_moe"}
        model = router._resolve_model(routing)
        assert model == "test-model"

    def test_resolve_cloud_model_name(self, settings_yaml):
        router = ModelRouter(settings_yaml)
        routing = {"backend": "cloud", "model": "primary"}
        model = router._resolve_model(routing)
        assert model == "anthropic/claude-sonnet-4-20250514"

    def test_resolve_params_merges_defaults_and_overrides(self, settings_yaml):
        router = ModelRouter(settings_yaml)
        routing = {
            "backend": "local",
            "model": "primary_moe",
            "params": {"temperature": 0.9, "min_p": 0.05},
        }
        params = router._resolve_params(routing)
        # Agent override should win over default
        assert params["temperature"] == 0.9
        # Agent-specific param preserved
        assert params["min_p"] == 0.05


class TestModelRouterCloudRouting:
    """Test cloud and hybrid mode routing."""

    def test_cloud_mode_routing(self, temp_dir):
        import yaml
        from pathlib import Path

        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir(exist_ok=True)
        settings = {
            "deployment_mode": "cloud",
            "models": {
                "local": {
                    "base_url": "http://localhost:8080/v1",
                    "models": {"primary_moe": "test"},
                    "default_params": {},
                },
                "cloud": {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "models": {"primary": "claude-sonnet"},
                    "default_params": {"primary": {"temperature": 0.7}},
                },
            },
            "agent_routing": {
                "studio_writer": {"backend": "cloud", "model": "primary"},
            },
        }
        config_path = config_dir / "settings.yaml"
        with open(config_path, "w") as f:
            yaml.dump(settings, f)

        router = ModelRouter(str(config_path))
        routing = router._get_routing("studio_writer")
        assert routing["backend"] == "cloud"

    def test_hybrid_mode_uses_agent_routing(self, temp_dir):
        import yaml
        from pathlib import Path

        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir(exist_ok=True)
        settings = {
            "deployment_mode": "hybrid",
            "models": {
                "local": {
                    "base_url": "http://localhost:8080/v1",
                    "models": {"primary_moe": "local-model"},
                    "default_params": {},
                },
                "cloud": {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "models": {"primary": "cloud-model"},
                    "default_params": {},
                },
            },
            "agent_routing": {
                "studio_reader": {"backend": "cloud", "model": "primary"},
                "studio_writer": {"backend": "local", "model": "primary_moe"},
            },
        }
        config_path = config_dir / "settings.yaml"
        with open(config_path, "w") as f:
            yaml.dump(settings, f)

        router = ModelRouter(str(config_path))

        # studio_reader should route to cloud
        routing = router._get_routing("studio_reader")
        assert routing["backend"] == "cloud"

        # studio_writer should route to local
        routing = router._get_routing("studio_writer")
        assert routing["backend"] == "local"


class TestModelRouterCompletion:
    """Test the complete() method."""

    @pytest.mark.asyncio
    async def test_complete_calls_local_backend(self, settings_yaml):
        router = ModelRouter(settings_yaml)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Generated text"}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        router._local_client = mock_client

        result = await router.complete("studio_writer", [{"role": "user", "content": "test"}])
        assert result == "Generated text"
        mock_client.post.assert_called_once()
        assert router.usage_log[-1]["prompt_tokens"] == 0

    @pytest.mark.asyncio
    async def test_complete_records_usage_and_cost(self, settings_yaml):
        router = ModelRouter(settings_yaml)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Text"}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "cost": 0.0042,
                      "prompt_tokens_details": {"cached_tokens": 1000}},
        }
        mock_response.raise_for_status = MagicMock()
        router._local_client = AsyncMock(post=AsyncMock(return_value=mock_response))

        await router.complete("studio_writer", [{"role": "user", "content": "test"}])
        assert router.usage_log == [{
            "role": "studio_writer",
            "model": "test-model",
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "cached_tokens": 1000,
            "cache_write_tokens": 0,
            "cost": 0.0042,
            "web_searches": 0,
        }]

    @pytest.mark.asyncio
    async def test_complete_retries_on_429(self, settings_yaml):
        """HTTP 429 should be retried."""
        router = ModelRouter(settings_yaml)

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"retry-after": "0"}

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        ok_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[rate_limited, ok_response])
        router._local_client = mock_client

        result = await router.complete("studio_writer", [{"role": "user", "content": "test"}])
        assert result == "ok"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_complete_retries_on_502(self, settings_yaml):
        """HTTP 502 should be retried."""
        import httpx

        router = ModelRouter(settings_yaml)

        error_response = MagicMock()
        error_response.status_code = 502
        error_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("502", request=MagicMock(), response=error_response)
        )

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        ok_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[error_response, ok_response])
        router._local_client = mock_client

        result = await router.complete("studio_writer", [{"role": "user", "content": "test"}])
        assert result == "ok"


class TestModelRouterHealthCheck:
    """Test health_check() for cloud and local backends."""

    @pytest.mark.asyncio
    async def test_health_check_cloud_success(self, temp_dir):
        import yaml
        from pathlib import Path

        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir(exist_ok=True)
        settings = {
            "deployment_mode": "cloud",
            "models": {
                "local": {"base_url": "http://localhost:8080/v1", "models": {}, "default_params": {}},
                "cloud": {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "models": {"primary": "test-model"},
                    "default_params": {},
                },
            },
            "agent_routing": {},
        }
        config_path = config_dir / "settings.yaml"
        with open(config_path, "w") as f:
            yaml.dump(settings, f)

        router = ModelRouter(str(config_path))
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"data": {"usage": 1.5, "limit": 10}})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        router._cloud_client = mock_client

        ok, msg = await router.health_check()
        assert ok is True
        assert "reachable" in msg.lower()
        assert "1.50 of a 10.00 limit" in msg
        mock_client.get.assert_awaited_once_with("/key")

    @pytest.mark.asyncio
    async def test_health_check_cloud_auth_failure(self, temp_dir):
        import yaml
        from pathlib import Path

        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir(exist_ok=True)
        settings = {
            "deployment_mode": "cloud",
            "models": {
                "local": {"base_url": "http://localhost:8080/v1", "models": {}, "default_params": {}},
                "cloud": {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "models": {"primary": "test-model"},
                    "default_params": {},
                },
            },
            "agent_routing": {},
        }
        config_path = config_dir / "settings.yaml"
        with open(config_path, "w") as f:
            yaml.dump(settings, f)

        router = ModelRouter(str(config_path))
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        router._cloud_client = mock_client

        ok, msg = await router.health_check()
        assert ok is False
        assert "401" in msg


class TestTimeoutConfiguration:
    """Test configurable timeout and CancelledError retry."""

    def test_cloud_timeout_from_config(self, settings_yaml):
        """Cloud client should use timeout_seconds from config."""
        router = ModelRouter(settings_yaml)
        # The config fixture has timeout_seconds: 300
        cloud_cfg = router.config["models"]["cloud"]
        assert cloud_cfg.get("timeout_seconds") == 300

    def test_local_timeout_from_config(self, settings_yaml):
        """Local client should use timeout_seconds from config."""
        router = ModelRouter(settings_yaml)
        local_cfg = router.config["models"]["local"]
        assert local_cfg.get("timeout_seconds") == 300

    @pytest.mark.asyncio
    async def test_complete_propagates_cancellation_without_retry(self, settings_yaml):
        """Stopping a planning tool must not silently start another request."""
        import asyncio

        router = ModelRouter(settings_yaml)

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        ok_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=[asyncio.CancelledError(), ok_response]
        )
        router._local_client = mock_client

        with pytest.raises(asyncio.CancelledError):
            await router.complete("studio_writer", [{"role": "user", "content": "test"}])
        assert mock_client.post.call_count == 1


async def test_streaming_chat_assembles_tools_reasoning_and_usage(settings_yaml):
    import json
    import httpx

    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "I will "}}]},
        {"choices": [{"index": 0, "delta": {"content": "check it.", "reasoning_details": [{"index": 0, "type": "reasoning.encrypted", "data": "abc", "format": "test"}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "read_file", "arguments": '{"path":'}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"outline.md"}'}}]}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.01}},
    ]

    def respond(request):
        payload = json.loads(request.content)
        assert payload["stream"] and payload["stream_options"]["include_usage"]
        return httpx.Response(200, text="\n\n".join("data: " + json.dumps(c) for c in chunks) + "\n\ndata: [DONE]\n")

    router = ModelRouter(settings_yaml)
    router._local_client = httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(respond))
    pieces = []
    try:
        answer = await router.chat("studio_writer", "System", [{"role": "user", "content": "Read"}], [], on_text=pieces.append)
    finally:
        await router.close()
    assert pieces == ["I will ", "check it."]
    assert answer["tool_calls"] == [{"id": "call_1", "name": "read_file", "arguments": {"path": "outline.md"}}]
    assert answer["native"]["reasoning_details"][0]["data"] == "abc"
    assert router.usage_log[-1]["cost"] == 0.01


async def test_web_results_stay_visible_on_the_next_step(settings_yaml):
    import json

    import httpx

    from src.model_router import _to_openai

    cite = {"type": "url_citation", "url_citation": {
        "url": "https://starwars.fandom.com/wiki/Battle_of_Endor/Legends", "title": "Battle of Endor",
        "content": "The Battle of Endor was fought in 4 ABY."}}
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "Checked.", "annotations": [cite, cite]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "c", "function": {"name": "status", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "server_tool_use": {"web_search_requests": 2}}},
    ]
    router = ModelRouter(settings_yaml)
    router._local_client = httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="\n\n".join("data: " + json.dumps(c) for c in chunks) + "\n\ndata: [DONE]\n")))
    try:
        answer = await router.chat("studio_writer", "System", [], [], on_text=lambda text: None)
    finally:
        await router.close()
    assert answer["content"] == "Checked."
    # The writer sees each page once, and how many searches it took.
    assert answer["sources"] == [{"title": "Battle of Endor", "url": "https://starwars.fandom.com/wiki/Battle_of_Endor/Legends"}]
    assert router.usage_log[-1]["web_searches"] == 2
    [sent] = _to_openai([{"role": "assistant", **answer}])
    assert "annotations" not in sent
    assert sent["content"].startswith("Checked.\n\n[Web results you saw")
    assert sent["content"].count("Battle_of_Endor/Legends") == 1 and "4 ABY" in sent["content"]


@pytest.mark.parametrize("ending", ["", ', "finish_reason": "length"'])
async def test_incomplete_stream_never_returns_an_executable_tool(settings_yaml, ending):
    import httpx

    response = '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"a","function":{"name":"write_file","arguments":"{}"}}]}' + ending + '}]}'
    router = ModelRouter(settings_yaml)
    router._local_client = httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(lambda request: httpx.Response(200, text="data: " + response + "\n")))
    try:
        with pytest.raises(RuntimeError, match="before it was complete"):
            await router.chat("studio_writer", "System", [], [], on_text=lambda text: None)
    finally:
        await router.close()


async def test_anthropic_stream_emits_text_and_preserves_native_blocks(settings_yaml):
    from types import SimpleNamespace

    async def texts():
        yield "First "
        yield "second."

    blocks = [SimpleNamespace(type="thinking", thinking="private", signature="signature"),
              SimpleNamespace(type="text", text="First second."),
              SimpleNamespace(type="tool_use", id="call1", name="status", input={})]
    stream = SimpleNamespace(text_stream=texts(), get_final_message=AsyncMock(return_value=SimpleNamespace(
        content=blocks, usage=SimpleNamespace(input_tokens=10, output_tokens=3), stop_reason="tool_use")))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=stream)
    context.__aexit__ = AsyncMock(return_value=None)
    client = MagicMock()
    client.beta.messages.stream.return_value = context
    router = ModelRouter(settings_yaml)
    router._get_anthropic_client = lambda backend: client
    pieces = []
    result = await router._anthropic_call("studio_chat", "anthropic", "test", "system", [], [], {}, pieces.append)
    assert pieces == ["First ", "second."]
    assert result["native"] == blocks
    assert result["tool_calls"] == [{"id": "call1", "name": "status", "arguments": {}}]


async def test_a_roles_server_tools_join_the_chats_own_tools(settings_yaml):
    import json
    import httpx

    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Found it."}}]})

    router = ModelRouter(settings_yaml)
    router.config["agent_routing"]["studio_writer"]["params"]["tools"] = [{"type": "openrouter:web_search"}]
    router._local_client = httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(respond))
    own = [{"name": "status", "description": "Status", "parameters": {"type": "object", "properties": {}}}]
    try:
        await router.chat("studio_writer", "System", [{"role": "user", "content": "Look it up"}], own)
    finally:
        await router.close()
    [payload] = payloads
    assert [t.get("type") for t in payload["tools"]] == ["function", "openrouter:web_search"]
    assert payload["tools"][0]["function"]["name"] == "status"


async def test_an_explicit_routing_overrides_the_role(settings_yaml):
    router = ModelRouter(settings_yaml)
    seen = {}

    async def fake_call(agent_role, backend, model, messages, params, **kwargs):
        seen.update(backend=backend, model=model, params=params)
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}

    router._openai_call = fake_call
    await router.chat(
        "studio_chat", "System", [{"role": "user", "content": "Hi"}], [],
        routing={"backend": "cloud", "model": "primary", "params": {"temperature": 0.2}},
    )
    assert seen["backend"] == "cloud"
    assert seen["model"] == "anthropic/claude-sonnet-4-20250514"
    assert seen["params"]["temperature"] == 0.2


def test_catalog_families_ignore_versions_and_releases():
    family = model_catalog.family
    assert family("anthropic/claude-opus-5.5") == family("anthropic/claude-opus-5") == "anthropic/claude-opus"
    assert family("deepseek/deepseek-v4.1-flash-1017") == "deepseek/deepseek-flash"
    assert family("google/gemini-3.1-pro-preview") == family("google/gemini-2.5-pro") == "google/gemini-pro"
    assert family("openai/gpt-6.2-terra") != family("openai/gpt-6.2-mini")


def test_the_catalog_offers_the_newest_of_each_recent_family():
    found = model_catalog.discovered(model_catalog.slim(CATALOG))
    offered = {model_id for model_id, entry in found.items() if not entry.get("hidden")}
    assert offered == {
        "google/gemini-4-argon", "anthropic/claude-sonnet-5.5", "anthropic/claude-opus-5.6",
        "openai/gpt-6.2-terra", "openai/gpt-6.2-mini", "x-ai/grok-5",
    }
    # Superseded in its family, or a family with nothing recent: kept, hidden.
    assert found["x-ai/grok-4.7"]["hidden"] and found["mistralai/mistral-large-2407"]["hidden"]
    assert found["anthropic/claude-opus-5.5"]["hidden"]
    # Coding, image and other makers' models, and variants, are left out.
    assert not {"qwen/qwen3-coder", "google/gemini-5-image", "meta-llama/llama-5",
                "anthropic/claude-opus-5.6:batch"} & set(found)
    terra = found["openai/gpt-6.2-terra"]
    assert terra["label"] == "GPT-6.2 Terra" and terra["price"] == {"in": 1.0, "out": 5.0}
    assert terra["efforts"] == ["low", "medium", "high"] and terra["discovered"]


def test_discovered_models_are_offered_but_never_picked_automatically(tmp_path, monkeypatch):
    config = tmp_path / "settings.yaml"
    config.write_text(yaml.safe_dump({
        "deployment_mode": "hybrid",
        "models": {
            "cloud": {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
                      "models": {"opus": {"id": "anthropic/claude-opus-5.5", "label": "Claude Opus 5.5", "hidden": True}}},
            "anthropic": {"api": "anthropic", "api_key_env": "ANTHROPIC_API_KEY",
                          "models": {"opus": {"id": "claude-opus-5-5"}}},
        },
        "agent_routing": {"studio_writer": {"backend": "anthropic", "model": "opus", "params": {}}},
    }), encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert model_catalog.refresh(config, lambda: CATALOG, now=CATALOG_NOW)
    loaded = load_config(config)
    cloud = loaded["models"]["cloud"]["models"]
    assert "openai/gpt-6.2-terra" in cloud
    # The configured entry keeps its alias and its hidden flag, and gains a price.
    assert "anthropic/claude-opus-5.5" not in cloud
    assert cloud["opus"]["hidden"] and cloud["opus"]["price"] == {"in": 4.0, "out": 20.0}
    # The writer's provider has no key, but nothing moves onto a discovered model.
    assert loaded["agent_routing"]["studio_writer"]["backend"] == "anthropic"
    # A role set to a discovered id still resolves once the catalog drops it.
    model_catalog.cache_path(config).unlink()
    router = ModelRouter(str(config))
    assert router._resolve_model({"backend": "cloud", "model": "openai/gpt-6.2-terra"}) == "openai/gpt-6.2-terra"


def test_the_catalog_cache_is_kept_for_a_day_and_survives_failures(tmp_path):
    config = tmp_path / "settings.yaml"
    assert model_catalog.stale(config)
    assert model_catalog.refresh(config, lambda: CATALOG, now=CATALOG_NOW)
    assert not model_catalog.stale(config, now=CATALOG_NOW + DAY - 60)
    assert model_catalog.stale(config, now=CATALOG_NOW + DAY)

    def offline():
        raise OSError("no network")

    assert not model_catalog.refresh(config, offline)
    assert not model_catalog.refresh(config, lambda: {"unexpected": "shape"})
    assert len(model_catalog.load(config)) == len(CATALOG)


async def test_a_dropped_connection_is_asked_again_until_text_has_arrived(settings_yaml, monkeypatch):
    import httpx

    monkeypatch.setattr("src.model_router.asyncio.sleep", AsyncMock())
    attempts = []

    def respond(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ReadError("connection reset")
        return httpx.Response(200, text='data: {"choices":[{"index":0,"delta":{"content":"Back."},"finish_reason":"stop"}]}\n\ndata: [DONE]\n')

    router = ModelRouter(settings_yaml)
    router._local_client = httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(respond))
    pieces = []
    try:
        await router.chat("studio_writer", "System", [{"role": "user", "content": "Hi"}], [], on_text=pieces.append)
    finally:
        await router.close()
    assert len(attempts) == 2 and pieces == ["Back."]


async def test_a_connection_dropped_after_text_arrived_is_not_asked_again(settings_yaml):
    import httpx

    class Drops(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"index":0,"delta":{"content":"Half"}}]}\n\n'
            raise httpx.ReadError("connection reset")

    attempts = []

    def respond(request):
        attempts.append(1)
        return httpx.Response(200, stream=Drops())

    router = ModelRouter(settings_yaml)
    router._local_client = httpx.AsyncClient(base_url="https://test.invalid", transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(httpx.ReadError):
            await router.chat("studio_writer", "System", [{"role": "user", "content": "Hi"}], [], on_text=lambda text: None)
    finally:
        await router.close()
    assert len(attempts) == 1


def test_retry_after_can_be_seconds_or_a_date():
    from src.model_router import _retry_delay

    assert _retry_delay("3") == 3
    assert _retry_delay("999") == 30
    assert _retry_delay(None) == 5
    assert _retry_delay("Wed, 21 Oct 2026 07:28:00 GMT") == 5
