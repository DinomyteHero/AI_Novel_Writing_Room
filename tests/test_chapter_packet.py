"""Tests for ChapterPacket + ChapterPacketCompiler (Slice 2).

Covers:
- compile_base produces expected fields from blueprint + seed.
- Base is immutable after creation (frozen dataclass).
- compile_overlay never mutates the base (base.overlay_version stays 0).
- overlay_version increments monotonically per overlay.
- Overlay carries scene_card + gap notes when story_state is wired.
- render_markdown preserves section ordering required by the parity test.
- to_json / from_json roundtrip.
- Slice-3/4/5 collaborators (promise_ledger, continuity_log, sociogram) are
  treated as optional \u2014 None keeps the relevant packet fields empty.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.pipeline.chapter_packet import ChapterPacket, ChapterPacketCompiler


@pytest.fixture
def blueprint_ch1() -> dict:
    return {
        "chapter_number": 1,
        "chapter_mission": "Establish the wrongness",
        "chapter_turn": "Passive unease becomes active pursuit",
        "structural_phase": "setup",
        "pov_allocation": ["Ben Skywalker"],
        "pacing_curve": "rising",
        "scene_plan": [
            {"scene_number": 1, "role": "hook", "purpose": "physical failure in sparring"},
            {"scene_number": 2, "role": "reveal", "purpose": "Luke validates wrongness"},
            {"scene_number": 3, "role": "decision", "purpose": "departure"},
        ],
        "reveal_payload": ["R01"],
        "hook_movements": {"planted": ["H01"], "advanced": [], "resolved": []},
        "subplot_obligations": ["SP-A"],
        "relationship_turns": [
            {"dyad": "Ben/Luke", "from": "distance", "to": "private alliance"},
        ],
        "exit_vector": "Ben in hyperspace, wrongness pulling not just pointing",
    }


@pytest.fixture
def concept_seed() -> dict:
    return {
        "meta": {"project_title": "Test Book", "franchise": "test"},
        "canon_pillars": [
            {"title": "Force wrongness", "body": "Wrongness is auditory, not visual"},
        ],
        "subplots": [
            {
                "subplot_id": "SP-A",
                "name": "The failing seal",
                "function": "Ben follows the wrongness to its source.",
            },
        ],
        "hooks": [
            {
                "hook_id": "H01",
                "description": "The wrongness has a direction.",
            },
        ],
        "revelation_schedule": [
            {
                "revelation_id": "R01",
                "what": "The wrongness in the Force has a source.",
            },
        ],
    }


@pytest.fixture
def compiler(blueprint_ch1, concept_seed) -> ChapterPacketCompiler:
    return ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
    )


def test_compile_base_hydrates_mission_and_pressure(compiler):
    base = compiler.compile_base(chapter_number=1)
    assert base.chapter_number == 1
    assert base.overlay_version == 0
    assert "wrongness" in base.mission
    assert "active pursuit" in base.chapter_turn
    assert len(base.pressure_ladder) == 3
    assert base.pressure_ladder[0]["scene_number"] == 1
    assert base.pressure_ladder[0]["label"] == "hook"
    assert base.pov_arc_pressure["pov_character"] == "Ben Skywalker"
    assert base.pov_arc_pressure["structural_phase"] == "setup"


def test_compile_base_includes_canon_slices(compiler):
    base = compiler.compile_base(chapter_number=1)
    titles = [s["title"] for s in base.canon_slices]
    assert "Force wrongness" in titles


def test_compile_base_builds_next_scene_obligations(compiler):
    base = compiler.compile_base(chapter_number=1)
    kinds = [o["kind"] for o in base.next_scene_obligations]
    assert "subplot" in kinds
    assert "relationship_turn" in kinds
    assert "reveal" in kinds
    assert "hook_planted" in kinds


def test_compile_base_resolves_model_facing_planning_ids(compiler):
    base = compiler.compile_base(chapter_number=1)
    notes = [o["note"] for o in base.next_scene_obligations]

    assert "The failing seal: Ben follows the wrongness to its source." in notes
    assert "The wrongness has a direction." in notes
    assert "The wrongness in the Force has a source." in notes
    assert "SP-A" not in notes
    assert "H01" not in notes
    assert "R01" not in notes


def test_overlay_omits_machine_tracking_ids_from_scene_card_json(compiler):
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={
            "chapter_number": 1,
            "scene_number": 1,
            "pov_character": "Ben",
            "mission": "test",
            "active_subplots": ["SP-A"],
            "promises_planted": ["PP01"],
            "hook_actions": [{"hook_id": "H01", "action": "plant"}],
            "revelations": ["R01"],
        },
    )

    rendered = overlay.render_markdown()
    scene_card_block = rendered.split("## Scene Card", 1)[1].split("```", 2)[1]
    assert "active_subplots" not in scene_card_block
    assert "promises_planted" not in scene_card_block
    assert "hook_actions" not in scene_card_block
    assert "revelations" not in scene_card_block


def test_compile_base_raises_for_missing_chapter(compiler):
    with pytest.raises(KeyError):
        compiler.compile_base(chapter_number=99)


def test_base_is_frozen_dataclass(compiler):
    base = compiler.compile_base(chapter_number=1)
    with pytest.raises(Exception):  # FrozenInstanceError subclasses AttributeError
        base.mission = "something else"
    with pytest.raises(Exception):
        base.overlay_version = 5


def test_overlay_does_not_mutate_base(compiler):
    base = compiler.compile_base(chapter_number=1)
    scene_card = {
        "chapter_number": 1, "scene_number": 1,
        "pov_character": "Ben", "mission": "spar and fail",
    }
    overlay = compiler.compile_overlay(base=base, scene_card=scene_card)
    # Base unchanged
    assert base.overlay_version == 0
    assert base.scene_card == {}
    # Overlay composed base + scene
    assert overlay.overlay_version == 1
    assert overlay.scene_number == 1
    assert overlay.scene_card["pov_character"] == "Ben"
    # Structural fields carry through
    assert overlay.mission == base.mission
    assert overlay.chapter_number == base.chapter_number
    assert overlay.pressure_ladder == base.pressure_ladder


def test_overlay_surfaces_scene_card_pov_arc_phase(compiler):
    """Scene-card pov_arc_phase + arc_phase_transition flow into pov_arc_pressure.

    Closes the gap where the chapter packet only carried chapter-level
    structural_phase from the blueprint; the drafter now sees the POV
    character's current Weiland arc phase + any transition this scene
    triggers.
    """
    base = compiler.compile_base(chapter_number=1)
    scene_card = {
        "chapter_number": 1,
        "scene_number": 1,
        "pov_character": "Ben",
        "mission": "spar and fail",
        "pov_arc_phase": "lie_reinforced",
        "arc_phase_transition": "lie_challenged",
    }
    overlay = compiler.compile_overlay(base=base, scene_card=scene_card)
    # Chapter-level fields preserved
    assert overlay.pov_arc_pressure["structural_phase"] == "setup"
    # Scene-level fields surfaced
    assert overlay.pov_arc_pressure["pov_arc_phase"] == "lie_reinforced"
    assert overlay.pov_arc_pressure["arc_phase_transition"] == "lie_challenged"
    # Rendered markdown carries them under the POV Arc Pressure heading
    rendered = overlay.render_markdown()
    arc_section = rendered.split("### POV Arc Pressure", 1)[1].split("###", 1)[0]
    assert "pov_arc_phase: lie_reinforced" in arc_section
    assert "arc_phase_transition: lie_challenged" in arc_section
    # Base is not mutated
    assert "pov_arc_phase" not in base.pov_arc_pressure


def test_overlay_pov_arc_phase_falls_back_to_voice_permissions(compiler):
    """When top-level pov_arc_phase is empty, voice permissions block wins."""
    base = compiler.compile_base(chapter_number=1)
    scene_card = {
        "chapter_number": 1,
        "scene_number": 1,
        "pov_character": "Ben",
        "mission": "spar and fail",
        "scene_voice_permissions": {
            "pov_arc_phase": "moment_of_truth",
        },
    }
    overlay = compiler.compile_overlay(base=base, scene_card=scene_card)
    assert overlay.pov_arc_pressure["pov_arc_phase"] == "moment_of_truth"


def test_overlay_omits_pov_arc_fields_when_scene_card_silent(compiler):
    """No scene-level Weiland fields → packet omits them entirely (no empty noise)."""
    base = compiler.compile_base(chapter_number=1)
    scene_card = {
        "chapter_number": 1,
        "scene_number": 1,
        "pov_character": "Ben",
        "mission": "spar and fail",
    }
    overlay = compiler.compile_overlay(base=base, scene_card=scene_card)
    assert "pov_arc_phase" not in overlay.pov_arc_pressure
    assert "arc_phase_transition" not in overlay.pov_arc_pressure
    # Chapter-level pressure still present
    assert overlay.pov_arc_pressure["structural_phase"] == "setup"


def test_overlay_version_monotonic(compiler):
    base = compiler.compile_base(chapter_number=1)
    scene1 = {"chapter_number": 1, "scene_number": 1}
    scene2 = {"chapter_number": 1, "scene_number": 2}
    o1 = compiler.compile_overlay(base=base, scene_card=scene1)
    o2 = compiler.compile_overlay(base=base, scene_card=scene2)
    assert o1.overlay_version == 1
    assert o2.overlay_version == 1  # each overlay composes base (overlay_version 0)
    # Sequential overlays off a previous overlay also increment.
    o3 = compiler.compile_overlay(base=o2, scene_card={"chapter_number": 1, "scene_number": 3})
    assert o3.overlay_version == 2


def test_overlay_pulls_open_gap_notes(blueprint_ch1, concept_seed):
    story_state = MagicMock()
    story_state.list_open_gaps.return_value = [
        {
            "gap_id": "gap_test_1",
            "isolated_scene": "ch01_sc02",
            "blocker_categories": ["CANON_BLOCKER"],
            "affected_scenes": ["ch01_sc03"],
            "created_at": "2026-04-20T10:00:00+00:00",
            "status": "open",
        }
    ]
    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
        story_state=story_state,
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 3},
    )
    assert len(overlay.trusted_state_gap_notes) == 1
    note = overlay.trusted_state_gap_notes[0]
    assert note["gap_id"] == "gap_test_1"
    story_state.list_open_gaps.assert_called_with(chapter_number=1)


def test_overlay_gap_notes_render_with_template(blueprint_ch1, concept_seed):
    story_state = MagicMock()
    story_state.list_open_gaps.return_value = [
        {
            "gap_id": "gap_test_1",
            "isolated_scene": "ch01_sc02",
            "blocker_categories": ["CANON_BLOCKER"],
            "affected_scenes": ["ch01_sc03"],
            "created_at": "2026-04-20T10:00:00+00:00",
            "status": "open",
        }
    ]
    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
        story_state=story_state,
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 3},
    )
    rendered = overlay.render_markdown()
    assert "Narrative Continuity Gaps" in rendered
    assert "ch01_sc02" in rendered
    assert "isolated" in rendered.lower()
    # The template must steer the drafter toward narrative gap-writing, not
    # confabulation.
    assert "unclear" in rendered.lower() or "write around" in rendered.lower()


def test_render_markdown_section_ordering(compiler):
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 1, "pov_character": "Ben"},
    )
    md = overlay.render_markdown()
    # Ordering invariants checked by the parity test in tests/test_packet_parity.py:
    # packet header before scene card; scene card before flat snapshot.
    i_pkt = md.find("## Chapter Packet")
    i_card = md.find("## Scene Card")
    assert i_pkt != -1
    assert i_card != -1
    assert i_pkt < i_card


def test_to_json_roundtrip(compiler):
    base = compiler.compile_base(chapter_number=1)
    payload = base.to_json()
    assert payload["overlay_version"] == 0
    assert payload["mission"] == base.mission
    # flat_context_snapshot is stripped on to_json() to avoid duplicating
    # the legacy ContextAssembler payload on disk.
    assert "flat_context_snapshot" not in payload
    roundtripped = ChapterPacket.from_json(payload)
    assert roundtripped.chapter_number == base.chapter_number
    assert roundtripped.mission == base.mission
    assert roundtripped.pressure_ladder == base.pressure_ladder


def test_slice3_5_hooks_empty_when_collaborators_none(compiler):
    base = compiler.compile_base(chapter_number=1)
    assert base.active_promises == []
    assert base.continuity_events == []
    assert base.relationship_context == {}


def test_slice3_active_promises_pulled_when_ledger_wired(blueprint_ch1, concept_seed):
    promise_ledger = MagicMock()
    promise_ledger.active_for_chapter.return_value = [
        {"promise_id": "P1", "setup_scene": "ch01_sc01",
         "due_by_scene": "ch05_close", "status": "open"},
    ]
    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
        promise_ledger=promise_ledger,
    )
    base = compiler.compile_base(chapter_number=1)
    assert base.active_promises == [
        {"promise_id": "P1", "setup_scene": "ch01_sc01",
         "due_by_scene": "ch05_close", "status": "open"},
    ]


def test_slice3_overlay_uses_list_top_urgent_with_real_ledger(
    blueprint_ch1, concept_seed,
):
    """Overlay must call list_top_urgent(at_scene=...) \u2014 not active_for_chapter \u2014
    so the drafter sees urgency-ranked promises for the *current* scene (spec \u00a77.3).
    """
    from src.memory.promise_ledger import PromiseLedger

    ledger = PromiseLedger(db_path=":memory:")
    ledger.initialize_from_planning(
        concept_seed={
            "story_physics": {
                "promise_payoff_ledger": [
                    {"promise_id": "FAR", "description": "Far deadline",
                     "planted_chapter": 1, "payoff_chapter": 9,
                     "type": "plot", "status": "unfulfilled"},
                    {"promise_id": "LATE", "description": "Already overdue",
                     "planted_chapter": 1, "payoff_chapter": 1,
                     "type": "plot", "status": "unfulfilled"},
                ],
            },
        },
        scene_cards=[],
    )
    # Leave setup so FAR and LATE both have setup_scene=ch01_sc01, due at
    # ch09_sc99 and ch01_sc99 respectively. At ch01_sc02 the LATE promise is
    # already overdue and must rank first.

    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
        promise_ledger=ledger,
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 2},
    )
    ids = [e["promise_id"] for e in overlay.active_promises]
    assert ids == ["LATE", "FAR"]
    # The LATE promise has passed its due_by_scene ch01_sc99? at ch01_sc02
    # sc02 < sc99 so LATE is still active-with-future-deadline from the
    # ledger's point of view. Distance sorts it *before* FAR. The overdue
    # marker only fires when sc index passes sc99, so neither entry is
    # overdue here \u2014 but the ranking proves list_top_urgent is the path.
    assert overlay.active_promises[0].get("status") != "paid"
    # active_promises_total_count tails the top-5 list.
    assert overlay.active_promises_total_count == 2
    ledger.close()


def test_slice3_overlay_renders_overdue_under_advisory_heading(
    blueprint_ch1, concept_seed,
):
    from src.memory.promise_ledger import PromiseLedger

    ledger = PromiseLedger(db_path=":memory:")
    # Hand-seed a promise that is explicitly overdue at the target scene.
    from datetime import datetime, timezone
    import json
    now = datetime.now(timezone.utc).isoformat()
    ledger.conn.execute(
        """
        INSERT INTO promise_ledger (
            promise_id, description, promise_type, setup_scene, payoff_scene,
            due_by_scene, status, progression_log, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("LATE", "Already overdue", "mystery", "ch01_sc01", None,
         "ch01_sc01", "progressing", json.dumps([]), now, now),
    )
    ledger.conn.commit()

    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
        promise_ledger=ledger,
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(
        base=base,
        scene_card={"chapter_number": 1, "scene_number": 5},
    )
    # The renderer splits overdue into its own heading with the advisory.
    assert "do not force payoff" in overlay.rendered_markdown
    # Overdue promise carries status='overdue' in the list.
    overdue_entries = [
        p for p in overlay.active_promises if p.get("status") == "overdue"
    ]
    assert len(overdue_entries) == 1
    assert overdue_entries[0]["promise_id"] == "LATE"
    ledger.close()


def test_slice5_relationship_context_uses_context_for_scene(
    blueprint_ch1, concept_seed,
):
    """Overlay prefers ``sociogram.context_for_scene`` (characters_present
    filter) over the chapter-scoped ``snapshot_for_chapter`` (spec \u00a79.5)."""
    from src.memory.sociogram import Sociogram

    graph = Sociogram(db_path=":memory:")
    try:
        graph.initialize_from_planning(concept_seed={
            "relationship_arcs": [
                {"dyad": "Ben Skywalker/Luke Skywalker", "arc_type": "reconciling"},
                {"dyad": "Ben Skywalker/Desh Lor", "arc_type": "deepening"},
                {"dyad": "Desh Lor/Luke Skywalker", "arc_type": "stable_opposition"},
            ],
        })
        compiler = ChapterPacketCompiler(
            concept_seed=concept_seed,
            blueprints={1: blueprint_ch1},
            sociogram=graph,
        )
        overlay = compiler.compile_overlay(
            base=compiler.compile_base(chapter_number=1),
            scene_card={
                "chapter_number": 1, "scene_number": 2,
                "pov_character": "Ben Skywalker",
                "characters_present": ["Ben Skywalker", "Luke Skywalker"],
            },
        )
        dyads = {k for k in overlay.relationship_context if not k.startswith("_")}
        assert dyads == {
            "Ben Skywalker \u2502 Luke Skywalker",
            "Luke Skywalker \u2502 Ben Skywalker",
        }
        # Dilution tail: 6 total directed edges \u2013 2 surfaced = 4 unshown.
        assert overlay.relationship_context["_unshown_edge_count"] == 4
        # Markdown renderer includes the scene anchor + unshown tail.
        assert "Relationship context" in overlay.rendered_markdown
        assert "+4 other edges" in overlay.rendered_markdown
    finally:
        graph.close()


def test_slice4_continuity_events_filtered_to_pov_and_present_chars(
    blueprint_ch1, concept_seed,
):
    """Overlay must narrow chapter-level continuity events to those whose
    subject is the POV or in characters_present (spec \u00a78.5). Prior-scene
    events from unrelated characters must not clutter the packet.
    """
    from src.memory.continuity_log import ContinuityLog

    log = ContinuityLog(db_path=":memory:")
    try:
        log.append({
            "event_type": "location_change", "scene_id": "ch01_sc01",
            "subject": "Ben Skywalker",
            "details": {"from_location": "home", "to_location": "hangar"},
            "confidence": 0.95, "extractor_version": "v0.1",
        })
        log.append({
            "event_type": "location_change", "scene_id": "ch01_sc01",
            "subject": "Lando",
            "details": {"from_location": "bar", "to_location": "landing pad"},
            "confidence": 0.95, "extractor_version": "v0.1",
        })

        compiler = ChapterPacketCompiler(
            concept_seed=concept_seed,
            blueprints={1: blueprint_ch1},
            continuity_log=log,
        )
        base = compiler.compile_base(chapter_number=1)
        overlay = compiler.compile_overlay(
            base=base,
            scene_card={
                "chapter_number": 1, "scene_number": 2,
                "pov_character": "Ben Skywalker",
                "characters_present": ["Ben Skywalker"],
            },
        )
        subjects = {ev["subject"] for ev in overlay.continuity_events}
        assert subjects == {"Ben Skywalker"}
    finally:
        log.close()


def test_slice4_overlay_does_not_surface_events_from_current_scene(
    blueprint_ch1, concept_seed,
):
    """An event from the scene being drafted must not appear in its own
    overlay \u2014 only strictly-prior events propagate (spec \u00a78.1)."""
    from src.memory.continuity_log import ContinuityLog

    log = ContinuityLog(db_path=":memory:")
    try:
        log.append({
            "event_type": "location_change", "scene_id": "ch01_sc02",
            "subject": "Ben Skywalker",
            "details": {"from_location": "a", "to_location": "b"},
            "confidence": 0.95, "extractor_version": "v0.1",
        })
        compiler = ChapterPacketCompiler(
            concept_seed=concept_seed,
            blueprints={1: blueprint_ch1},
            continuity_log=log,
        )
        overlay = compiler.compile_overlay(
            base=compiler.compile_base(chapter_number=1),
            scene_card={
                "chapter_number": 1, "scene_number": 2,
                "pov_character": "Ben Skywalker",
                "characters_present": ["Ben Skywalker"],
            },
        )
        assert overlay.continuity_events == []
    finally:
        log.close()


def test_slice3_active_promises_total_count_reflects_true_total(
    blueprint_ch1, concept_seed,
):
    """Spec \u00a77.3: the tail count is the *true* active count even when
    list_top_urgent caps at 5."""
    from src.memory.promise_ledger import PromiseLedger

    ledger = PromiseLedger(db_path=":memory:")
    from datetime import datetime, timezone
    import json
    now = datetime.now(timezone.utc).isoformat()
    for i in range(1, 9):
        ledger.conn.execute(
            """
            INSERT INTO promise_ledger (
                promise_id, description, promise_type, setup_scene, payoff_scene,
                due_by_scene, status, progression_log, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"P{i}", f"Promise {i}", "plot", "ch01_sc01", None,
             f"ch0{i+1}_sc01", "progressing", json.dumps([]), now, now),
        )
    ledger.conn.commit()

    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint_ch1},
        promise_ledger=ledger,
    )
    overlay = compiler.compile_overlay(
        base=compiler.compile_base(chapter_number=1),
        scene_card={"chapter_number": 1, "scene_number": 2},
    )
    assert len(overlay.active_promises) == 5
    assert overlay.active_promises_total_count == 8
    assert "5 of 8" in overlay.rendered_markdown
    ledger.close()
