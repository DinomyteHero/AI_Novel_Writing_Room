"""Slice 5 Sociogram unit tests (spec §9.6)."""

from __future__ import annotations

import pytest

from src.memory.sociogram import MAX_ABS_DELTA, Sociogram


@pytest.fixture
def graph() -> Sociogram:
    return Sociogram(db_path=":memory:")


# --------------------------------------------------- initialize_from_planning


def test_initialize_from_relationship_arcs_seeds_both_directions(graph):
    seed = {
        "relationship_arcs": [
            {"dyad": "Ben/Luke", "arc_type": "reconciling",
             "arc_summary": "Father-son reconciliation"},
        ],
    }
    count = graph.initialize_from_planning(concept_seed=seed)
    # Two directed edges: Ben\u2192Luke and Luke\u2192Ben.
    assert count == 2
    forward = graph.get_edge("Ben", "Luke")
    backward = graph.get_edge("Luke", "Ben")
    assert forward is not None and backward is not None
    assert forward["arc_type"] == "enemies_to_allies"  # alias mapped


def test_initialize_idempotent_does_not_clobber_state(graph):
    seed = {
        "relationship_arcs": [
            {"dyad": "Ben/Luke", "arc_type": "stable_alliance"},
        ],
    }
    graph.initialize_from_planning(concept_seed=seed)
    graph.apply_delta(
        subject="Ben", obj="Luke", scene_id="ch01_sc01",
        trust_delta=0.3, source="scene_card",
    )
    graph.initialize_from_planning(concept_seed=seed)  # re-seed
    row = graph.get_edge("Ben", "Luke")
    # Scene-card delta preserved across re-seed.
    assert row["trust"] == 0.3


def test_initialize_from_ensemble_cast_uses_initial_state(graph):
    seed = {
        "ensemble_cast": [
            {
                "name": "A",
                "relationships": [
                    {"target": "B", "arc_type": "mentor_to_peer",
                     "initial_trust": 0.5, "initial_warmth": 0.3,
                     "initial_power": -0.2},
                ],
            },
        ],
    }
    graph.initialize_from_planning(concept_seed=seed)
    edge = graph.get_edge("A", "B")
    assert edge["trust"] == 0.5
    assert edge["warmth"] == 0.3
    assert edge["power_balance"] == -0.2


# ------------------------------------------------------------- apply_delta


def test_apply_delta_accumulates_and_clamps(graph):
    seed = {"relationship_arcs": [{"dyad": "A/B", "arc_type": "stable_alliance"}]}
    graph.initialize_from_planning(concept_seed=seed)
    # Apply max-cap three times; value should clamp at 1.0.
    for scene in ("ch01_sc01", "ch01_sc02", "ch01_sc03"):
        graph.apply_delta(
            subject="A", obj="B", scene_id=scene,
            trust_delta=MAX_ABS_DELTA, source="scene_card",
        )
    row = graph.get_edge("A", "B")
    assert row["trust"] == 1.0


def test_apply_delta_rejects_over_cap(graph):
    seed = {"relationship_arcs": [{"dyad": "A/B", "arc_type": "stable_alliance"}]}
    graph.initialize_from_planning(concept_seed=seed)
    with pytest.raises(ValueError):
        graph.apply_delta(
            subject="A", obj="B", scene_id="ch01_sc01",
            trust_delta=MAX_ABS_DELTA + 0.01, source="scene_card",
        )


def test_apply_delta_rejects_bad_source(graph):
    seed = {"relationship_arcs": [{"dyad": "A/B", "arc_type": "stable_alliance"}]}
    graph.initialize_from_planning(concept_seed=seed)
    with pytest.raises(ValueError):
        graph.apply_delta(
            subject="A", obj="B", scene_id="ch01_sc01",
            trust_delta=0.1, source="llm_autotrust",
        )


def test_apply_delta_rejects_bad_scene_id(graph):
    seed = {"relationship_arcs": [{"dyad": "A/B", "arc_type": "stable_alliance"}]}
    graph.initialize_from_planning(concept_seed=seed)
    with pytest.raises(ValueError):
        graph.apply_delta(
            subject="A", obj="B", scene_id="Chapter 1",
            trust_delta=0.1, source="scene_card",
        )


def test_apply_delta_creates_edge_when_planning_missed_dyad(graph):
    graph.apply_delta(
        subject="A", obj="B", scene_id="ch01_sc01",
        warmth_delta=0.2, source="scene_card",
    )
    edge = graph.get_edge("A", "B")
    assert edge is not None
    assert edge["warmth"] == 0.2
    assert edge["arc_type"] == "other"


# ---------------------------------------------------- apply_scene_deltas


def test_apply_scene_deltas_skips_invalid_rows(graph):
    seed = {"relationship_arcs": [{"dyad": "A/B", "arc_type": "stable_alliance"}]}
    graph.initialize_from_planning(concept_seed=seed)
    updates = graph.apply_scene_deltas(scene_card={
        "chapter_number": 1, "scene_number": 2,
        "relationship_deltas": [
            {"subject": "A", "object": "B", "trust_delta": 0.2},
            {"subject": "", "object": "B", "trust_delta": 0.2},  # skip
            {"subject": "A", "object": "B", "trust_delta": 9.9},  # over cap \u2014 skip
        ],
    })
    assert len(updates) == 1
    assert updates[0]["trust"] == 0.2


# --------------------------------------------------------- context_for_scene


def test_context_for_scene_narrows_to_present_characters(graph):
    seed = {
        "relationship_arcs": [
            {"dyad": "A/B", "arc_type": "stable_alliance"},
            {"dyad": "A/C", "arc_type": "stable_alliance"},
            {"dyad": "B/C", "arc_type": "stable_opposition"},
        ],
    }
    graph.initialize_from_planning(concept_seed=seed)
    ctx = graph.context_for_scene(scene_card={
        "chapter_number": 1, "scene_number": 1,
        "pov_character": "A",
        "characters_present": ["A", "B"],
    })
    dyads = {k for k in ctx if not k.startswith("_")}
    # Only dyads fully contained in {A, B} surface: A\u2192B and B\u2192A (directed).
    assert dyads == {"A \u2502 B", "B \u2502 A"}
    assert ctx["_unshown_edge_count"] == 4  # 6 total edges - 2 shown


def test_context_for_scene_empty_when_no_characters_present(graph):
    seed = {"relationship_arcs": [{"dyad": "A/B", "arc_type": "stable_alliance"}]}
    graph.initialize_from_planning(concept_seed=seed)
    ctx = graph.context_for_scene(scene_card={
        "chapter_number": 1, "scene_number": 1,
    })
    assert set(ctx.keys()) == {"_unshown_edge_count"}
