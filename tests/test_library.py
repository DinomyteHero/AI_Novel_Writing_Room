"""The library model: series, books, plans, provenance, and prompt assembly."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.studio import prompts
from src.studio.project import Library, StudioError, count_words, slugify
from tests.conftest import OUTLINE


def test_slugify_and_count_words():
    assert slugify("Star Wars (Legends EU)") == "star-wars-legends-eu"
    assert slugify("  The Dark   Lighthouse! ") == "the-dark-lighthouse"
    assert count_words("# Chapter 1: The Storm\n\nRain fell on the glass.") == 5


def test_standalone_book_is_a_series_of_one(library: Library):
    book, written = library.new_book("The Dark Lighthouse")
    assert book.root == library.root / "the-dark-lighthouse" / "books" / "01-the-dark-lighthouse"
    assert sorted(p.name for p in written) == ["characters.md", "outline.md", "story_bible.md"]
    assert not book.series.bible_path.exists()
    assert book.title == "The Dark Lighthouse"
    assert book.label == "The Dark Lighthouse"
    assert book.read_plan().series_bible == ""


def test_adding_a_book_creates_series_bible_and_numbers_it(library: Library):
    first, _ = library.new_book("The Dark Lighthouse")
    first.bible_path.write_text("# The Dark Lighthouse\n\nmine\n", encoding="utf-8")
    second, written = library.new_book("Low Tide", series_title="The Dark Lighthouse")
    assert second.root.name == "02-low-tide"
    assert second.series.root == first.series.root
    assert {p.name for p in written} >= {"series_bible.md", "characters.md"}
    assert first.bible_path.read_text(encoding="utf-8") == "# The Dark Lighthouse\n\nmine\n"
    assert second.label == "The Dark Lighthouse, book 2: Low Tide"


def test_a_new_book_carries_the_cast_forward(library: Library):
    first, _ = library.new_book("Book One", series_title="Cycle")
    sheets = "## Mara\n- **How they talk:** dry, quick.\n"
    first.characters_path.write_text("# Characters: Book One\n\n" + sheets, encoding="utf-8")
    second, _ = library.new_book("Book Two", series_title="Cycle")
    assert second.characters_path.read_text(encoding="utf-8") == "# Characters: Book Two\n\n" + sheets
    assert first.characters_path.read_text(encoding="utf-8") == "# Characters: Book One\n\n" + sheets
    assert not (second.series.root / "characters.md").exists()
    assert second.series.plan_files() == [second.series.bible_path]


def test_new_series_starts_with_series_files(library: Library):
    book, written = library.new_book("Book One", series_title="The Unfinished Cycle")
    assert book.root.name == "01-book-one"
    assert book.series.bible_path.read_text(encoding="utf-8").startswith("# The Unfinished Cycle")
    assert book.series.title == "The Unfinished Cycle"


def test_duplicate_titles_are_refused(library: Library):
    library.new_book("The Dark Lighthouse")
    with pytest.raises(StudioError, match="already a book or series"):
        library.new_book("The Dark Lighthouse")
    with pytest.raises(StudioError, match="already has a book"):
        library.new_book("The Dark Lighthouse", series_title="The Dark Lighthouse")


def test_find_book(library: Library):
    with pytest.raises(StudioError, match="library is empty"):
        library.find_book()
    only, _ = library.new_book("The Dark Lighthouse")
    assert library.find_book().root == only.root
    library.new_book("Low Tide", series_title="Sea Stories")
    with pytest.raises(StudioError, match="Which book"):
        library.find_book()
    assert library.find_book("low tide").slug == "low-tide"
    with pytest.raises(StudioError, match="No book called 'Nope'"):
        library.find_book("Nope")


def test_outline_parsing_is_loose(book):
    chapters = book.read_plan().chapters()
    assert sorted(chapters) == [1, 2, 3]
    assert chapters[1].title == "The Storm"
    assert chapters[1].words == 2500
    assert chapters[2].title == "" and chapters[2].words is None
    assert chapters[3].title == "Low Tide" and chapters[3].words == 1800
    assert "Intro text" not in chapters[1].notes


def test_earlier_books_use_story_so_far_when_present(library: Library):
    first, _ = library.new_book("Book One", series_title="Cycle")
    plan = first.read_plan()
    first.write_chapter(1, "# Chapter 1\n\nFULL TEXT", plan, "build")
    second, _ = library.new_book("Book Two", series_title="Cycle")
    [earlier] = second.read_plan().earlier_books
    assert earlier.text.endswith("FULL TEXT") and not earlier.is_summary
    first.story_so_far_path.write_text("SUMMARY", encoding="utf-8")
    [earlier] = second.read_plan().earlier_books
    assert earlier.text == "SUMMARY" and earlier.is_summary
    assert first.read_plan().earlier_books == ()


def test_write_chapter_keeps_history_and_records_provenance(book):
    plan = book.read_plan()
    book.write_chapter(1, "first", plan, "build")
    book.write_chapter(1, "second", plan, "revise")
    assert book.chapter_path(1).read_text(encoding="utf-8") == "second\n"
    assert [p.read_text(encoding="utf-8") for p in book.history_dir.iterdir()] == ["first\n"]
    assert book._provenance()["1"]["source"] == "revise"


def test_chapter_state_tracks_what_changed(book):
    plan = book.read_plan()
    assert book.chapter_state(1, plan) == "missing"
    book.write_chapter(1, "text", plan, "build")
    book.write_chapter(2, "text", plan, "build")
    assert book.chapter_state(1, plan) == "current"

    book.outline_path.write_text(OUTLINE.replace("finds the lighthouse dark", "finds it lit"), encoding="utf-8")
    plan = book.read_plan()
    assert book.chapter_state(1, plan) == "outline changed"
    assert book.chapter_state(2, plan) == "current"

    book.bible_path.write_text("# The Dark Lighthouse\n\nNew premise.\n", encoding="utf-8")
    plan = book.read_plan()
    assert book.chapter_state(2, plan) == "plan changed"


def test_hand_written_and_orphaned_chapters(book):
    book.manuscript_dir.mkdir(parents=True, exist_ok=True)
    book.chapter_path(2).write_text("by hand", encoding="utf-8")
    book.chapter_path(9).write_text("orphan", encoding="utf-8")
    plan = book.read_plan()
    assert book.chapter_state(2, plan) == "current"
    assert book.chapter_state(9, plan) == "not in outline"


def test_plan_changed_since_review(book):
    assert book.plan_changed_since_review()
    review = book.notes_dir / "review_20260101-000000.md"
    review.write_text("notes", encoding="utf-8")
    old = review.stat().st_mtime - 100
    for path in book.plan_files():
        os.utime(path, (old, old))
    assert not book.plan_changed_since_review()
    os.utime(book.outline_path, None)
    assert book.plan_changed_since_review()


def test_prompt_order_puts_series_first_and_task_last(library: Library):
    first, _ = library.new_book("Book One", series_title="Cycle")
    first.write_chapter(1, "# Chapter 1\n\nBOOK ONE TEXT", first.read_plan(), "build")
    book, _ = library.new_book("Book Two", series_title="Cycle")
    book.outline_path.write_text("## Chapter 1: Return\n- Home again.\n", encoding="utf-8")
    plan = book.read_plan()
    messages = prompts.draft_messages(plan, plan.chapter(1), {}, words=3000, note="rainy")
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Co-Writer" in system and "Loose Craft Guide" in system
    order = [
        "# Series bible", "# Earlier book 1: Book One (full text)",
        "BOOK ONE TEXT", "# Story bible", "# Characters", "# Outline", "# The book so far", "# Task",
    ]
    positions = [user.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert "roughly 3,000 words" in user and "rainy" in user


def test_draft_and_critique_only_see_earlier_chapters(book):
    plan = book.read_plan()
    chapters = {1: "# Chapter 1\n\nONE", 3: "# Chapter 3\n\nTHREE"}
    draft = prompts.draft_messages(plan, plan.chapter(2), chapters, words=1000)[1]["content"]
    assert "ONE" in draft and "THREE" not in draft
    critique = prompts.critique_messages(plan, plan.chapter(2), chapters, "DRAFT", 1000)
    assert "Critic" in critique[0]["content"]
    text = critique[1]["content"]
    assert "DRAFT" in text and "THREE" not in text and "1,000 words" in text


def test_revise_sees_the_rest_of_the_book(book):
    plan = book.read_plan()
    chapters = {1: "ONE", 2: "TWO", 3: "THREE"}
    user = prompts.revise_messages(plan, chapters, 2, "TWO", "funnier")[1]["content"]
    rest, target = user.split("# Chapter 2 (the chapter to revise)")
    assert "ONE" in rest and "THREE" in rest and "TWO" not in rest
    assert "TWO" in target and "funnier" in target


def test_review_prompt_handles_a_plan_without_chapters(book):
    messages = prompts.review_messages(book.read_plan(), {})
    assert "**Your call:**" in messages[0]["content"]
    assert "No chapters have been drafted yet" in messages[1]["content"]


def test_default_settings_have_no_output_caps():
    import yaml

    config = yaml.safe_load((Path(__file__).parents[1] / "config" / "settings.yaml").read_text())
    for role in ("studio_chat", "studio_writer", "studio_critic", "studio_reader", "studio_notes"):
        assert "max_tokens" not in config["agent_routing"][role].get("params", {}), role
