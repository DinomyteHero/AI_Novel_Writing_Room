"""Regression tests for the continuity guardrails added to the chapter packet:

  * book-scoped Timeline Anchor (from concept_seed.meta.timeline_anchors)
  * per-scene POV Knowledge Horizon (from scene_card.pov_knowledge_state)

Both must be no-ops when the source data omits the field (so books that do
not opt in — e.g. Ruusan, Betrayal — render nothing new), and both must
survive the base->overlay deepcopy without mutating the immutable base.
"""

from src.pipeline.chapter_packet import (
    ChapterPacketCompiler,
    _extract_pov_knowledge_horizon,
)

_BLUEPRINT = {"chapter_mission": "Do the thing.", "chapter_turn": "It turns."}


def _compiler(meta_extra=None):
    seed = {"meta": {"project_title": "T", **(meta_extra or {})}}
    return ChapterPacketCompiler(concept_seed=seed, blueprints={1: _BLUEPRINT})


# --------------------------------------------------------------- timeline anchor
def test_timeline_anchor_populated_from_seed():
    anchors = ["Story opens 47 ABY", "Ben is about 21 now"]
    base = _compiler({"timeline_anchors": anchors}).compile_base(chapter_number=1)
    assert base.timeline_anchor == anchors
    md = base.render_markdown()
    assert "### Timeline Anchor" in md
    assert "Ben is about 21 now" in md


def test_timeline_anchor_noop_when_seed_silent():
    base = _compiler().compile_base(chapter_number=1)
    assert base.timeline_anchor == []
    assert "### Timeline Anchor" not in base.render_markdown()


def test_timeline_anchor_carries_to_overlay():
    base = _compiler({"timeline_anchors": ["X"]}).compile_base(chapter_number=1)
    overlay = _compiler({"timeline_anchors": ["X"]}).compile_overlay(
        base=base, scene_card={"scene_number": 1, "pov_character": "Ben"}
    )
    assert overlay.timeline_anchor == ["X"]
    assert "### Timeline Anchor" in overlay.render_markdown()


# ----------------------------------------------------------- pov knowledge horizon
def test_pov_knowledge_horizon_populated_from_scene_card():
    card = {
        "scene_number": 1,
        "pov_character": "Ben",
        "pov_knowledge_state": {
            "known_facts": ["the message"],
            "blocked_facts": ["the Iresh destination"],
            "uncertainty_notes": "only knows the message",
        },
    }
    base = _compiler().compile_base(chapter_number=1)
    overlay = _compiler().compile_overlay(base=base, scene_card=card)
    assert overlay.pov_knowledge_horizon["blocked_facts"] == ["the Iresh destination"]
    md = overlay.render_markdown()
    assert "### POV Knowledge Horizon" in md
    assert "does NOT yet know" in md
    assert "the Iresh destination" in md


def test_pov_knowledge_horizon_noop_when_card_silent():
    base = _compiler().compile_base(chapter_number=1)
    overlay = _compiler().compile_overlay(
        base=base, scene_card={"scene_number": 1, "pov_character": "Ben"}
    )
    assert overlay.pov_knowledge_horizon == {}
    assert "### POV Knowledge Horizon" not in overlay.render_markdown()
    # base never carries the per-scene field
    assert base.pov_knowledge_horizon == {}


def test_extract_pov_knowledge_horizon_drops_empties():
    assert _extract_pov_knowledge_horizon({}) == {}
    assert _extract_pov_knowledge_horizon({"pov_knowledge_state": "nope"}) == {}
    got = _extract_pov_knowledge_horizon(
        {"pov_knowledge_state": {"known_facts": [], "blocked_facts": ["a"], "uncertainty_notes": "  "}}
    )
    assert got == {"blocked_facts": ["a"]}


def test_overlay_does_not_mutate_base_horizon():
    base = _compiler({"timeline_anchors": ["X"]}).compile_base(chapter_number=1)
    _compiler({"timeline_anchors": ["X"]}).compile_overlay(
        base=base,
        scene_card={"scene_number": 1, "pov_knowledge_state": {"blocked_facts": ["secret"]}},
    )
    # The base is frozen + deepcopied; the overlay's horizon must not leak back.
    assert base.pov_knowledge_horizon == {}
    assert base.timeline_anchor == ["X"]
