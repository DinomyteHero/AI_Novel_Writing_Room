"""Slice 2 ChapterPacket + Compiler.

Typed runtime contract consumed by the drafter (ProseStylist) and reviewers
when ``runtime.chapter_packet.enabled: true``.

**Consistency model:** base + overlay.

- ``compile_base(chapter_number)`` is called once per chapter at chapter start.
  It pulls chapter-level planning context from ``concept_seed`` + the per-chapter
  blueprint, snapshots trusted state as of the chapter's first scene, and
  returns an **immutable** ``ChapterPacket`` with ``overlay_version=0``.

- ``compile_overlay(base, scene_card, trusted_state_snapshot)`` is called once
  per scene. It returns a **new** ``ChapterPacket`` that composes the base
  (never mutates it), stamps the current scene card, appends open gap notes
  that affect the current scene, increments ``overlay_version``, and captures
  a flat-assembly snapshot (voice rules, constraints, character voices, recent
  prose) so the drafter prompt is a token-superset of the legacy flat path.

Active promises (Slice 3) are wired through an optional ``promise_ledger``
dependency. The ``continuity_events`` and ``relationship_context`` packet
fields stay empty.

Persistence is the orchestrator's job (spec \u00a76.1.1): base \u2192
``runs/<run_id>/chapter_packets/chapter_NN.json``; overlay \u2192
``runs/<run_id>/chapter_packets/chapter_NN_sc_MM_overlay.json``.

See ``docs/architecture/architecture_upgrade_spec.md`` \u00a76.1.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import asdict, dataclass, field, fields, replace
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Optional

from src.pipeline.canon_guidance import render_guidance_for_packet

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.memory.context_assembler import ContextAssembler
    from src.memory.story_state import StoryState


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChapterPacket:
    """Typed chapter-level drafter context. Frozen so the base cannot drift
    after it is compiled (spec \u00a76.1.1 immutability rule)."""

    chapter_number: int
    overlay_version: int = 0
    mission: str = ""
    chapter_turn: str = ""
    pressure_ladder: list[dict] = field(default_factory=list)
    pov_arc_pressure: dict = field(default_factory=dict)
    next_scene_obligations: list[dict] = field(default_factory=list)
    active_promises: list[dict] = field(default_factory=list)     # Slice 3
    # Slice 3 (spec \u00a77.3): total count of *active* promises at overlay time.
    # ``active_promises`` is capped at 5 by ``list_top_urgent`` so the drafter
    # sees the most urgent slice without dilution; this tail keeps the total
    # visible (e.g. "5 of 23 open").
    active_promises_total_count: int = 0
    reveal_deadlines: list[dict] = field(default_factory=list)
    canon_slices: list[dict] = field(default_factory=list)
    canon_guidance: dict = field(default_factory=dict)
    relationship_context: dict = field(default_factory=dict)      # Slice 5
    exit_vector: dict = field(default_factory=dict)
    trusted_state_gap_notes: list[dict] = field(default_factory=list)
    exemplar_snippets: list[dict] = field(default_factory=list)
    anti_exemplar_snippets: list[dict] = field(default_factory=list)
    continuity_events: list[dict] = field(default_factory=list)   # Slice 4
    scene_number: int | None = None
    scene_card: dict = field(default_factory=dict)
    # Cached flat-context snapshot so overlays can be a strict token-superset
    # of the ContextAssembler.assemble() output. Written at overlay-compile time.
    flat_context_snapshot: str = ""
    # Cached rendered markdown; populated by render_markdown().
    rendered_markdown: str = ""

    # ------------------------------------------------------------------ dicts
    def to_json(self) -> dict:
        """Serializable dict suitable for JSON persistence.

        Drops ``flat_context_snapshot`` (it duplicates the legacy
        ContextAssembler payload; callers use ``rendered_markdown`` instead)
        and ``scene_number`` when None (absent on base packets, present on
        overlays). Those are the only keys that would otherwise fail the
        schema's integer typing.
        """
        d = asdict(self)
        d.pop("flat_context_snapshot", None)
        if d.get("scene_number") is None:
            d.pop("scene_number", None)
        return d

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "ChapterPacket":
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in payload.items() if k in known}
        return cls(**filtered)

    # ------------------------------------------------------------------ markdown
    def render_markdown(self) -> str:
        """Render the drafter-facing markdown.

        Structured chapter packet sections render first, followed by the flat
        context snapshot. Keeping the flat snapshot inline (rather than
        replacing it) is what makes the packet a token-superset of flat \u2014 the
        parity test in ``tests/test_packet_parity.py`` checks this invariant.

        Section order (also asserted by the parity test):
          1. Chapter Packet header (mission, turn)
          2. Pressure ladder / POV arc
          3. Next-scene obligations
          4. Canon slices
          5. Trusted-state gap notes (overlay only)
          6. Active promises / reveal deadlines (empty in Slice 2)
          7. Voice exemplars / anti-exemplars (before drafter instructions)
          8. Continuity events (empty in Slice 2)
          9. Relationship context (empty in Slice 2)
         10. Scene card (overlay only) \u2014 the scene contract appears here
             so downstream flat rendering does not duplicate it.
         11. Flat context snapshot (voice rules, writing constraints,
             character voices, recent prose, etc.)
        """
        parts: list[str] = []
        parts.append("## Chapter Packet")
        parts.append(f"- Chapter number: {self.chapter_number}")
        parts.append(f"- Overlay version: {self.overlay_version}")
        if self.scene_number is not None:
            parts.append(f"- Scene number: {self.scene_number}")
        if self.mission:
            parts.append("")
            parts.append("### Chapter Mission")
            parts.append(self.mission)
        if self.chapter_turn:
            parts.append("")
            parts.append("### Chapter Turn")
            parts.append(self.chapter_turn)

        if self.pressure_ladder:
            parts.append("")
            parts.append("### Pressure Ladder")
            for step in self.pressure_ladder:
                sc = step.get("scene_number")
                label = step.get("label", "")
                note = step.get("note", "")
                line = f"- Scene {sc}: {label}" if sc is not None else f"- {label}"
                if note:
                    line += f" \u2014 {note}"
                parts.append(line)

        if self.pov_arc_pressure:
            parts.append("")
            parts.append("### POV Arc Pressure")
            for k, v in self.pov_arc_pressure.items():
                parts.append(f"- {k}: {v}")

        if self.next_scene_obligations:
            parts.append("")
            parts.append("### Next-Scene Obligations")
            for ob in self.next_scene_obligations:
                kind = ob.get("kind", "obligation")
                note = ob.get("note", "")
                parts.append(f"- {kind}: {note}")

        if self.canon_slices:
            parts.append("")
            parts.append("### Canon Slices")
            for slc in self.canon_slices:
                title = slc.get("title") or "(untitled)"
                body = slc.get("body") or ""
                source = slc.get("source") or ""
                parts.append(f"- **{title}**" + (f" ({source})" if source else ""))
                if body:
                    parts.append(f"  {body}")

        if self.canon_guidance:
            parts.append("")
            parts.append("### Static Canon Guidance")
            parts.append(render_guidance_for_packet(self.canon_guidance))

        if self.trusted_state_gap_notes:
            parts.append("")
            parts.append("### Narrative Continuity Gaps")
            parts.append(
                "The following predecessor scenes were isolated and are not part "
                "of trusted continuity. Treat their referenced facts as unknown:"
            )
            for gap in self.trusted_state_gap_notes:
                cats = ", ".join(gap.get("blocker_categories") or []) or "isolated"
                created = gap.get("created_at") or ""
                parts.append(
                    f"- Scene {gap.get('isolated_scene', '?')} "
                    f"({cats}" + (f"; isolated {created}" if created else "") + "). "
                    "Do not assume any facts from this scene are in effect."
                )
            parts.append(
                "If your scene would naturally reference events from an isolated "
                "scene, write around them \u2014 summarize the gap narratively "
                "(e.g., \"something had happened, but the details remained "
                "unclear to her\") rather than invent specifics."
            )

        if self.active_promises:
            # Slice 3 (spec \u00a77.3): split urgent vs overdue, render with
            # type / due / setup details. Overdue promises carry the
            # ``do-not-force-payoff`` hint so the drafter treats them as
            # advisory only.
            parts.append("")
            total = self.active_promises_total_count or len(self.active_promises)
            shown = len(self.active_promises)
            non_overdue = [
                p for p in self.active_promises if p.get("status") != "overdue"
            ]
            overdue = [
                p for p in self.active_promises if p.get("status") == "overdue"
            ]
            parts.append(
                f"### Active promises ({shown} of {total} open; sorted by urgency)"
            )
            for p in non_overdue:
                parts.append(_format_active_promise_line(p))
            if overdue:
                parts.append("")
                parts.append(
                    "### Overdue promises (advisory only \u2014 do not force payoff in this scene)"
                )
                for p in overdue:
                    parts.append(_format_overdue_promise_line(p))

        if self.reveal_deadlines:
            parts.append("")
            parts.append("### Reveal Deadlines")
            for r in self.reveal_deadlines:
                note = r.get("note") or r.get("revelation_id", "(unknown)")
                due = r.get("due_by_scene", "")
                status = r.get("status", "")
                parts.append(f"- {note}: due {due}" + (f" [{status}]" if status else ""))

        if self.exemplar_snippets:
            parts.append("")
            parts.append("### Voice Exemplars")
            for snip in self.exemplar_snippets:
                label = snip.get("label", "exemplar")
                text = snip.get("text", "")
                parts.append(f"- **{label}**: {text}")

        if self.anti_exemplar_snippets:
            parts.append("")
            parts.append("### Voice Anti-Exemplars (do NOT write like this)")
            for snip in self.anti_exemplar_snippets:
                label = snip.get("label", "anti-exemplar")
                text = snip.get("text", "")
                parts.append(f"- **{label}**: {text}")

        if self.continuity_events:
            parts.append("")
            parts.append("### Trusted Continuity Events")
            for ev in self.continuity_events:
                et = ev.get("event_type", "event")
                summary = ev.get("summary", "")
                parts.append(f"- [{et}] {summary}")

        if self.relationship_context:
            # Slice 5 (spec \u00a79.5): render per-dyad trust/warmth/power_balance.
            # The overlay-scoped ``context_for_scene`` may attach an
            # ``_unshown_edge_count`` tail so the drafter sees the dilution
            # cap without being flooded with unrelated dyads.
            parts.append("")
            scene_anchor = ""
            # Scene anchor comes from the first dyad's updated_at_scene.
            for key, val in self.relationship_context.items():
                if isinstance(val, Mapping):
                    scene_anchor = val.get("updated_at_scene") or ""
                    break
            if scene_anchor:
                parts.append(f"### Relationship context (current state as of {scene_anchor})")
            else:
                parts.append("### Relationship Context")
            for key, val in self.relationship_context.items():
                if key.startswith("_"):
                    continue
                if isinstance(val, Mapping):
                    parts.append(_format_relationship_line(key, val))
                else:
                    parts.append(f"- {key}: {val}")
            unshown = self.relationship_context.get("_unshown_edge_count")
            if isinstance(unshown, int) and unshown > 0:
                parts.append(f"- _(+{unshown} other edges not surfaced this scene)_")

        if self.exit_vector:
            parts.append("")
            parts.append("### Exit Vector")
            for k, v in self.exit_vector.items():
                parts.append(f"- {k}: {v}")

        if self.scene_card:
            parts.append("")
            parts.append("## Scene Card")
            parts.append("```json")
            parts.append(json.dumps(_model_facing_scene_card(self.scene_card), indent=2))
            parts.append("```")

        if self.flat_context_snapshot:
            parts.append("")
            parts.append("## Flat Context Snapshot")
            parts.append(
                "Legacy ContextAssembler output is included verbatim below so "
                "every field the drafter historically saw is preserved."
            )
            parts.append("")
            parts.append(self.flat_context_snapshot)

        return _scrub_model_facing_text("\n".join(parts))


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class ChapterPacketCompiler:
    """Builds chapter packets from planning artifacts + trusted state.

    Constructor takes an optional ``promise_ledger`` collaborator (Slice 3);
    when ``None`` the ``active_promises`` packet field stays empty. The
    ``continuity_events`` and ``relationship_context`` fields are unpopulated.
    Deliberately does not hold a reference to the orchestrator \u2014 callers pass
    in what the compiler needs per call.
    """

    def __init__(
        self,
        *,
        concept_seed: Mapping[str, Any],
        blueprints: Mapping[int, Mapping[str, Any]],
        assembler: Optional["ContextAssembler"] = None,
        story_state: Optional["StoryState"] = None,
        promise_ledger=None,           # Slice 3
        canon_guidance_store=None,
        exemplar_snippets: list[dict] | None = None,
        anti_exemplar_snippets: list[dict] | None = None,
    ) -> None:
        self.concept_seed = dict(concept_seed)
        self.blueprints: dict[int, dict] = {int(k): dict(v) for k, v in blueprints.items()}
        self.assembler = assembler
        self.story_state = story_state
        self.promise_ledger = promise_ledger
        self.canon_guidance_store = canon_guidance_store
        self.exemplar_snippets = list(exemplar_snippets or [])
        self.anti_exemplar_snippets = list(anti_exemplar_snippets or [])
        self._subplots_by_id = _index_seed_refs(
            self.concept_seed.get("subplots") or [], ("subplot_id", "id")
        )
        self._hooks_by_id = _index_seed_refs(
            self.concept_seed.get("hooks") or [], ("hook_id", "id")
        )
        self._revelations_by_id = _index_seed_refs(
            self.concept_seed.get("revelation_schedule") or [],
            ("revelation_id", "info_id", "id"),
        )

    # ------------------------------------------------------------------ base
    def compile_base(self, *, chapter_number: int) -> ChapterPacket:
        blueprint = self.blueprints.get(chapter_number)
        if blueprint is None:
            raise KeyError(
                f"ChapterPacketCompiler.compile_base: no blueprint for chapter {chapter_number}"
            )

        mission = str(blueprint.get("chapter_mission", "") or "")
        chapter_turn = str(blueprint.get("chapter_turn", "") or "")

        pressure_ladder = self._build_pressure_ladder(blueprint)
        pov_arc_pressure = self._build_pov_arc_pressure(blueprint)
        next_scene_obligations = self._build_next_scene_obligations(blueprint)
        canon_slices = self._build_canon_slices(blueprint)
        reveal_deadlines = self._build_reveal_deadlines(blueprint)
        exit_vector = self._build_exit_vector(blueprint)

        active_promises = self._fetch_active_promises(chapter_number=chapter_number)

        return ChapterPacket(
            chapter_number=chapter_number,
            overlay_version=0,
            mission=mission,
            chapter_turn=chapter_turn,
            pressure_ladder=pressure_ladder,
            pov_arc_pressure=pov_arc_pressure,
            next_scene_obligations=next_scene_obligations,
            active_promises=active_promises,
            reveal_deadlines=reveal_deadlines,
            canon_slices=canon_slices,
            canon_guidance={},
            relationship_context={},
            exit_vector=exit_vector,
            trusted_state_gap_notes=[],
            exemplar_snippets=list(self.exemplar_snippets),
            anti_exemplar_snippets=list(self.anti_exemplar_snippets),
            continuity_events=[],
            scene_number=None,
            scene_card={},
            flat_context_snapshot="",
        )

    # --------------------------------------------------------------- overlay
    def compile_overlay(
        self,
        *,
        base: ChapterPacket,
        scene_card: Mapping[str, Any],
        trusted_state_snapshot: Mapping[str, Any] | None = None,
    ) -> ChapterPacket:
        """Compose a new packet for the scene. ``base`` is never mutated."""
        if not isinstance(base, ChapterPacket):
            raise TypeError("compile_overlay: base must be ChapterPacket")

        scene_number = int(
            scene_card.get("scene_number")
            or (trusted_state_snapshot or {}).get("scene_number")
            or 0
        ) or None

        gap_notes = self._fetch_gap_notes(base.chapter_number)
        flat_snapshot = self._render_flat_context_snapshot(scene_card)

        # Slice 3 (spec \u00a77.3): overlay uses scene-scoped ``list_top_urgent``
        # so the drafter sees the most urgent promises at *this* scene, not a
        # chapter-wide snapshot.
        scene_id = _scene_id(base.chapter_number, scene_number) if scene_number else None
        active_promises = self._fetch_active_promises_for_scene(
            chapter_number=base.chapter_number, scene_id=scene_id,
        )
        total_active = self._count_active_promises_for_scene(
            chapter_number=base.chapter_number, scene_id=scene_id,
        )
        canon_guidance = self._fetch_canon_guidance_for_scene(
            chapter_number=base.chapter_number,
            scene_card=scene_card,
        )

        scene_pov_arc_pressure = _enrich_pov_arc_pressure_for_scene(
            base.pov_arc_pressure, scene_card
        )

        overlay = replace(
            base,
            overlay_version=base.overlay_version + 1,
            scene_number=scene_number,
            scene_card=dict(scene_card),
            trusted_state_gap_notes=gap_notes,
            flat_context_snapshot=flat_snapshot,
            active_promises=active_promises,
            active_promises_total_count=total_active,
            canon_guidance=canon_guidance,
            pov_arc_pressure=scene_pov_arc_pressure,
        )
        return replace(overlay, rendered_markdown=overlay.render_markdown())

    # ------------------------------------------------------------------ builders
    def _build_pressure_ladder(self, blueprint: Mapping[str, Any]) -> list[dict]:
        scene_plan = blueprint.get("scene_plan") or []
        ladder: list[dict] = []
        for entry in scene_plan:
            if not isinstance(entry, Mapping):
                continue
            ladder.append({
                "scene_number": entry.get("scene_number"),
                "label": entry.get("role") or entry.get("label") or "",
                "note": entry.get("purpose") or "",
            })
        return ladder

    def _build_pov_arc_pressure(self, blueprint: Mapping[str, Any]) -> dict:
        pov = blueprint.get("pov_allocation") or []
        if isinstance(pov, list) and pov:
            primary = pov[0]
        else:
            primary = str(pov) if pov else ""
        return {
            "pov_character": primary,
            "structural_phase": blueprint.get("structural_phase", ""),
            "pacing_curve": blueprint.get("pacing_curve", ""),
        }

    def _build_next_scene_obligations(self, blueprint: Mapping[str, Any]) -> list[dict]:
        out: list[dict] = []
        for sub in blueprint.get("subplot_obligations") or []:
            out.append({"kind": "subplot", "note": self._resolve_subplot_ref(sub)})
        for turn in blueprint.get("relationship_turns") or []:
            if not isinstance(turn, Mapping):
                continue
            dyad = turn.get("dyad", "")
            frm = turn.get("from", "")
            to = turn.get("to", "")
            out.append({
                "kind": "relationship_turn",
                "note": f"{dyad}: {frm} \u2192 {to}".strip(),
            })
        for rid in (blueprint.get("reveal_payload") or []):
            out.append({"kind": "reveal", "note": self._resolve_revelation_ref(rid)})
        hooks = blueprint.get("hook_movements") or {}
        for planted in hooks.get("planted") or []:
            out.append({"kind": "hook_planted", "note": self._resolve_hook_ref(planted)})
        for advanced in hooks.get("advanced") or []:
            out.append({"kind": "hook_advanced", "note": self._resolve_hook_ref(advanced)})
        for resolved in hooks.get("resolved") or []:
            out.append({"kind": "hook_resolved", "note": self._resolve_hook_ref(resolved)})
        return out

    def _resolve_subplot_ref(self, ref: Any) -> str:
        return _resolve_seed_ref(
            ref,
            index=self._subplots_by_id,
            text_keys=("name", "function", "arc_summary"),
        )

    def _resolve_hook_ref(self, ref: Any) -> str:
        return _resolve_seed_ref(
            ref,
            index=self._hooks_by_id,
            text_keys=("description", "hook_type"),
        )

    def _resolve_revelation_ref(self, ref: Any) -> str:
        return _resolve_seed_ref(
            ref,
            index=self._revelations_by_id,
            text_keys=("what", "content", "summary", "description"),
        )

    def _build_canon_slices(self, blueprint: Mapping[str, Any]) -> list[dict]:
        slices: list[dict] = []
        for key in ("canon_pillars", "canon_slices", "canon_references"):
            val = self.concept_seed.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, Mapping):
                        slices.append({
                            "title": item.get("title") or item.get("name") or "",
                            "body": item.get("body") or item.get("summary") or item.get("description") or "",
                            "source": item.get("source") or key,
                        })
                    elif isinstance(item, str):
                        slices.append({"title": key, "body": item, "source": key})
        return slices

    def _fetch_canon_guidance_for_scene(
        self,
        *,
        chapter_number: int,
        scene_card: Mapping[str, Any],
    ) -> dict:
        """Load fresh static canon guidance for the current scene.

        Missing or stale guidance is intentionally non-fatal. The scouting
        workflow is a planning-time cache; runtime drafting should continue
        without injecting stale notes.
        """
        if self.canon_guidance_store is None:
            return {}
        blueprint = self.blueprints.get(int(chapter_number), {})
        try:
            guidance = self.canon_guidance_store.load_fresh(
                concept_seed=self.concept_seed,
                chapter_blueprint=blueprint,
                scene_card=scene_card,
            )
        except Exception:  # noqa: BLE001
            logger.exception("canon guidance lookup failed")
            return {}
        return dict(guidance or {})

    def _build_reveal_deadlines(self, blueprint: Mapping[str, Any]) -> list[dict]:
        out: list[dict] = []
        for rid in (blueprint.get("reveal_payload") or []):
            out.append({
                "revelation_id": str(rid),
                "note": self._resolve_revelation_ref(rid),
                "due_by_scene": f"ch{blueprint.get('chapter_number', 0):02d}_close",
                "status": "pending",
            })
        return out

    def _build_exit_vector(self, blueprint: Mapping[str, Any]) -> dict:
        raw = blueprint.get("exit_vector")
        if isinstance(raw, Mapping):
            return dict(raw)
        if isinstance(raw, str) and raw:
            return {"summary": raw}
        return {}

    # ------------------------------------------------------------------ lookups
    def _fetch_gap_notes(self, chapter_number: int) -> list[dict]:
        if self.story_state is None:
            return []
        try:
            return self.story_state.list_open_gaps(chapter_number=chapter_number)
        except Exception:  # noqa: BLE001 -- gap notes missing should not block draft
            logger.exception("list_open_gaps failed for chapter %s", chapter_number)
            return []

    def _fetch_active_promises(self, *, chapter_number: int) -> list[dict]:
        """Base-packet hook: chapter-scoped active promises (spec \u00a77.3).

        Used by ``compile_base`` before the scene is known. Overlay callers
        use ``_fetch_active_promises_for_scene`` so the rendered list is
        urgency-filtered against the *current* scene, not the chapter's first.
        """
        if self.promise_ledger is None:
            return []
        try:
            return list(self.promise_ledger.active_for_chapter(chapter_number))
        except Exception:  # noqa: BLE001
            logger.exception("promise_ledger.active_for_chapter failed")
            return []

    def _fetch_active_promises_for_scene(
        self, *, chapter_number: int, scene_id: str | None,
    ) -> list[dict]:
        """Overlay hook: top-5 urgent promises as of ``scene_id`` (spec \u00a77.3).

        Falls back to the chapter-scoped list when ``scene_id`` is unknown
        (e.g. base packet view) so the packet stays non-empty while still
        deterministic. Overdue rows carry ``status='overdue'`` so the renderer
        emits them under a separate heading with the do-not-force-payoff hint.
        """
        if self.promise_ledger is None:
            return []
        if not scene_id:
            return self._fetch_active_promises(chapter_number=chapter_number)
        try:
            return list(
                self.promise_ledger.list_top_urgent(at_scene=scene_id, n=5)
            )
        except Exception:  # noqa: BLE001
            logger.exception("promise_ledger.list_top_urgent failed")
            return []

    def _count_active_promises_for_scene(
        self, *, chapter_number: int, scene_id: str | None,
    ) -> int:
        if self.promise_ledger is None:
            return 0
        try:
            if scene_id:
                return int(self.promise_ledger.count_active(at_scene=scene_id))
            return len(self.promise_ledger.active_for_chapter(chapter_number))
        except Exception:  # noqa: BLE001
            logger.exception("promise_ledger count_active failed")
            return 0

    def _render_flat_context_snapshot(self, scene_card: Mapping[str, Any]) -> str:
        """Inline the legacy ContextAssembler output so the packet is a strict
        token-superset of flat. Missing assembler \u2192 empty string; callers who
        want parity must provide one."""
        if self.assembler is None:
            return ""
        try:
            return self.assembler.assemble(dict(scene_card))
        except Exception:  # noqa: BLE001 -- surface via packet_fallback_flat
            logger.exception("ContextAssembler.assemble failed during overlay")
            return ""


# --------------------------------------------------------------------------- #
# Module helpers                                                              #
# --------------------------------------------------------------------------- #


def _scene_id(chapter_number: int, scene_number: int) -> str:
    return f"ch{chapter_number:02d}_sc{scene_number:02d}"


def _enrich_pov_arc_pressure_for_scene(
    base_pressure: Mapping[str, Any],
    scene_card: Mapping[str, Any],
) -> dict:
    """Fold the scene card's Weiland arc fields into the chapter-level pressure dict.

    The base packet only knows the chapter blueprint, so its pov_arc_pressure
    carries the chapter's structural_phase and the chapter POV. The scene
    card may also declare ``pov_arc_phase`` (the POV character's current
    Weiland arc phase) and ``arc_phase_transition`` (the new phase if this
    scene flips it). Surface both so the drafter sees the scene's arc
    contract, not just the chapter's.

    The scene-card values fall back to ``scene_voice_permissions.pov_arc_phase``
    when the top-level field is empty, matching the resolution order used
    by ``src.prompting.scene_voice_permissions``.
    """
    enriched: dict[str, Any] = dict(base_pressure or {})

    pov_arc_phase = (scene_card.get("pov_arc_phase") or "").strip()
    if not pov_arc_phase:
        voice_block = scene_card.get("scene_voice_permissions") or {}
        if isinstance(voice_block, Mapping):
            pov_arc_phase = (voice_block.get("pov_arc_phase") or "").strip()
    if pov_arc_phase:
        enriched["pov_arc_phase"] = pov_arc_phase

    arc_phase_transition = (scene_card.get("arc_phase_transition") or "").strip()
    if arc_phase_transition:
        enriched["arc_phase_transition"] = arc_phase_transition

    scene_pov = (scene_card.get("pov_character") or "").strip()
    if scene_pov and not enriched.get("pov_character"):
        enriched["pov_character"] = scene_pov

    return enriched


_PLANNING_ID_RE = re.compile(r"\b(?:R\d{2}[a-z]?|H\d{2}|PP\d{2}|SP-[A-Z]|SP\d+)\b")

_MODEL_FACING_SCENE_CARD_OMIT_KEYS = {
    # Machine tracking IDs are already rendered as story-language obligations
    # in ChapterPacket sections above. Keep them out of the drafter-facing JSON
    # so prose models do not echo planning shorthand.
    "active_subplots",
    "plot_threads_advanced",
    "promises_planted",
    "promises_paid",
    "promises_progressed",
    "hook_actions",
    "revelations",
}


def _model_facing_scene_card(scene_card: Mapping[str, Any]) -> dict:
    return {
        key: _scrub_model_facing_value(value)
        for key, value in dict(scene_card).items()
        if key not in _MODEL_FACING_SCENE_CARD_OMIT_KEYS
    }


def _scrub_model_facing_value(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_model_facing_text(value)
    if isinstance(value, list):
        return [_scrub_model_facing_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            key: _scrub_model_facing_value(item)
            for key, item in value.items()
        }
    return copy.deepcopy(value)


def _scrub_model_facing_text(text: str) -> str:
    return _PLANNING_ID_RE.sub(_planning_id_label, text)


def _planning_id_label(match: re.Match[str]) -> str:
    token = match.group(0)
    if token.startswith("R"):
        return "this reveal"
    if token.startswith("H"):
        return "this hook"
    if token.startswith("PP"):
        return "this promise"
    return "this subplot"


def _index_seed_refs(
    items: Iterable[Any],
    id_keys: Iterable[str],
) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        for key in id_keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                out[value.strip()] = item
    return out


def _resolve_seed_ref(
    ref: Any,
    *,
    index: Mapping[str, Mapping[str, Any]],
    text_keys: Iterable[str],
) -> str:
    if isinstance(ref, Mapping):
        item: Mapping[str, Any] | None = ref
    elif isinstance(ref, str):
        item = index.get(ref.strip())
    else:
        item = None
    if item is None:
        return str(ref)

    fragments: list[str] = []
    for key in text_keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            fragments.append(value.strip())
    if not fragments:
        return str(ref)
    if len(fragments) == 1:
        return fragments[0]
    return f"{fragments[0]}: {fragments[1]}"


def _format_active_promise_line(entry: Mapping[str, Any]) -> str:
    pid = entry.get("promise_id", "(unknown)")
    ptype = entry.get("promise_type") or ""
    desc = entry.get("description") or ""
    head = f"[{ptype}] " if ptype else ""
    fragments: list[str] = []
    due = entry.get("due_by_scene")
    if due:
        fragments.append(f"due by {due}")
    setup = entry.get("setup_scene")
    if setup:
        fragments.append(f"planted {setup}")
    status = entry.get("status")
    if status and status not in ("overdue",):
        fragments.append(status)
    tail = f" ({'; '.join(fragments)})" if fragments else ""
    body = desc or pid
    return f"- {head}{body}{tail}"


def _format_relationship_line(key: str, value: Mapping[str, Any]) -> str:
    trust = float(value.get("trust", 0.0))
    warmth = float(value.get("warmth", 0.0))
    power = float(value.get("power_balance", 0.0))
    arc_type = value.get("arc_type") or ""
    fragments: list[str] = []
    fragments.append(f"trust {_format_signed(trust)}")
    fragments.append(f"warmth {_format_signed(warmth)}")
    fragments.append(f"power_balance {_format_signed(power)}")
    tail = "; ".join(fragments)
    arc = f" [{arc_type}]" if arc_type and arc_type != "other" else ""
    return f"- {key}: {tail}{arc}"


def _format_signed(value: float) -> str:
    if abs(value) < 1e-9:
        return "0.0"
    return f"{value:+.2f}"


def _format_overdue_promise_line(entry: Mapping[str, Any]) -> str:
    pid = entry.get("promise_id", "(unknown)")
    ptype = entry.get("promise_type") or ""
    desc = entry.get("description") or ""
    due = entry.get("due_by_scene") or ""
    overdue_by = entry.get("overdue_by_scenes")
    head = f"[{ptype}] " if ptype else ""
    fragments: list[str] = []
    if due:
        fragments.append(f"due by {due}")
    if isinstance(overdue_by, int) and overdue_by > 0:
        suffix = "scene" if overdue_by == 1 else "scenes"
        fragments.append(f"{overdue_by} {suffix} overdue")
    tail = f" ({'; '.join(fragments)})" if fragments else ""
    body = desc or pid
    return f"- {head}{body}{tail}"


__all__ = ["ChapterPacket", "ChapterPacketCompiler"]
