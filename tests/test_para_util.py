"""Unit tests for the shared paragraph-location helpers."""

from __future__ import annotations

import pytest

from src.quality._para_util import (
    line_to_paragraph_index,
    paragraph_indices_for_word,
    split_paragraphs,
)


class TestSplitParagraphs:
    def test_blank_line_separates_paragraphs(self):
        prose = "First paragraph.\n\nSecond paragraph.\n\nThird."
        assert split_paragraphs(prose) == [
            "First paragraph.",
            "Second paragraph.",
            "Third.",
        ]

    def test_multiple_blank_lines_treated_as_one_separator(self):
        prose = "First.\n\n\n\nSecond."
        assert split_paragraphs(prose) == ["First.", "Second."]

    def test_leading_trailing_whitespace_stripped(self):
        prose = "\n\n  First.  \n\n  Second.  \n\n"
        assert split_paragraphs(prose) == ["First.", "Second."]


class TestLineToParagraphIndex:
    def test_single_paragraph_all_lines_map_to_zero(self):
        prose = "Line one.\nLine two.\nLine three."
        for line in range(1, 4):
            assert line_to_paragraph_index(prose, line) == 0

    def test_lines_in_second_paragraph_map_to_one(self):
        prose = "Para zero line one.\nPara zero line two.\n\nPara one line one.\nPara one line two."
        assert line_to_paragraph_index(prose, 1) == 0
        assert line_to_paragraph_index(prose, 2) == 0
        assert line_to_paragraph_index(prose, 4) == 1
        assert line_to_paragraph_index(prose, 5) == 1

    def test_blank_line_between_paragraphs_maps_to_previous(self):
        prose = "First.\n\nSecond."
        # Line 2 is the blank separator — should resolve to paragraph 0
        assert line_to_paragraph_index(prose, 2) == 0

    def test_line_beyond_end_clamps_to_last_paragraph(self):
        prose = "Only paragraph."
        assert line_to_paragraph_index(prose, 999) == 0

    def test_three_paragraph_boundaries(self):
        prose = "One.\n\nTwo.\n\nThree."
        assert line_to_paragraph_index(prose, 1) == 0
        assert line_to_paragraph_index(prose, 3) == 1
        assert line_to_paragraph_index(prose, 5) == 2

    def test_non_positive_line_number_returns_zero(self):
        prose = "Something."
        assert line_to_paragraph_index(prose, 0) == 0
        assert line_to_paragraph_index(prose, -5) == 0


class TestParagraphIndicesForWord:
    def test_single_word_in_multiple_paragraphs(self):
        prose = "Silence fell.\n\nShe smiled.\n\nSilence again."
        assert paragraph_indices_for_word(prose, "silence") == [0, 2]

    def test_word_boundary_prevents_substring_match(self):
        prose = "He was silenced.\n\nPure silence."
        # "silence" should not match "silenced" (word boundary)
        assert paragraph_indices_for_word(prose, "silence") == [1]

    def test_case_insensitive_match(self):
        prose = "SILENCE fell.\n\nSilence returned."
        assert paragraph_indices_for_word(prose, "silence") == [0, 1]

    def test_no_match_returns_empty_list(self):
        prose = "Nothing here.\n\nOr here."
        assert paragraph_indices_for_word(prose, "moment") == []

    def test_multi_word_phrase_matched_literally(self):
        prose = "In that moment he knew.\n\nHe walked on."
        assert paragraph_indices_for_word(prose, "in that moment") == [0]

    def test_empty_word_returns_empty_list(self):
        prose = "Anything."
        assert paragraph_indices_for_word(prose, "") == []
