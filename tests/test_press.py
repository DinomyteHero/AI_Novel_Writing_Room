"""The press: chapter selection, estimates, the build loop and its guards."""

from __future__ import annotations

import dataclasses
import os
import time

import httpx
import pytest

from src.model_router import ModelServiceError
from src.studio import press
from src.studio.llm import CRITIC_ROLE, NOTES_ROLE, WRITER_ROLE, provider_error
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


def test_chapters_with_no_notes_are_not_built(book):
    book.outline_path.write_text(
        "# Outline\n\n## Chapter 1\n\n- What happens: Mara finds the light dark.\n\n"
        "## Chapter 2\n\n- What happens:\n- Ends at (optional):\n\n## Chapter 3\n\n-\n\n"
        "## Chapter 4: The Storm\n",
        encoding="utf-8",
    )
    plan = book.read_plan()
    assert [plan.chapter(n).blank for n in (1, 2, 3, 4)] == [False, True, True, False]
    # "all" stops before the first chapter with no notes, since chapters build in order.
    assert press.select_chapters(book, plan, "all") == [1]
    assert press.select_chapters(book, plan, "4") == [4]
    with pytest.raises(StudioError, match="Chapter 2 has no notes"):
        press.select_chapters(book, plan, "2")
    book.write_chapter(1, "x", plan, "build")
    for which in ("next", "all"):
        with pytest.raises(StudioError, match="Chapter 2 has no notes"):
            press.select_chapters(book, plan, which)


def test_a_new_book_has_nothing_to_build_yet(tmp_path):
    from src.studio.project import Library

    book, _ = Library(tmp_path).new_book("Lantern")
    plan = book.read_plan()
    assert all(plan.chapter(n).blank for n in (1, 2))
    with pytest.raises(StudioError, match="Chapter 1 has no notes"):
        press.select_chapters(book, plan, "all")


def test_provider_errors_are_explained_for_writers():
    import httpx

    from src.studio.llm import provider_error

    def status(code, body=None):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        return httpx.HTTPStatusError("x", request=request, response=httpx.Response(code, json=body, request=request))

    assert "turned down your API key (401)" in provider_error(status(401))
    assert "out of credit" in provider_error(status(402))
    assert "doesn't offer the chosen model (404): No such model" in provider_error(
        status(404, {"error": {"message": "No such model"}})
    )
    assert "busy" in provider_error(status(429))
    assert "having trouble (503)" in provider_error(status(503))
    assert "Check your internet connection" in provider_error(httpx.ConnectError("no route"))
    assert provider_error(RuntimeError("boom")) is None


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


async def test_build_snapshots_reference_notes_too(book):
    book.reference_dir.mkdir(parents=True, exist_ok=True)
    (book.reference_dir / "canon.md").write_text("# Canon\n\nJacen is 30.", encoding="utf-8")
    router = FakeRouter({WRITER_ROLE: [LONG], CRITIC_ROLE: ["No changes needed: it works."]})
    result = await press.build(book, router, [1], SETTINGS)
    snapshot = result.run_dir / "plan" / "reference" / "canon.md"
    assert snapshot.read_text(encoding="utf-8") == "# Canon\n\nJacen is 30."
    assert book.chapter_path(1).exists()


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
    router = FakeRouter({NOTES_ROLE: ["SUMMARY ONE", "SUMMARY TWO"]})
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


async def test_a_prompt_too_long_for_the_model_is_explained():
    from src.studio.llm import complete

    def refuse(messages):
        raise RuntimeError("prompt is too long: 1,200,000 tokens > 1,000,000 maximum")

    def fail(messages):
        raise RuntimeError("boom")

    router = FakeRouter({WRITER_ROLE: [refuse, fail]})
    with pytest.raises(StudioError, match="story-so-far"):
        await complete(router, WRITER_ROLE, [{"role": "user", "content": "x"}])
    with pytest.raises(RuntimeError, match="boom"):
        await complete(router, WRITER_ROLE, [{"role": "user", "content": "x"}])


def test_estimate_warns_only_when_one_call_gets_very_long(book):
    estimate = press.estimate(book, book.read_plan(), [1, 2], SETTINGS)
    assert 0 < estimate.largest_call < estimate.input_tokens
    assert "less reliably" not in estimate.describe()
    long = dataclasses.replace(estimate, largest_call=600_000)
    assert "600,000 tokens" in long.describe() and "story-so-far" in long.describe()


def test_usage_reports_what_came_from_cache():
    from src.studio.llm import Usage

    router = FakeRouter()
    router.usage_log += [{"prompt_tokens": 1000, "completion_tokens": 10, "cached_tokens": 800},
                         {"prompt_tokens": 1000, "completion_tokens": 10}]
    usage = Usage.since(router, 0)
    assert usage.cached_tokens == 800
    assert "2,000 tokens in (800 read from cache)" in usage.describe()


async def test_a_declined_draft_is_not_saved_as_a_chapter(book):
    router = FakeRouter({WRITER_ROLE: ["I can't write this chapter as described."]})
    with pytest.raises(StudioError, match="declined or answered something else") as caught:
        await press.build(book, router, [1], SETTINGS)
    assert not book.chapter_path(1).exists()
    assert "draft.md" in str(caught.value)


async def test_an_overlong_draft_cut_towards_its_plan_is_kept(book):
    # Chapter 1 plans 2,500 words. The draft runs far over, and the revision does as the critic asks.
    draft, cut = "# Chapter\n\n" + "word " * 6000, "# Chapter\n\n" + "word " * 2600
    router = FakeRouter({WRITER_ROLE: [draft, cut], CRITIC_ROLE: ["1. Cut the repeats."]})
    result = await press.build(book, router, [1], SETTINGS)
    assert result.chapters[0].revisions_kept == 1 and result.chapters[0].notes == []
    assert book.chapter_path(1).read_text(encoding="utf-8").strip() == cut.strip()


async def test_a_revision_far_below_the_plan_is_still_discarded_and_says_where_the_notes_are(book):
    draft = "# Chapter\n\n" + "word " * 6000
    router = FakeRouter({WRITER_ROLE: [draft, "# Chapter\n\n" + "word " * 1000], CRITIC_ROLE: ["1. Cut."]})
    result = await press.build(book, router, [1], SETTINGS)
    assert result.chapters[0].revisions_kept == 0
    assert "discarded" in result.chapters[0].notes[0] and "critique_1.md" in result.chapters[0].notes[0]
    assert "lower press.length_calibration" in result.chapters[0].notes[1]


class _Drops(FakeRouter):
    """Loses the connection on the nth model call."""

    def __init__(self, responses, drop_on):
        super().__init__(responses)
        self.drop_on, self.made = drop_on, 0

    async def complete(self, role, messages):
        self.made += 1
        if self.made == self.drop_on:
            raise httpx.ReadError("connection reset")
        return await super().complete(role, messages)


async def _fail_on_chapter_2_critique(book):
    router = _Drops({WRITER_ROLE: [LONG, LONGER], CRITIC_ROLE: ["No changes needed"]}, drop_on=4)
    with pytest.raises(httpx.ReadError) as caught:
        await press.build(book, router, [1, 2], SETTINGS)
    return caught.value


async def test_a_failed_build_writes_a_report_and_the_next_one_uses_the_paid_draft(book):
    failure = await _fail_on_chapter_2_critique(book)
    report = failure.report_path.read_text(encoding="utf-8")
    assert "stopped early" in report and "Chapter 2 failed" in report and "dropped" in report
    assert "| 1: The Storm |" in report and "Total: 3 call(s)" in report
    assert book.chapter_path(1).exists() and not book.chapter_path(2).exists()

    router = FakeRouter({CRITIC_ROLE: ["No changes needed"]})
    result = await press.build(book, router, [2], SETTINGS)
    assert router.roles() == [CRITIC_ROLE]
    assert "already paid for" in result.chapters[0].notes[0]
    assert book.chapter_path(2).read_text(encoding="utf-8").strip() == LONGER.strip()

    # Once saved, building the chapter again means a new draft.
    router = FakeRouter({CRITIC_ROLE: ["No changes needed"]})
    await press.build(book, router, [2], SETTINGS)
    assert router.roles()[0] == WRITER_ROLE


async def test_a_paid_draft_is_not_used_once_the_plan_changes(book):
    await _fail_on_chapter_2_critique(book)
    book.characters_path.write_text("## Mara\n- Someone new.\n", encoding="utf-8")
    router = FakeRouter({CRITIC_ROLE: ["No changes needed"]})
    await press.build(book, router, [2], SETTINGS)
    assert router.roles()[0] == WRITER_ROLE


async def test_a_paid_draft_is_not_used_once_an_earlier_chapter_changes(book):
    await _fail_on_chapter_2_critique(book)
    later = time.time() + 60
    os.utime(book.chapter_path(1), (later, later))
    router = FakeRouter({CRITIC_ROLE: ["No changes needed"]})
    await press.build(book, router, [2], SETTINGS)
    assert router.roles()[0] == WRITER_ROLE


async def test_a_declined_draft_is_never_reused(book):
    with pytest.raises(StudioError):
        await press.build(book, FakeRouter({WRITER_ROLE: ["I can't write this chapter as described."]}), [1], SETTINGS)
    router = FakeRouter({WRITER_ROLE: [LONG], CRITIC_ROLE: ["No changes needed"]})
    await press.build(book, router, [1], SETTINGS)
    assert router.roles()[0] == WRITER_ROLE


def test_estimate_allows_for_overrun_and_thinking(book):
    estimate = press.estimate(book, book.read_plan(), [1], SETTINGS)
    # Chapter 1 plans 2,500 words: a draft and a revision, double the words, thinking on top.
    assert estimate.output_tokens > 2500 * press.TOKENS_PER_WORD * 2 * 2 * 2


def test_provider_errors_name_a_dropped_connection_and_pass_on_the_services_words():
    assert "dropped before it finished" in provider_error(httpx.ReadError("reset"))
    assert "took too long" in provider_error(httpx.ReadTimeout("slow"))
    assert provider_error(ModelServiceError("It said why.")) == "It said why."
