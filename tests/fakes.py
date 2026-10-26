"""A stand-in for ModelRouter: scripted replies per role, every call recorded."""

from __future__ import annotations


class FakeRouter:
    def __init__(self, responses: dict[str, list] | None = None, default: str = "# Chapter\n\nText."):
        self.responses = {role: list(items) for role, items in (responses or {}).items()}
        self.default = default
        self.calls: list[tuple[str, list[dict]]] = []
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
