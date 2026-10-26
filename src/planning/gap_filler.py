"""Gap-filling proposals for the Story Brief.

The policy is deliberately conservative: the model proposes, the writer
confirms. ``propose_options`` is deterministic and offline; the async variant
uses the configured model when available. A delegated fill is marked as
``origin=delegated`` so it never masquerades as an authorial decision.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

_TEMPLATES: dict[str, tuple[str, ...]] = {
    "one_sentence_pitch": (
        "A retired operative is forced back into the field when the person they failed to protect becomes the target.",
        "A loyal insider discovers the institution they serve has been protecting the wrong secret.",
        "Two people who need each other to survive discover they want incompatible futures.",
    ),
    "emotional_core": (
        "Reckoning with the cost of choosing a cause over a person.",
        "Learning that safety bought with distance is not the same as being free.",
        "Deciding whether loyalty to a person can survive loyalty to what they represent.",
    ),
    "reader_promise": (
        "A tense, propulsive story that earns its emotional ending.",
        "A character-first thriller where every victory costs something the protagonist cannot get back.",
        "An intimate, morally complicated story about the people institutions use and discard.",
    ),
    "want": (
        "To prove they are not the person their past says they are.",
        "To protect someone who does not know they are in danger.",
        "To finish the work that got someone else killed.",
    ),
    "role": (
        "Protagonist — the character whose choice drives the story.",
        "Antagonist — the character whose vision makes the protagonist's choice necessary.",
        "Co-lead — the character who sees the protagonist more clearly than they see themselves.",
    ),
    "arc_type": (
        "Positive change — they stop believing the lie and pay for the truth.",
        "Flat — they hold their belief while the world tries to break it.",
        "Negative change — they embrace the lie and become the thing they feared.",
    ),
    "need": (
        "To accept that being useful is not the same as being loved.",
        "To stop treating control as the same thing as safety.",
        "To forgive themselves for the choice they made when they were powerless.",
    ),
    "lie_believed": (
        "That keeping everyone at a distance keeps them safe.",
        "That the system will reward doing the work correctly.",
        "That they are only valuable while they are useful.",
    ),
    "ghost": (
        "A failure they survived but never explained.",
        "A betrayal that taught them to move first.",
        "A loss they have reframed as a lesson instead of a wound.",
    ),
    "question": (
        "Can you love someone without trying to save them?",
        "Is loyalty to a person the same as loyalty to what they represent?",
        "What is the difference between justice and revenge when the law has already failed?",
    ),
    "premise": (
        "A person who has spent years avoiding their past is forced to return to it when it starts killing people they love.",
        "A loyal insider discovers the institution they serve has been protecting the wrong secret.",
        "Two people who need each other to survive discover they want incompatible futures.",
    ),
    "function": (
        "A place where the protagonist cannot use their usual authority.",
        "A place that rewards the antagonist's version of the truth.",
        "A place where the protagonist has to choose between two people they love.",
    ),
    "rule": (
        "The world punishes open use of power but rewards quiet leverage.",
        "The technology works exactly once per person, and everyone knows it.",
        "The institution can protect you only by owning the story of what you did.",
    ),
    "register": (
        "Close third, concrete, dry, with short bursts of lyricism earned by pressure.",
        "Warm, wry, fast-moving commercial prose with a melancholy undertow.",
        "Spare and controlled, with the emotional weight carried by what is omitted.",
    ),
    "pov": (
        "Close third, single POV, past tense.",
        "Close third, alternating between the two leads, past tense.",
        "First person, unreliable, present tense.",
    ),
}

_FALLBACK = (
    "A concrete, low-risk option that can be revised later.",
    "A more emotionally expensive option that raises the stakes.",
    "A stranger option that opens a different story direction.",
)


def _name(brief: Mapping[str, Any], gap: Mapping[str, Any]) -> str:
    # Avoid importing the story_brief module at module import time.
    from src.planning.story_brief import entity_name

    return entity_name(
        brief,
        str(gap.get("entity_type") or "character"),
        str(gap.get("entity_id") or "protagonist"),
    )


def propose_options(
    gap: Mapping[str, Any],
    brief: Mapping[str, Any],
    n: int = 3,
) -> list[str]:
    """Return deterministic options for a gap (offline fallback)."""
    field = str(gap.get("field") or "")
    options = list(_TEMPLATES.get(field, _FALLBACK))[:n]
    if options and field in {"want", "need", "lie_believed", "ghost"}:
        name = _name(brief, gap)
        options = [option.replace("they", name, 1) if option.startswith("To ") else option for option in options]
    return options


async def propose_options_with_model(
    gap: Mapping[str, Any],
    brief: Mapping[str, Any],
    router: Any,
    *,
    n: int = 3,
) -> list[str]:
    """Ask the planning model for concrete options, falling back to templates."""
    prompt = (
        "You are helping a novelist fill one planning gap. Return JSON only: "
        '{"options": ["...", "...", "..."]}.\n\n'
        f"Gap: {gap.get('prompt') or gap.get('field')}\n"
        f"Entity: {gap.get('entity_type')}/{gap.get('entity_id')}\n"
        f"Known brief: {json.dumps(dict(brief), ensure_ascii=False)[:6000]}\n\n"
        f"Give {n} concrete, distinct options. Each option must be one or two "
        "sentences, specific enough to guide a scene, and must not invent "
        "proper nouns that are not already in the brief."
    )
    try:
        result = await router.complete_structured(
            "story_brief_planner",
            [
                {"role": "system", "content": "You propose planning options; the author decides."},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception:
        return propose_options(gap, brief, n=n)
    if not isinstance(result, dict):
        return propose_options(gap, brief, n=n)
    options = [str(item) for item in (result.get("options") or []) if str(item).strip()]
    return options[:n] or propose_options(gap, brief, n=n)


__all__ = ["propose_options", "propose_options_with_model"]
