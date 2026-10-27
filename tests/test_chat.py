"""The app's room chat: tools, file safety, undo, history and review calls."""

import pytest

from src.studio import chat, jobs, press
from src.studio.project import StudioError
from tests.fakes import FakeRouter

SETTINGS = press.PressSettings()


def outline_path(book):
    return f"books/{book.root.name}/outline.md"


async def test_turn_sends_current_files_and_applies_an_edit(book):
    rel = outline_path(book)
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {
            "path": rel, "old_text": "- She finds the boat.",
            "new_text": "- She finds the boat. The rope was cut.", "summary": "The rope was cut",
        })]},
        "Done. Should Mara notice straight away?",
    ]})
    result = await chat.run_turn(book.series, book, router, [], "Make it deliberate.", SETTINGS)

    assert "The rope was cut." in book.outline_path.read_text(encoding="utf-8")
    assert result.reply == "Done. Should Mara notice straight away?"
    [item] = result.items
    assert item["kind"] == "activity" and item["file"] == rel and item["text"] == "The rope was cut"
    first = router.calls[0][1]
    assert "Story Session" in first[0]["content"] and "Loose Craft Guide" in first[0]["content"]
    assert "lighthouse keeper's niece" in first[-1]["content"]
    assert first[-1]["content"].endswith("Make it deliberate.")
    # The tool result went back to the model before its final answer.
    assert router.calls[1][1][-1] == {
        "role": "tool", "tool_call_id": "call0", "content": f"Saved {rel}.", "is_error": False
    }


async def test_history_is_plain_text_and_files_only_in_the_newest_message(book):
    router = FakeRouter({"studio_chat": ["First answer.", "Second answer."]})
    first = await chat.run_turn(book.series, book, router, [], "One", SETTINGS)
    history = chat.history_entries("One", [], first)
    assert history == [{"role": "user", "content": "One"}, {"role": "assistant", "content": "First answer."}]
    await chat.run_turn(book.series, book, router, history, "Two", SETTINGS)
    sent = router.calls[1][1]
    assert sent[1:3] == history
    assert "# The project's files right now" in sent[3]["content"]


async def test_tool_errors_go_back_to_the_model_and_nothing_outside_is_touched(book, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text("keep", encoding="utf-8")
    chapter = f"books/{book.root.name}/manuscript/chapter_01.md"
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [
            ("write_file", {"path": "../../secret.md", "content": "x", "summary": ""}),
            ("write_file", {"path": chapter, "content": "x", "summary": ""}),
            ("edit_file", {"path": outline_path(book), "old_text": "Chapter", "new_text": "x", "summary": ""}),
        ]},
        "Sorry about that.",
    ]})
    result = await chat.run_turn(book.series, book, router, [], "Try things", SETTINGS)
    tool_results = [m for m in router.calls[1][1] if m["role"] == "tool"]
    assert all(m["is_error"] for m in tool_results)
    assert "outside this project" in tool_results[0]["content"]
    assert "revise_chapter" in tool_results[1]["content"]
    assert "exactly once" in tool_results[2]["content"]
    assert outside.read_text(encoding="utf-8") == "keep"
    assert not book.chapter_path(1).exists()
    assert result.items == []


async def test_undo_and_redo_and_refuse_after_a_manual_edit(book):
    rel = outline_path(book)
    before = book.outline_path.read_text(encoding="utf-8")
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {"path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone", "summary": "Title"})]},
        "Done.",
    ]})
    [item] = (await chat.run_turn(book.series, book, router, [], "Name it", SETTINGS)).items
    undone = chat.undo(book.series, item)
    assert undone["undone"] and book.outline_path.read_text(encoding="utf-8") == before
    redone = chat.undo(book.series, undone)
    assert not redone["undone"] and "Chapter 2: Gone" in book.outline_path.read_text(encoding="utf-8")
    book.outline_path.write_text("The writer's own edit.\n", encoding="utf-8")
    with pytest.raises(StudioError, match="changed since"):
        chat.undo(book.series, redone)
    assert book.outline_path.read_text(encoding="utf-8") == "The writer's own edit.\n"


async def test_add_book_switches_to_it_and_carries_the_cast(book):
    router = FakeRouter({"studio_chat": [{"tool_calls": [("add_book", {"title": "Low Tide"})]}, "Book 2 is ready."]})
    result = await chat.run_turn(book.series, book, router, [], "A sequel!", SETTINGS)
    assert result.book.number == 2 and result.book.title == "Low Tide"
    assert "Nineteen years to ask." in result.book.characters_path.read_text(encoding="utf-8")
    assert book.series.bible_path.exists()


async def test_propose_build_makes_a_card_and_builds_nothing(book):
    router = FakeRouter({"studio_chat": [{"tool_calls": [("propose_build", {"which": "next"})]}, "Ready when you are."]})
    result = await chat.run_turn(book.series, book, router, [], "Build it", SETTINGS)
    [card] = result.items
    assert card["kind"] == "approval" and card["numbers"] == [1] and card["status"] == "pending"
    assert "model call" in card["detail"]
    assert not book.chapter_path(1).exists()
    assert router.roles() == ["studio_chat", "studio_chat"]


async def test_review_points_and_recording_a_call(book, tmp_path):
    path = tmp_path / "review.md"
    path.write_text(
        "1. **Overall.** Fine.\n\n## Points to consider\n\n"
        "### 1. Tobias has no motive\n\n**What I noticed:** blank.\n\n**Your call:**\n\n"
        "### 2. Chapters 4 and 5 end alike\n\n**What I noticed:** same.\n\n**Your call:**\n\n"
        "## One question for the author\n\nWhy now?\n",
        encoding="utf-8",
    )
    points = chat.review_points(path.read_text(encoding="utf-8"))
    assert [p["title"] for p in points] == ["Tobias has no motive", "Chapters 4 and 5 end alike"]
    assert "Why now" not in points[1]["body"]
    chat.record_call(path, 2, "Agreed.")
    text = path.read_text(encoding="utf-8")
    assert "**Your call:** Agreed." in text and text.count("**Your call:**\n") == 1
    assert [p["call"] for p in chat.review_points(text)] == ["", "Agreed."]


def test_reference_files_reach_every_prompt(book):
    (book.series.reference_dir).mkdir()
    (book.series.reference_dir / "canon.md").write_text("The ferry runs Tuesdays.", encoding="utf-8")
    (book.series.reference_dir / "map.png").write_bytes(b"\x89PNG")
    plan = book.read_plan()
    assert plan.reference == (("canon.md", "The ferry runs Tuesdays."),)
    assert "reference/canon.md" in plan.files()
    from src.studio import prompts

    messages = prompts.draft_messages(plan, plan.chapter(1), {}, words=1000)
    assert "# Reference: canon.md\n\nThe ferry runs Tuesdays." in messages[1]["content"]


def test_background_build_reports_progress_and_stops_after_the_chapter(book):
    router = FakeRouter({"studio_critic": ["No changes needed"] * 3})
    job = jobs.start_build(book, lambda: router, [1, 2, 3], press.PressSettings())
    job.stop()
    job.join(10)
    snap = job.snapshot()
    assert snap["state"] in ("stopped", "finished")
    assert len(snap["results"]) < 3 or snap["state"] == "finished"
    assert all(book.chapter_path(r["number"]).exists() for r in snap["results"])


def test_only_one_build_per_book(book):
    gate = __import__("threading").Event()

    class Slow(FakeRouter):
        async def complete(self, role, messages):
            import asyncio

            while not gate.is_set():
                await asyncio.sleep(0.01)
            return await super().complete(role, messages)

    router = Slow({"studio_critic": ["No changes needed"]})
    job = jobs.start_build(book, lambda: router, [1], press.PressSettings())
    with pytest.raises(StudioError, match="already building"):
        jobs.start_build(book, lambda: router, [1], press.PressSettings())
    gate.set()
    job.join(10)
    assert job.snapshot()["state"] == "finished"


async def test_exploring_cannot_write_even_if_model_requests_it(book):
    before = book.outline_path.read_text(encoding="utf-8")
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("write_file", {"path": outline_path(book), "content": "changed", "summary": "Oops"})]},
        "Here are some ideas instead.",
    ]})
    result = await chat.run_turn(book.series, book, router, [], "What if?", SETTINGS, explore=True)
    assert book.outline_path.read_text(encoding="utf-8") == before
    assert result.items == []
    assert "exploring only" in router.calls[1][1][-1]["content"]


async def test_selected_chapter_edit_preserves_surrounding_text_and_history(book):
    original = "# Chapter 1\n\nBefore.\n\nThe light went out.\n\nAfter.\n"
    book.write_chapter(1, original, book.read_plan(), "manual")
    path = f"books/{book.root.name}/manuscript/chapter_01.md"
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_passage", {"old_text": "The light went out.", "new_text": "Mara killed the light.", "summary": "Made Mara act"})]},
        "Changed the passage.",
    ]})
    result = await chat.run_turn(book.series, book, router, [], "Make her act", SETTINGS,
                                 selection={"path": path, "version": chat.version(original)})
    assert book.chapter_path(1).read_text(encoding="utf-8") == original.replace("The light went out.", "Mara killed the light.")
    assert any(p.read_text(encoding="utf-8") == original for p in book.history_dir.glob("*.md"))
    assert result.items[0]["before"] == original


async def test_whole_file_replacement_refuses_a_new_manual_edit(book):
    def change_while_thinking(messages):
        book.bible_path.write_text("# The author's new direction\n", encoding="utf-8")
        return {"tool_calls": [("write_file", {"path": f"books/{book.root.name}/story_bible.md", "content": "Old idea", "summary": "Replace"})]}

    router = FakeRouter({"studio_chat": [change_while_thinking, "I'll read it again."]})
    await chat.run_turn(book.series, book, router, [], "Update it", SETTINGS)
    assert book.bible_path.read_text(encoding="utf-8") == "# The author's new direction\n"
    assert "Read" in router.calls[1][1][-1]["content"]


async def test_size_is_checked_every_step_and_too_long_is_explained(book, monkeypatch):
    rel = outline_path(book)
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {"path": rel, "old_text": "- She finds the boat.",
                                       "new_text": "- She finds the rope.", "summary": "Rope"})]},
        "Done.",
    ]})
    # Pretend the tool result pushed the conversation over the limit.
    monkeypatch.setattr(chat, "estimate_tokens", lambda text: 10**9 if f"Saved {rel}." in text else 0)
    with pytest.raises(StudioError, match="Start a new chat"):
        await chat.run_turn(book.series, book, router, [], "Change it.", SETTINGS)
    assert "She finds the rope." in book.outline_path.read_text(encoding="utf-8")  # completed edits stay

    def refuse(messages):
        raise RuntimeError("This model's maximum context length is 1000000 tokens")

    with pytest.raises(StudioError, match="story-so-far"):
        await chat.run_turn(book.series, book, FakeRouter({"studio_chat": [refuse]}), [], "Hi.", SETTINGS)


async def test_the_chat_model_gives_reviews_and_ideas_itself(book):
    # In the app, the selected chat model does reviews and ideas in the
    # conversation; no other model is called and no tool hands them off.
    assert not {"review", "ideas"} & {t["name"] for t in chat.TOOLS}
    assert "give the second opinion or the ideas yourself" in chat.system_prompt()
    router = FakeRouter({"studio_chat": ["### 1. The middle is thin\n\nTwo options: …"]})
    result = await chat.run_turn(book.series, book, router, [], "I'm stuck.", SETTINGS)
    assert router.roles() == ["studio_chat"] and result.reply.startswith("### 1.")
