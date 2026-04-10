"""Tests for lore_extractor — prompt building and result parsing."""

import json

import pytest

from src.worldbuilding.lore_extractor import (
    build_concept_seed_extraction_prompt,
    build_chapter_extraction_prompt,
    parse_extraction_result,
)


class TestConceptSeedPrompt:
    def test_builds_valid_messages(self):
        seed = {"meta": {"project_title": "Test"}, "ensemble_cast": []}
        messages = build_concept_seed_extraction_prompt(seed)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_includes_seed_in_user_message(self):
        seed = {"meta": {"project_title": "The Purge's Echo"}}
        messages = build_concept_seed_extraction_prompt(seed)
        assert "The Purge's Echo" in messages[1]["content"]

    def test_system_prompt_mentions_categories(self):
        seed = {}
        messages = build_concept_seed_extraction_prompt(seed)
        assert "faction" in messages[0]["content"]
        assert "location" in messages[0]["content"]
        assert "terminology" in messages[0]["content"]


class TestChapterPrompt:
    def test_builds_valid_messages(self):
        messages = build_chapter_extraction_prompt(
            "Chapter prose here...",
            {"chapter_number": 1},
        )
        assert len(messages) == 2

    def test_includes_existing_titles(self):
        messages = build_chapter_extraction_prompt(
            "Some chapter text",
            {"chapter_number": 3},
            existing_titles=["Sith Order", "Korriban"],
        )
        assert "Sith Order" in messages[0]["content"]
        assert "Korriban" in messages[0]["content"]

    def test_no_existing_titles(self):
        messages = build_chapter_extraction_prompt(
            "Some chapter text",
            {"chapter_number": 1},
            existing_titles=None,
        )
        assert "Already known" not in messages[0]["content"]


class TestParseExtractionResult:
    def test_valid_result(self):
        raw = json.dumps({
            "extracted_entries": [
                {
                    "category": "faction",
                    "title": "Sith Order",
                    "content": "An ancient dark side order",
                    "tags": ["dark_side", "force"],
                    "thematic_notes": "Decay and power",
                },
                {
                    "category": "location",
                    "title": "Korriban",
                    "content": "The Sith homeworld",
                },
            ]
        })
        entries = parse_extraction_result(raw)
        assert len(entries) == 2
        assert entries[0]["category"] == "faction"
        assert entries[0]["title"] == "Sith Order"
        assert entries[0]["tags"] == ["dark_side", "force"]
        assert entries[1]["category"] == "location"

    def test_strips_markdown_fences(self):
        raw = '```json\n{"extracted_entries": [{"category": "faction", "title": "F", "content": "C"}]}\n```'
        entries = parse_extraction_result(raw)
        assert len(entries) == 1

    def test_skips_invalid_category(self):
        raw = json.dumps({
            "extracted_entries": [
                {"category": "invalid_cat", "title": "T", "content": "C"},
                {"category": "faction", "title": "Valid", "content": "C"},
            ]
        })
        entries = parse_extraction_result(raw)
        assert len(entries) == 1
        assert entries[0]["title"] == "Valid"

    def test_skips_missing_required_fields(self):
        raw = json.dumps({
            "extracted_entries": [
                {"category": "faction", "title": ""},  # missing content
                {"category": "faction", "content": "C"},  # missing title
                {"category": "faction", "title": "Valid", "content": "Good"},
            ]
        })
        entries = parse_extraction_result(raw)
        assert len(entries) == 1

    def test_malformed_json_returns_empty(self):
        entries = parse_extraction_result("not valid json at all")
        assert entries == []

    def test_missing_entries_key_returns_empty(self):
        raw = json.dumps({"other_key": []})
        entries = parse_extraction_result(raw)
        assert entries == []

    def test_optional_fields_default(self):
        raw = json.dumps({
            "extracted_entries": [
                {"category": "faction", "title": "F", "content": "C"},
            ]
        })
        entries = parse_extraction_result(raw)
        assert entries[0]["tags"] == []
        assert entries[0]["thematic_notes"] is None
        assert entries[0]["speech_patterns"] is None
