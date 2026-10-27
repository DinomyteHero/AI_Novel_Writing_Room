"""room.py and press.py end to end, with a fake model in place of OpenRouter."""

from __future__ import annotations

import pytest

from src.studio import cli
from src.studio.llm import CRITIC_ROLE, READER_ROLE, WRITER_ROLE
from tests.conftest import OUTLINE
from tests.fakes import FakeRouter


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    router = FakeRouter()
    monkeypatch.setattr(cli, "_router", lambda args: router)
    library = ["--library", str(tmp_path / "library")]

    def invoke(tool, *argv):
        main = cli.room_main if tool == "room" else cli.press_main
        code = main([argv[0], *library, *argv[1:]])
        out = capsys.readouterr()
        return code, out.out + out.err

    invoke.router = router
    invoke.library = tmp_path / "library"
    return invoke


def _outline(run):
    path = next(run.library.glob("*/books/*/outline.md"))
    path.write_text(OUTLINE, encoding="utf-8")


def test_new_books_and_status(run):
    code, out = run("room", "status")
    assert code == 1 and "library is empty" in out
    code, out = run("room", "new", "The Dark Lighthouse")
    assert code == 0 and "created" in out and "press.py build next" in out
    code, out = run("room", "new", "Low Tide", "--series", "The Dark Lighthouse")
    assert code == 0 and "series_bible.md" in out
    code, out = run("room", "books")
    assert "(series)" in out and "Low Tide: 0 chapter(s) written" in out
    code, out = run("room", "status")
    assert code == 1 and "Which book?" in out
    code, out = run("room", "status", "--title", "Low Tide")
    assert code == 0 and "No review yet" in out


def test_build_next_then_all_with_confirmation(run):
    run("room", "new", "The Dark Lighthouse")
    _outline(run)
    run.router.responses = {
        WRITER_ROLE: ["# Chapter 1\n\n" + "w " * 3000],
        CRITIC_ROLE: ["No changes needed. Strong."],
    }
    code, out = run("press", "build", "next")
    assert code == 0, out
    assert "Building chapter(s) 1" in out and "Chapter 1: 3,000 words (planned 2,500)" in out
    assert "Report:" in out

    code, out = run("press", "build", "all")
    assert code == 1 and "Add --yes" in out
    code, out = run("press", "build", "all", "--yes", "--rounds", "0")
    assert code == 0 and "Chapter 3:" in out

    code, out = run("room", "status")
    assert "3 of 3 chapters written" in out


def test_rebuilding_a_chapter_asks_first(run):
    run("room", "new", "The Dark Lighthouse")
    _outline(run)
    run("press", "build", "1", "--rounds", "0")
    code, out = run("press", "build", "1", "--rounds", "0")
    assert code == 1 and "already exists. Rebuild it?" in out
    code, out = run("press", "build", "1", "--rounds", "0", "--yes")
    assert code == 0
    assert len(list(run.library.glob("*/books/*/manuscript/.history/*.md"))) == 1


def test_review_rename_and_export(run):
    run("room", "new", "The Dark Lighthouse")
    _outline(run)
    run.router.responses = {READER_ROLE: ["### 1. Stakes\n\n**Your call:**"]}
    code, out = run("room", "review")
    assert code == 0 and "notes/review_" in out.replace("\\", "/")

    run("press", "build", "1", "--rounds", "0")
    code, out = run("room", "rename", "Mara", "Maren")
    assert code == 0 and "Nothing has changed yet" in out
    code, out = run("room", "rename", "Mara", "Maren", "--apply")
    assert code == 0 and "Replaced" in out
    outline = next(run.library.glob("*/books/*/outline.md")).read_text(encoding="utf-8")
    assert "Maren finds the lighthouse dark" in outline

    code, out = run("press", "export")
    assert code == 0 and "export/manuscript.md" in out.replace("\\", "/")


def test_check_exit_code(run):
    code, out = run("room", "check")
    assert code == 0 and out.startswith("Ready:")
    run.router.health = (False, "Invalid API key (401 Unauthorized)")
    code, out = run("room", "check")
    assert code == 1 and "Problem: Invalid API key" in out


def test_missing_api_key_is_explained(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    library = ["--library", str(tmp_path / "library")]
    cli.room_main(["new", "The Dark Lighthouse", *library])
    code = cli.press_main(["build", "next", *library])
    err = capsys.readouterr().err
    assert code == 1 and "No API key found" in err and "Traceback" not in err


def test_service_errors_are_explained(run, monkeypatch):
    import httpx

    async def fail(role, messages):
        raise httpx.ConnectError("no route to host")

    run("room", "new", "The Dark Lighthouse")
    _outline(run)
    monkeypatch.setattr(run.router, "complete", fail)
    code, out = run("press", "build", "next")
    assert code == 1 and "couldn't get an answer from the model service" in out
