"""Stand-ins for the outside world: ModelRouter (scripted replies per role,
every call recorded) and OpenRouter's model catalog."""

from __future__ import annotations

DAY = 24 * 60 * 60
CATALOG_NOW = 1_800_000_000


def catalog_model(model_id: str, name: str, days_old: int, context: int = 1_048_576,
                  price: tuple[float, float] = (2, 10), output: tuple[str, ...] = ("text",)) -> dict:
    """One entry in the shape of https://openrouter.ai/api/v1/models."""
    return {
        "id": model_id, "name": name, "created": CATALOG_NOW - days_old * DAY, "context_length": context,
        "architecture": {"input_modalities": ["text"], "output_modalities": list(output)},
        "pricing": {"prompt": f"{price[0] / 1e6:.10f}", "completion": f"{price[1] / 1e6:.10f}"},
        "supported_parameters": ["max_tokens", "reasoning", "tools"],
        "reasoning": {"supported_efforts": ["high", "medium", "low"]},
        "expiration_date": None,
    }


CATALOG = [
    # Configured in settings.yaml: they gain prices.
    catalog_model("google/gemini-4-argon", "Google: Gemini 4 Argon", 15),
    catalog_model("anthropic/claude-sonnet-5.5", "Anthropic: Claude Sonnet 5.5", 30, price=(3, 15)),
    catalog_model("anthropic/claude-opus-5.5", "Anthropic: Claude Opus 5.5", 36, price=(4, 20)),
    # New: offered beside them.
    catalog_model("anthropic/claude-opus-5.6", "Anthropic: Claude Opus 5.6", 2, price=(4, 20)),
    catalog_model("openai/gpt-6.2-terra", "OpenAI: GPT-6.2 Terra", 1, price=(1, 5)),
    catalog_model("openai/gpt-6.2-mini", "OpenAI: GPT-6.2 Mini", 1, context=400_000, price=(0.2, 1.25)),
    catalog_model("x-ai/grok-5", "xAI: Grok 5", 30),
    # Superseded or old: kept hidden.
    catalog_model("x-ai/grok-4.7", "xAI: Grok 4.7", 60),
    catalog_model("mistralai/mistral-large-2407", "Mistral: Mistral Large 2407", 800),
    # Not for prose, not a main maker, or a variant: left out.
    catalog_model("qwen/qwen3-coder", "Qwen: Qwen3 Coder", 5),
    catalog_model("google/gemini-5-image", "Google: Gemini 5 Image", 5, output=("image", "text")),
    catalog_model("meta-llama/llama-5", "Meta: Llama 5", 5),
    catalog_model("anthropic/claude-opus-5.6:batch", "Anthropic: Claude Opus 5.6 (batch)", 2),
]


class FakeRouter:
    def __init__(self, responses: dict[str, list] | None = None, default: str = "# Chapter\n\nText."):
        self.responses = {role: list(items) for role, items in (responses or {}).items()}
        self.default = default
        self.calls: list[tuple[str, list[dict]]] = []
        self.routings: list[dict | None] = []
        self.usage_log: list[dict] = []
        self.health = (True, "Cloud API reachable, key valid")

    async def complete(self, role: str, messages: list[dict]) -> str:
        self.calls.append((role, messages))
        queue = self.responses.get(role)
        reply = queue.pop(0) if queue else self.default
        if callable(reply):
            reply = reply(messages)
        self.usage_log.append(
            {"role": role, "model": "fake", "prompt_tokens": 100, "completion_tokens": 10, "cost": 0.001}
        )
        return reply

    async def chat(self, role: str, system: str, messages: list[dict], tools: list[dict], on_text=None,
                   routing: dict | None = None) -> dict:
        """Scripted replies are strings (a final answer) or dicts with
        ``tool_calls`` as ``[(name, arguments), ...]``, and optionally the
        ``sources`` and ``web_searches`` a provider-side web search returns."""
        self.routings.append(routing)
        self.calls.append((role, [{"role": "system", "content": system}] + list(messages)))
        queue = self.responses.get(role)
        reply = queue.pop(0) if queue else "Done."
        if callable(reply):
            reply = reply(messages)
        self.usage_log.append(
            {"role": role, "model": "fake", "prompt_tokens": 100, "completion_tokens": 10, "cost": 0.001,
             "web_searches": reply.get("web_searches", 0) if isinstance(reply, dict) else 0}
        )
        if isinstance(reply, str):
            if on_text:
                on_text(reply)
            return {"content": reply, "tool_calls": [], "native": None}
        calls = [
            {"id": f"call{i}", "name": name, "arguments": args}
            for i, (name, args) in enumerate(reply.get("tool_calls", []))
        ]
        return {"content": reply.get("content", ""), "tool_calls": calls, "native": reply.get("native"),
                "sources": reply.get("sources", [])}

    async def health_check(self) -> tuple[bool, str]:
        return self.health

    async def close(self) -> None:
        pass

    def roles(self) -> list[str]:
        return [role for role, _ in self.calls]

    def user_message(self, index: int) -> str:
        return self.calls[index][1][1]["content"]

    def system_message(self, index: int) -> str:
        return self.calls[index][1][0]["content"]
