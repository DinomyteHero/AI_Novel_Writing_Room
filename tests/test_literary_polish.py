from unittest.mock import AsyncMock, MagicMock

from src.agents.literary_polish import LiteraryPolish


def _context():
    return {
        "source_prose": "Draft prose.",
        "scene_card": {
            "chapter_number": 5,
            "scene_number": 2,
            "pov_character": "Ben Skywalker",
            "characters_present": ["Ben Skywalker", "Sera", "Kael"],
            "closing_hook": "Ben leaves with the archive unsettled.",
        },
        "generation_brief": {"scene_objective": "Keep the archive revelation bounded."},
        "continuity_lockfile": {
            "scene_id": "ch05_sc02",
            "locked_facts": [{"id": "count", "text": "Twelve anchors."}],
            "withheld_information": [{"path": "$.turning", "text": "Name deferred."}],
        },
        "motif_ledger": {"motifs": [{"term": "wrongness", "count": 4}]},
        "copydesk_report": {"flags": [{"code": "em_dash_density"}]},
        "voltage_report": {"total_score": 17},
        "scene_contract": {"scene_id": "ch05_sc02", "checks": []},
        "scene_contract_validation": {"passed": True},
    }


async def test_literary_polish_prompt_carries_lockfile_and_forbids_invention():
    router = MagicMock()
    router.complete = AsyncMock(return_value="Polished prose.")
    agent = LiteraryPolish(router)

    await agent.run(_context())

    content = router.complete.await_args.args[1][-1]["content"]
    assert "Continuity Lockfile" in content
    assert "Twelve anchors" in content
    assert "Motif Ledger" in content
    assert "Forbidden changes" in content
    assert "no new lore" in content
    assert "no reassigned dialogue ownership" in content


async def test_literary_polish_returns_clean_prose_without_fences():
    router = MagicMock()
    router.complete = AsyncMock(return_value="```markdown\nPolished prose.\n```")
    agent = LiteraryPolish(router)

    result = await agent.run(_context())

    assert result["prose"] == "Polished prose."
    assert result["was_literary_polished"] is True
