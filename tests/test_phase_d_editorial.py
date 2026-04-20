"""Phase D — editorial consultant + plan-approval gate.

Covers four components:

1. ``EditorialConsultant`` agent — context assembly, verdict + section
   parsing from a mocked LLM markdown response.
2. ``compile_bundle`` integration — the ``editorial_router`` kwarg
   triggers a review call, writes ``editorial_reviews/review_<ts>.md``,
   and populates ``report.editorial``.
3. ``scripts/approve_plan.approve_plan`` — stamps
   ``compile_metadata.plan_approved`` into the persisted seed and
   appends a record to ``approvals.jsonl``.
4. ``src.main.check_plan_approval`` — the drafting-time gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.approve_plan import approve_plan
from scripts.compile_bundle import CompileReport, compile_bundle
from src.agents.editorial_consultant import (
    EditorialConsultant,
    _extract_top_sections,
    _extract_verdict,
    _sample_blueprints,
    _sample_scene_cards,
)
from src.main import check_plan_approval
from src.project_paths import ProjectPaths
from workflows._shared.io import write_artifact
from workflows._shared.legacy_seed_loader import load_seed
from workflows.canon_drafter.importers.legacy_seed import import_from_seed as cd_import
from workflows.canon_drafter.validate import validate as v_cd
from workflows.character_forge.importers.legacy_seed import import_from_seed as cf_import
from workflows.character_forge.validate import validate as v_cf
from workflows.outline_planner.importers.legacy_seed import import_from_seed as op_import
from workflows.outline_planner.validate import validate as v_op
from workflows.scene_card_authoring.importers.legacy_seed import import_from_seed as sca_import
from workflows.scene_card_authoring.validate import validate as v_sca
from workflows.universe_builder.importers.legacy_seed import import_from_seed as ub_import
from workflows.universe_builder.validate import validate as v_ub
from workflows.voice_discovery.importers.legacy_seed import import_from_seed as vd_import
from workflows.voice_discovery.validate import validate as v_vd

REPO_ROOT = Path(__file__).resolve().parents[1]
RUUSAN_BOOK_DIR = (
    REPO_ROOT / "data" / "franchises" / "star-wars-legends-eu"
    / "books" / "the-ruusan-atonement"
)
RUUSAN_SEED = RUUSAN_BOOK_DIR / "concept_seed.json"
RUUSAN_SCENE_CARDS = RUUSAN_BOOK_DIR / "scene_cards"
RUUSAN_FRANCHISE_META = (
    REPO_ROOT / "data" / "franchises" / "star-wars-legends-eu" / "franchise_meta.json"
)


# --------------------------------------------------------------------------- #
# 1. EditorialConsultant agent                                                  #
# --------------------------------------------------------------------------- #


_MOCK_REPORT_MD = """## Top 3 Strengths

- The protagonist's Lie (vulnerability = death) is concrete and testable.
- Hook architecture is tight; every promise is paid before the climax.
- Midpoint pivot genuinely flips reactive to proactive.

## Top 5 Concerns

- Antagonist motivation is murky in chapters 8-11. Fix: tie directly to the protagonist's Ghost.
- Two POV characters test the theme the same way. One should be cut or re-angled.
- Convolution: 18 named speaking roles by chapter 4. Trim.
- Midpoint beat is stated in scene card but not dramatized in blueprint 13.
- Climax pivots away from the opening's promise of intimate reckoning.

## Brooks Structural Verdict

- Part 1 Setup: works
- First Plot Point: works
- Part 2 Response: partially works — Ch 8 reads too active
- Midpoint: partially works — see concern above
- Part 3 Attack: works
- Second Plot Point: works
- Part 4 Resolution: partially works

## Weiland Arc Verdict

- Maren: concrete Lie/Ghost/Want/Need; arc_type matches phase map.
- Darian: muddled — Want and Need collapse to same action.

## Convolution Metrics

- Named speakers: 18 (over tolerance)
- Factions: 3 (ok)
- Subplots: 4 (at ceiling)
- Open hooks at 25%: 6 (over)
- Unique terminology: 44 (manageable in this franchise)

## Genre Reader's Gut Read

A Star Wars Legends reader would keep going past chapter 3 on Ben's voice alone.
By the midpoint they'd be invested in Maren. But the Darian subplot and the
convolution at chapter 4 would test their patience.

## Recommendations

**Pre-drafting fixes**:
- Re-angle Darian's arc so Want ≠ Need.
- Cut or merge one of the two thematic mirror characters.
- Trim 4-5 named speakers from chapters 1-4.

**During-drafting watch-outs**:
- Watch Ch 8 for over-active protagonist stance.
- Make the midpoint beat dramatized, not recited.

VERDICT: revise_plan
"""


def test_extract_verdict_happy_path():
    assert _extract_verdict(_MOCK_REPORT_MD) == "revise_plan"


def test_extract_verdict_missing_returns_unknown():
    assert _extract_verdict("no marker here") == "unknown"


def test_extract_verdict_case_insensitive():
    assert _extract_verdict("\nVerdict: Ready_To_Draft\n") == "ready_to_draft"


def test_extract_sections_picks_up_all_known():
    sections = _extract_top_sections(_MOCK_REPORT_MD)
    assert set(sections.keys()) == {
        "strengths", "concerns", "brooks_verdict",
        "weiland_verdict", "convolution", "gut_read", "recommendations",
    }
    assert "vulnerability = death" in sections["strengths"]
    # Recommendations section contains both the pre-draft + during-draft
    # subheads; order preserved as the LLM emitted them.
    assert "Pre-drafting" in sections["recommendations"]
    assert "During-drafting" in sections["recommendations"]


def test_sample_blueprints_covers_structural_beats():
    bps = [{"chapter_number": i} for i in range(1, 21)]
    sampled = _sample_blueprints(bps, total_chapters=20)
    # 6 labels; in a 20-chapter book all should resolve distinctly.
    assert len(sampled) == 6
    labels = [lbl for lbl, _ in sampled]
    assert labels == ["opening", "first_plot_point", "midpoint",
                      "second_plot_point", "climax", "resolution"]


def test_sample_scene_cards_deduplicates_in_short_book():
    cards = [
        {"chapter_number": 1, "scene_number": 1},
        {"chapter_number": 2, "scene_number": 1},
    ]
    sampled = _sample_scene_cards(cards, total_chapters=2)
    # Opening/FPP/midpoint/SPP/climax/resolution would all collapse onto
    # chapters 1 or 2 — we expect at most 2 distinct picks.
    chapter_numbers = {c["chapter_number"] for c in sampled}
    assert chapter_numbers.issubset({1, 2})
    assert len(sampled) == len(chapter_numbers)


@pytest.mark.asyncio
async def test_editorial_consultant_run_parses_mock_response():
    router = MagicMock()
    router.complete = AsyncMock(return_value=_MOCK_REPORT_MD)

    agent = EditorialConsultant(router)
    context = {
        "concept_seed": {
            "meta": {
                "franchise": "test-fr", "genre": "thriller",
                "tone": "dark", "target_chapters": 10,
            },
            "premise": {"logline": "A test book"},
        },
        "chapter_blueprints": [{"chapter_number": i} for i in range(1, 11)],
        "scene_cards": [{"chapter_number": 1, "scene_number": 1}],
        "physics_report": {"passed": True, "critical_count": 0, "warn_count": 0},
    }
    result = await agent.run(context)

    assert result["verdict"] == "revise_plan"
    assert "strengths" in result["sections"]
    assert result["report_markdown"] == _MOCK_REPORT_MD
    router.complete.assert_awaited_once()


# --------------------------------------------------------------------------- #
# 2. compile_bundle editorial integration                                       #
# --------------------------------------------------------------------------- #


def _stage_ruusan(tmp_path: Path) -> ProjectPaths:
    seed = load_seed(RUUSAN_SEED)
    paths = ProjectPaths(
        "the-ruusan-atonement", base_dir=str(tmp_path),
        franchise_slug="star-wars-legends-eu",
    )
    paths.ensure_dirs()
    paths.workflows_dir.mkdir(parents=True, exist_ok=True)
    write_artifact(
        paths.workflows_dir / "universe.json",
        ub_import(seed, franchise_meta_path=RUUSAN_FRANCHISE_META),
        surface="universe-builder", validator=v_ub,
    )
    write_artifact(
        paths.workflows_dir / "canon.json",
        cd_import(seed),
        surface="canon-drafter", validator=v_cd,
    )
    write_artifact(
        paths.workflows_dir / "voice.json",
        vd_import(seed),
        surface="voice-discovery", validator=v_vd,
    )
    write_artifact(
        paths.workflows_dir / "characters.json",
        cf_import(seed),
        surface="character-forge", validator=v_cf,
    )
    write_artifact(
        paths.workflows_dir / "outline.json",
        op_import(seed, extracted_scene_cards_dir=RUUSAN_SCENE_CARDS),
        surface="outline-planner", validator=v_op,
    )
    write_artifact(
        paths.workflows_dir / "scene_cards.json",
        sca_import(seed, extracted_scene_cards_dir=RUUSAN_SCENE_CARDS),
        surface="scene-card-authoring", validator=v_sca,
    )
    return paths


@pytest.mark.skipif(
    not RUUSAN_SEED.exists() or not RUUSAN_SCENE_CARDS.exists(),
    reason="Ruusan committed artifacts missing",
)
def test_compile_bundle_with_mock_router_emits_review(tmp_path):
    paths = _stage_ruusan(tmp_path)
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=_MOCK_REPORT_MD)

    report = compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
        editorial_router=mock_router,
    )

    mock_router.complete.assert_awaited_once()
    assert report.editorial, "editorial section missing"
    assert report.editorial.get("verdict") == "revise_plan"
    assert report.editorial.get("scene_card_count", 0) > 0

    reviews_dir = paths.book_dir / "editorial_reviews"
    review_files = sorted(reviews_dir.glob("review_*.md"))
    assert len(review_files) == 1
    content = review_files[0].read_text(encoding="utf-8")
    assert "VERDICT: revise_plan" in content


@pytest.mark.skipif(
    not RUUSAN_SEED.exists() or not RUUSAN_SCENE_CARDS.exists(),
    reason="Ruusan committed artifacts missing",
)
def test_compile_bundle_without_router_skips_review(tmp_path):
    paths = _stage_ruusan(tmp_path)
    report = compile_bundle(
        franchise_slug="star-wars-legends-eu",
        book_slug="the-ruusan-atonement",
        base_dir=str(tmp_path),
    )
    assert report.editorial == {}
    assert not (paths.book_dir / "editorial_reviews").exists()


# --------------------------------------------------------------------------- #
# 3. approve_plan CLI                                                           #
# --------------------------------------------------------------------------- #


def _write_minimal_seed(tmp_path: Path, extra_metadata: dict | None = None) -> Path:
    paths = ProjectPaths(
        "sample-book", base_dir=str(tmp_path), franchise_slug="sample-fr",
    )
    paths.ensure_dirs()
    seed: dict = {"meta": {"project_title": "Sample", "target_chapters": 5}}
    if extra_metadata:
        seed["compile_metadata"] = extra_metadata
    paths.concept_seed_path.write_text(
        json.dumps(seed, indent=2) + "\n", encoding="utf-8",
    )
    return paths.concept_seed_path


def test_approve_plan_stamps_seed(tmp_path):
    seed_path = _write_minimal_seed(
        tmp_path, extra_metadata={"physics_validated": True},
    )
    record = approve_plan(
        franchise_slug="sample-fr", book_slug="sample-book",
        base_dir=str(tmp_path),
        reviewer="alice", notes="looks good",
    )
    updated = json.loads(seed_path.read_text(encoding="utf-8"))
    assert updated["compile_metadata"]["plan_approved"] is True
    assert updated["compile_metadata"]["plan_approved_by"] == "alice"
    assert updated["compile_metadata"]["plan_approved_at"]
    # approvals.jsonl appended
    approvals_path = (
        seed_path.parent / "editorial_reviews" / "approvals.jsonl"
    )
    assert approvals_path.exists()
    lines = approvals_path.read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(lines[-1])
    assert entry["action"] == "approve"
    assert entry["reviewer"] == "alice"
    assert entry["notes"] == "looks good"
    assert record == entry


def test_approve_plan_unapprove_clears_stamp(tmp_path):
    _write_minimal_seed(tmp_path)
    approve_plan(
        franchise_slug="sample-fr", book_slug="sample-book",
        base_dir=str(tmp_path), reviewer="bob",
    )
    record = approve_plan(
        franchise_slug="sample-fr", book_slug="sample-book",
        base_dir=str(tmp_path), reviewer="bob", unapprove=True,
    )
    seed_path = (
        tmp_path / "data" / "franchises" / "sample-fr"
        / "books" / "sample-book" / "concept_seed.json"
    )
    updated = json.loads(seed_path.read_text(encoding="utf-8"))
    assert updated["compile_metadata"]["plan_approved"] is False
    assert record["action"] == "unapprove"


def test_approve_plan_missing_seed_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        approve_plan(
            franchise_slug="ghost-fr", book_slug="ghost-book",
            base_dir=str(tmp_path),
        )


# --------------------------------------------------------------------------- #
# 4. src.main.check_plan_approval gate                                          #
# --------------------------------------------------------------------------- #


def test_gate_rejects_unstamped_seed():
    ok, msg = check_plan_approval(
        {}, allow_unapproved=False, seed_path="seed.json",
    )
    assert ok is False
    assert "plan has not been approved" in msg
    assert "approve_plan.py" in msg


def test_gate_rejects_physics_validated_but_not_approved():
    seed = {"compile_metadata": {"physics_validated": True}}
    ok, msg = check_plan_approval(
        seed, allow_unapproved=False, seed_path="seed.json",
    )
    assert ok is False
    assert "physics_validated=True" in msg


def test_gate_accepts_approved_plan():
    seed = {"compile_metadata": {
        "physics_validated": True, "plan_approved": True,
    }}
    ok, msg = check_plan_approval(seed, allow_unapproved=False)
    assert ok is True
    assert msg == ""


def test_gate_allows_unapproved_override():
    ok, msg = check_plan_approval({}, allow_unapproved=True)
    assert ok is True
    assert msg == ""


def test_gate_treats_truthy_non_bool_as_unapproved():
    """Only strict True unlocks — 'yes', 1, etc. do not.

    Protects against sloppy hand-edits to concept_seed.json.
    """
    seed = {"compile_metadata": {"plan_approved": "yes"}}
    ok, _ = check_plan_approval(seed, allow_unapproved=False)
    assert ok is False
