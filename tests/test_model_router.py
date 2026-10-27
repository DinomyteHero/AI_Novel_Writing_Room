"""Tests for ModelRouter."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.model_router import ModelRouter


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
