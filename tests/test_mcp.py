"""The Claude plugin's MCP tools, driven through JSON-RPC messages."""

import io
import json

from src.studio import jobs
from src.studio.mcp import TOOLS, Tools, handle, serve
from tests.fakes import FakeRouter


def tools_for(library, router, tmp_path):
    config = tmp_path / "settings.yaml"
    config.write_text("deployment_mode: local\nmodels: {local: {base_url: x}}\npress: {revision_rounds: 1}\n")
    return Tools(library, lambda: router, config)


def call(tools, name, **arguments):
    reply = handle(tools, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}})
    result = reply["result"]
    return result["content"][0]["text"], result["isError"]


def test_handshake_and_listing(library, tmp_path):
    tools = tools_for(library, FakeRouter(), tmp_path)
    out = io.StringIO()
    serve(tools, io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
        'not json\n'
        '{"jsonrpc":"2.0","id":3,"method":"resources/list"}\n'
    ), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, None, 3]
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert len(replies[1]["result"]["tools"]) == len(TOOLS)
    assert replies[2]["error"]["code"] == -32700 and replies[3]["error"]["code"] == -32601


def test_new_book_then_series_and_status(library, tmp_path):
    tools = tools_for(library, FakeRouter(), tmp_path)
    assert call(tools, "status") == ("The library is empty. Start a book with new_book.", True)
    text, error = call(tools, "new_book", new_title="Low Tide", series="Salt")
    assert not error and "Created" in text
    call(tools, "new_book", new_title="Dead Air", series="Salt")
    listing, _ = call(tools, "list_books")
    assert "Salt (series" in listing and "book 2: Dead Air" in listing
    assert "Which book?" in call(tools, "status")[0]
    assert call(tools, "status", title="Dead Air")[1] is False


def test_build_runs_in_the_background_and_asks_before_rebuilding(book, library, tmp_path):
    router = FakeRouter({"studio_critic": ["No changes needed"] * 2})
    tools = tools_for(library, router, tmp_path)
    estimate, _ = call(tools, "estimate_build", which="next")
    assert estimate.startswith("Chapter(s) 1: about 3 model call(s)")
    text, error = call(tools, "start_build", which="next")
    assert not error and "background" in text
    jobs.job_for(book).join(10)
    status, _ = call(tools, "build_status")
    assert "State: finished" in status and "Chapter 1:" in status
    text, error = call(tools, "start_build", which="1")
    assert error and "rebuild=true" in text
    assert call(tools, "start_build", which="1", rebuild=True)[1] is False
    jobs.job_for(book).join(10)


def test_review_rename_and_errors_come_back_as_text(book, library, tmp_path):
    router = FakeRouter({"studio_reader": ["### 1. A point\n\n**Your call:**\n"]})
    tools = tools_for(library, router, tmp_path)
    text, error = call(tools, "review")
    assert not error and "### 1. A point" in text
    preview, _ = call(tools, "rename", old="Mara", new="Maren")
    assert preview.startswith("Preview only, nothing changed:")
    assert "Mara" in book.characters_path.read_text(encoding="utf-8")
    call(tools, "rename", old="Mara", new="Maren", apply=True)
    assert "Maren" in book.characters_path.read_text(encoding="utf-8")
    assert call(tools, "revise_chapter", chapter=9, note="x") == ("Chapter 9 hasn't been written yet.", True)
    assert call(tools, "new_book")[1] is True


def test_ideas_come_back_as_text(book, library, tmp_path):
    router = FakeRouter({"studio_reader": ["### 1. A gap\n\n**Your call:**\n"]})
    text, error = call(tools_for(library, router, tmp_path), "ideas")
    assert not error and "### 1. A gap" in text and "ideas_" in text
