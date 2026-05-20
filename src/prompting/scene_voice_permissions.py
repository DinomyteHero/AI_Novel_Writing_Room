"""Shared scene-level voice-permission normalization and rendering.

This module centralizes the legacy scene-card fields that control per-scene
voice permissions. It also accepts the additive ``scene_voice_permissions``
schema, which provides a franchise- and author-agnostic representation for the
same contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


_HEIGHTENED_INTERIORITY = "heightened_interiority"


@dataclass(frozen=True)
class SceneVoicePermissions:
    """Normalized per-scene voice-permission fields."""

    notes: str = ""
    anti_patterns: tuple[str, ...] = ()
    pov_arc_phase: str = ""
    primary_anchor: str = ""
    supporting_anchors: tuple[str, ...] = ()
    authorized_modes: tuple[str, ...] = ()
    prohibited_modes: tuple[str, ...] = ()
    intensity_guidance_source: str = ""

    @property
    def has_heightened_interiority_signal(self) -> bool:
        return (
            _HEIGHTENED_INTERIORITY in self.authorized_modes
            or _HEIGHTENED_INTERIORITY in self.prohibited_modes
        )

    @property
    def heightened_interiority_permitted(self) -> bool:
        return _HEIGHTENED_INTERIORITY in self.authorized_modes

    @property
    def has_stover_permission(self) -> bool:
        """Legacy compatibility alias for older tests/callers."""
        return self.has_heightened_interiority_signal

    @property
    def stover_permitted(self) -> bool:
        """Legacy compatibility alias for older tests/callers."""
        return self.heightened_interiority_permitted

    @property
    def uses_legacy_stover_guidance(self) -> bool:
        return self.intensity_guidance_source == "legacy_stover"

    @property
    def has_drafter_surface(self) -> bool:
        return any((
            self.notes,
            self.anti_patterns,
            self.pov_arc_phase,
            self.primary_anchor,
            self.supporting_anchors,
            self.has_heightened_interiority_signal,
        ))

    @property
    def has_canon_surface(self) -> bool:
        return bool(
            self.notes
            or self.anti_patterns
            or self.heightened_interiority_permitted
        )


_PART_1_PHASES = frozenset({"lie_established", "lie_reinforced"})
_PART_2_3_PHASES = frozenset({
    "lie_questioned", "lie_cracking", "lie_deepened", "point_of_no_return",
})
_PART_3_4_PHASES = frozenset({
    "lie_confronted", "truth_accepted", "truth_rejected",
    "lie_acted_upon", "lie_consequence",
    "truth_tested", "truth_pressured", "truth_reaffirmed",
    "truth_glimpsed", "disillusionment_accepted",
})


def _register_guidance_for_phase(phase: str) -> str:
    if phase in _PART_1_PHASES:
        return (
            "Part 1 register \u2014 reactive, tactile, sensory. Character feels "
            "problems before naming them. No clinical articulation."
        )
    if phase in _PART_2_3_PHASES:
        return (
            "Part 2-3 register \u2014 interior tension permitted, but still grounded "
            "in sensation. No mission-debrief sentences."
        )
    if phase in _PART_3_4_PHASES:
        return (
            "Part 3-4 register \u2014 analytical precision permitted where earned. "
            "Character may articulate what they now understand."
        )
    return "Honor the scene-card notes above for voice register."


def _normalize_string_values(raw: object) -> tuple[str, ...]:
    """Normalize a string-or-list field into a deduplicated tuple of strings."""
    if raw in (None, ""):
        return ()

    values: list[str] = []
    if isinstance(raw, str):
        candidates = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        candidates = raw
    else:
        candidates = [raw]

    for candidate in candidates:
        text = str(candidate).strip()
        if text and text not in values:
            values.append(text)
    return tuple(values)


def _normalize_text_value(raw: object) -> str:
    if raw in (None, ""):
        return ""
    return str(raw).strip()


def normalize_scene_voice_permissions(
    scene_card: Mapping[str, object] | None,
) -> SceneVoicePermissions:
    """Normalize legacy and generic scene-card voice-permission fields."""
    if not scene_card:
        return SceneVoicePermissions()

    voice_block_raw = scene_card.get("scene_voice_permissions")
    voice_block = (
        voice_block_raw if isinstance(voice_block_raw, Mapping) else {}
    )
    anchor_profile_raw = voice_block.get("anchor_profile")
    anchor_profile = (
        anchor_profile_raw if isinstance(anchor_profile_raw, Mapping) else {}
    )

    if "notes" in voice_block:
        notes = _normalize_text_value(voice_block.get("notes"))
    else:
        notes = _normalize_text_value(scene_card.get("notes"))

    if "anti_patterns" in voice_block:
        anti_patterns = _normalize_string_values(voice_block.get("anti_patterns"))
    else:
        anti_patterns = _normalize_string_values(scene_card.get("anti_patterns"))

    if "pov_arc_phase" in voice_block:
        pov_arc_phase = _normalize_text_value(voice_block.get("pov_arc_phase"))
    else:
        pov_arc_phase = _normalize_text_value(scene_card.get("pov_arc_phase"))

    if anchor_profile:
        primary_anchor = _normalize_text_value(anchor_profile.get("primary"))
        supporting_anchors = _normalize_string_values(
            anchor_profile.get("supporting")
        )
    else:
        if "primary_anchor" in voice_block:
            primary_anchor = _normalize_text_value(voice_block.get("primary_anchor"))
        else:
            primary_anchor = _normalize_text_value(scene_card.get("primary_anchor"))

        if "supporting_anchors" in voice_block:
            supporting_anchors = _normalize_string_values(
                voice_block.get("supporting_anchors")
            )
        else:
            supporting_anchors = _normalize_string_values(
                scene_card.get("supporting_anchor")
            )

    authorized_modes: tuple[str, ...] = ()
    prohibited_modes: tuple[str, ...] = ()
    generic_permissions_present = False

    if "authorized_modes" in voice_block:
        authorized_modes = _normalize_string_values(
            voice_block.get("authorized_modes")
        )
        generic_permissions_present = True
    if "prohibited_modes" in voice_block:
        prohibited_modes = _normalize_string_values(
            voice_block.get("prohibited_modes")
        )
        generic_permissions_present = True

    intensity_guidance_source = ""
    if generic_permissions_present:
        intensity_guidance_source = "generic_modes"
    else:
        stover_raw = scene_card.get("stover_permitted")
        if isinstance(stover_raw, bool):
            intensity_guidance_source = "legacy_stover"
            if stover_raw:
                authorized_modes = (_HEIGHTENED_INTERIORITY,)
            else:
                prohibited_modes = (_HEIGHTENED_INTERIORITY,)

    return SceneVoicePermissions(
        notes=notes,
        anti_patterns=anti_patterns,
        pov_arc_phase=pov_arc_phase,
        primary_anchor=primary_anchor,
        supporting_anchors=supporting_anchors,
        authorized_modes=authorized_modes,
        prohibited_modes=prohibited_modes,
        intensity_guidance_source=intensity_guidance_source,
    )


def render_scene_voice_contract(
    scene_card: Mapping[str, object] | None,
) -> str:
    """Render the top-of-prompt Scene Voice Contract block."""
    permissions = normalize_scene_voice_permissions(scene_card)
    if not permissions.has_drafter_surface:
        return ""

    lines: list[str] = ["## Scene Voice Contract (READ FIRST \u2014 ABSOLUTE)"]
    if permissions.notes:
        lines.append(permissions.notes)
    if permissions.primary_anchor or permissions.supporting_anchors:
        lines.append("")
        lines.append("### Scene Anchor Profile")
        lines.append(
            "Primary anchor sets the prose surface; supporting anchors are beat-level accents only."
        )
        if permissions.primary_anchor:
            lines.append(f"- Primary anchor: {permissions.primary_anchor}")
        if permissions.supporting_anchors:
            lines.append(
                f"- Supporting anchors: {', '.join(permissions.supporting_anchors)}"
            )
    if permissions.has_heightened_interiority_signal:
        lines.append("")
        if permissions.uses_legacy_stover_guidance:
            lines.append("### Stover Permission")
            if permissions.heightened_interiority_permitted:
                lines.append(
                    "Stover-style interior density is permitted in this scene when the surrounding prose earns it."
                )
            else:
                lines.append(
                    "Stover-style interior density is not permitted in this scene; keep the prose surface in the listed anchors and scene notes."
                )
        else:
            lines.append("### Heightened Interiority Permission")
            if permissions.heightened_interiority_permitted:
                lines.append(
                    "Heightened interior density is permitted in this scene when the surrounding prose earns it."
                )
            else:
                lines.append(
                    "Heightened interior density is not permitted in this scene; keep the prose surface in the listed anchors and scene notes."
                )
    if permissions.anti_patterns:
        lines.append("")
        lines.append("### Anti-Patterns (from scene card)")
        lines.extend(f"- {item}" for item in permissions.anti_patterns)
    if permissions.pov_arc_phase:
        lines.append("")
        lines.append("### POV Arc Phase")
        lines.append(
            f"{permissions.pov_arc_phase} \u2014 "
            f"{_register_guidance_for_phase(permissions.pov_arc_phase)}"
        )
    return "\n".join(lines)


# Top-level scene-card fields that have been superseded by the additive
# `scene_voice_permissions` block. Authors should migrate into the nested
# shape; the readers above still accept these for backwards compatibility,
# but authoring-time tooling surfaces a deprecation warning so the migration
# debt is visible per-card.
_LEGACY_VOICE_FIELDS: tuple[str, ...] = (
    "primary_anchor",
    "supporting_anchor",
    "stover_permitted",
)


def detect_legacy_voice_fields(
    scene_card: Mapping[str, object] | None,
) -> list[str]:
    """Return legacy top-level voice field names present on the scene card.

    A card that carries *only* the nested ``scene_voice_permissions`` object
    returns ``[]``. A card that carries one or more of the top-level
    ``primary_anchor`` / ``supporting_anchor`` / ``stover_permitted`` fields
    returns them in declaration order so callers can surface a deprecation
    warning with specific field names.

    The normalized reader in this module still honors the legacy fields for
    backwards compatibility; this helper exists for authoring-time tooling
    (bundle compile, authoring skills) so the migration backlog is visible.
    """
    if not scene_card:
        return []
    return [field for field in _LEGACY_VOICE_FIELDS if field in scene_card]
