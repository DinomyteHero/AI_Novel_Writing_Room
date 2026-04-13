"""Routes agent LLM calls to the appropriate backend based on config."""

import asyncio
import json
import logging
import os
import random
import re
from pathlib import Path
from typing import Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

# Regex for stripping markdown code fences: ```json, ```JSON, ``` json, etc.
_FENCE_OPEN = re.compile(r"^```\s*\w*\s*\n", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"\n```\s*$")


class ModelRouter:
    """Routes agent LLM calls to the appropriate backend based on config.

    All agent code calls the router; the router reads the config to determine
    which backend (llama-server local or OpenRouter cloud) handles each request.
    """

    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        for key in ("deployment_mode", "models"):
            if key not in self.config:
                raise ValueError(
                    f"Missing required config key '{key}' in {config_path}"
                )
        self.mode = self.config["deployment_mode"]
        self._local_client: Optional[httpx.AsyncClient] = None
        self._cloud_client: Optional[httpx.AsyncClient] = None

        # Warn when per-agent backend overrides are present but will be ignored
        if self.mode in ("local", "cloud"):
            backends = {
                v.get("backend")
                for v in self.config.get("agent_routing", {}).values()
                if isinstance(v, dict) and v.get("backend")
            }
            if len(backends) > 1 or (backends and backends != {self.mode}):
                logger.info(
                    "deployment_mode=%s — per-agent 'backend' overrides in "
                    "agent_routing are ignored (use 'hybrid' to honour them)",
                    self.mode,
                )

    async def _get_local_client(self) -> httpx.AsyncClient:
        if self._local_client is None:
            timeout = self.config["models"]["local"].get("timeout_seconds", 300.0)
            self._local_client = httpx.AsyncClient(
                base_url=self.config["models"]["local"]["base_url"],
                timeout=float(timeout),
            )
        return self._local_client

    async def _get_cloud_client(self) -> httpx.AsyncClient:
        if self._cloud_client is None:
            cloud_cfg = self.config["models"]["cloud"]
            api_key = os.environ.get(cloud_cfg["api_key_env"], "")
            if not api_key:
                logger.warning(
                    "Cloud API key env var '%s' is empty — cloud requests will fail",
                    cloud_cfg["api_key_env"],
                )
            timeout = cloud_cfg.get("timeout_seconds", 300.0)
            self._cloud_client = httpx.AsyncClient(
                base_url=cloud_cfg["base_url"],
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=float(timeout),
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

        # Prompt caching for Anthropic models (OpenRouter top-level cache_control)
        caching_cfg = self.config.get("pipeline", {}).get("prompt_caching", {})
        if caching_cfg.get("enabled", False) and model.startswith("anthropic/"):
            ttl = str(caching_cfg.get("anthropic_ttl", "1h"))
            cache_control = {"type": "ephemeral"}
            if ttl == "1h":
                cache_control["ttl"] = "1h"
            payload["cache_control"] = cache_control

        if backend == "local":
            client = await self._get_local_client()
        else:
            client = await self._get_cloud_client()

        max_retries = self.config.get("pipeline", {}).get("max_http_retries", 2)
        for attempt in range(max_retries + 1):
            try:
                response = await client.post("/chat/completions", json=payload)
                if response.status_code == 429 and attempt < max_retries:
                    retry_after = int(response.headers.get("retry-after", "5"))
                    await asyncio.sleep(min(retry_after, 30))
                    continue
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if content is None:
                    logger.warning(
                        "LLM returned null content for %s (finish_reason=%s)",
                        agent_role,
                        data["choices"][0].get("finish_reason", "unknown"),
                    )
                    return ""
                return content
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (502, 503) and attempt < max_retries:
                    await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                    continue
                raise
            except (httpx.ConnectError, httpx.ReadTimeout) as e:
                if attempt < max_retries:
                    await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                    continue
                raise
            except asyncio.CancelledError:
                if attempt < max_retries:
                    logger.warning(
                        "Request cancelled (timeout) on attempt %d/%d for %s — retrying",
                        attempt + 1, max_retries + 1, agent_role,
                    )
                    await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                    continue
                raise
        raise RuntimeError("Unreachable: retry loop exhausted")

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Strip markdown code fences from a string."""
        cleaned = text.strip()
        if _FENCE_OPEN.match(cleaned):
            cleaned = _FENCE_OPEN.sub("", cleaned, count=1)
            cleaned = _FENCE_CLOSE.sub("", cleaned)
        return cleaned.strip()

    async def complete_structured(
        self,
        agent_role: str,
        messages: list[dict],
        override_params: Optional[dict] = None,
    ) -> dict:
        """Send a completion request expecting structured JSON output.

        Retries once on JSON parse failure with a corrective prompt.
        On second failure, raises json.JSONDecodeError for callers to handle.
        """
        json_instruction = {
            "role": "system",
            "content": "Respond with valid JSON only. No markdown, no preamble.",
        }
        messages_with_json = [json_instruction] + messages

        raw = await self.complete(agent_role, messages_with_json, override_params)
        cleaned = self._strip_fences(raw)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # One retry: send the broken output back with a corrective prompt
            retry_messages = messages_with_json + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON. "
                        "Return ONLY the corrected JSON object. "
                        "No markdown fences, no commentary, no explanation."
                    ),
                },
            ]
            retry_raw = await self.complete(
                agent_role, retry_messages, override_params
            )
            retry_cleaned = self._strip_fences(retry_raw)
            return json.loads(retry_cleaned)

    async def health_check(self) -> tuple[bool, str]:
        """Verify API connectivity and key validity.

        Returns (success, message).
        """
        if self.mode == "local":
            try:
                client = await self._get_local_client()
                response = await client.get("/models")
                response.raise_for_status()
                return True, "Local server reachable"
            except httpx.ConnectError:
                return False, "Local server unreachable at " + self.config["models"]["local"]["base_url"]
            except Exception as e:
                return False, f"Local server error: {e}"
        else:
            try:
                client = await self._get_cloud_client()
                response = await client.get("/models", params={"limit": 1})
                if response.status_code == 401:
                    return False, "Invalid API key (401 Unauthorized)"
                if response.status_code == 403:
                    return False, "API key lacks permissions (403 Forbidden)"
                response.raise_for_status()
                return True, "Cloud API reachable, key valid"
            except httpx.ConnectError:
                return False, "Cannot connect to OpenRouter (network error)"
            except httpx.TimeoutException:
                return False, "OpenRouter connection timed out"
            except Exception as e:
                return False, f"Health check failed: {e}"

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

    # ------------------------------------------------------------------ #
    # Concept Workshop session helpers
    # ------------------------------------------------------------------ #

    def start_workshop_session(self) -> None:
        """Prepare the backend for a concept workshop session.

        In local mode this would restart llama-server with the extended
        context_size from ``concept_workshop_local``.  In cloud/hybrid
        mode this is a no-op — the cloud API handles context natively.
        """
        if self.mode == "local":
            ws_cfg = self.config.get("concept_workshop_local", {})
            self._workshop_context_size = ws_cfg.get("context_size", 131072)
            self._original_context_size = (
                self.config.get("local_inference", {}).get("context_size", 32768)
            )
            # In a real deployment this would restart llama-server with
            # the new context_size.  For now, record the override so
            # callers (and tests) can verify the intent.
            self.config.setdefault("local_inference", {})[
                "context_size"
            ] = self._workshop_context_size

    def end_workshop_session(self) -> None:
        """Restore standard backend settings after a workshop session.

        Reverses the context_size override applied by
        ``start_workshop_session()``.  No-op in cloud/hybrid mode.
        """
        if self.mode == "local":
            original = getattr(self, "_original_context_size", 32768)
            self.config.setdefault("local_inference", {})["context_size"] = original

    async def close(self):
        """Close HTTP clients."""
        if self._local_client:
            await self._local_client.aclose()
        if self._cloud_client:
            await self._cloud_client.aclose()
