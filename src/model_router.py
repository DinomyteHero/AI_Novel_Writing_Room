"""Routes agent LLM calls to the appropriate backend based on config."""

import json
import os
from pathlib import Path
from typing import Optional

import httpx
import yaml


class ModelRouter:
    """Routes agent LLM calls to the appropriate backend based on config.

    All agent code calls the router; the router reads the config to determine
    which backend (llama-server local or OpenRouter cloud) handles each request.
    """

    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.mode = self.config["deployment_mode"]
        self._local_client: Optional[httpx.AsyncClient] = None
        self._cloud_client: Optional[httpx.AsyncClient] = None

    async def _get_local_client(self) -> httpx.AsyncClient:
        if self._local_client is None:
            self._local_client = httpx.AsyncClient(
                base_url=self.config["models"]["local"]["base_url"],
                timeout=300.0,
            )
        return self._local_client

    async def _get_cloud_client(self) -> httpx.AsyncClient:
        if self._cloud_client is None:
            cloud_cfg = self.config["models"]["cloud"]
            api_key = os.environ.get(cloud_cfg["api_key_env"], "")
            self._cloud_client = httpx.AsyncClient(
                base_url=cloud_cfg["base_url"],
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=120.0,
            )
        return self._cloud_client

    async def complete(
        self,
        agent_role: str,
        messages: list[dict],
        override_params: Optional[dict] = None,
    ) -> str:
        """Send a completion request for the given agent role."""
        routing = self._get_routing(agent_role)
        backend = routing["backend"]
        model = self._resolve_model(routing)
        params = {**self._resolve_params(routing), **(override_params or {})}

        payload = {
            "model": model,
            "messages": messages,
            **params,
        }

        if backend == "local":
            client = await self._get_local_client()
        else:
            client = await self._get_cloud_client()

        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def complete_structured(
        self,
        agent_role: str,
        messages: list[dict],
        override_params: Optional[dict] = None,
    ) -> dict:
        """Send a completion request expecting structured JSON output."""
        json_instruction = {
            "role": "system",
            "content": "Respond with valid JSON only. No markdown, no preamble.",
        }
        messages_with_json = [json_instruction] + messages

        raw = await self.complete(agent_role, messages_with_json, override_params)

        # Strip markdown fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]

        return json.loads(cleaned)

    def _get_routing(self, agent_role: str) -> dict:
        if self.mode == "local":
            # In local mode, still check agent_routing for per-agent params
            agent_cfg = self.config.get("agent_routing", {}).get(agent_role, {})
            return {
                "backend": "local",
                "model": agent_cfg.get("model", "primary_moe"),
                "params": agent_cfg.get("params", {}),
            }
        elif self.mode == "cloud":
            agent_cfg = self.config.get("agent_routing", {}).get(agent_role, {})
            return {
                "backend": "cloud",
                "model": agent_cfg.get("model", "primary"),
                "params": agent_cfg.get("params", {}),
            }
        else:  # hybrid
            return self.config.get("agent_routing", {}).get(
                agent_role,
                {"backend": "local", "model": "primary_moe"},
            )

    def _resolve_model(self, routing: dict) -> str:
        backend = routing["backend"]
        model_key = routing.get("model", "primary_moe")
        models = self.config["models"][backend]["models"]
        return models.get(model_key, model_key)

    def _resolve_params(self, routing: dict) -> dict:
        backend = routing["backend"]
        model_key = routing.get("model", "primary_moe")
        base_params = (
            self.config["models"][backend]
            .get("default_params", {})
            .get(model_key, {})
        )
        override = routing.get("params", {})
        return {**base_params, **override}

    async def close(self):
        """Close HTTP clients."""
        if self._local_client:
            await self._local_client.aclose()
        if self._cloud_client:
            await self._cloud_client.aclose()
