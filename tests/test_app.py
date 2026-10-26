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

import pytest
import yaml

from src.app import api as app_api
from src.app.server import make_handler
from src.studio import jobs
from src.studio.project import Library, StudioError
from tests.fakes import FakeRouter

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config" / "settings.yaml"
    path.parent.mkdir()
    path.write_text((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return path


def make_app(tmp_path, config, router=None):
    router = router or FakeRouter()
    return app_api.App(Library(tmp_path / "library"), config, tmp_path / ".env", make_router=lambda: router), router


def write_bible(messages):
    files = messages[-1]["content"]
    path = next(line[2:] for line in files.splitlines() if line.startswith("- books/") and line.endswith("story_bible.md"))
    return {"tool_calls": [("write_file", {
        "path": path, "content": "# The Dark Lighthouse\n\nA keeper's niece keeps the light.", "summary": "Filed your idea",
    })]}


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
    assert "Chapter 2: Gone" in book.outline_path.read_text(encoding="utf-8")
    assert record["title"] == "Call chapter 2 Gone"
    record = app.undo(pid, chat["id"], activity["id"])
    assert "Chapter 2: Gone" not in book.outline_path.read_text(encoding="utf-8")
    assert app.recents()[0]["title"] == "Call chapter 2 Gone"


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
    # Moving the writer drops the DeepSeek-only provider pin.
    assert overlay["agent_routing"]["studio_writer"] == {"backend": "cloud", "model": "claude", "params": {}}
    assert app.press_settings().revision_rounds == 2
    assert app.config()["agent_routing"]["studio_critic"]["model"] == "gemini"
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
