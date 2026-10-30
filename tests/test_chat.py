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


async def test_ask_mode_stages_an_edit_without_saving(book):
    rel = outline_path(book)
    before = book.outline_path.read_text(encoding="utf-8")
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {
            "path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone",
            "summary": "Named chapter 2",
        })]},
        "Staged it; choose whether to use it.",
    ]})
    result = await chat.run_turn(book.series, book, router, [], "Name it", SETTINGS, edit_mode="ask")
    [proposal] = result.items
    assert proposal["kind"] == "proposal" and proposal["status"] == "pending"
    assert proposal["before"] == before and "## Chapter 2: Gone" in proposal["after"]
    assert book.outline_path.read_text(encoding="utf-8") == before
    assert "Staged" in router.calls[1][1][-1]["content"]


async def test_ask_mode_stages_a_chapter_revision_without_saving(book):
    book.write_chapter(1, "# Chapter 1\n\nOriginal.", book.read_plan(), "build")
    router = FakeRouter({
        "studio_chat": [
            {"tool_calls": [("revise_chapter", {"chapter": 1, "note": "make it colder"})]},
            "Staged the revision.",
        ],
        "studio_writer": ["# Chapter 1\n\nColder."],
    })
    result = await chat.run_turn(book.series, book, router, [], "Make it colder", SETTINGS, edit_mode="ask")
    [proposal] = result.items
    assert proposal["kind"] == "proposal" and proposal["verb"] == "Revised"
    assert proposal["after"].startswith("# Chapter 1\n\nColder.")
    assert book.chapter_path(1).read_text(encoding="utf-8") == "# Chapter 1\n\nOriginal.\n"


async def test_ask_mode_stages_a_selected_passage_without_saving(book):
    original = "# Chapter 1\n\nBefore.\n\nThe light went out.\n\nAfter.\n"
    book.write_chapter(1, original, book.read_plan(), "manual")
    path = f"books/{book.root.name}/manuscript/chapter_01.md"
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_passage", {"old_text": "The light went out.",
                                          "new_text": "Mara killed the light.",
                                          "summary": "Made Mara act"})]},
        "Staged the passage.",
    ]})
    result = await chat.run_turn(
        book.series, book, router, [], "Make her act", SETTINGS, edit_mode="ask",
        selection={"path": path, "version": chat.version(original)},
    )
    [proposal] = result.items
    assert proposal["kind"] == "proposal" and proposal["verb"] == "Edited passage"
    assert book.chapter_path(1).read_text(encoding="utf-8") == original
    assert "Mara killed the light." in proposal["after"]


async def test_another_turn_unaffected_by_a_staged_proposal(book):
    rel = outline_path(book)
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {
            "path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone",
            "summary": "Named chapter 2",
        })]},
        "Staged.",
        "The plan still says Chapter 2.",
    ]})
    await chat.run_turn(book.series, book, router, [], "Name it", SETTINGS, edit_mode="ask")
    await chat.run_turn(book.series, book, router, [], "What does it say?", SETTINGS)
    assert "## Chapter 2: Gone" not in book.outline_path.read_text(encoding="utf-8")


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


async def test_tool_events_stream_running_and_done(book):
    rel = outline_path(book)
    events = []
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {
            "path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone",
            "summary": "Named chapter 2",
        })]},
        "Done.",
    ]})
    await chat.run_turn(book.series, book, router, [], "Name it", SETTINGS, on_event=events.append)
    tools = [e for e in events if e["kind"] == "tool" and e["id"] == "call0"]
    assert [t["status"] for t in tools] == ["running", "done"]
    assert tools[0]["name"] == "edit_file" and tools[0]["target"] == rel


async def test_story_so_far_undo_restores_the_previous_notes(book):
    book.write_chapter(1, "# Chapter 1\n\nA chapter.", book.read_plan(), "build")
    book.story_so_far_path.write_text("OLD NOTES\n", encoding="utf-8")
    router = FakeRouter({
        "studio_chat": [{"tool_calls": [("story_so_far", {})]}, "Saved."],
        "studio_notes": ["NEW NOTES"],
    })
    result = await chat.run_turn(book.series, book, router, [], "Write the notes", SETTINGS)
    [item] = result.items
    assert item["before"] == "OLD NOTES\n" and item["after"] == "NEW NOTES\n"
    chat.undo(book.series, item)
    assert book.story_so_far_path.read_text(encoding="utf-8") == "OLD NOTES\n"


async def test_rename_keeps_history_and_can_be_undone(book):
    book.write_chapter(1, "# Chapter 1\n\nMara went out.", book.read_plan(), "build")
    original_chapter = book.chapter_path(1).read_text(encoding="utf-8")
    original_characters = book.characters_path.read_text(encoding="utf-8")
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("rename", {"old": "Mara", "new": "Maren", "apply": True})]},
        "Renamed.",
    ]})
    result = await chat.run_turn(book.series, book, router, [], "Rename Mara", SETTINGS)
    [item] = result.items
    assert item["verb"] == "Renamed" and item["changes"]
    assert "Maren went out." in book.chapter_path(1).read_text(encoding="utf-8")
    assert any("Mara went out." in p.read_text(encoding="utf-8")
               for p in book.history_dir.glob("*.md"))
    undone = chat.undo(book.series, item)
    assert undone["undone"]
    assert book.chapter_path(1).read_text(encoding="utf-8") == original_chapter
    assert book.characters_path.read_text(encoding="utf-8") == original_characters
    assert book.chapter_state(1, book.read_plan()) == "current"


async def test_add_book_switches_to_it_and_carries_the_cast(book):
    router = FakeRouter({"studio_chat": [{"tool_calls": [("add_book", {"title": "Low Tide", "series_title": "The Salt Road"})]}, "Book 2 is ready."]})
    result = await chat.run_turn(book.series, book, router, [], "A sequel!", SETTINGS)
    assert result.book.number == 2 and result.book.title == "Low Tide"
    assert "Nineteen years to ask." in result.book.characters_path.read_text(encoding="utf-8")
    assert book.series.bible_path.read_text(encoding="utf-8").startswith("# The Salt Road")
    assert result.book.series.title == "The Salt Road"


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


async def test_the_chat_model_can_review_itself_or_ask_a_fresh_model(book):
    # The chat can give its own review, but the app also offers a second
    # opinion from the studio_reader model.
    assert "review" in {t["name"] for t in chat.TOOLS}
    assert "a fresh model sees different things" in chat.system_prompt()
    router = FakeRouter({"studio_chat": ["### 1. The middle is thin\n\nTwo options: …"]})
    result = await chat.run_turn(book.series, book, router, [], "I'm stuck.", SETTINGS)
    assert router.roles() == ["studio_chat"] and result.reply.startswith("### 1.")


async def test_the_chat_can_ask_for_a_fresh_eyes_read(book):
    book.write_chapter(1, "# Chapter 1\n\nA line on the page.", book.read_plan(), "build")
    router = FakeRouter({
        "studio_chat": [{"tool_calls": [("fresh_eyes", {"chapter": 1})]}, "Here's the reader's reaction."],
        "studio_reader": ["What held me: the line."],
    })
    result = await chat.run_turn(book.series, book, router, [], "Read it fresh", SETTINGS)
    assert router.roles() == ["studio_chat", "studio_reader", "studio_chat"]
    [item] = result.items
    assert item["verb"] == "Wrote" and "/notes/fresh_eyes_" in item["file"]
    assert "lighthouse keeper's niece" not in router.calls[1][1][1]["content"]


async def test_the_chat_can_ask_a_different_model_for_a_review(book):
    router = FakeRouter({
        "studio_chat": [{"tool_calls": [("review", {})]}, "Here's the second opinion."],
        "studio_reader": ["### 1. The ferry thread stalls\n\n**What I noticed:** "
                          "chapters five and six never mention it.\n\n**Your call:**"],
    })
    result = await chat.run_turn(book.series, book, router, [], "Can I get a second opinion?", SETTINGS)
    assert router.roles() == ["studio_chat", "studio_reader", "studio_chat"]
    [item] = result.items
    assert item["verb"] == "Wrote" and "/notes/review_" in item["file"]
    assert item["text"] == "A second opinion from a different model"
    assert "### 1. The ferry thread stalls" in router.calls[2][1][-1]["content"]


async def test_the_chat_can_ask_a_second_model_for_ideas(book):
    router = FakeRouter({
        "studio_chat": [{"tool_calls": [("ideas", {})]}, "Here's what the other model offered."],
        "studio_reader": ["### 1. A gap\n\n**What's open:** the middle.\n\n**Your call:**"],
    })
    result = await chat.run_turn(book.series, book, router, [], "Give me more options.", SETTINGS)
    assert router.roles() == ["studio_chat", "studio_reader", "studio_chat"]
    [item] = result.items
    assert item["verb"] == "Wrote" and "/notes/ideas_" in item["file"]
    assert "### 1. A gap" in router.calls[2][1][-1]["content"]


async def test_change_records_stay_out_of_the_models_own_replies(book):
    rel = outline_path(book)
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {"path": rel, "old_text": "- She finds the boat.",
                                       "new_text": "- She finds the boat, cut loose.", "summary": "Cut the boat loose"})]},
        "Done.",
    ]})
    result = await chat.run_turn(book.series, book, router, [], "Cut it loose.", SETTINGS)
    history = chat.history_entries("Cut it loose.", [], result)
    assert [h["role"] for h in history] == ["user", "assistant", "user", "assistant"]
    assert history[1]["content"] == "Done." and "[Edited" not in history[1]["content"]
    assert history[2]["content"].startswith("[From the app, not the writer")
    assert f"- Edited {rel}: Cut the boat loose" in history[2]["content"]


async def test_a_reply_that_claims_an_unmade_edit_is_sent_back_to_make_it(book):
    rel = outline_path(book)
    router = FakeRouter({"studio_chat": [
        f"[Edited {rel}: Kept the boat]\n\nFiled: the guard kept his boat.",
        {"tool_calls": [("edit_file", {"path": rel, "old_text": "- She finds the boat.",
                                       "new_text": "- She finds the boat the guard kept.", "summary": "Kept the boat"})]},
        "Filed: the guard kept his boat.",
    ]})
    result = await chat.run_turn(book.series, book, router, [], "Keep that.", SETTINGS)
    assert "the guard kept." in book.outline_path.read_text(encoding="utf-8")
    assert result.reply == "Filed: the guard kept his boat."
    nudge = router.calls[1][1][-1]
    assert nudge["role"] == "user" and "only change through tool calls" in nudge["content"]


async def test_a_prose_claim_of_filing_in_a_turn_that_changed_nothing_is_flagged(book):
    router = FakeRouter({"studio_chat": [
        "Good. Filed the boat-taking on his line.",
        "Good. Filed the boat-taking on his line.",
    ]})
    events = []
    result = await chat.run_turn(book.series, book, router, [], "Keep that.", SETTINGS, on_event=events.append)
    assert "only change through tool calls" in router.calls[1][1][-1]["content"]
    # The writer is told why the reply they were reading is being redone.
    phases = [e["text"] for e in events if e["kind"] == "phase"]
    assert phases == ["Thinking about your story…", "Checking that reply against your files…"]
    assert result.reply.endswith("(Nothing was changed in your files this turn.)")
    # A plain "nothing filed yet" isn't a claim, so it goes through untouched.
    router = FakeRouter({"studio_chat": ["Nothing filed yet: say the word."]})
    result = await chat.run_turn(book.series, book, router, [], "What if?", SETTINGS)
    assert result.reply == "Nothing filed yet: say the word." and len(router.calls) == 1


async def test_a_claimed_edit_that_never_happens_is_removed_and_flagged(book):
    before = book.outline_path.read_text(encoding="utf-8")
    claim = f"[Edited {outline_path(book)}: Kept the boat]\n\nFiled."
    router = FakeRouter({"studio_chat": [claim, claim]})
    result = await chat.run_turn(book.series, book, router, [], "Keep that.", SETTINGS)
    assert book.outline_path.read_text(encoding="utf-8") == before and not result.items
    assert "[Edited" not in result.reply and result.reply.startswith("Filed.")
    assert "Nothing was changed in your files this turn" in result.reply


async def test_web_searches_are_shown_and_kept_for_later_turns(book):
    page = {"title": "Jori Lekauf", "url": "https://starwars.fandom.com/wiki/Jori_Lekauf"}
    router = FakeRouter({"studio_chat": [
        {"content": "He died on Vulpter.", "sources": [page], "web_searches": 2},
        "From memory, worth checking.",
    ]})
    events = []
    result = await chat.run_turn(book.series, book, router, [], "Is Jori alive?", SETTINGS, on_event=events.append)

    [item] = result.items
    assert item["kind"] == "sources" and item["searches"] == 2 and item["sources"] == [page]
    assert any(e["kind"] == "item" and e["item"] is item for e in events)
    assert "2 web searches" in result.usage.describe()
    history = chat.history_entries("Is Jori alive?", [], result)
    assert "Jori Lekauf (https://starwars.fandom.com/wiki/Jori_Lekauf)" in history[2]["content"]

    # A reply that searched nothing leaves no sources and no claim of one.
    quiet = await chat.run_turn(book.series, book, router, history, "And Shevu?", SETTINGS)
    assert quiet.items == [] and "web search" not in quiet.usage.describe()


async def test_an_edit_matches_across_curly_and_straight_quotes(book):
    book.outline_path.write_text("## Chapter 1\n- Sam’s “test” of Holt\n", encoding="utf-8")
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {"path": outline_path(book), "old_text": "Sam's \"test\"", "new_text": "The trial", "summary": ""})]},
        "Done.",
    ]})
    await chat.run_turn(book.series, book, router, [], "Edit it", SETTINGS)
    assert book.outline_path.read_text(encoding="utf-8") == "## Chapter 1\n- The trial of Holt\n"

    book.outline_path.write_text("- Sam’s test\n- Sam's test\n", encoding="utf-8")
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {"path": outline_path(book), "old_text": "Sam“s test", "new_text": "changed", "summary": ""})]},
        "Sorry.",
    ]})
    await chat.run_turn(book.series, book, router, [], "Edit it", SETTINGS)
    assert "changed" not in book.outline_path.read_text(encoding="utf-8")  # no single match, so nothing changes
