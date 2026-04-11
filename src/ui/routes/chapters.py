"""Chapter and manuscript API endpoints."""

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.ui.app import get_app_state

router = APIRouter(tags=["chapters"])


class ExportRequest(BaseModel):
    formats: list[str] = ["md", "docx", "epub"]
    output_dir: Optional[str] = None


@router.get("/chapters")
async def list_chapters(request: Request):
    """List all generated chapters from the manuscripts directory."""
    state = get_app_state(request)
    manuscripts_dir = Path(state.manuscripts_dir)

    if not manuscripts_dir.exists():
        return {"chapters": []}

    chapters = []
    pattern = re.compile(r"chapter_(\d+)_scene_(\d+)\.md")

    for path in sorted(manuscripts_dir.glob("chapter_*.md")):
        match = pattern.match(path.name)
        if not match:
            continue

        chapter_num = int(match.group(1))
        scene_num = int(match.group(2))
        try:
            text = path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            continue
        word_count = len(text.split())

        entry = {
            "chapter_number": chapter_num,
            "scene_number": scene_num,
            "word_count": word_count,
            "path": str(path),
        }

        # Attach quality score from chapter_log if available
        if state.story_state:
            log = state.story_state.get_chapter_log(chapter_num)
            if log and log.get("quality_scores"):
                scores = log["quality_scores"]
                if isinstance(scores, str):
                    import json
                    try:
                        scores = json.loads(scores)
                    except json.JSONDecodeError:
                        scores = {}
                entry["quality_scores"] = scores

        chapters.append(entry)

    return {"chapters": chapters}


@router.get("/chapters/{chapter_num}/{scene_num}")
async def get_chapter(chapter_num: int, scene_num: int, request: Request):
    """Get the full prose text for a chapter/scene."""
    state = get_app_state(request)
    path = Path(state.manuscripts_dir) / f"chapter_{chapter_num:02d}_scene_{scene_num:02d}.md"

    if not path.exists():
        raise HTTPException(404, f"Chapter {chapter_num} scene {scene_num} not found")

    text = path.read_text(encoding="utf-8")
    return {
        "chapter_number": chapter_num,
        "scene_number": scene_num,
        "prose": text,
        "word_count": len(text.split()),
    }


@router.get("/chapters/{chapter_num}/{scene_num}/metrics")
async def get_chapter_metrics(chapter_num: int, scene_num: int, request: Request):
    """Get quality metrics for a chapter."""
    state = get_app_state(request)

    if not state.story_state:
        raise HTTPException(503, "Story state not initialized")

    log = state.story_state.get_chapter_log(chapter_num)
    if not log:
        raise HTTPException(404, f"No metrics for chapter {chapter_num}")

    return log


@router.get("/chapters/{chapter_num}/{scene_num}/evaluation")
async def get_chapter_evaluation(chapter_num: int, scene_num: int, request: Request):
    """Get gate critic and LLM judge evaluations for a chapter."""
    state = get_app_state(request)

    result = {"chapter_number": chapter_num, "scene_number": scene_num}

    # Get gate verdict from ledger
    gate_events = state.ledger.get_events(
        chapter_number=chapter_num, event_type="gate_pass", limit=1
    )
    if not gate_events:
        gate_events = state.ledger.get_events(
            chapter_number=chapter_num, event_type="gate_fail", limit=1
        )
    if gate_events:
        result["gate_evaluation"] = gate_events[-1].get("payload", {})

    # Get judge evaluation from ledger
    judge_events = state.ledger.get_events(
        chapter_number=chapter_num, event_type="judge_evaluation", limit=1
    )
    if judge_events:
        result["judge_evaluation"] = judge_events[-1].get("payload", {})

    return result


@router.get("/manuscript/summary")
async def get_manuscript_summary(request: Request):
    """Get manuscript-level statistics."""
    state = get_app_state(request)
    manuscripts_dir = Path(state.manuscripts_dir)

    if not manuscripts_dir.exists():
        return {"total_word_count": 0, "chapter_count": 0, "chapters": []}

    pattern = re.compile(r"chapter_(\d+)_scene_(\d+)\.md")
    chapters = []
    total_words = 0

    for path in sorted(manuscripts_dir.glob("chapter_*.md")):
        match = pattern.match(path.name)
        if not match:
            continue
        text = path.read_text(encoding="utf-8")
        wc = len(text.split())
        total_words += wc
        chapters.append({
            "chapter_number": int(match.group(1)),
            "scene_number": int(match.group(2)),
            "word_count": wc,
        })

    return {
        "total_word_count": total_words,
        "chapter_count": len(chapters),
        "chapters": chapters,
    }


@router.post("/export")
async def export_manuscript(body: ExportRequest, request: Request):
    """Trigger manuscript export to specified formats."""
    state = get_app_state(request)

    if not state.export_manager:
        raise HTTPException(503, "Export manager not available")

    results = state.export_manager.export_all(
        output_dir=body.output_dir or state.export_dir,
        formats=body.formats,
    )

    state.ledger.emit("export_complete", payload={"formats": body.formats})
    return {"exports": {k: str(v) if v else None for k, v in results.items()}}


@router.get("/export/download/{fmt}")
async def download_export(fmt: str, request: Request):
    """Download an exported manuscript file."""
    if fmt not in ("md", "docx", "epub"):
        raise HTTPException(400, f"Invalid format: {fmt}")

    state = get_app_state(request)
    export_dir = Path(state.export_dir)
    if not export_dir.exists():
        raise HTTPException(404, "No exports found. Run export first.")

    # Find the exported file
    extensions = {"md": ".md", "docx": ".docx", "epub": ".epub"}
    ext = extensions[fmt]

    files = sorted(export_dir.glob(f"*{ext}"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise HTTPException(404, f"No {fmt} export found")

    return FileResponse(
        path=str(files[0]),
        filename=files[0].name,
        media_type="application/octet-stream",
    )
