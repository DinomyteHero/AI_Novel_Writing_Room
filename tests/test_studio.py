"""Tests for the studio simple core (src/studio, scripts/studio.py). No model calls."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from src.studio import (
    StoryProject,
    StudioError,
    draft_chapter,
    export_book,
    next_chapter,
    polish_chapter,
    review_book,
    revise_chapter,
)
from src.studio import writer

ROOT = Path(__file__).resolve().parents[1]

OUTLINE = """# Outline

Intro text that isn't a chapter.

## Chapter 1: The Storm
- Mara finds the lighthouse dark.

## Chapter 2
- The keeper is missing.

### chapter 3 — Low Tide
- She finds the boat.
"""


class FakeRouter:
    def __init__(self, response: str = "# Chapter 1: The Storm\n\nRain."):
        self.response = response
        self.calls: list[tuple[str, list[dict]]] = []

    async def complete(self, role: str, messages: list[dict]) -> str:
        self.calls.append((role, messages))
        return self.response


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def project(tmp_path: Path) -> StoryProject:
    proj = StoryProject.for_book("The Dark Lighthouse", base_dir=str(tmp_path))
    proj.create()
    proj.bible_path.write_text("# Bible\n\nMara is a lighthouse keeper's niece.", encoding="utf-8")
    proj.outline_path.write_text(OUTLINE, encoding="utf-8")
    return proj


def test_paths_follow_project_paths(tmp_path: Path):
    original = StoryProject.for_book("The Dark Lighthouse", base_dir=str(tmp_path))
    fic = StoryProject.for_book("Red Sky", "Star Wars (Legends EU)", base_dir=str(tmp_path))
    assert original.root == tmp_path / "data" / "projects" / "the-dark-lighthouse" / "story"
    assert fic.root == (
        tmp_path / "data" / "franchises" / "star-wars-legends-eu" / "books" / "red-sky" / "story"
    )


def test_create_writes_templates_without_overwriting(tmp_path: Path):
    proj = StoryProject.for_book("The Dark Lighthouse", base_dir=str(tmp_path))
    assert {p.name for p in proj.create()} == {"story_bible.md", "outline.md"}
    assert proj.read_bible().startswith("# The Dark Lighthouse")
    proj.bible_path.write_text("mine", encoding="utf-8")
    assert proj.create() == []
    assert proj.read_bible() == "mine"


def test_outline_parsing_is_loose(project: StoryProject):
    plans = project.outline_chapters()
    assert sorted(plans) == [1, 2, 3]
    assert plans[1].title == "The Storm"
    assert plans[2].title == ""
    assert plans[3].title == "Low Tide"
    assert plans[1].notes == "- Mara finds the lighthouse dark."
    assert "Intro text" not in plans[1].notes


def test_draft_sends_whole_book_and_saves(project: StoryProject):
    project.write_chapter(1, "# Chapter 1: The Storm\n\nEarlier chapter text.")
    router = FakeRouter("# Chapter 2: Gone\n\nThe keeper's chair was empty.")
    path = _run(draft_chapter(project, router, 2, words=2500, note="open at dawn"))

    role, messages = router.calls[0]
    assert role == writer.WRITER_ROLE
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Co-Writer" in system and "Loose Craft Guide" in system
    assert "lighthouse keeper's niece" in user
    assert "Earlier chapter text." in user
    assert "The keeper is missing." in user
    assert "roughly 2,500 words" in user
    assert "open at dawn" in user
    assert user.index("# Story bible") < user.index("Earlier chapter text.") < user.index("# Task")
    assert path == project.chapter_path(2)
    assert path.read_text(encoding="utf-8").startswith("# Chapter 2: Gone")


def test_draft_only_includes_earlier_chapters(project: StoryProject):
    project.write_chapter(3, "# Chapter 3\n\nLATER CHAPTER")
    router = FakeRouter()
    _run(draft_chapter(project, router, 1))
    user = router.calls[0][1][1]["content"]
    assert "LATER CHAPTER" not in user
    assert "No chapters written yet" in user


def test_draft_refuses_overwrite_unless_forced(project: StoryProject):
    project.write_chapter(1, "first version")
    with pytest.raises(StudioError, match="already has a draft"):
        _run(draft_chapter(project, FakeRouter(), 1))
    _run(draft_chapter(project, FakeRouter("second version"), 1, force=True))
    assert project.chapter_path(1).read_text(encoding="utf-8") == "second version\n"
    history = list(project.history_dir.iterdir())
    assert [p.read_text(encoding="utf-8") for p in history] == ["first version\n"]


def test_draft_requires_outline_entry(project: StoryProject):
    with pytest.raises(StudioError, match="no '## Chapter 9' section"):
        _run(draft_chapter(project, FakeRouter(), 9))


def test_empty_response_saves_nothing(project: StoryProject):
    with pytest.raises(StudioError, match="empty response"):
        _run(draft_chapter(project, FakeRouter("   "), 1))
    assert not project.chapter_path(1).exists()


def test_code_fences_are_stripped(project: StoryProject):
    _run(draft_chapter(project, FakeRouter("```markdown\n# Chapter 1\n\nText.\n```"), 1))
    assert project.chapter_path(1).read_text(encoding="utf-8") == "# Chapter 1\n\nText.\n"


def test_oversized_book_is_refused(project: StoryProject, monkeypatch):
    monkeypatch.setattr(writer, "MAX_PROMPT_TOKENS", 10)
    router = FakeRouter()
    with pytest.raises(StudioError, match="more than the 10"):
        _run(draft_chapter(project, router, 1))
    assert router.calls == []


def test_revise_shows_rest_of_book_and_keeps_history(project: StoryProject):
    project.write_chapter(1, "# Chapter 1\n\nONE")
    project.write_chapter(2, "# Chapter 2\n\nTWO")
    project.write_chapter(3, "# Chapter 3\n\nTHREE")
    router = FakeRouter("# Chapter 2\n\nTWO, revised")
    _run(revise_chapter(project, router, 2, "make it funnier"))

    user = router.calls[0][1][1]["content"]
    rest, target = user.split("# Chapter 2 (the chapter to revise)")
    assert "ONE" in rest and "THREE" in rest and "TWO" not in rest
    assert "TWO" in target and "make it funnier" in target
    assert "Reviser" in router.calls[0][1][0]["content"]
    assert project.chapter_path(2).read_text(encoding="utf-8") == "# Chapter 2\n\nTWO, revised\n"
    assert len(list(project.history_dir.iterdir())) == 1


def test_revise_needs_a_draft_and_a_note(project: StoryProject):
    with pytest.raises(StudioError, match="hasn't been drafted"):
        _run(revise_chapter(project, FakeRouter(), 1, "note"))
    project.write_chapter(1, "text")
    with pytest.raises(StudioError, match="Say what you'd like changed"):
        _run(revise_chapter(project, FakeRouter(), 1, "  "))


def test_polish_is_a_revision_with_the_standard_note(project: StoryProject):
    project.write_chapter(1, "text")
    router = FakeRouter("polished")
    _run(polish_chapter(project, router, 1))
    assert "light line edit" in router.calls[0][1][1]["content"]


def test_review_uses_reader_role_and_writes_notes(project: StoryProject):
    project.write_chapter(1, "# Chapter 1\n\nONE")
    router = FakeRouter("## What's working\n\nLots.")
    path = _run(review_book(project, router))
    role, messages = router.calls[0]
    assert role == writer.READER_ROLE
    assert "First Reader" in messages[0]["content"]
    assert "ONE" in messages[1]["content"]
    assert path.parent == project.notes_dir
    assert path.read_text(encoding="utf-8").startswith("## What's working")


def test_review_and_export_need_chapters(project: StoryProject):
    with pytest.raises(StudioError):
        _run(review_book(project, FakeRouter()))
    with pytest.raises(StudioError):
        export_book(project)


def test_next_chapter_and_export_order(project: StoryProject):
    assert next_chapter(project) == 1
    project.write_chapter(2, "# Chapter 2\n\nTWO")
    project.write_chapter(1, "# Chapter 1\n\nONE")
    assert next_chapter(project) == 3
    project.write_chapter(3, "# Chapter 3\n\nTHREE")
    with pytest.raises(StudioError, match="Every chapter"):
        next_chapter(project)
    text = export_book(project).read_text(encoding="utf-8")
    assert text.startswith("# The Dark Lighthouse")
    assert text.index("ONE") < text.index("TWO") < text.index("THREE")


def _load_cli():
    spec = importlib.util.spec_from_file_location("studio_cli", ROOT / "scripts" / "studio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_new_status_export(tmp_path: Path, capsys):
    cli = _load_cli()
    base = ["--title", "The Dark Lighthouse", "--base-dir", str(tmp_path)]
    assert cli.main(["status", *base]) == 1
    assert "Run 'new' first" in capsys.readouterr().err

    assert cli.main(["new", *base]) == 0
    proj = StoryProject.for_book("The Dark Lighthouse", base_dir=str(tmp_path))
    proj.outline_path.write_text(OUTLINE, encoding="utf-8")
    proj.write_chapter(1, "# Chapter 1: The Storm\n\nRain fell on the glass.")

    assert cli.main(["status", *base]) == 0
    out = capsys.readouterr().out
    assert "1 of 3 outlined chapters drafted, 5 words" in out
    assert "not drafted" in out

    assert cli.main(["export", *base]) == 0
    assert proj.export_path.exists()


def test_studio_routing_entries_exist():
    import yaml

    routing = yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))[
        "agent_routing"
    ]
    assert writer.WRITER_ROLE in routing and writer.READER_ROLE in routing
