"""WorkshopSummarizer — compresses conversation history into structured summaries.

Triggers when the session transcript approaches the context window threshold
and rebuilds the conversation context with recent turns at full fidelity and
earlier history represented through a structured summary.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.model_router import ModelRouter
from src.concept_workshop.workshop_state import ConceptWorkshopState

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Summary dataclass
# ------------------------------------------------------------------ #

@dataclass
class WorkshopSessionSummary:
    """Structured summary of a workshop session segment."""

    session_id: str = ""
    summary_timestamp: str = ""
    tokens_compressed: int = 0
    decisions_confirmed: dict = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)
    current_step: str = ""
    narrative_summary: str = ""
    key_decisions_reasoning: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> WorkshopSessionSummary:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ------------------------------------------------------------------ #
# Summarizer
# ------------------------------------------------------------------ #

# Prompt template for the utility model — structured summary extraction.
_SUMMARY_PROMPT = """\
You are a conversation summarizer for a concept-workshop session.

Given the conversation history and confirmed state below, produce a structured
JSON summary of the session so far.

Confirmed state:
{confirmed_state}

Open questions:
{open_questions}

Respond with JSON only:
{{
  "decisions_confirmed": {{ ... }},
  "open_questions": ["..."],
  "current_step": "Step N — description",
  "key_decisions_reasoning": ["..."]
}}
"""

# Prompt template for the primary model — narrative summary.
_NARRATIVE_PROMPT = """\
Summarize the following concept-workshop conversation in 2-3 sentences.
Focus on what concept has been developed so far and what key creative
decisions were made.  Do not list decisions — write a short narrative
paragraph.

Conversation:
{conversation}
"""


class WorkshopSummarizer:
    """Compresses workshop conversation history when context is running low."""

    DEFAULT_TOKEN_THRESHOLD = 24_000
    DEFAULT_RECENT_TURNS = 8
    CHARS_PER_TOKEN = 4  # Simple approximation.

    def __init__(self, router: ModelRouter, project_dir: Path):
        self.router = router
        self.project_dir = Path(project_dir)

    # ------------------------------------------------------------------ #
    # Threshold check
    # ------------------------------------------------------------------ #

    def should_summarize(
        self,
        conversation_history: list[dict],
        token_threshold: int = DEFAULT_TOKEN_THRESHOLD,
    ) -> bool:
        """Return True when estimated tokens exceed the threshold."""
        total_chars = sum(len(m.get("content", "")) for m in conversation_history)
        estimated_tokens = total_chars / self.CHARS_PER_TOKEN
        return estimated_tokens > token_threshold

    @staticmethod
    def estimate_tokens(conversation_history: list[dict]) -> int:
        total_chars = sum(len(m.get("content", "")) for m in conversation_history)
        return int(total_chars / 4)

    # ------------------------------------------------------------------ #
    # Summarization
    # ------------------------------------------------------------------ #

    async def summarize(
        self,
        conversation_history: list[dict],
        state: ConceptWorkshopState,
        session_id: str = "session_001",
    ) -> WorkshopSessionSummary:
        """Compress conversation history into a structured summary."""

        tokens_before = self.estimate_tokens(conversation_history)
        confirmed_summary = state.get_confirmed_summary()
        open_qs = state.get_open_questions()

        # --- Structured summary via utility model ---
        conversation_text = self._format_conversation(conversation_history)
        structured_prompt = _SUMMARY_PROMPT.format(
            confirmed_state=confirmed_summary,
            open_questions="\n".join(f"- {q}" for q in open_qs[:10]),
        )
        messages = [
            {"role": "system", "content": structured_prompt},
            {"role": "user", "content": conversation_text},
        ]
        try:
            structured = await self.router.complete_structured("summarizer", messages)
        except Exception:
            logger.warning("Structured summary extraction failed; using fallback.")
            structured = {}

        # --- Narrative summary via primary model ---
        narrative_messages = [
            {
                "role": "user",
                "content": _NARRATIVE_PROMPT.format(
                    conversation=conversation_text[:8000],
                ),
            },
        ]
        try:
            narrative = await self.router.complete("concept_workshop", narrative_messages)
        except Exception:
            logger.warning("Narrative summary generation failed; using fallback.")
            narrative = "Summary unavailable."

        summary = WorkshopSessionSummary(
            session_id=session_id,
            summary_timestamp=datetime.now(timezone.utc).isoformat(),
            tokens_compressed=tokens_before,
            decisions_confirmed=structured.get("decisions_confirmed", {}),
            open_questions=structured.get("open_questions", [q.split("—")[0].strip() for q in open_qs[:10]]),
            current_step=structured.get("current_step", "Unknown"),
            narrative_summary=narrative,
            key_decisions_reasoning=structured.get("key_decisions_reasoning", []),
        )

        # Persist the summary.
        self._save_summary(summary)

        return summary

    # ------------------------------------------------------------------ #
    # Context rebuild
    # ------------------------------------------------------------------ #

    def rebuild_context(
        self,
        summary: WorkshopSessionSummary,
        recent_turns: list[dict],
        state: ConceptWorkshopState,
    ) -> list[dict]:
        """Return a compressed conversation suitable for the next API call.

        Structure:
        1. System prompt context block (confirmed state + summary)
        2. Recent turns at full fidelity
        """
        confirmed = state.get_confirmed_summary()
        open_qs = state.get_open_questions()

        context_block = (
            "## Session context (compressed from earlier conversation)\n\n"
            f"### Confirmed decisions\n{confirmed}\n\n"
            f"### Summary of prior discussion\n{summary.narrative_summary}\n\n"
            f"### Key reasoning\n"
            + "\n".join(f"- {r}" for r in summary.key_decisions_reasoning)
            + "\n\n### Open questions\n"
            + "\n".join(f"- {q}" for q in open_qs[:10])
        )

        rebuilt: list[dict] = [
            {"role": "system", "content": context_block},
        ]
        rebuilt.extend(recent_turns)
        return rebuilt

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _format_conversation(self, history: list[dict]) -> str:
        lines = []
        for msg in history:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            lines.append(f"[{role}]: {content}")
        return "\n\n".join(lines)

    def _save_summary(self, summary: WorkshopSessionSummary) -> None:
        sessions_dir = self.project_dir / "workshop_sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        path = sessions_dir / f"{summary.session_id}_summary.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2, ensure_ascii=False)
