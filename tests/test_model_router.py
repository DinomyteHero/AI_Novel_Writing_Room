"""Tests for ModelRouter."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.model_router import ModelRouter


class TestModelRouterRouting:
    """Test routing logic for different deployment modes."""

    def test_local_mode_routes_to_local(self, settings_yaml):
        router = ModelRouter(settings_yaml)
        routing = router._get_routing("plot_architect")
        assert routing["backend"] == "local"

    def test_local_mode_uses_agent_params(self, settings_yaml):
        router = ModelRouter(settings_yaml)
        routing = router._get_routing("plot_architect")
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
                "prose_stylist": {"backend": "cloud", "model": "primary"},
            },
        }
        config_path = config_dir / "settings.yaml"
        with open(config_path, "w") as f:
            yaml.dump(settings, f)

        router = ModelRouter(str(config_path))
        routing = router._get_routing("prose_stylist")
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
                "voice_checker": {"backend": "cloud", "model": "primary"},
                "prose_stylist": {"backend": "local", "model": "primary_moe"},
            },
        }
        config_path = config_dir / "settings.yaml"
        with open(config_path, "w") as f:
            yaml.dump(settings, f)

        router = ModelRouter(str(config_path))

        # voice_checker should route to cloud
        routing = router._get_routing("voice_checker")
        assert routing["backend"] == "cloud"

        # prose_stylist should route to local
        routing = router._get_routing("prose_stylist")
        assert routing["backend"] == "local"


class TestModelRouterCompletion:
    """Test the complete() and complete_structured() methods."""

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

        result = await router.complete("prose_stylist", [{"role": "user", "content": "test"}])
        assert result == "Generated text"
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_structured_parses_json(self, settings_yaml):
        router = ModelRouter(settings_yaml)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"verdict": "pass", "score": 0.9}'}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        router._local_client = mock_client

        result = await router.complete_structured("gate_critic", [{"role": "user", "content": "test"}])
        assert result["verdict"] == "pass"
        assert result["score"] == 0.9

    @pytest.mark.asyncio
    async def test_complete_structured_strips_markdown_fences(self, settings_yaml):
        router = ModelRouter(settings_yaml)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '```json\n{"verdict": "pass"}\n```'}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        router._local_client = mock_client

        result = await router.complete_structured("gate_critic", [{"role": "user", "content": "test"}])
        assert result["verdict"] == "pass"


class TestConceptWorkshopRouting:
    """Test concept_workshop agent routing and session helpers."""

    def _make_router(self, temp_dir, mode="hybrid"):
        import yaml
        from pathlib import Path

        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir(exist_ok=True)
        settings = {
            "deployment_mode": mode,
            "models": {
                "local": {
                    "base_url": "http://localhost:8080/v1",
                    "models": {"primary_moe": "local-model"},
                    "default_params": {"primary_moe": {"temperature": 0.7}},
                },
                "cloud": {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "models": {"primary": "cloud-model"},
                    "default_params": {"primary": {"temperature": 0.7, "max_tokens": 4096}},
                },
            },
            "agent_routing": {
                "concept_workshop": {
                    "backend": "cloud",
                    "model": "primary",
                    "params": {"temperature": 0.7, "max_tokens": 8192},
                },
                "voice_checker": {"backend": "cloud", "model": "primary"},
            },
            "concept_workshop_local": {
                "model": "primary_moe",
                "context_size": 131072,
                "params": {"temperature": 0.7, "min_p": 0.05},
            },
            "local_inference": {"context_size": 32768},
        }
        config_path = config_dir / "settings.yaml"
        with open(config_path, "w") as f:
            yaml.dump(settings, f)
        return ModelRouter(str(config_path))

    def test_hybrid_routes_to_cloud(self, temp_dir):
        router = self._make_router(temp_dir, mode="hybrid")
        routing = router._get_routing("concept_workshop")
        assert routing["backend"] == "cloud"
        assert routing["model"] == "primary"

    def test_cloud_routes_to_cloud(self, temp_dir):
        router = self._make_router(temp_dir, mode="cloud")
        routing = router._get_routing("concept_workshop")
        assert routing["backend"] == "cloud"

    def test_cloud_resolves_params(self, temp_dir):
        router = self._make_router(temp_dir, mode="cloud")
        routing = router._get_routing("concept_workshop")
        assert routing["params"]["temperature"] == 0.7
        assert routing["params"]["max_tokens"] == 8192

    def test_start_workshop_session_local(self, temp_dir):
        router = self._make_router(temp_dir, mode="local")
        assert router.config["local_inference"]["context_size"] == 32768
        router.start_workshop_session()
        assert router.config["local_inference"]["context_size"] == 131072

    def test_end_workshop_session_restores(self, temp_dir):
        router = self._make_router(temp_dir, mode="local")
        router.start_workshop_session()
        router.end_workshop_session()
        assert router.config["local_inference"]["context_size"] == 32768

    def test_start_end_noop_in_cloud(self, temp_dir):
        router = self._make_router(temp_dir, mode="cloud")
        # Should not raise.
        router.start_workshop_session()
        router.end_workshop_session()

    def test_start_end_noop_in_hybrid(self, temp_dir):
        router = self._make_router(temp_dir, mode="hybrid")
        router.start_workshop_session()
        router.end_workshop_session()
