"""The app's backend (src/app/api.py) and its local server, with a fake model."""

import base64
import io
import json
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import yaml

from src import model_catalog
from src.app import api as app_api
from src.app.server import make_handler
from src.studio import jobs, press
from src.studio.project import Library, StudioError, locate_library
from tests.fakes import CATALOG, FakeRouter, catalog_model

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config" / "settings.yaml"
    path.parent.mkdir()
    path.write_text((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def make_app(tmp_path, config, router=None, fetch=lambda: CATALOG):
    router = router or FakeRouter()
    return app_api.App(
        Library(tmp_path / "library"), config, tmp_path / ".env", make_router=lambda: router, fetch_catalog=fetch,
    ), router


def write_bible(messages):
    files = messages[-1]["content"]
    path = next(line[2:] for line in files.splitlines() if line.startswith("- books/") and line.endswith("story_bible.md"))
    return {"tool_calls": [("write_file", {
        "path": path, "content": "# The Dark Lighthouse\n\nA keeper's niece keeps the light.", "summary": "Filed your idea",
    })]}


def test_a_staged_change_can_be_used_kept_or_marked_stale(tmp_path, config, book):
    app, router = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    rel = f"books/{book.root.name}/outline.md"
    original = book.outline_path.read_text(encoding="utf-8")

    router.responses["studio_chat"] = [
        {"tool_calls": [("edit_file", {
            "path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone",
            "summary": "Named chapter 2",
        })]},
        "Staged it.",
    ]
    record = app.send(pid, "project", "Name chapter 2", edit_mode="ask")
    proposal = next(i for i in record["items"] if i["kind"] == "proposal")
    assert book.outline_path.read_text(encoding="utf-8") == original
    record = app.decide_proposal(pid, "project", proposal["id"], "accept")
    accepted = next(i for i in record["items"] if i["id"] == proposal["id"])
    assert accepted["kind"] == "activity" and "## Chapter 2: Gone" in book.outline_path.read_text()
    assert any("## Chapter 2" in p.read_text(encoding="utf-8") for p in book.root.glob(".history/*"))
    assert app.undo(pid, "project", proposal["id"])["items"]  # the accepted change is undoable

    router.responses["studio_chat"] = [
        {"tool_calls": [("edit_file", {
            "path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone",
            "summary": "Named chapter 2",
        })]},
        "Staged it again.",
    ]
    record = app.send(pid, "project", "Try again", edit_mode="ask")
    proposal = next(i for i in record["items"] if i["kind"] == "proposal")
    record = app.decide_proposal(pid, "project", proposal["id"], "keep")
    kept = next(i for i in record["items"] if i["id"] == proposal["id"])
    assert kept["status"] == "rejected" and "## Chapter 2: Gone" not in book.outline_path.read_text()

    router.responses["studio_chat"] = [
        {"tool_calls": [("edit_file", {
            "path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone",
            "summary": "Named chapter 2",
        })]},
        "Staged a third time.",
    ]
    record = app.send(pid, "project", "One more", edit_mode="ask")
    proposal = next(i for i in record["items"] if i["kind"] == "proposal" and i["status"] == "pending")
    book.outline_path.write_text("The writer edited this at the same time.\n", encoding="utf-8")
    record = app.decide_proposal(pid, "project", proposal["id"], "accept")
    stale = next(i for i in record["items"] if i["id"] == proposal["id"])
    assert stale["status"] == "stale"
    assert book.outline_path.read_text(encoding="utf-8") == "The writer edited this at the same time.\n"


def test_a_staged_chapter_revision_can_be_accepted(tmp_path, config, book):
    app, router = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    book.write_chapter(1, "# Chapter 1\n\nOriginal.", book.read_plan(), "build")
    router.responses["studio_chat"] = [
        {"tool_calls": [("revise_chapter", {"chapter": 1, "note": "colder"})]},
        "Staged the revision.",
    ]
    router.responses["studio_writer"] = ["# Chapter 1\n\nColder."]
    record = app.send(book.series.root.name, "project", "Make it colder", edit_mode="ask")
    proposal = next(i for i in record["items"] if i["kind"] == "proposal")
    assert book.chapter_path(1).read_text(encoding="utf-8") == "# Chapter 1\n\nOriginal.\n"
    app.decide_proposal(book.series.root.name, "project", proposal["id"], "accept")
    assert book.chapter_path(1).read_text(encoding="utf-8") == "# Chapter 1\n\nColder.\n"
    assert any("Original." in p.read_text(encoding="utf-8") for p in book.history_dir.glob("*.md"))


def test_an_unfinished_run_is_reported_as_interrupted(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    run = book.runs_dir / "20260101-000000"
    (run / "plan").mkdir(parents=True)
    data = app.project(book.series.root.name)
    assert data["interrupted"] == f"books/{book.root.name}/runs/20260101-000000"
    (run / "report.md").write_text("done\n", encoding="utf-8")
    assert app.project(book.series.root.name)["interrupted"] == ""


def test_new_project_runs_the_first_turn_in_the_project_chat(tmp_path, config):
    app, router = make_app(tmp_path, config, FakeRouter({"studio_chat": [write_bible, "What should we call Mara's uncle?"]}))
    result = app.create_project("A lighthouse keeper's niece finds the light dark.")
    pid = result["project"]
    record = result["chat"]
    assert [i["kind"] for i in record["items"]] == ["user", "activity", "assistant"]
    assert app.projects()[0]["title"] == "The Dark Lighthouse"
    assert app.load_chat(pid, "project")["history"][0]["content"].startswith("A lighthouse")
    # Once it has a name, the folders follow, and the chat's links still work.
    assert pid == "the-dark-lighthouse" and record["project"] == pid
    assert record["items"][1]["file"] == "books/01-the-dark-lighthouse/story_bible.md"
    assert app.read_file(pid, record["items"][1]["file"])["text"].startswith("# The Dark Lighthouse")
    # Until then, a second untitled project gets its own folder.
    assert app.create_project("Another idea")["project"] == "untitled-book"
    assert app.create_project("A third idea")["project"] == "untitled-book-2"


def test_new_series_has_a_series_bible_and_book_groups(tmp_path, config):
    app, _ = make_app(tmp_path, config)
    pid = app.create_project("Three winters on an island.", kind="series")["project"]
    data = app.project(pid)
    assert data["isSeries"] and data["groups"][0]["label"] == "Whole series"
    assert [f["label"] for f in data["groups"][1]["files"]] == ["Story bible", "Characters", "Outline"]
    assert [r["scope"] for r in data["reference"]] == ["series", "book"]


def test_a_chat_stays_with_its_book_when_a_series_grows(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    chat = app.new_chat(pid)
    first = app.send(pid, chat["id"], "Plan this book.")
    assert first["book"] == book.root.name

    second, _ = book.series.add_book("The Salt Road")
    record = app.send(pid, chat["id"], "And the sequel?", folder=second.root.name)
    assert record["book"] == book.root.name
    # A new chat opens on the newest book, but the old chat keeps its own.
    assert app.project(pid)["book"]["folder"] == second.root.name


def test_send_undo_and_chat_listing(tmp_path, config, book):
    app, router = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    rel = f"books/{book.root.name}/outline.md"
    router.responses["studio_chat"] = [
        {"tool_calls": [("edit_file", {"path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone", "summary": "Named chapter 2"})]},
        "Named it.",
    ]
    chat = app.new_chat(pid)
    record = app.send(pid, chat["id"], "Call chapter 2 Gone")
    activity = next(i for i in record["items"] if i["kind"] == "activity")
    assert record["turn"]["usage"].startswith("2 call(s)")
    assert "Chapter 2: Gone" in book.outline_path.read_text(encoding="utf-8")
    assert record["title"] == "Call chapter 2 Gone"
    record = app.undo(pid, chat["id"], activity["id"])
    assert "Chapter 2: Gone" not in book.outline_path.read_text(encoding="utf-8")
    assert app.recents()[0]["title"] == "Call chapter 2 Gone"


def test_a_corrupt_chat_is_skipped_not_fatal(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    chats = book.series.root / "chats"
    chats.mkdir()
    (chats / "broken.json").write_text(
        json.dumps({"id": "broken", "title": "Broken", "updated": "2026-01-01"}), encoding="utf-8"
    )
    projects = app.projects()
    assert projects and all(c["id"] != "broken" for p in projects for c in p["chats"])
    assert not any(c["id"] == "broken" for c in app.recents())


def test_build_from_a_card_records_the_result(tmp_path, config, book):
    app, router = make_app(tmp_path, config, FakeRouter({"studio_critic": ["No changes needed"]}))
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    router.responses["studio_chat"] = [{"tool_calls": [("propose_build", {"which": "next"})]}, "Card's up."]
    record = app.send(pid, "project", "Build the first chapter")
    card = next(i for i in record["items"] if i["kind"] == "approval")
    snap = app.build(pid, card["book"], card["which"], "project", card["id"])
    jobs.job_for(book).join(10)
    record = app.load_chat(pid, "project")
    assert next(i for i in record["items"] if i["id"] == card["id"])["status"] == "approved"
    result = record["items"][-1]
    assert result["kind"] == "result" and result["text"].startswith("Finished: chapter(s) 1")
    assert result["report"].startswith(f"books/{book.root.name}/runs/") and result["report"].endswith("report.md")
    assert snap["numbers"] == [1] and book.chapter_path(1).exists()
    assert app.project(pid)["chapters"][0]["state"] == "current"


def test_reference_upload_reads_word_files_and_refuses_images(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as docx:
        docx.writestr("word/document.xml", '<w:document><w:body><w:p><w:r><w:t>The ferry runs Tuesdays.</w:t></w:r></w:p>'
                      '<w:p><w:r><w:t>Storms stop it.</w:t></w:r></w:p></w:body></w:document>')
    data = app.add_reference(pid, "book", None, "canon notes.docx", base64.b64encode(buffer.getvalue()).decode())
    [ref] = data["reference"][0]["files"]
    assert ref["name"] == "canon notes.md"
    assert book.read_plan().reference == (("canon notes.md", "The ferry runs Tuesdays.\n\nStorms stop it.\n"),)
    with pytest.raises(StudioError, match="image"):
        app.add_reference(pid, "book", None, "map.png", base64.b64encode(b"x").decode())


def test_removing_a_reference_keeps_a_history_copy(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    app.add_reference(pid, "book", None, "canon.md", base64.b64encode(b"The ferry runs Tuesdays.").decode())
    ref = book.reference_dir / "canon.md"
    app.remove_reference(pid, f"books/{book.root.name}/reference/canon.md")
    assert not ref.exists()
    copies = list((book.reference_dir / ".history").glob("canon.*.md"))
    assert copies and "The ferry runs Tuesdays." in copies[0].read_text(encoding="utf-8")


def test_writer_edits_keep_the_old_chapter_and_refuse_odd_paths(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    plan = book.read_plan()
    book.write_chapter(1, "Old text.", plan, "build")
    app.save_file(pid, f"books/{book.root.name}/manuscript/chapter_01.md", "New text.")
    assert book.chapter_path(1).read_text(encoding="utf-8") == "New text.\n"
    assert any(p.read_text(encoding="utf-8").startswith("Old text") for p in book.history_dir.iterdir())
    with pytest.raises(StudioError):
        app.save_file(pid, "../../escape.md", "x")
    with pytest.raises(StudioError):
        app.save_file(pid, f"books/{book.root.name}/manuscript/.provenance.json", "{}")


def test_settings_write_keys_and_choices_outside_settings_yaml(tmp_path, config, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    app, _ = make_app(tmp_path, config)
    before = config.read_text(encoding="utf-8")
    settings = app.set_key("cloud", "sk-or-test-1234")
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "OPENROUTER_API_KEY=sk-or-test-1234\n"
    cloud = next(p for p in settings["providers"] if p["key"] == "cloud")
    assert cloud["connected"] and cloud["masked"] == "••••1234"
    writer = next(r for r in settings["roles"] if r["key"] == "studio_writer")
    assert writer["available"] and any(o["label"] == "Claude Opus 5.5" for o in writer["options"])

    app.set_role("studio_writer", "cloud", "claude")
    app.set_press(revision_rounds=2, default_chapter_words=4000)
    overlay = yaml.safe_load((config.parent / "settings.local.yaml").read_text(encoding="utf-8"))
    # Moving the writer drops the old model's own settings (its reasoning effort).
    assert overlay["agent_routing"]["studio_writer"] == {"backend": "cloud", "model": "claude", "params": {}}
    assert app.press_settings().revision_rounds == 2
    assert app.config()["agent_routing"]["studio_critic"]["model"] == "claudesonnet"
    assert config.read_text(encoding="utf-8") == before

    with pytest.raises(StudioError, match="one line"):
        app.set_key("cloud", "sk-or-x\nOTHER=1")
    app.set_key("cloud", "")
    assert "OPENROUTER_API_KEY" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_missing_key_is_explained_before_anything_is_created(tmp_path, config, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    app = app_api.App(Library(tmp_path / "library"), config, tmp_path / ".env")
    with pytest.raises(StudioError, match="Settings"):
        app.create_project("An idea")
    assert not (tmp_path / "library").exists()


def test_server_requires_the_token_and_returns_plain_errors(tmp_path, config):
    app, _ = make_app(tmp_path, config)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, "secret"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, token="secret", body=None):
        request = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"X-Writers-Room-Token": token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert 'window.WR_TOKEN = "secret"' in page
        assert call("/api/state", token="wrong")[0] == 403
        assert call("/api/state")[0] == 200
        status, body = call("/api/projects", body={"idea": ""})
        assert status == 400 and body["error"] == "Type an idea first, even a single line."
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + "/static/../../config/settings.yaml")
        assert error.value.code == 404
        rebound = urllib.request.Request(base + "/", headers={"Host": "evil.example:8765"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(rebound)
        assert error.value.code == 403
    finally:
        server.shutdown()


def test_chat_references_survive_reload_and_message_only_is_temporary(tmp_path, config, book):
    app, router = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    app.send(pid, "project", "Read these", [
        {"name": "canon.md", "text": "The ferry runs Tuesdays.", "scope": "chat"},
        {"name": "temporary.md", "text": "A one-turn experiment.", "scope": "message"},
    ])
    assert "A one-turn experiment." in router.calls[0][1][-1]["content"]
    app2 = app_api.App(app.library, config, tmp_path / ".env", make_router=lambda: router)
    app2.send(pid, "project", "When does the ferry run?")
    sent = router.calls[-1][1][-1]["content"]
    assert "The ferry runs Tuesdays." in sent and "A one-turn experiment." not in sent
    assert not book.read_plan().reference  # Chat attachments don't silently reach the Press.
    attachment = app2.load_chat(pid, "project")["attachments"][0]
    app2.forget_attachment(pid, "project", attachment["path"])
    app2.send(pid, "project", "Continue")
    assert "The ferry runs Tuesdays." not in router.calls[-1][1][-1]["content"]


def test_reference_scopes_and_filename_collisions(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    app.send(pid, "project", "Keep these", [
        {"name": "canon.md", "text": "Book canon.", "scope": "book"},
        {"name": "canon.md", "text": "More canon.", "scope": "book"},
        {"name": "world.md", "text": "Series canon.", "scope": "series"},
    ])
    assert (book.reference_dir / "canon.md").read_text() == "Book canon."
    assert (book.reference_dir / "canon-2.md").read_text() == "More canon."
    next_book, _ = book.series.add_book("Next")
    assert next_book.read_plan().reference == (("world.md", "Series canon."),)


def test_failed_turn_keeps_completed_changes_and_undo(tmp_path, config, book):
    def fail(messages):
        raise RuntimeError("Connection lost")

    rel = f"books/{book.root.name}/outline.md"
    router = FakeRouter({"studio_chat": [
        {"tool_calls": [("edit_file", {"path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone", "summary": "Named chapter"})]}, fail,
    ]})
    app, _ = make_app(tmp_path, config, router)
    app.library = Library(book.series.root.parent)
    events = []
    record = app.send(book.series.root.name, "project", "Name chapter 2", on_event=events.append)
    assert record["turn"]["state"] == "failed"
    activity = next(i for i in record["items"] if i["kind"] == "activity")
    assert any(e["kind"] == "item" for e in events)
    assert "Named chapter" in record["history"][-2]["content"]
    app.undo(book.series.root.name, "project", activity["id"])
    assert "Chapter 2: Gone" not in book.outline_path.read_text()


def test_a_rejected_key_is_named_in_the_chat(tmp_path, config, book):
    import httpx

    def reject(messages):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        raise httpx.HTTPStatusError("401", request=request, response=httpx.Response(401, request=request))

    app, _ = make_app(tmp_path, config, FakeRouter({"studio_chat": [reject]}))
    app.library = Library(book.series.root.parent)
    record = app.send(book.series.root.name, "project", "Hello")
    assert record["turn"]["state"] == "failed"
    assert "turned down your API key (401)" in record["items"][-1]["text"]


def test_stop_cancels_waiting_model_but_keeps_completed_tool(tmp_path, config, book):
    import asyncio

    waiting, cancelled = threading.Event(), threading.Event()
    rel = f"books/{book.root.name}/outline.md"

    class Slow(FakeRouter):
        async def chat(self, *args, **kwargs):
            if self.calls:
                waiting.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return await super().chat(*args, **kwargs)

    router = Slow({"studio_chat": [{"tool_calls": [("edit_file", {
        "path": rel, "old_text": "## Chapter 2", "new_text": "## Chapter 2: Gone", "summary": "Named chapter",
    })]}]})
    app, _ = make_app(tmp_path, config, router)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    worker = threading.Thread(target=lambda: app.send(pid, "project", "Name chapter 2"), daemon=True)
    worker.start()
    try:
        assert waiting.wait(5)
        assert any(i["kind"] == "activity" for i in app.load_chat(pid, "project")["items"])
        with pytest.raises(StudioError, match="already working"):
            app.send(pid, "project", "Another request")
    finally:
        app.stop_turn(pid, "project")
        worker.join(5)
    assert not worker.is_alive() and cancelled.is_set()
    assert app.load_chat(pid, "project")["turn"]["state"] == "stopped"
    assert "Chapter 2: Gone" in book.outline_path.read_text()


def test_restart_recovers_pending_turn_once(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    record = app.load_chat(pid, "project")
    record["items"] = [{"kind": "user", "text": "An idea", "id": "u"},
                       {"kind": "activity", "verb": "Edited", "file": "outline.md", "text": "Saved a decision", "id": "a"}]
    record["turn"] = {"state": "running", "prompt": "An idea", "files": [], "start": 1, "text": "Partial reply"}
    app._save_chat(pid, record)
    recovered = app.load_chat(pid, "project")
    assert recovered["turn"]["state"] == "interrupted"
    assert "Saved a decision" in recovered["history"][-2]["content"]
    assert len(app.load_chat(pid, "project")["history"]) == 4


def test_editor_and_selection_detect_changed_files(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid, path = book.series.root.name, f"books/{book.root.name}/outline.md"
    opened = app.read_file(pid, path)
    book.outline_path.write_text("New manual plan", encoding="utf-8")
    with pytest.raises(StudioError, match="changed while"):
        app.save_file(pid, path, "Old plan", opened["version"])
    with pytest.raises(StudioError, match="selected document changed"):
        app.send(pid, "project", "Discuss", selection={"path": path, "version": opened["version"], "text": "Chapter 1"})
    assert book.outline_path.read_text() == "New manual plan"


def test_streaming_http_sends_events_and_requires_token(tmp_path, config):
    app, _ = make_app(tmp_path, config, FakeRouter({"studio_chat": ["A live reply."]}))
    pid = app.create_project("An idea", defer=True)["project"]
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, "secret"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/api/send/stream"
    body = json.dumps({"project": pid, "chat": "project", "text": "Let's plan"}).encode()
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(url, data=body))
        assert error.value.code == 403
        request = urllib.request.Request(url, data=body, headers={"X-Writers-Room-Token": "secret"})
        with urllib.request.urlopen(request) as response:
            assert response.headers["Content-Type"].startswith("application/x-ndjson")
            events = [json.loads(line) for line in response]
        assert events[0]["kind"] == "started" and events[-1]["kind"] == "done"
        assert any(e["kind"] == "text" and e["text"] == "A live reply." for e in events)
    finally:
        server.shutdown()
        server.server_close()


def test_ideas_open_as_points_with_their_own_choices(tmp_path, config, book):
    # Ideas files come from room.py ideas or the plugin; the app opens them.
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    book.notes_dir.mkdir(parents=True, exist_ok=True)
    (book.notes_dir / "ideas_20261027-190000.md").write_text(
        "Thin in the middle.\n\n### 1. The keeper's secret\n\n**Options:**\n- **A.** x\n\n**Your call:**\n", encoding="utf-8")
    file = app.read_file(pid, f"books/{book.root.name}/notes/ideas_20261027-190000.md")
    assert file["kind"] == "ideas" and [p["title"] for p in file["points"]] == ["The keeper's secret"]
    assert app.project(pid)["ideas"][0]["path"] == file["path"]
    updated = app.review_call(pid, file["path"], 1, "Use the pick.")
    assert updated["points"][0]["call"] == "Use the pick."
    with pytest.raises(StudioError, match="isn't a review"):
        app.review_call(pid, f"books/{book.root.name}/outline.md", 1, "x")


def test_project_reports_book_size_and_titles_from_chapter_headings(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    book.write_chapter(2, "# Chapter 2: Low Water\n\nShe waited.", book.read_plan(), "build")
    data = app.project(book.series.root.name)
    titles = {c["number"]: c["title"] for c in data["chapters"]}
    assert titles[1] == "The Storm"  # from the outline
    assert titles[2] == "Low Water"  # the outline has none, so the chapter's own heading
    assert 0 < data["context"]["tokens"] < data["context"]["limit"]
    assert data["context"]["parts"]
    assert sum(p["tokens"] for p in data["context"]["parts"]) == data["context"]["tokens"]
    # A role on a smaller model makes the meter honest about that model.
    app.set_role("studio_writer", "cloud", "aion")
    assert app.project(book.series.root.name)["context"]["limit"] == 262_000


def test_a_chat_keeps_its_own_model_and_effort(tmp_path, config, book, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app, router = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    first = app.new_chat(pid)
    second = app.new_chat(pid)

    offered = {o["model"] for role in app.settings()["roles"] for o in role["options"]}
    assert {"deepseekpro", "gemini", "gpt"}.isdisjoint(offered)

    app.set_chat_model(pid, first["id"], "cloud", "deepseekflash")
    record = app.set_chat_effort(pid, first["id"], "high")
    assert record["model"] == {"backend": "cloud", "model": "deepseekflash"}
    assert record["effort"] == "high"

    app.send(pid, first["id"], "Hello")
    routing = router.routings[-1]
    assert routing["backend"] == "cloud" and routing["model"] == "deepseekflash"
    assert routing["params"]["reasoning"] == {"effort": "high"}
    assert any(t.get("type") == "openrouter:web_search" for t in routing["params"]["tools"])

    # The other chat still uses the studio_chat default.
    app.send(pid, second["id"], "Hello")
    assert router.routings[-1] is None

    # A new model clears the old model's effort.
    record = app.set_chat_model(pid, first["id"], "cloud", "geminiargon")
    assert record["effort"] == ""
    with pytest.raises(StudioError, match="isn't available for this model"):
        app.set_chat_effort(pid, first["id"], "max")
    with pytest.raises(StudioError, match="isn't available"):
        app.set_chat_model(pid, first["id"], "cloud", "not-a-model")
    with pytest.raises(StudioError, match="isn't available"):
        app.set_chat_model(pid, first["id"], "cloud", "deepseekpro")
    with pytest.raises(StudioError, match="isn't available"):
        app.set_role("studio_writer", "cloud", "gpt")


def test_chat_model_effort_and_web_search_follow_the_settings(tmp_path, config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app, _ = make_app(tmp_path, config)
    chat_role = lambda s: next(r for r in s["roles"] if r["key"] == "studio_chat")  # noqa: E731
    role = chat_role(app.settings())
    assert role["web"] and role["effort"] == "" and role["efforts"] == ["low", "medium", "high"]

    role = chat_role(app.set_effort("studio_chat", "low"))
    assert role["effort"] == "low" and role["web"]  # the web tools stay
    role = chat_role(app.set_effort("studio_chat", ""))
    assert role["effort"] == ""

    role = chat_role(app.set_role("studio_chat", "cloud", "deepseekflash"))
    assert role["web"] and "max" in role["efforts"]
    routing = app.config()["agent_routing"]["studio_chat"]
    assert "provider" not in routing["params"]  # no other role's provider pin comes along
    # Off OpenRouter the server tools would be refused, so they're dropped.
    app.set_role("studio_chat", "openai", "terra")
    assert "tools" not in app.config()["agent_routing"]["studio_chat"]["params"]
    with pytest.raises(StudioError, match="Unknown role"):
        app.set_effort("nobody", "high")


def test_a_new_chat_starts_on_the_model_picked_before_it(tmp_path, config, book, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app, router = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name

    record = app.new_chat(pid, "cloud", "geminiargon", "high")
    assert record["model"] == {"backend": "cloud", "model": "geminiargon"} and record["effort"] == "high"
    app.send(pid, record["id"], "Hello")
    assert router.routings[-1]["model"] == "geminiargon"
    assert router.routings[-1]["params"]["reasoning"] == {"effort": "high"}

    # Only an effort: the default model, at that effort.
    assert app.new_chat(pid, effort="low")["effort"] == "low"
    assert "model" not in app.new_chat(pid)
    with pytest.raises(StudioError, match="isn't available"):
        app.new_chat(pid, "cloud", "deepseekpro")


def test_openrouter_models_are_offered_with_prices_and_refreshed_daily(tmp_path, config, book, monkeypatch):
    catalog, fetched = list(CATALOG), []

    def fetch():
        fetched.append(1)
        return catalog

    app, router = make_app(tmp_path, config, fetch=fetch)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name

    def chat_options():
        role = next(r for r in app.settings()["roles"] if r["key"] == "studio_chat")
        return {o["model"]: o for o in role["options"]}

    # Only once OpenRouter is connected.
    assert app.refresh_models() == {"updated": False} and not fetched
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    routing = app.config()["agent_routing"]
    assert "openai/gpt-6.2-terra" not in chat_options() and chat_options()["geminiargon"]["price"] is None

    assert app.refresh_models() == {"updated": True}
    assert app.refresh_models() == {"updated": False} and len(fetched) == 1  # fresh for a day
    options = chat_options()
    assert options["geminiargon"]["price"] == {"in": 2.0, "out": 10.0} and not options["geminiargon"]["small"]
    assert options["openai/gpt-6.2-terra"]["label"] == "GPT-6.2 Terra"
    assert options["openai/gpt-6.2-mini"]["small"] and options["openai/gpt-6.2-mini"]["context"] == 400_000
    # Superseded models aren't offered, and a configured one isn't listed twice.
    assert "x-ai/grok-4.7" not in options and "anthropic/claude-opus-5.5" not in options
    # New models are only offered: no role moves to one.
    assert app.config()["agent_routing"] == routing

    # A chat and a role can choose one.
    cid = app.new_chat(pid, "cloud", "x-ai/grok-5")["id"]
    app.send(pid, cid, "Hello")
    assert router.routings[-1]["model"] == "x-ai/grok-5"
    app.set_role("studio_writer", "cloud", "anthropic/claude-opus-5.6")
    assert app.config()["agent_routing"]["studio_writer"]["model"] == "anthropic/claude-opus-5.6"

    # A day later a newer Grok takes its place in the lists; the chat keeps its choice.
    catalog.append(catalog_model("x-ai/grok-5.1", "xAI: Grok 5.1", 0))
    cache = model_catalog.cache_path(config)
    cache.write_text(json.dumps({**json.loads(cache.read_text(encoding="utf-8")), "fetched": 0}), encoding="utf-8")
    assert app.refresh_models() == {"updated": True}
    options = chat_options()
    assert "x-ai/grok-5.1" in options and "x-ai/grok-5" not in options
    app.send(pid, cid, "Hello again")
    assert router.routings[-1]["model"] == "x-ai/grok-5"
    with pytest.raises(StudioError, match="isn't available"):
        app.new_chat(pid, "cloud", "x-ai/grok-5")


def test_a_failed_model_refresh_keeps_the_lists_and_waits_before_trying_again(tmp_path, config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    tries = []

    def offline():
        tries.append(1)
        raise httpx.ConnectError("offline")

    app, _ = make_app(tmp_path, config, fetch=offline)
    roles = app.settings()["roles"]
    assert app.refresh_models() == {"updated": False}
    assert app.refresh_models() == {"updated": False} and len(tries) == 1
    assert app.settings()["roles"] == roles


def test_the_build_card_gives_a_rough_cost_from_catalog_prices(tmp_path, config, book, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    assert "$" not in app.estimate(pid, None, "all")["detail"]  # no prices yet
    app.refresh_models()
    assert "At list prices that's roughly $" in app.estimate(pid, None, "all")["detail"]

    # The writer (Gemini 4 Argon, $2/$10) drafts and revises; the critic
    # (Claude Sonnet 5.5, $3/$15) critiques.
    guess = press.Estimate(3, 3_000_000, 20_000, critic_input_tokens=1_000_000, critic_output_tokens=10_000)
    assert app_api.build_cost(app.config(), guess) == pytest.approx(2 * 2 + 0.01 * 10 + 1 * 3 + 0.01 * 15)
    # No price for the critic's model: no figure, unless the build has no critique.
    app.set_role("studio_critic", "cloud", "minimax")
    assert app_api.build_cost(app.config(), guess) is None
    assert app_api.build_cost(app.config(), press.Estimate(1, 1_000_000, 0)) == pytest.approx(2)


def test_the_library_folder_is_chosen_in_settings_and_remembered(tmp_path, config):
    app, _ = make_app(tmp_path, config)
    assert app.settings()["library"]["source"] == "default"
    elsewhere = tmp_path / "Novels"
    with pytest.raises(StudioError, match="can't find a folder"):
        app.set_library(str(elsewhere))
    with pytest.raises(StudioError, match="full path"):
        app.set_library("Novels")
    elsewhere.mkdir()
    (elsewhere / "Old Book").mkdir()  # not a series: ignored

    settings = app.set_library(f'"{elsewhere}"')
    assert settings["library"] == {"path": str(elsewhere), "source": "saved"}
    assert app.library.root == elsewhere and app.projects() == []
    app.library.new_book("Moved Here")
    assert [p["title"] for p in app.projects()] == ["Moved Here"]

    # The next start, and the command line, find it too; a flag or the environment wins.
    root = config.parent.parent
    assert locate_library(root) == (elsewhere, "saved")
    assert locate_library(root, str(tmp_path / "flagged"))[1] == "flag"


def test_roles_nobody_chose_move_to_a_connected_provider(tmp_path, config, monkeypatch):
    app, _ = make_app(tmp_path, config)
    routing = lambda: app.config()["agent_routing"]  # noqa: E731
    assert routing()["studio_writer"]["backend"] == "cloud"  # nothing connected: as shipped

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert routing()["studio_writer"] == {"backend": "anthropic", "model": "opus", "params": {}}
    # The second-opinion roles take a different model from the writer.
    assert routing()["studio_critic"]["model"] == "sonnet"
    assert routing()["studio_reader"]["model"] == "sonnet"
    settings = app.settings()
    assert settings["automatic"]
    writer = next(r for r in settings["roles"] if r["key"] == "studio_writer")
    assert writer["available"] and writer["currentLabel"] == "Claude Opus 5.5"

    # A writer's own choice stays, and is no longer automatic until they say so.
    assert not app.set_role("studio_critic", "anthropic", "opus")["automatic"]
    assert routing()["studio_critic"]["model"] == "opus"
    assert app.use_automatic()["automatic"]
    assert routing()["studio_critic"]["model"] == "sonnet"

    # With OpenRouter connected, the shipped choices are used as they are.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert routing()["studio_writer"]["model"] == "geminiargon"


def test_the_build_card_carries_the_build_options(tmp_path, config, book, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    estimate = app.estimate(pid, None, "all")
    # Chapter 1 and 3 have lengths in the outline; chapter 2 doesn't.
    assert estimate["press"] == {"revision_rounds": 1, "default_chapter_words": 3000, "unsized": 1}
    app.set_press(revision_rounds=0, default_chapter_words=4000)
    assert app.estimate(pid, None, "all")["press"]["revision_rounds"] == 0
    assert app.estimate(pid, None, "1")["press"]["unsized"] == 0


def test_reference_upload_reads_web_pages_and_ebooks(tmp_path, config, book):
    app, _ = make_app(tmp_path, config)
    app.library = Library(book.series.root.parent)
    pid = book.series.root.name
    page = b"<html><head><style>p{}</style></head><body><h1>Chapter 1</h1><p>The ferry&rsquo;s late.</p></body></html>"
    app.add_reference(pid, "book", None, "work.html", base64.b64encode(page).decode())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as epub:
        epub.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        epub.writestr("OEBPS/content.opf", '<package><manifest><item id="b" href="two.xhtml"/><item id="a" href="one.xhtml"/>'
                      '</manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>')
        epub.writestr("OEBPS/one.xhtml", "<html><body><p>First.</p></body></html>")
        epub.writestr("OEBPS/two.xhtml", "<html><body><p>Second.</p></body></html>")
    app.add_reference(pid, "book", None, "canon.epub", base64.b64encode(buffer.getvalue()).decode())
    reference = dict(book.read_plan().reference)
    assert reference["work.md"] == "Chapter 1\n\nThe ferry\u2019s late.\n"
    assert reference["canon.md"] == "First.\n\nSecond.\n"


def test_folders_keep_their_names_while_a_build_runs(tmp_path, config, monkeypatch):
    app, _ = make_app(tmp_path, config)
    book, _ = app.library.new_book("Untitled book")
    book.bible_path.write_text("# The Ferry\n", encoding="utf-8")

    class Running:
        state = "running"

    monkeypatch.setattr(jobs, "job_for", lambda b: Running())
    assert app._settle_names("untitled-book") == "untitled-book"
    assert book.root.exists()
    monkeypatch.setattr(jobs, "job_for", lambda b: None)
    assert app._settle_names("untitled-book") == "the-ferry"


def test_a_build_that_cannot_start_does_not_stay_running(book):
    def broken():
        raise RuntimeError("no client")

    job = jobs.BuildJob(book, broken, [1], app_api.press.PressSettings())
    job.start().join(10)
    assert job.state == "failed" and "no client" in job.error
