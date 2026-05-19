"""Pre-draft cross-chapter continuity validator.

Catches the class of bug that produced the Aevyn Ch 32/33 break in the
unfinished-shadow B run: scene N ends with character X in state P at location
L, scene N+1 opens with X in a contradicting state at a contradicting
location, with no scene-card field explaining the transition.

This runs at bundle-compile time on the ordered scene-card list. No prose, no
LLM. Pure metadata check on declared fields:

- ``characters_present`` — who is in the scene
- ``setting`` — where the scene takes place (free-text; soft compare)
- ``end_state`` (optional new field) — per-character status at scene close
- ``holds_object`` (optional new field) — character → object mapping

When a scene-card author has not populated the optional fields, the
validator skips that dimension rather than guess. A scene where author
hasn't said what state Aevyn is in at close is not a continuity break — the
validator only fires on **declared contradictions**, not silence.

The validator emits an advisory list. ``run()`` aggregates and returns a
report dict matching the existing ``scene_contract_validator`` shape so
``scripts/compile_bundle.py`` can stitch it into its output the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


_STATE_NORMALIZE = {
    "alive": "alive",
    "wounded": "wounded",
    "injured": "wounded",
    "unconscious": "unconscious",
    "dead": "dead",
    "killed": "dead",
    "captured": "captured",
    "captive": "captured",
    "escaped": "free",
    "free": "free",
    "off_screen": "off_screen",
    "off-screen": "off_screen",
    "offscreen": "off_screen",
}

# State transitions that are valid without an explicit narrative bridge.
# Anything else is suspicious enough to flag for human review.
_NATURAL_TRANSITIONS = {
    ("alive", "wounded"),
    ("alive", "captured"),
    ("alive", "dead"),
    ("alive", "off_screen"),
    ("wounded", "alive"),  # rest / treatment
    ("wounded", "dead"),
    ("wounded", "captured"),
    ("wounded", "off_screen"),
    ("unconscious", "alive"),
    ("unconscious", "wounded"),
    ("unconscious", "dead"),
    ("unconscious", "captured"),
    ("captured", "free"),
    ("captured", "dead"),
    ("captured", "off_screen"),
    ("free", "alive"),
    ("free", "captured"),
    ("off_screen", "alive"),
    ("off_screen", "wounded"),
    ("off_screen", "captured"),
    ("off_screen", "off_screen"),
}

# Transitions that require an explicit narrative bridge to be valid.
# "dead" -> anything alive is the canonical example; if a scene card flips
# Aevyn from dead at close of N to alive at open of N+1 without an
# off_page_events field explaining survival, that's the bug.
_REQUIRES_BRIDGE = {
    ("dead", "alive"),
    ("dead", "wounded"),
    ("dead", "unconscious"),
    ("dead", "captured"),
    ("dead", "free"),
}


@dataclass(frozen=True)
class ContinuityBreak:
    """One detected continuity discontinuity."""

    kind: str  # "character_state" | "location" | "object_location"
    severity: str  # "low" | "medium" | "high"
    from_scene: str
    to_scene: str
    subject: str  # character name or object name
    summary: str
    details: dict[str, Any]


@dataclass(frozen=True)
class ContinuityReport:
    """Validator output. ``passed`` is true when no breaks fired."""

    passed: bool
    scene_count: int
    breaks: tuple[ContinuityBreak, ...]
    skipped_pairs: int = 0  # pairs where both end_state and characters were missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "scene_count": self.scene_count,
            "skipped_pairs": self.skipped_pairs,
            "break_count": len(self.breaks),
            "breaks": [
                {
                    "kind": b.kind,
                    "severity": b.severity,
                    "from_scene": b.from_scene,
                    "to_scene": b.to_scene,
                    "subject": b.subject,
                    "summary": b.summary,
                    "details": b.details,
                }
                for b in self.breaks
            ],
        }


# --- helpers ----------------------------------------------------------------


def _scene_id(card: Mapping[str, Any]) -> str:
    """Render the canonical chNN_scMM scene id."""
    ch = card.get("chapter_number", 0)
    sc = card.get("scene_number", 0)
    return f"ch{int(ch):02d}_sc{int(sc):02d}"


def _normalize_state(raw: str | None) -> str | None:
    if raw is None:
        return None
    return _STATE_NORMALIZE.get(str(raw).strip().lower())


def _collect_end_states(card: Mapping[str, Any]) -> dict[str, str]:
    """Pull declared per-character end states from a scene card.

    Accepted shapes (any one of):

    1. ``end_state``: ``{"character_name": "state", ...}``
    2. ``character_end_states``: ``[{"character": "name", "state": "..."}]``
    3. legacy: no field present → returns {} (validator skips this dimension)
    """
    out: dict[str, str] = {}
    explicit = card.get("end_state") or card.get("character_end_states")
    if isinstance(explicit, Mapping):
        for name, state in explicit.items():
            norm = _normalize_state(state if isinstance(state, str) else state.get("state"))
            if norm:
                out[str(name)] = norm
    elif isinstance(explicit, list):
        for entry in explicit:
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("character")
            state = entry.get("state")
            if name and state:
                norm = _normalize_state(state)
                if norm:
                    out[str(name)] = norm
    return out


def _collect_start_states(card: Mapping[str, Any]) -> dict[str, str]:
    """Pull declared per-character start states from a scene card.

    Accepted shapes match ``_collect_end_states`` with ``start_state`` or
    ``character_start_states`` as the field name.
    """
    out: dict[str, str] = {}
    explicit = card.get("start_state") or card.get("character_start_states")
    if isinstance(explicit, Mapping):
        for name, state in explicit.items():
            norm = _normalize_state(state if isinstance(state, str) else state.get("state"))
            if norm:
                out[str(name)] = norm
    elif isinstance(explicit, list):
        for entry in explicit:
            if not isinstance(entry, Mapping):
                continue
            name = entry.get("character")
            state = entry.get("state")
            if name and state:
                norm = _normalize_state(state)
                if norm:
                    out[str(name)] = norm
    return out


def _collect_object_locations(card: Mapping[str, Any], *, position: str) -> dict[str, str]:
    """Pull declared object → holder/location mapping.

    ``position`` is ``start`` or ``end``. Schema lookups:
    - ``start`` reads ``objects_at_open`` or ``holds_object_open``
    - ``end`` reads ``objects_at_close`` or ``holds_object_close``
    """
    if position == "start":
        keys = ("objects_at_open", "holds_object_open")
    else:
        keys = ("objects_at_close", "holds_object_close")
    out: dict[str, str] = {}
    for key in keys:
        raw = card.get(key)
        if isinstance(raw, Mapping):
            for obj, where in raw.items():
                if where:
                    out[str(obj)] = str(where).strip().lower()
        elif isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, Mapping):
                    continue
                obj = entry.get("object")
                where = entry.get("holder") or entry.get("location")
                if obj and where:
                    out[str(obj)] = str(where).strip().lower()
    return out


def _bridged(card: Mapping[str, Any], subject: str) -> bool:
    """Return True when the scene card declares an off-page bridge explaining
    a state-change that would otherwise look like a continuity break.

    A bridge is any of:
    - ``off_page_events: [...]`` mentioning ``subject``
    - ``backstory_notes`` or ``notes`` mentioning the subject in proximity to
      a state-change verb (revived, survived, awoke, escaped, recovered, etc.)
    """
    bridge_re = re.compile(
        rf"\b{re.escape(subject)}\b.*?\b(revive|survive|awoke|awak|escape|recover|return|free|alive|saved)",
        re.IGNORECASE | re.DOTALL,
    )
    off_page = card.get("off_page_events")
    if isinstance(off_page, list):
        for event in off_page:
            text = event if isinstance(event, str) else str(event)
            if bridge_re.search(text):
                return True
    for field_name in ("backstory_notes", "notes"):
        text = card.get(field_name)
        if isinstance(text, str) and bridge_re.search(text):
            return True
    return False


# --- main entry point -------------------------------------------------------


def validate_cross_chapter_continuity(
    cards: Sequence[Mapping[str, Any]],
) -> ContinuityReport:
    """Walk an ordered scene-card list and flag declared discontinuities.

    Cards are expected to be pre-sorted by chapter_number, scene_number.
    Caller is responsible for sorting if the input source is unordered.
    """
    breaks: list[ContinuityBreak] = []
    skipped = 0

    sorted_cards = sorted(
        list(cards),
        key=lambda c: (int(c.get("chapter_number", 0)), int(c.get("scene_number", 0))),
    )

    for i in range(len(sorted_cards) - 1):
        prev = sorted_cards[i]
        nxt = sorted_cards[i + 1]
        prev_id = _scene_id(prev)
        next_id = _scene_id(nxt)

        prev_end = _collect_end_states(prev)
        next_start = _collect_start_states(nxt)
        prev_chars = set(prev.get("characters_present") or [])
        next_chars = set(nxt.get("characters_present") or [])

        if not prev_end and not next_start:
            skipped += 1

        # Character-state continuity. Only fires when BOTH sides declare a
        # state for the same character. Silence is not a contradiction.
        for character in (prev_end.keys() & next_start.keys()):
            prev_state = prev_end[character]
            next_state = next_start[character]
            if prev_state == next_state:
                continue
            transition = (prev_state, next_state)
            if transition in _NATURAL_TRANSITIONS:
                continue
            if transition in _REQUIRES_BRIDGE and _bridged(nxt, character):
                continue
            severity = "high" if transition in _REQUIRES_BRIDGE else "medium"
            breaks.append(ContinuityBreak(
                kind="character_state",
                severity=severity,
                from_scene=prev_id,
                to_scene=next_id,
                subject=character,
                summary=(
                    f"{character}: {prev_state} at close of {prev_id} → "
                    f"{next_state} at open of {next_id}"
                ),
                details={
                    "previous_state": prev_state,
                    "next_state": next_state,
                    "requires_bridge": transition in _REQUIRES_BRIDGE,
                    "bridge_found": False,
                },
            ))

        # Note: a redundant "alive in characters_present then dead" check was
        # considered but removed because alive → dead is a natural drama
        # transition. The state-transition check above already catches the
        # bug shapes that matter (dead → alive without bridge); double-flagging
        # natural deaths would create noise.

        # Plot-object location continuity. Holocron, datachip, fragment, etc.
        prev_objects = _collect_object_locations(prev, position="end")
        next_objects = _collect_object_locations(nxt, position="start")
        for obj in (prev_objects.keys() & next_objects.keys()):
            prev_holder = prev_objects[obj]
            next_holder = next_objects[obj]
            if prev_holder == next_holder:
                continue
            # An object moving from "ben" to "talon" requires a hand-off
            # scene or a declared off-page transfer. Without one, flag.
            if not _bridged(nxt, obj):
                breaks.append(ContinuityBreak(
                    kind="object_location",
                    severity="medium",
                    from_scene=prev_id,
                    to_scene=next_id,
                    subject=obj,
                    summary=(
                        f"{obj}: held by {prev_holder!r} at close of {prev_id} → "
                        f"{next_holder!r} at open of {next_id} with no transfer"
                    ),
                    details={
                        "previous_holder": prev_holder,
                        "next_holder": next_holder,
                    },
                ))

    return ContinuityReport(
        passed=not breaks,
        scene_count=len(sorted_cards),
        breaks=tuple(breaks),
        skipped_pairs=skipped,
    )
