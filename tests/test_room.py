"""The room: revise, polish, review, rename, status, check."""

from __future__ import annotations

import pytest

from src.studio import prompts, room
from src.studio.llm import READER_ROLE, WRITER_ROLE
from src.studio.project import StudioError
from tests.fakes import FakeRouter


async def test_revise_keeps_history_and_records_source(book):
    plan = book.read_plan()
    book.write_chapter(1, "# Chapter 1\n\nONE", plan, "build")
    router = FakeRouter({WRITER_ROLE: ["# Chapter 1\n\nONE, funnier"]})
    await room.revise_chapter(book, router, 1, "make it funnier")
    assert router.roles() == [WRITER_ROLE]
    assert "make it funnier" in router.user_message(0)
    assert book.chapter_path(1).read_text(encoding="utf-8") == "# Chapter 1\n\nONE, funnier\n"
    assert len(list(book.history_dir.iterdir())) == 1
    assert book._provenance()["1"]["source"] == "revise"


async def test_revise_needs_a_chapter_and_a_note(book):
    with pytest.raises(StudioError, match="hasn't been written"):
        await room.revise_chapter(book, FakeRouter(), 1, "note")
    book.write_chapter(1, "text", book.read_plan(), "build")
    with pytest.raises(StudioError, match="Say what you'd like changed"):
        await room.revise_chapter(book, FakeRouter(), 1, "  ")


async def test_empty_reply_saves_nothing(book):
    book.write_chapter(1, "original", book.read_plan(), "build")
    with pytest.raises(StudioError, match="empty response"):
        await room.revise_chapter(book, FakeRouter({WRITER_ROLE: ["   "]}), 1, "note")
    assert book.chapter_path(1).read_text(encoding="utf-8") == "original\n"


async def test_polish_is_a_revision_with_the_standard_note(book):
    book.write_chapter(1, "text", book.read_plan(), "build")
    router = FakeRouter()
    await room.polish_chapter(book, router, 1)
    assert prompts.POLISH_NOTE in router.user_message(0)
    assert book._provenance()["1"]["source"] == "polish"


async def test_review_reads_everything_and_writes_notes(book):
    book.write_chapter(1, "# Chapter 1\n\nONE", book.read_plan(), "build")
    router = FakeRouter({READER_ROLE: ["### 1. Stakes\n\n**Your call:**"]})
    path = await room.review(book, router)
    assert router.roles() == [READER_ROLE]
    assert "Second Opinion" in router.system_message(0)
    user = router.user_message(0)
    assert "lighthouse keeper's niece" in user and "Nineteen years to ask." in user and "ONE" in user
    assert path.parent == book.notes_dir and path.name.startswith("review_")
    assert book.latest_review() == path
    assert not book.plan_changed_since_review()


@pytest.fixture
def series_with_mara(library):
    first, _ = library.new_book("Book One", series_title="Cycle")
    second, _ = library.new_book("Book Two", series_title="Cycle")
    second.series.characters_path.write_text("## Mara\n", encoding="utf-8")
    first.characters_path.write_text("## Mara\n- Mara's boat.\n", encoding="utf-8")
    first.outline_path.write_text("## Chapter 1\n- Mara sails.\n", encoding="utf-8")
    first.write_chapter(1, "Mara ran the Marathon. Mara's hands shook.", first.read_plan(), "build")
    first.notes_dir.joinpath("review_1.md").write_text("Mara", encoding="utf-8")
    return first, second


def test_rename_preview_changes_nothing(series_with_mara):
    first, second = series_with_mara
    before = first.chapter_path(1).read_text(encoding="utf-8")
    hits = room.find_name(second, "Mara")
    assert {h.path.name for h in hits} == {"characters.md", "outline.md", "chapter_01.md"}
    assert sum(h.count for h in hits) == 6
    assert first.chapter_path(1).read_text(encoding="utf-8") == before


def test_rename_apply_is_whole_word_and_keeps_chapters_current(series_with_mara):
    first, second = series_with_mara
    assert first.chapter_state(1, first.read_plan()) == "current"
    room.apply_rename(second, "Mara", "Maren")
    chapter = first.chapter_path(1).read_text(encoding="utf-8")
    assert chapter == "Maren ran the Marathon. Maren's hands shook.\n"
    assert "Maren" in second.series.characters_path.read_text(encoding="utf-8")
    assert first.notes_dir.joinpath("review_1.md").read_text(encoding="utf-8") == "Mara"
    assert first.chapter_state(1, first.read_plan()) == "current"


def test_status_reports_chapters_and_stale_ones(book):
    plan = book.read_plan()
    book.write_chapter(1, "# Chapter 1\n\nfour words of prose", plan, "build")
    book.outline_path.write_text(book.outline_path.read_text().replace("dark", "lit"), encoding="utf-8")
    report = room.status(book)
    states = {row.number: row.state for row in report.chapters}
    assert states == {1: "outline changed", 2: "missing", 3: "missing"}
    assert report.total_words == 4
    assert report.latest_review is None and report.plan_changed_since_review


async def test_check_passes_the_router_answer_through():
    router = FakeRouter()
    router.health = (False, "Invalid API key (401 Unauthorized)")
    assert await room.check(router) == (False, "Invalid API key (401 Unauthorized)")
