"""Parity tests for Slice 2 ChapterPacket vs flat ContextAssembler output.

Invariant (spec \u00a76.1.5): when ``runtime.chapter_packet.enabled: true``, the
packet's rendered markdown must be a token-superset of what
``ContextAssembler.assemble(scene_card)`` produced on the same scene. Any
token present in flat must appear in the packet render; the reverse is not
required (packet adds structured chapter-level fields).

Additional ordering invariants:
- voice rules / exemplars render before the drafter-facing scene card so the
  drafter sees register guidance before the contract.
- the scene card must render before any "Writing Constraints" / banned-phrase
  block so the drafter associates the list with the contract that precedes it.

These tests use in-memory fixtures so they run offline. The live bench
parity (manual judgment, spec \u00a76.1.5) remains a human step.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.pipeline.chapter_packet import ChapterPacketCompiler


def _tokenize(text: str) -> set[str]:
    """Lowercased whitespace + punctuation split, matching the spec's
    tokenization rule for the superset check."""
    return set(re.findall(r"[A-Za-z0-9_\-]+", text.lower()))


class _FakeAssembler:
    """Minimal stand-in for ContextAssembler.assemble.

    Produces a flat string with the canonical sections a real assembler would
    emit so the parity test can verify the packet renderer preserves them
    without standing up Chroma/SQLite dependencies.
    """

    def __init__(self, scene_card_payload: dict, voice_rule_text: str,
                 constraints_text: str, concept_seed: dict | None = None) -> None:
        self._scene_card = scene_card_payload
        self._voice_rule_text = voice_rule_text
        self._constraints_text = constraints_text
        self.concept_seed = concept_seed or {}

    def assemble(self, scene_card: dict) -> str:
        parts = [
            "## Story Bible",
            "The galaxy far, far away.",
            "## Character Voices",
            "Ben Skywalker speaks like his father but sharper.",
            "## Scene Card",
            "```json",
            json.dumps(scene_card, indent=2),
            "```",
            self._voice_rule_text,
            f"## Writing Constraints\n{self._constraints_text}",
        ]
        return "\n\n".join(parts)


@pytest.fixture
def blueprint() -> dict:
    return {
        "chapter_number": 1,
        "chapter_mission": "Establish the wrongness",
        "chapter_turn": "Passive unease becomes active pursuit",
        "pov_allocation": ["Ben Skywalker"],
        "scene_plan": [
            {"scene_number": 1, "role": "hook", "purpose": "failure in sparring"},
            {"scene_number": 2, "role": "reveal", "purpose": "Luke validates"},
            {"scene_number": 3, "role": "decision", "purpose": "departure"},
        ],
        "reveal_payload": ["R01"],
        "hook_movements": {"planted": ["H01"], "advanced": [], "resolved": []},
        "subplot_obligations": ["SP-A"],
        "relationship_turns": [],
    }


@pytest.fixture
def scene_card() -> dict:
    return {
        "chapter_number": 1,
        "scene_number": 1,
        "pov_character": "Ben Skywalker",
        "mission": "Spar alone, feel the wrongness physically",
        "turning_point": "Ben misreads an opening and takes a hit",
        "characters_present": ["Ben Skywalker"],
        "closing_hook": "The wrongness does not retreat when he stops moving.",
        "target_word_count": 1250,
    }


@pytest.fixture
def fake_assembler(scene_card) -> _FakeAssembler:
    return _FakeAssembler(
        scene_card_payload=scene_card,
        voice_rule_text=(
            "## Voice Rules\n"
            "- Zahn-style tight third-person interiority.\n"
            "- No melodrama; clinical observation.\n"
        ),
        constraints_text="Do not write purple prose. Avoid adverbs.",
    )


@pytest.fixture
def compiler(blueprint, scene_card, fake_assembler):
    concept_seed = {
        "meta": {"project_title": "Test Book", "franchise": "test-franchise"},
        "canon_pillars": [
            {"title": "Force wrongness", "body": "Wrongness is auditory, not visual"},
        ],
    }
    return ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints={1: blueprint},
        assembler=fake_assembler,
        exemplar_snippets=[
            {"label": "Zahn ch4 open", "text": "The bridge smelled of ozone."},
        ],
    )


def test_packet_is_token_superset_of_flat(compiler, scene_card, fake_assembler):
    flat = fake_assembler.assemble(scene_card)
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(base=base, scene_card=scene_card)
    packet_md = overlay.render_markdown()

    flat_tokens = _tokenize(flat)
    packet_tokens = _tokenize(packet_md)

    missing = flat_tokens - packet_tokens
    assert not missing, (
        f"Packet render is missing tokens present in flat context: "
        f"{sorted(missing)[:20]}"
    )


def test_packet_section_ordering_invariants(compiler, scene_card):
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(base=base, scene_card=scene_card)
    md = overlay.render_markdown()

    i_exemplars = md.find("Voice Exemplars")
    i_scene_card = md.find("## Scene Card")
    i_writing_constraints = md.find("Writing Constraints")

    # Exemplars (when present) must precede the scene card so voice register
    # frames the contract, not the other way around.
    if i_exemplars != -1:
        assert i_exemplars < i_scene_card, (
            "Voice exemplars must render before the scene card."
        )
    # The scene card (contract) must precede the banned-phrase constraints
    # block so the drafter associates the list with the scene it's drafting.
    if i_writing_constraints != -1:
        assert i_scene_card < i_writing_constraints, (
            "Scene card must render before Writing Constraints."
        )


def test_empty_flat_still_renders_valid_packet(blueprint, scene_card):
    """With no assembler wired, the packet still compiles (flat_context_snapshot
    is empty) and the structured sections are produced correctly."""
    compiler = ChapterPacketCompiler(
        concept_seed={"meta": {"project_title": "x", "franchise": "y"}},
        blueprints={1: blueprint},
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(base=base, scene_card=scene_card)
    md = overlay.render_markdown()
    assert "Chapter Packet" in md
    assert "Scene Card" in md
    # Flat snapshot absent.
    assert "Flat Context Snapshot" not in md


def test_packet_fallback_on_assembler_failure(blueprint, scene_card):
    """Assembler raising during flat snapshot must not blow up packet build.

    Downstream fallback-on-error is the orchestrator's concern; the compiler
    just returns an empty snapshot and keeps going. Ensures
    ``runtime.chapter_packet.fallback_on_error`` can cleanly route to flat.
    """

    class _BadAssembler:
        concept_seed: dict = {}

        def assemble(self, _: dict) -> str:
            raise RuntimeError("assembler boom")

    compiler = ChapterPacketCompiler(
        concept_seed={"meta": {"project_title": "x", "franchise": "y"}},
        blueprints={1: blueprint},
        assembler=_BadAssembler(),
    )
    base = compiler.compile_base(chapter_number=1)
    overlay = compiler.compile_overlay(base=base, scene_card=scene_card)
    assert overlay.flat_context_snapshot == ""
    assert "Chapter Packet" in overlay.render_markdown()
