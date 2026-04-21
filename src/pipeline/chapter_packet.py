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

Active promises (Slice 3), continuity events (Slice 4), and relationship
context (Slice 5) are wired through optional dependencies and stay empty here.

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
                rid = r.get("revelation_id", "(unknown)")
                due = r.get("due_by_scene", "")
                status = r.get("status", "")
                parts.append(f"- {rid}: due {due}" + (f" [{status}]" if status else ""))

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
            parts.append("")
            parts.append("### Relationship Context")
            for k, v in self.relationship_context.items():
                parts.append(f"- {k}: {v}")

        if self.exit_vector:
            parts.append("")
            parts.append("### Exit Vector")
            for k, v in self.exit_vector.items():
                parts.append(f"- {k}: {v}")

        if self.scene_card:
            parts.append("")
            parts.append("## Scene Card")
            parts.append("```json")
            parts.append(json.dumps(dict(self.scene_card), indent=2))
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

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class ChapterPacketCompiler:
    """Builds chapter packets from planning artifacts + trusted state.

    Constructor takes optional Slice-3/4/5 collaborators; those stay ``None``
    for Slice 2 and the corresponding packet fields stay empty. Deliberately
    does not hold a reference to the orchestrator \u2014 callers pass in what the
    compiler needs per call.
    """

    def __init__(
        self,
        *,
        concept_seed: Mapping[str, Any],
        blueprints: Mapping[int, Mapping[str, Any]],
        assembler: Optional["ContextAssembler"] = None,
        story_state: Optional["StoryState"] = None,
        promise_ledger=None,           # Slice 3
        continuity_log=None,           # Slice 4
        sociogram=None,                # Slice 5
        exemplar_snippets: list[dict] | None = None,
        anti_exemplar_snippets: list[dict] | None = None,
    ) -> None:
        self.concept_seed = dict(concept_seed)
        self.blueprints: dict[int, dict] = {int(k): dict(v) for k, v in blueprints.items()}
        self.assembler = assembler
        self.story_state = story_state
        self.promise_ledger = promise_ledger
        self.continuity_log = continuity_log
        self.sociogram = sociogram
        self.exemplar_snippets = list(exemplar_snippets or [])
        self.anti_exemplar_snippets = list(anti_exemplar_snippets or [])

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
        continuity_events = self._fetch_continuity_events(chapter_number=chapter_number)
        relationship_context = self._fetch_relationship_context(chapter_number=chapter_number)

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
            relationship_context=relationship_context,
            exit_vector=exit_vector,
            trusted_state_gap_notes=[],
            exemplar_snippets=list(self.exemplar_snippets),
            anti_exemplar_snippets=list(self.anti_exemplar_snippets),
            continuity_events=continuity_events,
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
        # chapter-wide snapshot. Slice 4/5 follow the same "refresh at overlay"
        # pattern once their stores are populated.
        scene_id = _scene_id(base.chapter_number, scene_number) if scene_number else None
        active_promises = self._fetch_active_promises_for_scene(
            chapter_number=base.chapter_number, scene_id=scene_id,
        )
        total_active = self._count_active_promises_for_scene(
            chapter_number=base.chapter_number, scene_id=scene_id,
        )
        continuity_events = self._fetch_continuity_events_for_scene(
            chapter_number=base.chapter_number, scene_id=scene_id,
            scene_card=scene_card,
        )
        relationship_context = self._fetch_relationship_context_for_scene(
            chapter_number=base.chapter_number, scene_card=scene_card,
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
            continuity_events=continuity_events,
            relationship_context=relationship_context,
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
            out.append({"kind": "subplot", "note": str(sub)})
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
            out.append({"kind": "reveal", "note": str(rid)})
        hooks = blueprint.get("hook_movements") or {}
        for planted in hooks.get("planted") or []:
            out.append({"kind": "hook_planted", "note": str(planted)})
        for advanced in hooks.get("advanced") or []:
            out.append({"kind": "hook_advanced", "note": str(advanced)})
        for resolved in hooks.get("resolved") or []:
            out.append({"kind": "hook_resolved", "note": str(resolved)})
        return out

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

    def _build_reveal_deadlines(self, blueprint: Mapping[str, Any]) -> list[dict]:
        out: list[dict] = []
        for rid in (blueprint.get("reveal_payload") or []):
            out.append({
                "revelation_id": str(rid),
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

    def _fetch_continuity_events(self, *, chapter_number: int) -> list[dict]:
        """Base-packet hook: chapter-scoped continuity events.

        Used by ``compile_base`` when the scene is not yet known. Overlay
        callers use ``_fetch_continuity_events_for_scene`` to narrow by the
        scene's POV and characters_present so the drafter does not wade
        through unrelated rows.
        """
        if self.continuity_log is None:
            return []
        try:
            return list(self.continuity_log.events_for_chapter(chapter_number))
        except Exception:  # noqa: BLE001
            logger.exception("continuity_log.events_for_chapter failed")
            return []

    def _fetch_continuity_events_for_scene(
        self,
        *,
        chapter_number: int,
        scene_id: str | None,
        scene_card: Mapping[str, Any] | None,
    ) -> list[dict]:
        """Overlay hook: chapter events filtered to those whose subject is
        the POV or among ``characters_present``, bounded to strictly-before
        ``scene_id`` so the scene does not see its own events (spec \u00a78.1
        narrow-events invariant \u2014 only prior-state continuity propagates)."""
        base_rows = self._fetch_continuity_events(chapter_number=chapter_number)
        if not base_rows:
            return []
        if scene_card is None:
            return base_rows
        subjects: set[str] = set()
        pov = scene_card.get("pov_character")
        if isinstance(pov, str) and pov:
            subjects.add(pov)
        for char in scene_card.get("characters_present") or []:
            if isinstance(char, str) and char:
                subjects.add(char)
        if not subjects:
            return base_rows
        out: list[dict] = []
        for row in base_rows:
            if row.get("subject") in subjects and not _scene_id_strictly_at_or_after(
                row.get("scene_id"), scene_id,
            ):
                out.append(row)
        return out

    def _fetch_relationship_context(self, *, chapter_number: int) -> dict:
        """Base-packet hook: chapter-scoped relationship snapshot.

        Used by ``compile_base`` before the scene is known. Overlay callers
        go through ``_fetch_relationship_context_for_scene`` so the POV /
        characters_present filter is applied per Slice 5.
        """
        if self.sociogram is None:
            return {}
        try:
            return dict(self.sociogram.snapshot_for_chapter(chapter_number))
        except Exception:  # noqa: BLE001
            logger.exception("sociogram.snapshot_for_chapter failed")
            return {}

    def _fetch_relationship_context_for_scene(
        self, *, chapter_number: int, scene_card: Mapping[str, Any] | None,
    ) -> dict:
        """Overlay hook: prefer the Sociogram's ``context_for_scene`` when
        available (narrows to POV + characters_present dyads); otherwise
        fall back to the chapter-scoped snapshot."""
        if self.sociogram is None:
            return {}
        method = getattr(self.sociogram, "context_for_scene", None)
        if callable(method) and scene_card is not None:
            try:
                return dict(method(scene_card=scene_card))
            except Exception:  # noqa: BLE001
                logger.exception("sociogram.context_for_scene failed")
        return self._fetch_relationship_context(chapter_number=chapter_number)

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


_SCENE_ID_RE = re.compile(r"^ch(\d{2})_sc(\d{2})$")


def _scene_id_strictly_at_or_after(scene_a: str | None, scene_b: str | None) -> bool:
    """True when ``scene_a`` is >= ``scene_b``. Used by the overlay's
    continuity filter to keep a scene from seeing its own events."""
    if not scene_a or not scene_b:
        return False
    ma = _SCENE_ID_RE.match(scene_a)
    mb = _SCENE_ID_RE.match(scene_b)
    if ma is None or mb is None:
        return False
    return (int(ma.group(1)), int(ma.group(2))) >= (int(mb.group(1)), int(mb.group(2)))


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
