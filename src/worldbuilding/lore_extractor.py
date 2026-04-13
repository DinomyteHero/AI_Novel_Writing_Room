"""LLM-assisted worldbuilding extraction from concept seeds and chapter prose.

Provides prompt templates and response parsing for extracting structured
lore entries from unstructured text via the ModelRouter.
"""

import json
import logging
import re
from typing import Optional

from src.worldbuilding.worldbuilding_db import LORE_CATEGORIES

logger = logging.getLogger(__name__)

_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "extracted_entries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": LORE_CATEGORIES,
                    },
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "valid_from": {"type": ["string", "null"]},
                    "valid_until": {"type": ["string", "null"]},
                    "thematic_notes": {"type": ["string", "null"]},
                    "speech_patterns": {"type": ["string", "null"]},
                },
                "required": ["category", "title", "content"],
            },
        },
    },
    "required": ["extracted_entries"],
}


def build_concept_seed_extraction_prompt(concept_seed: dict) -> list[dict]:
    """Build messages for LLM-assisted extraction from a concept seed."""
    seed_text = json.dumps(concept_seed, indent=2)

    system_msg = (
        "You are a worldbuilding analyst. Extract structured worldbuilding entries "
        "from the provided concept seed JSON. Focus on:\n"
        "- Factions, political systems, and power structures\n"
        "- Locations and geography\n"
        "- Cultural practices, species traits, and social customs\n"
        "- Technology, Force mechanics, or magic systems\n"
        "- Historical events referenced in backstories\n"
        "- Terminology specific to this story's universe\n"
        "- Character backgrounds that establish world facts\n\n"
        "For each entry, provide:\n"
        "- category: one of " + str(LORE_CATEGORIES) + "\n"
        "- title: a concise name for the entry\n"
        "- content: a thorough description (2-4 sentences)\n"
        "- tags: searchable keywords\n"
        "- thematic_notes: how this should FEEL in prose (optional)\n"
        "- speech_patterns: how characters from this group talk (optional, for factions/cultures)\n"
        "- valid_from/valid_until: in-universe timeline bounds if applicable\n\n"
        "Do NOT extract individual character personalities (those belong in character sheets).\n"
        "Do NOT extract plot structure (that belongs in scene cards).\n"
        "Focus on WORLD FACTS that agents need for consistency."
    )

    user_msg = f"Extract worldbuilding entries from this concept seed:\n\n{seed_text}"

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def build_chapter_extraction_prompt(
    chapter_text: str,
    scene_card: dict,
    existing_titles: Optional[list[str]] = None,
) -> list[dict]:
    """Build messages for extracting worldbuilding from generated chapter prose."""
    existing_str = ""
    if existing_titles:
        existing_str = (
            "\n\nAlready known lore entries (do NOT duplicate these):\n"
            + "\n".join(f"- {t}" for t in existing_titles)
        )

    scene_context = json.dumps(scene_card, indent=2)

    system_msg = (
        "You are a worldbuilding extraction agent. Scan the provided chapter prose "
        "for NEW worldbuilding assertions — facts about the world that were established "
        "or revealed in this chapter's narrative. Look for:\n"
        "- New locations, buildings, or geographic features described\n"
        "- Cultural customs, rituals, or social norms shown in action\n"
        "- Political structures, hierarchies, or power dynamics revealed\n"
        "- Technology, weapons, or tools with specific properties\n"
        "- Historical events referenced in dialogue or narration\n"
        "- New terminology, slang, titles, or units of measurement used\n"
        "- Species traits or Force/magic mechanics demonstrated\n\n"
        "For each extraction, provide:\n"
        "- category: one of " + str(LORE_CATEGORIES) + "\n"
        "- title: a concise name\n"
        "- content: what was established (cite the specific assertion, not opinions)\n"
        "- tags: searchable keywords\n\n"
        "Only extract CONCRETE WORLD FACTS, not character emotions, plot events, "
        "or things that are clearly temporary scene dressing.\n"
        "Do NOT extract things that are already in the known entries list."
        + existing_str
    )

    user_msg = (
        f"Scene card for context:\n```json\n{scene_context}\n```\n\n"
        f"Chapter prose to scan:\n\n{chapter_text}"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def parse_extraction_result(raw_result: str) -> list[dict]:
    """Parse and validate LLM extraction output.

    Tolerates missing optional fields, validates category enum.
    Returns a list of dicts ready for ``LoreService.create_lore_entry()``.
    """
    try:
        # Strip markdown fences if present
        text = raw_result.strip()
        had_fences = text.startswith("```")
        if had_fences:
            text = re.sub(r"^```\w*\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)

        # Strip preamble text before JSON (e.g. "Here are the entries:")
        first_brace = -1
        for ch in ('{', '['):
            pos = text.find(ch)
            if pos != -1 and (first_brace == -1 or pos < first_brace):
                first_brace = pos
        had_preamble = first_brace > 0
        if had_preamble:
            logger.info("Lore extractor: stripped %d chars of preamble before JSON", first_brace)
            text = text[first_brace:]

        # Strip postamble text after JSON
        last_brace = max(text.rfind('}'), text.rfind(']'))
        if last_brace != -1:
            text = text[:last_brace + 1]

        if had_fences or had_preamble:
            logger.info("Lore extractor: model output required cleanup (fences=%s, preamble=%s)",
                        had_fences, had_preamble)

        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse extraction result as JSON. Raw (first 500 chars): %s",
            raw_result[:500],
        )
        return []

    # Handle LLM returning a bare list instead of the expected wrapper dict
    if isinstance(data, list):
        entries_raw = data
    elif isinstance(data, dict):
        entries_raw = data.get("extracted_entries", [])
    else:
        return []

    if not isinstance(entries_raw, list):
        return []

    valid_entries = []
    for entry in entries_raw:
        if not isinstance(entry, dict):
            continue

        category = entry.get("category", "")
        title = entry.get("title", "")
        content = entry.get("content", "")

        if not category or not title or not content:
            continue
        if category not in LORE_CATEGORIES:
            logger.warning("Unknown category '%s' in extraction, skipping", category)
            continue

        valid_entries.append({
            "category": category,
            "title": title,
            "content": content,
            "tags": entry.get("tags", []),
            "valid_from": entry.get("valid_from"),
            "valid_until": entry.get("valid_until"),
            "thematic_notes": entry.get("thematic_notes"),
            "speech_patterns": entry.get("speech_patterns"),
        })

    return valid_entries
