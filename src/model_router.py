"""Routes each role's model calls to the provider configured for it.

Backends are the entries under ``models`` in config/settings.yaml. Most speak
the OpenAI-compatible chat-completions API (OpenRouter, OpenAI, Google's
Gemini endpoint, a local llama-server or Ollama); a backend with
``api: anthropic`` goes through the official Anthropic SDK instead.

``config/settings.local.yaml``, when present, is laid over the base settings.
The app writes the writer's choices there (which model plays which role, build
settings, a local server address), so settings.yaml stays as shipped.
"""

import asyncio
import copy
import json
import logging
import os
import random
from pathlib import Path
from typing import Callable, Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

# Anthropic requires an output limit on every request. This is the most the
# current models allow, so it caps nothing in practice; responses stream so a
# long one can't hit a request timeout.
ANTHROPIC_MAX_TOKENS = 128_000
# Models that take Anthropic's server-side refusal fallback ("default" form).
_FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Request settings that only make sense for OpenAI-compatible providers.
_OPENAI_ONLY_PARAMS = {"temperature", "top_p", "top_k", "min_p", "reasoning", "provider"}


def local_overlay_path(config_path: str | Path) -> Path:
    path = Path(config_path)
    return path.with_name(f"{path.stem}.local{path.suffix}")


def _merge(base: dict, overlay: dict, replace: tuple[str, ...] = ("agent_routing",)) -> dict:
    """Deep-merge ``overlay`` into a copy of ``base``. Each role under
    agent_routing is replaced whole, so a role moved to another model doesn't
    keep the old model's provider-specific params."""
    out = copy.deepcopy(base)
    for key, value in (overlay or {}).items():
        if key in replace and isinstance(value, dict):
            out[key] = {**(out.get(key) or {}), **copy.deepcopy(value)}
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value, replace=())
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(config_path: str | Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    overlay = local_overlay_path(config_path)
    if overlay.exists():
        with open(overlay, encoding="utf-8") as f:
            config = _merge(config, yaml.safe_load(f) or {})
    return config


class ModelRouter:
    """Routes role calls to the appropriate backend based on config."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config = load_config(config_path)
        for key in ("deployment_mode", "models"):
            if key not in self.config:
                raise ValueError(
                    f"Missing required config key '{key}' in {config_path}"
                )
        self.mode = self.config["deployment_mode"]
        self._local_client: Optional[httpx.AsyncClient] = None
        self._cloud_client: Optional[httpx.AsyncClient] = None
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._anthropic_clients: dict = {}
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

    # ------------------------------------------------------------------ #
    # Backends
    # ------------------------------------------------------------------ #

    def backend_config(self, backend: str) -> dict:
        return self.config["models"][backend]

    def is_anthropic(self, backend: str) -> bool:
        return self.backend_config(backend).get("api") == "anthropic"

    def api_key(self, backend: str) -> str:
        env = self.backend_config(backend).get("api_key_env")
        return os.environ.get(env, "") if env else ""

    def backends_in_use(self) -> list[str]:
        roles = (self.config.get("agent_routing") or {}).keys()
        return sorted({self._get_routing(role)["backend"] for role in roles})

    def missing_keys(self) -> list[str]:
        """Env var names of API keys the configured roles need but don't have."""
        missing = []
        for backend in self.backends_in_use():
            env = self.backend_config(backend).get("api_key_env")
            if env and not os.environ.get(env):
                missing.append(env)
        return missing

    async def _get_local_client(self) -> httpx.AsyncClient:
        return await self._get_client("local")

    async def _get_cloud_client(self) -> httpx.AsyncClient:
        return await self._get_client("cloud")

    async def _get_client(self, backend: str) -> httpx.AsyncClient:
        """An OpenAI-compatible client for ``backend``."""
        current = {"local": self._local_client, "cloud": self._cloud_client}.get(
            backend, self._clients.get(backend)
        )
        if current is not None:
            return current
        cfg = self.backend_config(backend)
        headers = {}
        if cfg.get("api_key_env"):
            api_key = self.api_key(backend)
            if not api_key:
                logger.warning(
                    "API key env var '%s' is empty — requests to %s will fail",
                    cfg["api_key_env"], backend,
                )
            headers["Authorization"] = f"Bearer {api_key}"
        client = httpx.AsyncClient(
            base_url=cfg["base_url"],
            headers=headers,
            timeout=float(cfg.get("timeout_seconds", 300.0)),
        )
        if backend == "local":
            self._local_client = client
        elif backend == "cloud":
            self._cloud_client = client
        else:
            self._clients[backend] = client
        return client

    def _get_anthropic_client(self, backend: str):
        if backend not in self._anthropic_clients:
            from anthropic import AsyncAnthropic

            cfg = self.backend_config(backend)
            self._anthropic_clients[backend] = AsyncAnthropic(
                api_key=self.api_key(backend) or None,
                timeout=float(cfg.get("timeout_seconds", 600.0)),
                max_retries=int(self.config.get("pipeline", {}).get("max_http_retries", 2)),
            )
        return self._anthropic_clients[backend]

    # ------------------------------------------------------------------ #
    # Calls
    # ------------------------------------------------------------------ #

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
        if self.is_anthropic(backend):
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            rest = _to_anthropic([m for m in messages if m["role"] != "system"], self._cache_control())
            reply = await self._anthropic_call(agent_role, backend, model, system, rest, [], params)
            return reply["content"]
        message = await self._openai_call(agent_role, backend, model, messages, params)
        return message.get("content") or ""

    async def chat(
        self,
        agent_role: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        on_text: Callable[[str], None] | None = None,
        routing: dict | None = None,
    ) -> dict:
        """One step of a tool-using conversation.

        ``messages`` use a neutral shape: ``{"role": "user", "content": str}``,
        ``{"role": "assistant", "content": str, "tool_calls": [...], "native": ...}``
        and ``{"role": "tool", "tool_call_id": str, "content": str}``. ``tools``
        are ``{"name", "description", "parameters"}`` (JSON schema). Returns
        ``{"content": str, "tool_calls": [{"id", "name", "arguments"}], "native": ...}``;
        pass the whole dict back as the assistant message to continue, so each
        provider gets its own message back unchanged.
        """
        routing = routing or self._get_routing(agent_role)
        backend = routing["backend"]
        model = self._resolve_model(routing)
        params = self._resolve_params(routing)
        # Tools in a role's params are OpenRouter server tools (web search,
        # web fetch) that OpenRouter runs itself; they join the chat's own.
        server_tools = params.pop("tools", [])
        # Steps within one chat turn are seconds apart, so the conversation's
        # cache marker uses the cheaper 5-minute entry.
        if self.is_anthropic(backend):
            return await self._anthropic_call(
                agent_role, backend, model, system, _to_anthropic(messages, self._cache_control("5m")),
                tools, params, on_text,
            )
        payload_messages = [{"role": "system", "content": system}] + _to_openai(messages)
        openai_tools = [
            {"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["parameters"],
            }}
            for t in tools
        ] + list(server_tools)
        message = await self._openai_call(
            agent_role, backend, model, payload_messages, params, tools=openai_tools, on_text=on_text,
            cache_ttl="5m",
        )
        calls = []
        for call in message.get("tool_calls") or []:
            raw = call.get("function", {}).get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except json.JSONDecodeError:
                arguments = {"_invalid_json": raw}
            calls.append({"id": call.get("id"), "name": call["function"]["name"], "arguments": arguments})
        return {"content": message.get("content") or "", "tool_calls": calls, "native": message}

    async def _openai_call(
        self,
        agent_role: str,
        backend: str,
        model: str,
        messages: list[dict],
        params: dict,
        tools: Optional[list[dict]] = None,
        on_text: Callable[[str], None] | None = None,
        cache_ttl: str | None = None,
    ) -> dict:
        # Anthropic models behind OpenRouter cache only at explicit markers on
        # content blocks (a request-level marker is ignored there): one on the
        # static system prompt, one where a message's stable parts end. Other
        # providers cache matching prefixes on their own and get plain text.
        cache_control = self._cache_control() if model.startswith("anthropic/") else None
        if cache_control:
            messages = self._apply_cache_control(messages, cache_control)
        payload = {
            "model": model,
            "messages": _with_parts(messages, cache_control and self._cache_control(cache_ttl)),
            **params,
        }
        if tools:
            payload["tools"] = tools

        client = await self._get_client(backend)
        max_retries = self.config.get("pipeline", {}).get("max_http_retries", 2)
        streamed = False

        def received(text):
            nonlocal streamed
            streamed = True
            on_text(text)

        for attempt in range(max_retries + 1):
            try:
                if on_text:
                    data = await self._openai_stream(client, payload, received)
                else:
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
                details = usage.get("prompt_tokens_details") or {}
                self.usage_log.append({
                    "role": agent_role,
                    "model": model,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "cached_tokens": details.get("cached_tokens") or 0,
                    "cache_write_tokens": details.get("cache_write_tokens") or 0,
                    "cost": usage.get("cost"),
                })
                finish_reason = choices[0].get("finish_reason")
                message = choices[0]["message"]
                if message.get("content") is None and not message.get("tool_calls"):
                    logger.warning(
                        "LLM returned null content for %s (finish_reason=%s)",
                        agent_role,
                        finish_reason or "unknown",
                    )
                if finish_reason == "length":
                    logger.warning(
                        "LLM output for %s was truncated at the token limit "
                        "(finish_reason=length, model=%s, chars=%d) — the result "
                        "is incomplete; raise max_tokens for this role.",
                        agent_role, model, len(message.get("content") or ""),
                    )
                return message
            except httpx.HTTPStatusError as e:
                if not streamed and e.response.status_code in (429, 502, 503) and attempt < max_retries:
                    await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                    continue
                raise
            except (httpx.ConnectError, httpx.ReadTimeout):
                if not streamed and attempt < max_retries:
                    await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                    continue
                raise
        raise RuntimeError("Unreachable: retry loop exhausted")

    @staticmethod
    async def _openai_stream(client, payload: dict, on_text: Callable[[str], None]) -> dict:
        message = {"role": "assistant", "content": ""}
        calls, reasoning = {}, {}
        usage, finish = {}, None
        async with client.stream("POST", "/chat/completions", json={
            **payload, "stream": True, "stream_options": {"include_usage": True},
        }) as response:
            if response.is_error:
                await response.aread()
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    break
                if not raw:
                    continue
                chunk = json.loads(raw)
                if chunk.get("error"):
                    error = chunk["error"]
                    detail = error.get("message") if isinstance(error, dict) else error
                    raise RuntimeError(f"The model service interrupted its reply ({str(detail)[:200]}). Try again.")
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    if choice.get("index", 0) != 0:
                        continue
                    finish = choice.get("finish_reason") or finish
                    delta = choice.get("delta") or {}
                    for key in ("content", "reasoning", "refusal"):
                        if delta.get(key):
                            message[key] = message.get(key, "") + delta[key]
                            if key == "content":
                                on_text(delta[key])
                    if delta.get("annotations"):
                        message.setdefault("annotations", []).extend(delta["annotations"])
                    for part in delta.get("reasoning_details") or []:
                        entry = reasoning.setdefault(part.get("index", 0), {})
                        for key, value in part.items():
                            entry[key] = entry.get(key, "") + value if key in ("text", "signature", "data") and isinstance(value, str) else value
                    for part in delta.get("tool_calls") or []:
                        entry = calls.setdefault(part["index"], {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        if part.get("id"):
                            entry["id"] = part["id"]
                        for key in ("name", "arguments"):
                            entry["function"][key] += (part.get("function") or {}).get(key) or ""
        if finish is None or finish == "length":
            raise RuntimeError("The model's reply ended before it was complete. Try again; no unfinished tool call was applied.")
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        if reasoning:
            message["reasoning_details"] = [reasoning[i] for i in sorted(reasoning)]
        return {"choices": [{"message": message, "finish_reason": finish}], "usage": usage}

    async def _anthropic_call(
        self,
        agent_role: str,
        backend: str,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        params: dict,
        on_text: Callable[[str], None] | None = None,
    ) -> dict:
        client = self._get_anthropic_client(backend)
        kwargs = {
            "model": model,
            "max_tokens": int(params.get("max_tokens", ANTHROPIC_MAX_TOKENS)),
            "messages": messages,
        }
        kwargs.update({k: v for k, v in params.items() if k not in _OPENAI_ONLY_PARAMS | {"max_tokens"}})
        if system:
            kwargs["system"] = [{"type": "text", "text": system}]
            if cache_control := self._cache_control():
                kwargs["system"][0]["cache_control"] = cache_control
        if tools:
            kwargs["tools"] = [
                {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                for t in tools
            ]
        if model in _FALLBACK_MODELS:
            kwargs["betas"] = [_FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        async with client.beta.messages.stream(**kwargs) as stream:
            if on_text:
                async for text in stream.text_stream:
                    on_text(text)
            message = await stream.get_final_message()
        if on_text and message.stop_reason == "max_tokens":
            raise RuntimeError("The model's reply ended before it was complete. Try again; no unfinished tool call was applied.")
        usage = message.usage
        self.usage_log.append({
            "role": agent_role,
            "model": model,
            "prompt_tokens": (usage.input_tokens or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0),
            "completion_tokens": usage.output_tokens or 0,
            "cached_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "cost": None,
        })
        if message.stop_reason == "refusal":
            logger.warning("The model declined the request for %s (model=%s)", agent_role, model)
        text = "".join(b.text for b in message.content if b.type == "text")
        calls = [
            {"id": b.id, "name": b.name, "arguments": dict(b.input or {})}
            for b in message.content
            if b.type == "tool_use"
        ]
        return {"content": text, "tool_calls": calls, "native": list(message.content)}

    def _cache_control(self, ttl: str | None = None) -> dict | None:
        """A cache marker with the configured TTL (or ``ttl``), or None when
        prompt caching is turned off."""
        caching = self.config.get("pipeline", {}).get("prompt_caching", {})
        if not caching.get("enabled", False):
            return None
        ttl = ttl or str(caching.get("anthropic_ttl", "1h"))
        return {"type": "ephemeral", "ttl": "1h"} if ttl == "1h" else {"type": "ephemeral"}

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

    # ------------------------------------------------------------------ #
    # Checks
    # ------------------------------------------------------------------ #

    async def health_check(self) -> tuple[bool, str]:
        """Verify that every backend the roles use is reachable and accepts its key."""
        backends = ["local"] if self.mode == "local" else (
            ["cloud"] if self.mode == "cloud" else self.backends_in_use() or ["cloud"]
        )
        results = [await self.check_backend(b) for b in backends]
        if len(results) == 1:
            return results[0]
        ok = all(r[0] for r in results)
        return ok, "; ".join(f"{b}: {msg}" for b, (_, msg) in zip(backends, results))

    async def check_backend(self, backend: str) -> tuple[bool, str]:
        cfg = self.backend_config(backend)
        if self.is_anthropic(backend):
            return await self._check_anthropic(backend)
        if backend == "local" or not cfg.get("api_key_env"):
            try:
                client = await self._get_client(backend)
                response = await client.get("/models")
                response.raise_for_status()
                return True, "Local server reachable"
            except httpx.ConnectError:
                return False, "Local server unreachable at " + cfg["base_url"]
            except Exception as e:
                return False, f"Local server error: {e}"
        name = cfg.get("label") or cfg.get("provider") or backend
        try:
            client = await self._get_client(backend)
            # OpenRouter's /models is public, so only /key proves the key works.
            openrouter = "openrouter.ai" in cfg.get("base_url", "")
            response = await client.get("/key" if openrouter else "/models")
            if response.status_code == 401:
                return False, "Invalid API key (401 Unauthorized)"
            if response.status_code == 403:
                return False, "API key lacks permissions (403 Forbidden)"
            response.raise_for_status()
            message = "Cloud API reachable, key valid"
            if openrouter:
                info = response.json().get("data") or {}
                if info.get("usage") is not None:
                    message += f"; credits used so far: {info['usage']:.2f}"
                if info.get("limit") is not None:
                    message += f" of a {info['limit']:.2f} limit"
            return True, message
        except httpx.ConnectError:
            return False, f"Cannot connect to {name} (network error)"
        except httpx.TimeoutException:
            return False, f"{name} connection timed out"
        except Exception as e:
            return False, f"Health check failed: {e}"

    async def _check_anthropic(self, backend: str) -> tuple[bool, str]:
        import anthropic

        if not self.api_key(backend):
            return False, "No API key set"
        try:
            await self._get_anthropic_client(backend).models.list(limit=1)
            return True, "Anthropic API reachable, key valid"
        except anthropic.AuthenticationError:
            return False, "Invalid API key (401 Unauthorized)"
        except anthropic.PermissionDeniedError:
            return False, "API key lacks permissions (403 Forbidden)"
        except anthropic.APIConnectionError:
            return False, "Cannot connect to Anthropic (network error)"
        except anthropic.APIStatusError as e:
            return False, f"Health check failed: {e.status_code}"

    # ------------------------------------------------------------------ #
    # Routing
    # ------------------------------------------------------------------ #

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
        models = self.config["models"][backend].get("models") or {}
        model = models.get(model_key, model_key)
        return model["id"] if isinstance(model, dict) else model

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
            ) or {}
            known_ids = {m["id"] if isinstance(m, dict) else m for m in models.values()}
            if model_key not in models and model_key not in known_ids and "/" not in str(model_key):
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

    async def close(self):
        """Close HTTP clients."""
        for client in [self._local_client, self._cloud_client, *self._clients.values()]:
            if client:
                await client.aclose()
        for client in self._anthropic_clients.values():
            await client.close()


def _blocks(message: dict, cache_control: dict | None) -> list[dict]:
    """A message's ``parts`` as text blocks, with the marker on the last part
    before ``cache_upto`` (the end of what stays the same between calls)."""
    blocks = [{"type": "text", "text": part} for part in message["parts"]]
    upto = message.get("cache_upto", len(blocks))
    if cache_control and 0 < upto <= len(blocks):
        blocks[upto - 1]["cache_control"] = cache_control
    return blocks


def _with_parts(messages: list[dict], cache_control: dict | None) -> list[dict]:
    """OpenAI-format messages without the ``parts`` bookkeeping: content
    blocks with a cache marker when one is given, plain text otherwise."""
    out = []
    for m in messages:
        if "parts" in m:
            plain = {k: v for k, v in m.items() if k not in ("parts", "cache_upto")}
            if cache_control:
                plain["content"] = _blocks(m, cache_control)
            m = plain
        out.append(m)
    return out


def _sources_note(annotations: list[dict]) -> str:
    """The web results a server-side search showed the model, written back
    into its own message: providers don't return them on later steps, and a
    model that can't see its sources goes looking for them again."""
    seen, lines = set(), []
    for item in annotations:
        cite = item.get("url_citation") or {}
        url = cite.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        snippet = " ".join((cite.get("content") or "").split())[:800]
        lines.append(f"- {cite.get('title') or url} ({url}): {snippet}")
    if not lines:
        return ""
    return "\n\n[Web results you saw while writing this, kept so you can use them:]\n" + "\n".join(lines)


def _to_openai(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m["role"] == "assistant":
            if isinstance(m.get("native"), dict):
                native = dict(m["native"])
                found = native.pop("annotations", None)
                if found:
                    native["content"] = (native.get("content") or "") + _sources_note(found)
                out.append(native)
                continue
            entry = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                entry["tool_calls"] = [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                    for c in m["tool_calls"]
                ]
            out.append(entry)
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            out.append({k: m[k] for k in ("role", "content", "parts", "cache_upto") if k in m})
    return out


def _to_anthropic(messages: list[dict], cache_control: dict | None = None) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m["role"] == "assistant":
            if isinstance(m.get("native"), list):
                content = m["native"]
            else:
                content = [{"type": "text", "text": m.get("content") or "(no reply)"}]
                content += [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}
                    for c in m.get("tool_calls") or []
                ]
            out.append({"role": "assistant", "content": content})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if m.get("is_error"):
                block["is_error"] = True
            last = out[-1] if out else None
            if last and last["role"] == "user" and isinstance(last["content"], list) and all(
                b.get("type") == "tool_result" for b in last["content"]
            ):
                last["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif "parts" in m:
            out.append({"role": "user", "content": _blocks(m, cache_control)})
        else:
            out.append({"role": "user", "content": m["content"]})
    return out
