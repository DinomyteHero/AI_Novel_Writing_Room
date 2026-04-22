"""Opt-in model-obedience diagnostic.

This utility intentionally lives outside ``tests/`` and is not part of the
normal pytest suite. Run it directly when you want a live OpenRouter check.

Budget: ~$0.02-0.05 for one short Sonnet 4.6 completion.
"""

import asyncio
import os
from pathlib import Path

import httpx


SYSTEM = """You are drafting a short prose passage (~250 words) for a Legends-era Star Wars novel. The POV character is Ben Skywalker, 22, tired Jedi Knight.

VOICE RULE (READ BEFORE WRITING): Ben's interiority in this Part-1 scene must be REACTIVE and TACTILE. He feels the wrongness before he can name it. His body registers the disturbance; his mind does NOT analyse it. Narrate only through:
  - sensory register (what his body does, what the room sounds like, what he notices and can't name)
  - auditory/vibrational metaphor if you must reach for metaphor at all

DO NOT:
  - describe the Force using any structural, architectural, mechanical, musical-beat, or analytical framing
  - use words like "structural", "layer", "architecture", "measurable", "the Force's answer", "lagged behind", "second beat", "a frequency", "pattern", "confirmation"
  - write a sentence Ben could read out loud in a mission debrief
  - explain what the disturbance IS - only render what it feels like on his body

If any sentence in your draft could be lifted into a formal report, that sentence is wrong.

Write the opening 250 words of the scene. Ben alone in the Temple training salle after a sparring loss, running an unlit Shii-Cho form, noticing that the Force is "arriving late" against his body's expectation. No other characters in this passage. End at a natural paragraph break."""

USER = "Draft the 250-word opening."


def _load_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


async def call(api_key: str) -> tuple[str, dict]:
    async with httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=120.0,
    ) as client:
        resp = await client.post(
            "/chat/completions",
            json={
                "model": "anthropic/claude-sonnet-4.5",
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": USER},
                ],
                "temperature": 0.8,
                "max_tokens": 500,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        text = data["choices"][0]["message"]["content"]
        return text, usage


def main() -> int:
    _load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set.")

    text, usage = asyncio.run(call(api_key))

    print("=" * 70)
    print("MODEL OBEDIENCE TEST - reframed directive at top")
    print("=" * 70)
    print(text)
    print()
    print("Usage:", usage)

    Path("tmp_diagnostic/obedience_reframed.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
