"""Tests for the Story Brief, claim ledger, gap policy, and sheets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validate

from src.planning import story_brief as sb
from src.planning.gap_filler import propose_options
from src.planning.session_extractor import extract_claims
from workflows.idea_session_capture import IdeaSessionCapture


def _seed_minimal(brief: dict) -> dict:
    sb.add_claim(brief, entity_type="intent", field="one_sentence_pitch",
                 value="A retired spy is pulled back in by her daughter.")
    sb.add_claim(brief, entity_type="intent", field="reader_promise",
                 value="A spy thriller with an earned emotional ending.")
    sb.add_claim(brief, entity_type="intent", field="emotional_core",
                 value="Reckoning with a life lived in lies.")
    sb.add_claim(brief, entity_type="plot", field="premise",
                 value="Mara wants to protect her daughter, but the agency wants the daughter first.")
    sb.add_claim(brief, entity_type="theme", field="question",
                 value="Can you love someone without trying to save them?")
    sb.add_claim(brief, entity_type="voice", field="pov",
                 value="Close third, single POV, past tense.")
    sb.add_claim(brief, entity_type="character", entity_id="mara", field="name",
                 value="Mara Vance")
    sb.add_claim(brief, entity_type="character", entity_id="mara", field="role",
                 value="Protagonist")
    sb.add_claim(brief, entity_type="character", entity_id="mara", field="want",
                 value="To get her daughter out of the country.")
    sb.add_claim(brief, entity_type="character", entity_id="mara", field="need",
                 value="To stop treating love as a security operation.")
    return brief


def test_new_brief_has_essential_gaps():
    brief = sb.new_brief("T", "F")
    gaps = sb.detect_gaps(brief)
    assert any(g["gap_id"] == "intent:book:reader_promise" for g in gaps)
    assert any(g["gap_id"] == "character:protagonist:name" for g in gaps)
    assert sb.coverage(brief)["ready_for_expand"] is False
    assert sb.coverage(brief)["ready_for_sheets"] is False


def test_confirmed_claim_supersedes_previous_value():
    brief = sb.new_brief("T", "F")
    first = sb.add_claim(brief, entity_type="intent", field="reader_promise",
                         value="A romance.")
    second = sb.add_claim(brief, entity_type="intent", field="reader_promise",
                          value="A spy thriller.")
    assert sb.get_claim(brief, first["claim_id"])["status"] == "superseded"
    assert sb.resolve_value(brief, "intent", "book", "reader_promise") == "A spy thriller."
    assert second["status"] == "confirmed"


def test_inferred_claim_is_proposed_and_needs_confirmation():
    brief = sb.new_brief("T", "F")
    claim = sb.add_claim(
        brief, entity_type="character", entity_id="mara", field="want",
        value="To clear her name.", origin="inferred",
    )
    assert claim["status"] == "proposed"
    assert claim["confidence"] == "inferred"
    confirmed = sb.confirm_claim(brief, claim["claim_id"])
    assert confirmed["status"] == "confirmed"
    assert confirmed["confidence"] == "explicit"


def test_delegated_claim_can_flow_downstream():
    brief = sb.new_brief("T", "F")
    claim = sb.add_claim(
        brief, entity_type="intent", field="reader_promise",
        value="A tense spy story.", origin="delegated",
    )
    assert claim["status"] == "confirmed"
    assert claim["origin"] == "delegated"


def test_minimal_brief_becomes_ready():
    brief = _seed_minimal(sb.new_brief("T", "F"))
    coverage = sb.coverage(brief)
    assert coverage["ready_for_expand"] is True
    assert coverage["gaps_essential"] == 0


def test_character_gaps_follow_tier():
    brief = sb.new_brief("T", "F")
    sb.add_claim(brief, entity_type="character", entity_id="mara", field="name",
                 value="Mara")
    sb.add_claim(brief, entity_type="character", entity_id="mara", field="tier",
                 value="supporting")
    gaps = [g for g in sb.detect_gaps(brief) if g["entity_id"] == "mara"]
    fields = {g["field"] for g in gaps}
    assert "want" in fields
    assert "need" not in fields


def test_questions_become_gaps():
    brief = sb.new_brief("T", "F")
    sb.add_question(
        brief, entity_type="world", entity_id="world", field="canon_status",
        question="Is this our world or a secondary world?", blocking=True,
    )
    gaps = sb.detect_gaps(brief)
    assert any(g.get("question_id") for g in gaps)


def test_propose_options_are_specific():
    brief = sb.new_brief("T", "F")
    sb.add_claim(brief, entity_type="character", entity_id="mara", field="name",
                 value="Mara")
    gap = next(g for g in sb.detect_gaps(brief) if g["gap_id"] == "character:mara:want")
    options = propose_options(gap, brief)
    assert len(options) == 3
    assert all(len(option) > 20 for option in options)


def test_character_sheet_contains_status_and_open_gaps():
    brief = _seed_minimal(sb.new_brief("T", "F"))
    sheet = sb.render_character_sheet(brief, "mara")
    assert sheet.startswith("---\n")
    assert "name: Mara Vance" in sheet
    assert "status: draft" in sheet  # lie/ghost/arc/voice still open
    assert "## Open Gaps" in sheet
    assert "## Want" in sheet


def test_write_sheets_creates_review_files(tmp_path: Path):
    brief = _seed_minimal(sb.new_brief("T", "F"))
    paths = sb.write_sheets(brief, tmp_path / "sheets")
    names = {p.name for p in paths}
    assert "mara.md" in names
    assert "plot.md" in names
    assert "world.md" in names
    assert "review.md" in names
    assert (tmp_path / "sheets" / "characters" / "mara.md").exists()


def test_capture_story_brief_round_trip(tmp_path: Path):
    cap = IdeaSessionCapture("Test Book", "Original", base_dir=str(tmp_path))
    cap.init_workspace()
    assert cap.story_brief_path.exists()
    claim = cap.add_claim(
        entity_type="intent", field="reader_promise",
        value="A spy thriller with an earned ending.",
    )
    assert claim["status"] == "confirmed"
    brief = json.loads(cap.story_brief_path.read_text(encoding="utf-8"))
    assert brief["claims"][0]["field"] == "reader_promise"


def test_capture_fill_gap_delegates_scaffold(tmp_path: Path):
    cap = IdeaSessionCapture("Test Book", "Original", base_dir=str(tmp_path))
    cap.init_workspace()
    claim = cap.fill_gap("intent:book:reader_promise", mode="delegate")
    assert claim["origin"] == "delegated"
    assert claim["status"] == "confirmed"
    assert cap.story_coverage()["claims_confirmed"] == 1


def test_capture_write_review_sheets(tmp_path: Path):
    cap = IdeaSessionCapture("Test Book", "Original", base_dir=str(tmp_path))
    cap.init_workspace()
    cap.add_claim(
        entity_type="character", entity_id="mara", field="name", value="Mara Vance",
    )
    paths = cap.write_review_sheets()
    assert paths
    assert (cap.sheets_dir / "characters" / "mara.md").exists()


def test_expand_uses_story_brief_character(tmp_path: Path):
    cap = IdeaSessionCapture("Test Book", "Original", base_dir=str(tmp_path))
    cap.init_workspace()
    cap.set_north_star(one_sentence_pitch="A retired spy is pulled back in by her daughter.")
    cap.add_decision(surface="characters", topic="protagonist", decision="Mara", confidence="settled")
    cap.add_claim(
        entity_type="character", entity_id="mara", field="name", value="Mara Vance",
    )
    cap.add_claim(
        entity_type="character", entity_id="mara", field="role", value="Protagonist",
    )
    result = cap.expand_to_surface_drafts(surfaces=["characters"])
    assert result["written"]
    characters = json.loads((cap.paths.workflows_dir / "characters.json").read_text(encoding="utf-8"))
    assert characters["ensemble_cast"][0]["name"] == "Mara Vance"


def test_expand_with_populated_brief_stays_schema_valid(tmp_path: Path):
    cap = IdeaSessionCapture("Test Book", "Original", base_dir=str(tmp_path))
    cap.init_workspace()
    cap.set_north_star(one_sentence_pitch="A retired spy is pulled back in by her daughter.")
    cap.add_decision(surface="characters", topic="protagonist", decision="Mara", confidence="settled")
    cap.add_claim(entity_type="intent", field="one_sentence_pitch",
                  value="A retired spy is pulled back in by her daughter.")
    cap.add_claim(entity_type="intent", field="reader_promise",
                  value="A spy thriller with an earned emotional ending.")
    cap.add_claim(entity_type="intent", field="emotional_core",
                  value="Reckoning with a life lived in lies.")
    cap.add_claim(entity_type="plot", field="premise",
                  value="Mara wants to protect her daughter, but the agency wants the daughter first.")
    cap.add_claim(entity_type="plot", field="inciting_incident",
                  value="Her daughter is taken.")
    cap.add_claim(entity_type="theme", field="question",
                  value="Can you love someone without trying to save them?")
    cap.add_claim(entity_type="voice", field="pov",
                  value="Close third, single POV, past tense.")
    cap.add_claim(entity_type="character", entity_id="mara", field="name",
                  value="Mara Vance")
    cap.add_claim(entity_type="character", entity_id="mara", field="role",
                  value="Protagonist")
    result = cap.expand_to_surface_drafts()
    assert len(result["written"]) == 6  # five JSON artifacts + scene-card intent



def test_story_brief_matches_schema():
    schema = json.loads(
        Path("schemas/story_brief.json").read_text(encoding="utf-8")
    )
    brief = _seed_minimal(sb.new_brief("T", "F"))
    validate(instance=brief, schema=schema)


class _FakeRouter:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def complete_structured(self, role, messages):
        self.calls.append((role, messages))
        return self.payload


@pytest.mark.asyncio
async def test_extractor_returns_proposals_only():
    brief = sb.new_brief("T", "F")
    router = _FakeRouter({
        "claims": [
            {
                "entity_type": "character",
                "entity_id": "Mara Vance",
                "field": "want",
                "value": "To get her daughter out of the country.",
                "confidence": "explicit",
                "source_quote": "she just wants out",
            },
            {"entity_type": "nonsense", "field": "x", "value": "y"},
        ]
    })
    claims = await extract_claims(router, "Mara wants out.", brief)
    assert len(claims) == 1
    assert claims[0]["entity_id"] == "Mara Vance"
    assert claims[0]["confidence"] == "explicit"
    assert router.calls[0][0] == "story_brief_extractor"


@pytest.mark.asyncio
async def test_capture_infer_claims_persists_proposals(tmp_path: Path):
    cap = IdeaSessionCapture("Test Book", "Original", base_dir=str(tmp_path))
    cap.init_workspace()
    router = _FakeRouter({
        "claims": [{
            "entity_type": "character",
            "entity_id": "mara",
            "field": "lie_believed",
            "value": "That distance keeps people safe.",
            "confidence": "inferred",
            "source_quote": "I keep people at arm's length",
        }]
    })
    added = await cap.infer_claims("I keep people at arm's length.", router)
    assert len(added) == 1
    assert added[0]["status"] == "proposed"
    assert added[0]["origin"] == "inferred"
    brief = cap.load_story_brief()
    assert brief["claims"][0]["source_quote"]


@pytest.mark.asyncio
async def test_fill_gap_with_model_uses_first_option(tmp_path: Path):
    cap = IdeaSessionCapture("Test Book", "Original", base_dir=str(tmp_path))
    cap.init_workspace()
    router = _FakeRouter({"options": [
        "A tense spy thriller with an earned ending.",
        "A slower character study.",
    ]})
    claim = await cap.fill_gap_with_model(
        "intent:book:reader_promise", router, mode="delegate",
    )
    assert claim["origin"] == "delegated"
    assert claim["value"].startswith("A tense spy thriller")


def test_cli_accepts_options_after_subcommands(tmp_path: Path, capsys):
    from scripts.story_brief import main as cli

    common = ["--title", "CLI Book", "--franchise", "Original",
              "--base-dir", str(tmp_path)]
    assert cli(["init", *common]) == 0
    assert cli(["status", *common]) == 0
    assert cli([
        "claim", "add", *common,
        "--type", "intent", "--field", "reader_promise",
        "--value", "A tense spy story with an earned ending.",
    ]) == 0
    out = capsys.readouterr().out
    assert "Story Brief" in out
    assert "clm_" in out



