"""The press: chapter selection, estimates, the build loop and its guards."""

from __future__ import annotations

import dataclasses

import pytest

from src.studio import press
from src.studio.llm import CRITIC_ROLE, READER_ROLE, WRITER_ROLE
from src.studio.project import StudioError
from tests.fakes import FakeRouter

SETTINGS = press.PressSettings(revision_rounds=1, default_chapter_words=3000)
LONG = "# Chapter\n\n" + "word " * 200
LONGER = "# Chapter\n\n" + "word " * 220


def test_select_chapters(book):
    plan = book.read_plan()
    assert press.select_chapters(book, plan, "next") == [1]
    assert press.select_chapters(book, plan, "all") == [1, 2, 3]
    book.write_chapter(1, "x", plan, "build")
    assert press.select_chapters(book, plan, "next") == [2]
    assert press.select_chapters(book, plan, "all") == [2, 3]
    assert press.select_chapters(book, plan, "1") == [1]
    with pytest.raises(StudioError, match="no '## Chapter 7'"):
        press.select_chapters(book, plan, "7")
    with pytest.raises(StudioError, match="isn't 'next', 'all'"):
        press.select_chapters(book, plan, "soon")


def test_settings_from_config_and_lengths(book):
    settings = press.PressSettings.from_config(
        {"press": {"revision_rounds": 2, "length_calibration": 1.5, "default_chapter_words": 2000}}
    )
    chapters = book.read_plan().chapters()
    assert settings.revision_rounds == 2
    assert settings.target_words(chapters[1]) == 2500
    assert settings.asked_words(chapters[1]) == 3750
    assert settings.asked_words(chapters[2]) == 3000
    assert press.PressSettings.from_config({}) == press.PressSettings()


def test_estimate_counts_calls_and_grows_with_chapters(book):
    plan = book.read_plan()
    one = press.estimate(book, plan, [1], SETTINGS)
    three = press.estimate(book, plan, [1, 2, 3], SETTINGS)
    assert one.calls == 3 and three.calls == 9
    assert three.input_tokens > 3 * one.input_tokens
    no_rounds = press.estimate(book, plan, [1], dataclasses.replace(SETTINGS, revision_rounds=0))
    assert no_rounds.calls == 1


async def test_build_drafts_critiques_revises_and_records_everything(book):
    router = FakeRouter({
        WRITER_ROLE: [LONG, LONGER],
        CRITIC_ROLE: ["1. The storm needs playing out."],
    })
    result = await press.build(book, router, [1], SETTINGS)
    assert router.roles() == [WRITER_ROLE, CRITIC_ROLE, WRITER_ROLE]
    assert "The storm needs playing out." in router.user_message(2)
    assert book.chapter_path(1).read_text(encoding="utf-8").strip() == LONGER.strip()
    assert book._provenance()["1"]["source"] == "build"

    folder = result.run_dir / "chapter_01"
    assert {p.name for p in folder.iterdir()} == {"draft.md", "critique_1.md", "revision_1.md"}
    assert (result.run_dir / "plan" / "outline.md").read_text(encoding="utf-8") == book.read_plan().outline
    [chapter] = result.chapters
    assert chapter.revisions_kept == 1 and chapter.draft_words == 200 and chapter.final_words == 220
    assert result.usage.calls == 3 and result.usage.cost == pytest.approx(0.003)
    report = result.report_path.read_text(encoding="utf-8")
    assert "| 1: The Storm | 2,500 | 200 | 220 | 1 |" in report


async def test_no_changes_needed_skips_the_revision(book):
    router = FakeRouter({WRITER_ROLE: [LONG], CRITIC_ROLE: ["**No changes needed.** It works."]})
    result = await press.build(book, router, [1], SETTINGS)
    assert router.roles() == [WRITER_ROLE, CRITIC_ROLE]
    assert result.chapters[0].revisions_kept == 0
    assert "asked for no changes" in result.chapters[0].notes[0]


async def test_a_gutted_revision_is_discarded(book):
    router = FakeRouter({WRITER_ROLE: [LONG, "# Chapter\n\nshort"], CRITIC_ROLE: ["1. Cut."]})
    result = await press.build(book, router, [1], SETTINGS)
    assert book.chapter_path(1).read_text(encoding="utf-8").strip() == LONG.strip()
    assert "discarded" in result.chapters[0].notes[0]


async def test_rounds_control_the_number_of_calls(book):
    router = FakeRouter({WRITER_ROLE: [LONG] * 5, CRITIC_ROLE: ["1. More."] * 2})
    await press.build(book, router, [1], dataclasses.replace(SETTINGS, revision_rounds=2))
    assert router.roles() == [WRITER_ROLE, CRITIC_ROLE, WRITER_ROLE, CRITIC_ROLE, WRITER_ROLE]
    router = FakeRouter({WRITER_ROLE: [LONG]})
    await press.build(book, router, [2], dataclasses.replace(SETTINGS, revision_rounds=0))
    assert router.roles() == [WRITER_ROLE]


async def test_chapters_build_in_order_on_a_frozen_plan(book):
    router = FakeRouter(
        {WRITER_ROLE: ["# Chapter 1\n\nFIRST " + "w " * 300, "# Chapter 2\n\nSECOND " + "w " * 300]}
    )

    def edit_outline_after_first(result):
        if result.number == 1:
            book.outline_path.write_text(
                book.outline_path.read_text().replace("The keeper is missing.", "CHANGED MID-RUN"),
                encoding="utf-8",
            )

    result = await press.build(
        book, router, [1, 2], dataclasses.replace(SETTINGS, revision_rounds=0),
        on_done=edit_outline_after_first,
    )
    second_prompt = router.user_message(1)
    assert "FIRST" in second_prompt
    assert "The keeper is missing." in second_prompt and "CHANGED MID-RUN" not in second_prompt
    assert result.outline_changed == [2]


async def test_short_chapters_get_a_length_note(book):
    router = FakeRouter({WRITER_ROLE: [LONG]})
    result = await press.build(book, router, [1], dataclasses.replace(SETTINGS, revision_rounds=0))
    assert "Came in at 200 of the planned 2,500 words" in result.chapters[0].notes[0]


async def test_empty_draft_saves_no_chapter(book):
    with pytest.raises(StudioError, match="empty response"):
        await press.build(book, FakeRouter({WRITER_ROLE: [""]}), [1], SETTINGS)
    assert not book.chapter_path(1).exists()


async def test_story_so_far_is_written_archived_and_used_by_later_books(library):
    first, _ = library.new_book("Book One", series_title="Cycle")
    with pytest.raises(StudioError, match="no chapters yet"):
        await press.story_so_far(first, FakeRouter())
    first.write_chapter(1, "# Chapter 1\n\nFULL", first.read_plan(), "build")
    router = FakeRouter({READER_ROLE: ["SUMMARY ONE", "SUMMARY TWO"]})
    await press.story_so_far(first, router)
    await press.story_so_far(first, router)
    assert first.story_so_far_path.read_text(encoding="utf-8") == "SUMMARY TWO\n"
    assert any(p.name.startswith("story_so_far.") for p in first.history_dir.iterdir())
    second, _ = library.new_book("Book Two", series_title="Cycle")
    assert second.read_plan().earlier_books[0].text == "SUMMARY TWO\n"


def test_export_stitches_chapters_in_order(book):
    with pytest.raises(StudioError, match="no chapters"):
        press.export_book(book)
    plan = book.read_plan()
    book.write_chapter(2, "# Chapter 2\n\nTWO", plan, "build")
    book.write_chapter(1, "# Chapter 1\n\nONE", plan, "build")
    text = press.export_book(book).read_text(encoding="utf-8")
    assert text.startswith("# The Dark Lighthouse") and text.index("ONE") < text.index("TWO")
