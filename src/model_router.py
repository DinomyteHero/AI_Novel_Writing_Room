"""Routes agent LLM calls to the appropriate backend based on config."""

import asyncio
import json
import logging
import os
import random
from typing import Optional

import httpx
import yaml

logger = logging.getLogger(__name__)


class ModelRouter:
    """Routes agent LLM calls to the appropriate backend based on config.

    All agent code calls the router; the router reads the config to determine
    which backend (llama-server local or OpenRouter cloud) handles each request.
    """

    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        for key in ("deployment_mode", "models"):
            if key not in self.config:
                raise ValueError(
                    f"Missing required config key '{key}' in {config_path}"
                )
        self.mode = self.config["deployment_mode"]
        self._local_client: Optional[httpx.AsyncClient] = None
        self._cloud_client: Optional[httpx.AsyncClient] = None
        self.usage_log: list[dict] = []

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

        self._validate_routing()

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

        # Prompt caching for Anthropic models. OpenRouter/Anthropic expect
        # cache_control on a message *content block*, not at the request top
        # level (the latter is silently ignored). Mark the large static system
        # prompt as the cache breakpoint.
        caching_cfg = self.config.get("pipeline", {}).get("prompt_caching", {})
        if caching_cfg.get("enabled", False) and model.startswith("anthropic/"):
            ttl = str(caching_cfg.get("anthropic_ttl", "1h"))
            cache_control = {"type": "ephemeral"}
            if ttl == "1h":
                cache_control["ttl"] = "1h"
            payload["messages"] = self._apply_cache_control(messages, cache_control)

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
                choices = data.get("choices")
                if not choices:
                    error_payload = data.get("error", data)
                    error_text = json.dumps(error_payload, ensure_ascii=False)[:1000]
                    if attempt < max_retries:
                        logger.warning(
                            "LLM response missing choices for %s on attempt %d/%d "
                            "(model=%s): %s",
                            agent_role,
                            attempt + 1,
                            max_retries + 1,
                            model,
                            error_text,
                        )
                        await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                        continue
                    raise RuntimeError(
                        "LLM response missing choices for "
                        f"{agent_role} (model={model}): {error_text}"
                    )
                usage = data.get("usage") or {}
                self.usage_log.append({
                    "role": agent_role,
                    "model": model,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "cost": usage.get("cost"),
                })
                finish_reason = choices[0].get("finish_reason")
                content = choices[0]["message"]["content"]
                if content is None:
                    logger.warning(
                        "LLM returned null content for %s (finish_reason=%s)",
                        agent_role,
                        finish_reason or "unknown",
                    )
                    return ""
                if finish_reason == "length":
                    logger.warning(
                        "LLM output for %s was truncated at the token limit "
                        "(finish_reason=length, model=%s, chars=%d) — the result "
                        "is incomplete; raise max_tokens for this role.",
                        agent_role, model, len(content),
                    )
                return content
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (502, 503) and attempt < max_retries:
                    await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                    continue
                raise
            except (httpx.ConnectError, httpx.ReadTimeout):
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
    def _apply_cache_control(messages: list[dict], cache_control: dict) -> list[dict]:
        """Return a copy of messages with cache_control on the LAST system
        message (rendered as a content-block array). Anthropic caches the whole
        prefix up to and including the marked block, so the last system message
        (the large static prompt) is the right breakpoint. No-op if there is no
        string-content system message.
        """
        out = [dict(m) for m in messages]
        target = None
        for i, m in enumerate(out):
            if m.get("role") == "system" and isinstance(m.get("content"), str):
                target = i
        if target is not None:
            out[target] = {
                "role": "system",
                "content": [{
                    "type": "text",
                    "text": out[target]["content"],
                    "cache_control": cache_control,
                }],
            }
        return out

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
                # /models is public, so only /key proves the key itself works.
                client = await self._get_cloud_client()
                response = await client.get("/key")
                if response.status_code == 401:
                    return False, "Invalid API key (401 Unauthorized)"
                if response.status_code == 403:
                    return False, "API key lacks permissions (403 Forbidden)"
                response.raise_for_status()
                info = response.json().get("data") or {}
                message = "Cloud API reachable, key valid"
                if info.get("usage") is not None:
                    message += f"; credits used so far: {info['usage']:.2f}"
                if info.get("limit") is not None:
                    message += f" of a {info['limit']:.2f} limit"
                return True, message
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

    def _validate_routing(self) -> None:
        """Warn at load time about agent_routing models that resolve to neither
        a known alias nor a literal provider model id, catching a typo'd alias
        before it becomes a 400 at request time.
        """
        for role, cfg in (self.config.get("agent_routing") or {}).items():
            if not isinstance(cfg, dict):
                continue
            model_key = cfg.get("model")
            if not model_key:
                continue
            backend = cfg.get("backend") if self.mode == "hybrid" else self.mode
            models = (
                self.config.get("models", {})
                .get(backend or self.mode, {})
                .get("models", {})
            )
            if model_key not in models and "/" not in str(model_key):
                logger.warning(
                    "agent_routing[%s].model=%r is neither a known %s alias nor "
                    "a literal provider model id; calls for this role will likely "
                    "fail at request time.",
                    role, model_key, backend or self.mode,
                )

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

    async def close(self):
        """Close HTTP clients."""
        if self._local_client:
            await self._local_client.aclose()
        if self._cloud_client:
            await self._cloud_client.aclose()
