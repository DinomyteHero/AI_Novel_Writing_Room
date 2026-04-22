"""Deterministic scene-card \u2192 GenerationBrief assembler.

The long-term replacement for the PlotArchitect LLM agent. Reads an
enriched scene card plus runtime voice/franchise context and builds a
``GenerationBrief`` dict matching ``schemas/generation_brief.json`` without
any LLM call. Brooks' framing: plot decisions belong upstream, in
planning. The drafter's job is to execute the plan, not rediscover it.

## Separation of concerns

ContextAssembler stays as the **data provider** \u2014 it reads the concept
seed, chapter memory, prior scenes, voice definitions, franchise profile,
and negative constraints. It does not transform scene cards.

BriefAssembler is a **pure transformer** \u2014 it consumes a scene card plus
ContextAssembler's outputs and emits a typed brief. No IO, no LLM calls,
no state. The brief is the drafter-facing artifact PlotArchitect currently
produces via a Sonnet-tier LLM round-trip; once scene cards carry the
enriched planning fields, this module replaces that round-trip entirely.

## Enrichment fallback policy

Scene cards that carry the post-enrichment fields
(``turning_point_detail``, ``emotional_arc``, ``key_beats``) produce a
fully-populated brief. Legacy cards that only carry the scalar
``turning_point`` / ``emotional_trajectory`` strings produce a **partial
brief with a warning flag**:

- ``turning_point_detail`` absent \u2192 ``turning_point = {trigger: <legacy>,
  shift: "", cost: ""}`` and a warning is recorded.
- ``emotional_arc`` absent \u2192 ``emotional_arc = {start: <legacy>, shift: "",
  end: ""}`` and a warning is recorded.
- ``key_beats`` absent \u2192 brief omits the field; the drafter falls back to
  the scene card's ``mission`` + ``turning_point`` + ``closing_hook``. A
  warning is recorded.

Missing fields surface through ``AssembledBrief.warnings`` so the
orchestrator can emit a ledger warn event (``brief_assembler_partial``) and
the operator sees the planning gap. The brief is still handed to the
drafter; partial planning is better than pipeline abort for the dual-phase
migration window.

## Not in scope

- **Voice prose synthesis** (reference-author channeling phrases): the
  ``voice_guidance`` field on the brief is a thin summary, not a
  prompt-shaped author-channeling block. That synthesis lives in
  ``src/prompting/franchise_voice.py`` already (or is part of the
  drafter's system prompt). BriefAssembler references those rules but
  does not re-synthesize them.
- **Hook agenda / subplot context**: these flow through
  ContextAssembler's assembled context and the chapter packet overlay,
  not through the brief. The brief carries *IDs* for hooks/subplots/
  revelations; the full text lives elsewhere.
- **Anti-pattern extraction from raw notes**: handled at authoring time
  (via the enrichment script) or by the author directly on the scene
  card's ``anti_patterns`` array. BriefAssembler merges voice-level
  anti-patterns from ``scene_voice_permissions.anti_patterns`` with
  structural ones from the top-level ``anti_patterns`` array.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

from src.prompting.scene_voice_permissions import (
    normalize_scene_voice_permissions,
)


_VALID_OPENING_MODES = frozenset({
    "in_medias_res", "sensory_hook", "dialogue_hook", "contrast",
})


@dataclass
class AssembledBrief:
    """Result of BriefAssembler.assemble.

    ``brief`` matches ``schemas/generation_brief.json``. ``warnings`` is a
    list of strings the orchestrator can emit as ledger warn events so the
    operator sees planning gaps on legacy / partially-enriched cards.
    """

    brief: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _to_past_tense_closing(closing_hook: str) -> str:
    """Minimal heuristic for present \u2192 past tense on closing-hook prose.

    The scene-card convention is to author closing_hook in present tense
    (\"a text message arrives\") because planning reads cleaner that way.
    The drafter writes in past tense. We apply a very small rewrite so
    the drafter is not handed a tense-mismatched sentence to copy.

    This is intentionally conservative: only four irregular verbs and the
    generic ``-s`` present-tense third-person singular. Anything more
    ambitious belongs in the enrichment script where a human can review.
    """
    if not closing_hook:
        return ""

    # Leave the string mostly intact; small substitutions only. Callers
    # can override by populating ``closing_beat`` directly on the card
    # (schema already permits this via the enrichment script).
    replacements = [
        (" arrives ", " arrived "),
        (" arrives.", " arrived."),
        (" opens ", " opened "),
        (" opens.", " opened."),
        (" locks ", " locked "),
        (" locks.", " locked."),
        (" finds ", " found "),
        (" finds.", " found."),
        (" is ", " was "),
        (" are ", " were "),
    ]
    result = closing_hook
    for old, new in replacements:
        result = result.replace(old, new)
    return result


def _partial_turning_point_from_legacy(
    legacy_turning_point: str,
) -> tuple[dict[str, str], str]:
    """Build a partial turning_point {trigger,shift,cost} dict from the
    legacy scalar string, returning the warning message too."""
    if not legacy_turning_point:
        return {"trigger": "", "shift": "", "cost": ""}, (
            "scene_card has no turning_point_detail AND no legacy "
            "turning_point string \u2014 drafter will operate without a "
            "turning-point constraint"
        )
    return (
        {"trigger": legacy_turning_point, "shift": "", "cost": ""},
        "scene_card missing turning_point_detail \u2014 brief falls back to the "
        "legacy turning_point string as 'trigger' only; run enrich_scene_cards "
        "to migrate",
    )


def _partial_emotional_arc_from_legacy(
    legacy_trajectory: str,
) -> tuple[dict[str, str], str]:
    """Build a partial emotional_arc {start,shift,end} dict from the legacy
    trajectory string, returning the warning message too."""
    if not legacy_trajectory:
        return {"start": "", "shift": "", "end": ""}, (
            "scene_card has no emotional_arc AND no legacy "
            "emotional_trajectory string \u2014 brief ships without an "
            "emotional-arc constraint"
        )
    # Convention is "start -> shift -> end"; split on '->' when present,
    # otherwise dump the whole string into 'shift' so the drafter at least
    # sees the planned trajectory as mid-scene guidance.
    parts = [p.strip() for p in legacy_trajectory.split("->") if p.strip()]
    if len(parts) == 3:
        return (
            {"start": parts[0], "shift": parts[1], "end": parts[2]},
            "scene_card missing emotional_arc \u2014 brief parsed the legacy "
            "trajectory string into start/shift/end; run enrich_scene_cards "
            "to authoritatively migrate",
        )
    return (
        {"start": "", "shift": legacy_trajectory, "end": ""},
        "scene_card missing emotional_arc \u2014 brief falls back to the "
        "legacy emotional_trajectory string as 'shift' only; run "
        "enrich_scene_cards to migrate",
    )


def _merge_anti_patterns(scene_card: Mapping[str, Any]) -> list[str]:
    """Concatenate top-level structural anti-patterns with voice-level ones
    from ``scene_voice_permissions.anti_patterns``, preserving order and
    deduplicating."""
    out: list[str] = []
    seen: set[str] = set()

    # Structural / compositional anti-patterns (top-level field).
    for item in scene_card.get("anti_patterns") or []:
        if isinstance(item, str) and item and item not in seen:
            out.append(item)
            seen.add(item)

    # Voice-register anti-patterns (nested under scene_voice_permissions).
    voice_block = scene_card.get("scene_voice_permissions")
    if isinstance(voice_block, Mapping):
        for item in voice_block.get("anti_patterns") or []:
            if isinstance(item, str) and item and item not in seen:
                out.append(item)
                seen.add(item)

    return out


def _scene_objective_from_card(scene_card: Mapping[str, Any]) -> str:
    """Derive ``scene_objective`` from mission + structural_phase.

    Format: ``<mission> (<structural_phase> phase)``. The drafter's job is
    to execute the mission within the named phase; the phase tag keeps the
    structural context visible even when the mission string is terse.
    """
    mission = str(scene_card.get("mission") or "").strip()
    phase = str(scene_card.get("structural_phase") or "").strip()
    if mission and phase:
        return f"{mission} ({phase} phase)"
    return mission or phase or ""


class BriefAssembler:
    """Pure transformer that builds a ``GenerationBrief`` from a scene card.

    Construct with optional franchise / voice context providers so the
    assembler can populate ``voice_guidance`` without callers having to
    shuffle context dicts. Context providers are optional: when absent,
    ``voice_guidance`` falls back to a minimal default.
    """

    def __init__(
        self,
        *,
        pov_approach: Optional[str] = None,
        franchise_profile_text: Optional[str] = None,
    ) -> None:
        self._pov_approach = pov_approach or ""
        self._franchise_profile_text = franchise_profile_text or ""

    def assemble(self, scene_card: Mapping[str, Any]) -> AssembledBrief:
        """Return an ``AssembledBrief`` for the given scene card.

        Never raises for missing optional fields; instead records warnings
        on the result so the orchestrator can surface them as ledger warn
        events (``brief_assembler_partial``).
        """
        warnings: list[str] = []
        brief: dict[str, Any] = {}

        scene_objective = _scene_objective_from_card(scene_card)
        if not scene_objective:
            warnings.append(
                "scene_card missing both mission and structural_phase \u2014 "
                "scene_objective will be empty"
            )
        brief["scene_objective"] = scene_objective

        # turning_point: prefer enriched object, fall back to legacy string
        tp_detail = scene_card.get("turning_point_detail")
        if isinstance(tp_detail, Mapping) and all(
            isinstance(tp_detail.get(k), str) and tp_detail.get(k)
            for k in ("trigger", "shift", "cost")
        ):
            brief["turning_point"] = {
                "trigger": str(tp_detail["trigger"]),
                "shift": str(tp_detail["shift"]),
                "cost": str(tp_detail["cost"]),
            }
        else:
            tp_partial, warning = _partial_turning_point_from_legacy(
                str(scene_card.get("turning_point") or "")
            )
            brief["turning_point"] = tp_partial
            warnings.append(warning)

        # closing_beat: prefer explicit card field when set, else derive
        # from closing_hook with a minimal present-to-past rewrite.
        closing_beat = scene_card.get("closing_beat")
        if isinstance(closing_beat, str) and closing_beat.strip():
            brief["closing_beat"] = closing_beat.strip()
        else:
            brief["closing_beat"] = _to_past_tense_closing(
                str(scene_card.get("closing_hook") or "")
            )
            if not brief["closing_beat"]:
                warnings.append(
                    "scene_card has no closing_hook \u2014 drafter will choose its "
                    "own closing moment (structural risk)"
                )

        # emotional_arc: prefer enriched object, fall back to legacy string
        emo = scene_card.get("emotional_arc")
        if isinstance(emo, Mapping) and all(
            isinstance(emo.get(k), str) and emo.get(k)
            for k in ("start", "shift", "end")
        ):
            brief["emotional_arc"] = {
                "start": str(emo["start"]),
                "shift": str(emo["shift"]),
                "end": str(emo["end"]),
            }
        else:
            arc_partial, warning = _partial_emotional_arc_from_legacy(
                str(scene_card.get("emotional_trajectory") or "")
            )
            brief["emotional_arc"] = arc_partial
            warnings.append(warning)

        # target_word_count: required; echo the scene card value.
        twc = scene_card.get("target_word_count")
        if isinstance(twc, int) and twc > 0:
            brief["target_word_count"] = twc
        else:
            warnings.append(
                "scene_card missing target_word_count \u2014 defaulting to 3500"
            )
            brief["target_word_count"] = 3500

        # Optional fields \u2014 only included when populated on the card.
        opening_mode = scene_card.get("opening_mode")
        if (
            isinstance(opening_mode, str)
            and opening_mode in _VALID_OPENING_MODES
        ):
            brief["opening_mode"] = opening_mode

        key_beats = scene_card.get("key_beats")
        if isinstance(key_beats, list) and len(key_beats) >= 3:
            cleaned = []
            for beat in key_beats[:5]:
                if not isinstance(beat, Mapping):
                    continue
                if all(
                    isinstance(beat.get(k), str) and beat.get(k)
                    for k in ("beat_description", "state_change", "pov_reaction")
                ):
                    cleaned.append({
                        "beat_description": str(beat["beat_description"]),
                        "state_change": str(beat["state_change"]),
                        "pov_reaction": str(beat["pov_reaction"]),
                    })
            if len(cleaned) >= 3:
                brief["key_beats"] = cleaned
            else:
                warnings.append(
                    "scene_card key_beats present but fewer than 3 well-formed "
                    "entries after validation \u2014 dropping the field"
                )
        elif scene_card.get("key_beats") is not None:
            warnings.append(
                "scene_card has key_beats but it is empty or too short "
                "(needs 3-5 entries) \u2014 drafter will plan beats itself"
            )
        else:
            warnings.append(
                "scene_card missing key_beats \u2014 drafter will plan beats "
                "from mission + turning_point only; run enrich_scene_cards "
                "to supply concrete beats"
            )

        # Required-hook / subplot / revelation IDs echo directly.
        hook_ids = [
            action.get("hook_id")
            for action in scene_card.get("hook_actions") or []
            if isinstance(action, Mapping) and action.get("hook_id")
        ]
        if hook_ids:
            brief["required_hooks"] = hook_ids
        subplot_ids = [
            sid for sid in scene_card.get("active_subplots") or []
            if isinstance(sid, str) and sid
        ]
        if subplot_ids:
            brief["required_subplots"] = subplot_ids
        revelation_ids = [
            rid for rid in scene_card.get("revelations") or []
            if isinstance(rid, str) and rid
        ]
        if revelation_ids:
            brief["required_revelations"] = revelation_ids

        anti_patterns = _merge_anti_patterns(scene_card)
        if anti_patterns:
            brief["anti_patterns"] = anti_patterns

        # voice_guidance: thin summary pulling from card + context providers.
        # The drafter's system prompt already carries the franchise/voice
        # rules; this field exists so PlotArchitect-era call sites have a
        # consistent scene-level register pointer.
        voice_bits: list[str] = []
        permissions = normalize_scene_voice_permissions(scene_card)
        if permissions.primary_anchor:
            voice_bits.append(f"Primary anchor: {permissions.primary_anchor}")
        if permissions.supporting_anchors:
            voice_bits.append(
                f"Supporting anchors: {', '.join(permissions.supporting_anchors)}"
            )
        if self._pov_approach:
            voice_bits.append(self._pov_approach.strip())
        if voice_bits:
            brief["voice_guidance"] = " \u2014 ".join(voice_bits)

        return AssembledBrief(brief=brief, warnings=warnings)
