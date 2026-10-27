"""One way to call a model: size-checked, fence-stripped, never empty."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.studio.project import StudioError
from src.studio.prompts import message_tokens

if TYPE_CHECKING:
    from src.model_router import ModelRouter

CHAT_ROLE = "studio_chat"
WRITER_ROLE = "studio_writer"
CRITIC_ROLE = "studio_critic"
READER_ROLE = "studio_reader"

# Headroom below the ~1M-token windows of the default models, leaving room
# for the response.
MAX_PROMPT_TOKENS = 900_000
# Above this, models read the book less reliably and every call costs more.
LONG_PROMPT_TOKENS = 500_000

TOO_LONG = (
    "This call is more than the model can read at once. For a long series, write "
    "story-so-far notes for finished books (press.py story-so-far) so later books "
    "send those instead of the full text."
)
# How providers word a prompt that doesn't fit the model's context window.
_TOO_LONG = re.compile(
    r"prompt is too long|context.{0,20}(length|window|limit)|maximum context|too many (input )?tokens",
    re.IGNORECASE,
)

_FENCE = re.compile(r"^```[a-zA-Z]*\n(.*)\n```$", re.DOTALL)


def _clean(text: str) -> str:
    text = text.strip()
    match = _FENCE.match(text)
    return match.group(1).strip() if match else text


def too_long(exc: Exception) -> bool:
    """Whether a provider error says the prompt didn't fit. Our size check is
    an estimate, so a call it lets through can still be refused."""
    response = getattr(exc, "response", None)
    try:
        body = response.text if response is not None else ""
    except Exception:  # an unread streaming body
        body = ""
    return bool(_TOO_LONG.search(f"{exc} {body}"))


async def complete(router: "ModelRouter", role: str, messages: list[dict]) -> str:
    size = message_tokens(messages)
    if size > MAX_PROMPT_TOKENS:
        raise StudioError(
            f"This call would send about {size:,} tokens, more than the "
            f"{MAX_PROMPT_TOKENS:,} the tool allows. For a long series, write "
            "story-so-far notes for finished books (press.py story-so-far) so "
            "later books send those instead of the full text."
        )
    try:
        text = _clean(await router.complete(role, messages))
    except Exception as exc:
        if too_long(exc):
            raise StudioError(TOO_LONG) from exc
        raise
    if not text:
        raise StudioError("The model returned an empty response; nothing was saved.")
    return text


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost: float | None = None

    @classmethod
    def since(cls, router: "ModelRouter", start: int) -> "Usage":
        usage = cls()
        for entry in router.usage_log[start:]:
            usage.calls += 1
            usage.prompt_tokens += entry.get("prompt_tokens") or 0
            usage.completion_tokens += entry.get("completion_tokens") or 0
            usage.cached_tokens += entry.get("cached_tokens") or 0
            if entry.get("cost") is not None:
                usage.cost = (usage.cost or 0.0) + entry["cost"]
        return usage

    def add(self, other: "Usage") -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cached_tokens += other.cached_tokens
        if other.cost is not None:
            self.cost = (self.cost or 0.0) + other.cost

    def describe(self) -> str:
        cached = f" ({self.cached_tokens:,} read from cache)" if self.cached_tokens else ""
        text = (
            f"{self.calls} call(s), {self.prompt_tokens:,} tokens in{cached}, "
            f"{self.completion_tokens:,} out"
        )
        return text + (f", cost {self.cost:.4f} credits" if self.cost is not None else "")
