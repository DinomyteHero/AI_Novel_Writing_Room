"""Read-only chapter and manuscript endpoints."""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from src.ui.app import get_app_state

router = APIRouter(tags=["chapters"])

_SCENE_FILE_RE = re.compile(r"chapter_(\d+)_scene_(\d+)\.md$")


@router.get("/chapters")
async def list_chapters(request: Request):
    """List generated chapter/scene prose files."""
    state = get_app_state(request)
    manuscripts_dir = Path(state.manuscripts_dir)
    if not manuscripts_dir.exists():
        return {"chapters": []}

    chapters = []
    for path in sorted(manuscripts_dir.glob("chapter_*.md")):
        match = _SCENE_FILE_RE.match(path.name)
        if not match:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        chapters.append({
            "chapter_number": int(match.group(1)),
            "scene_number": int(match.group(2)),
            "word_count": len(text.split()),
            "path": str(path),
        })
    return {"chapters": chapters}


@router.get("/chapters/{chapter_num}/{scene_num}")
async def get_chapter(chapter_num: int, scene_num: int, request: Request):
    """Get the full prose text for a chapter/scene."""
    state = get_app_state(request)
    path = (
        Path(state.manuscripts_dir)
        / f"chapter_{chapter_num:02d}_scene_{scene_num:02d}.md"
    )
    if not path.exists():
        raise HTTPException(404, f"Chapter {chapter_num} scene {scene_num} not found")

    text = path.read_text(encoding="utf-8")
    return {
        "chapter_number": chapter_num,
        "scene_number": scene_num,
        "prose": text,
        "word_count": len(text.split()),
    }


@router.get("/manuscript/summary")
async def get_manuscript_summary(request: Request):
    """Get manuscript-level statistics."""
    state = get_app_state(request)
    manuscripts_dir = Path(state.manuscripts_dir)
    if not manuscripts_dir.exists():
        return {"total_word_count": 0, "chapter_count": 0, "chapters": []}

    chapters = []
    total_words = 0
    for path in sorted(manuscripts_dir.glob("chapter_*.md")):
        match = _SCENE_FILE_RE.match(path.name)
        if not match:
            continue
        word_count = len(path.read_text(encoding="utf-8").split())
        total_words += word_count
        chapters.append({
            "chapter_number": int(match.group(1)),
            "scene_number": int(match.group(2)),
            "word_count": word_count,
        })

    return {
        "total_word_count": total_words,
        "chapter_count": len({c["chapter_number"] for c in chapters}),
        "chapters": chapters,
    }
