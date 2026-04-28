"""IdeaSessionCapture — headless api for the idea-session front-door surface.

This module is the interop seam between Claude Code and Codex. The
conversation that drives a capture lives in `workflows/idea_session_capture/SKILL.md`
(portable markdown both tools can read). The state mutations and the
expand-to-surface-drafts bridge live here so both tools mutate identical
state through the same Python entry points.

Three responsibilities:

1. **Scaffolding** — `init_workspace` creates `workflows/idea_session/`
   with `capture.json`, `session.md`, `surface_handoffs/*.md` and an
   optional copied transcript.
2. **State mutation** — `add_decision`, `add_open_question`,
   `update_handoff`, `set_north_star`, `set_status` provide a typed
   surface that the chat agent (Claude or Codex) calls instead of
   hand-editing JSON. Each call validates against `schema.json`.
3. **Expansion** — `expand_to_surface_drafts` reads a populated capture
   and pre-seeds the six downstream surface artifacts
   (`universe.json`, `canon.json`, `voice.json`, `characters.json`,
   `outline.json`, `scene_cards.json`) with whatever the capture
   already has. The author opens each surface to a partly-filled
   draft, not a blank file. Existing artifacts are never clobbered;
   `--force` is required to overwrite.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any

from src.project_paths import ProjectPaths, _slugify_franchise, slugify_title
from workflows._shared.schema_loader import load_surface_schema

logger = logging.getLogger(__name__)


SURFACES: tuple[str, ...] = (
    "universe",
    "canon",
    "voice",
    "characters",
    "outline",
    "scene_cards",
)

CAPTURE_FILENAME = "capture.json"
SESSION_FILENAME = "session.md"
SURFACE_HANDOFF_DIRNAME = "surface_handoffs"
RAW_TRANSCRIPT_FILENAME = "raw_transcript.md"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class CaptureStatus:
    """Lightweight readiness summary for a capture session."""

    title: str
    franchise: str
    updated_at: str | None
    decisions_count: int
    open_questions_count: int
    handoff_status: dict[str, dict[str, Any]]
    relationship: dict[str, Any]
    ready_for_expand: bool


class IdeaSessionCapture:
    """Programmatic surface for an idea-session capture workspace.

    Both Claude Code and Codex chat agents call this class for state
    mutation; only the surrounding chat experience differs.
    """

    SURFACES = SURFACES

    def __init__(
        self,
        title: str,
        franchise: str,
        *,
        base_dir: str | Path = ".",
    ) -> None:
        self.title = title
        self.franchise = franchise
        self.book_slug = slugify_title(title)
        self.franchise_slug = _slugify_franchise(franchise)
        self.paths = ProjectPaths(
            self.book_slug,
            base_dir=str(base_dir),
            franchise_slug=self.franchise_slug,
        )
        self._schema: dict[str, Any] | None = None

    # ---- paths ---------------------------------------------------------

    @property
    def workspace(self) -> Path:
        return self.paths.workflows_dir / "idea_session"

    @property
    def capture_path(self) -> Path:
        return self.workspace / CAPTURE_FILENAME

    @property
    def session_path(self) -> Path:
        return self.workspace / SESSION_FILENAME

    @property
    def surface_handoff_dir(self) -> Path:
        return self.workspace / SURFACE_HANDOFF_DIRNAME

    @property
    def raw_transcript_path(self) -> Path:
        return self.workspace / RAW_TRANSCRIPT_FILENAME

    # ---- schema --------------------------------------------------------

    def _schema_doc(self) -> dict[str, Any]:
        if self._schema is None:
            try:
                self._schema = load_surface_schema(
                    "workflows.idea_session_capture"
                )
            except Exception:
                schema_path = (
                    Path(__file__).resolve().parent / "schema.json"
                )
                self._schema = json.loads(schema_path.read_text(encoding="utf-8"))
        return self._schema

    def _validate_capture(self, capture: dict[str, Any]) -> list[str]:
        """Lightweight structural validation matching schema.json shape.

        We avoid jsonschema as a hard dep here; the bundle compiler does
        the deep schema check at compile time. This catches the obvious
        author errors at capture-write time so a Codex/Claude session
        does not silently corrupt the file.
        """
        errors: list[str] = []
        required_top = (
            "surface",
            "schema_version",
            "project",
            "relationship",
            "north_star",
            "surface_handoffs",
        )
        for key in required_top:
            if key not in capture:
                errors.append(f"missing required top-level field: {key}")
        if capture.get("surface") not in (None, "idea-session-capture"):
            errors.append(
                "surface must be 'idea-session-capture' "
                f"(got {capture.get('surface')!r})"
            )
        confidence = {"open", "tentative", "settled"}
        for idx, decision in enumerate(capture.get("decisions") or []):
            if not isinstance(decision, dict):
                errors.append(f"decisions[{idx}] is not an object")
                continue
            if decision.get("confidence") and decision["confidence"] not in confidence:
                errors.append(
                    f"decisions[{idx}].confidence must be one of {sorted(confidence)}"
                )
        return errors

    # ---- scaffolding ---------------------------------------------------

    def init_workspace(
        self,
        *,
        session_name: str = "initial-idea-session",
        transcript_path: str | Path | None = None,
        project_scope: str = "standalone",
        canon_status: str | None = None,
        series_id: str | None = None,
        book_number: int | None = None,
        cosmology_id: str | None = None,
        source_franchise: str | None = None,
        source_work: str | None = None,
        parent_project: str | None = None,
        branch_point: str | None = None,
        base_source: str | None = None,
        force: bool = False,
    ) -> dict[str, list[Path]]:
        """Create the capture workspace. Idempotent unless force=True."""
        capture = self._default_capture(
            session_name=session_name,
            transcript_path=str(transcript_path) if transcript_path else None,
            project_scope=project_scope,
            canon_status=canon_status,
            series_id=series_id,
            book_number=book_number,
            cosmology_id=cosmology_id,
            source_franchise=source_franchise,
            source_work=source_work,
            parent_project=parent_project,
            branch_point=branch_point,
            base_source=base_source,
        )

        written: list[Path] = []
        skipped: list[Path] = []

        if self._write_json(self.capture_path, capture, force=force):
            written.append(self.capture_path)
        else:
            skipped.append(self.capture_path)

        if self._write_text(
            self.session_path,
            self._session_markdown(),
            force=force,
        ):
            written.append(self.session_path)
        else:
            skipped.append(self.session_path)

        readme_path = self.workspace / "README.md"
        if self._write_text(readme_path, self._readme_text(), force=force):
            written.append(readme_path)
        else:
            skipped.append(readme_path)

        for surface in SURFACES:
            path = self.surface_handoff_dir / f"{surface}.md"
            text = self._surface_handoff_markdown(surface)
            if self._write_text(path, text, force=force):
                written.append(path)
            else:
                skipped.append(path)

        if transcript_path is not None:
            src = Path(transcript_path)
            if not src.exists():
                raise FileNotFoundError(f"transcript not found: {src}")
            if self._write_text(
                self.raw_transcript_path,
                src.read_text(encoding="utf-8"),
                force=force,
            ):
                written.append(self.raw_transcript_path)
            else:
                skipped.append(self.raw_transcript_path)

        return {"written": written, "skipped": skipped}

    # ---- state ---------------------------------------------------------

    def load(self) -> dict[str, Any]:
        if not self.capture_path.exists():
            raise FileNotFoundError(
                f"No capture at {self.capture_path}; run init_workspace first."
            )
        return json.loads(self.capture_path.read_text(encoding="utf-8"))

    def save(self, capture: dict[str, Any]) -> None:
        errors = self._validate_capture(capture)
        if errors:
            raise ValueError(
                "capture.json failed structural validation:\n  - "
                + "\n  - ".join(errors)
            )
        capture["updated_at"] = _utc_now()
        self._write_json(self.capture_path, capture, force=True)

    def status(self) -> CaptureStatus:
        capture = self.load()
        decisions = capture.get("decisions") or []
        open_questions = capture.get("open_questions") or []
        handoffs = capture.get("surface_handoffs") or {}
        relationship = capture.get("relationship") or {}
        ready = self._is_ready_for_expand(capture)
        return CaptureStatus(
            title=capture.get("project", {}).get("title", self.title),
            franchise=capture.get("project", {}).get("franchise", self.franchise),
            updated_at=capture.get("updated_at"),
            decisions_count=len(decisions),
            open_questions_count=len(open_questions),
            handoff_status={
                surface: {
                    "status": (handoffs.get(surface) or {}).get("status", "missing"),
                    "settled": len(
                        (handoffs.get(surface) or {}).get("settled_inputs") or []
                    ),
                    "questions": len(
                        (handoffs.get(surface) or {}).get("questions_to_resolve")
                        or []
                    ),
                }
                for surface in SURFACES
            },
            relationship=relationship,
            ready_for_expand=ready,
        )

    def add_decision(
        self,
        *,
        surface: str,
        topic: str,
        decision: str,
        confidence: str = "tentative",
    ) -> None:
        capture = self.load()
        capture.setdefault("decisions", []).append(
            {
                "surface": surface,
                "topic": topic,
                "decision": decision,
                "confidence": confidence,
            }
        )
        self.save(capture)

    def add_open_question(
        self,
        *,
        surface: str,
        question: str,
        why_it_matters: str = "",
    ) -> None:
        capture = self.load()
        capture.setdefault("open_questions", []).append(
            {
                "surface": surface,
                "question": question,
                "why_it_matters": why_it_matters,
            }
        )
        self.save(capture)

    def update_handoff(
        self,
        surface: str,
        *,
        status: str | None = None,
        settled_inputs: list[str] | None = None,
        questions_to_resolve: list[str] | None = None,
        notes: str | None = None,
    ) -> None:
        if surface not in SURFACES:
            raise ValueError(f"unknown surface: {surface}")
        capture = self.load()
        handoffs = capture.setdefault("surface_handoffs", {})
        block = handoffs.setdefault(
            surface,
            {
                "status": "not_started",
                "settled_inputs": [],
                "questions_to_resolve": [],
                "notes": "",
            },
        )
        if status is not None:
            block["status"] = status
        if settled_inputs is not None:
            block["settled_inputs"] = list(settled_inputs)
        if questions_to_resolve is not None:
            block["questions_to_resolve"] = list(questions_to_resolve)
        if notes is not None:
            block["notes"] = notes
        self.save(capture)

    def set_north_star(
        self,
        *,
        one_sentence_pitch: str | None = None,
        reader_promise: str | None = None,
        emotional_core: str | None = None,
        author_intent: str | None = None,
        non_negotiables: list[str] | None = None,
        avoid: list[str] | None = None,
    ) -> None:
        capture = self.load()
        ns = capture.setdefault(
            "north_star",
            {
                "one_sentence_pitch": "",
                "reader_promise": "",
                "emotional_core": "",
                "author_intent": "",
                "non_negotiables": [],
                "avoid": [],
            },
        )
        if one_sentence_pitch is not None:
            ns["one_sentence_pitch"] = one_sentence_pitch
        if reader_promise is not None:
            ns["reader_promise"] = reader_promise
        if emotional_core is not None:
            ns["emotional_core"] = emotional_core
        if author_intent is not None:
            ns["author_intent"] = author_intent
        if non_negotiables is not None:
            ns["non_negotiables"] = list(non_negotiables)
        if avoid is not None:
            ns["avoid"] = list(avoid)
        self.save(capture)

    # ---- expansion -----------------------------------------------------

    def expand_to_surface_drafts(
        self,
        *,
        force: bool = False,
        surfaces: list[str] | None = None,
    ) -> dict[str, list[Path]]:
        """Pre-seed the six surface artifacts from capture state.

        For each surface in `surfaces` (default: all six), this writes
        a partial `workflows/<surface>.json` skeleton populated with
        whatever the capture already knows. The downstream skill opens
        the file to a populated draft instead of a blank one.

        Existing files are skipped unless `force=True`. The expansion
        is intentionally conservative — it only fills the few fields
        the capture authoritatively carries (north_star, relationship,
        per-surface handoff settled_inputs). Surface schemas have many
        optional fields; this leaves them empty for the surface session
        to deepen.
        """
        capture = self.load()
        target_surfaces = surfaces or list(SURFACES)
        written: list[Path] = []
        skipped: list[Path] = []

        if not self._is_ready_for_expand(capture):
            raise ValueError(
                "Capture is not ready to expand. Set north_star.one_sentence_pitch "
                "and at least one decision before expanding."
            )

        for surface in target_surfaces:
            if surface == "scene_cards":
                # Scene cards are per-card files, not a single artifact.
                # The capture's scene_cards handoff produces an
                # `_intent.md` brief instead of a JSON skeleton.
                path = (
                    self.paths.workflows_dir
                    / "scene_cards"
                    / "_intent.md"
                )
                text = self._scene_cards_intent(capture)
                if self._write_text(path, text, force=force):
                    written.append(path)
                else:
                    skipped.append(path)
                continue

            artifact_path = self.paths.workflows_dir / f"{surface}.json"
            draft = self._build_surface_draft(surface, capture)
            errors = _validate_surface_draft(surface, draft)
            if errors:
                raise RuntimeError(
                    f"expand_to_surface_drafts produced an invalid {surface!r} "
                    f"skeleton (schema drift bug). Errors: {errors}"
                )
            if self._write_json(artifact_path, draft, force=force):
                written.append(artifact_path)
            else:
                skipped.append(artifact_path)

        return {"written": written, "skipped": skipped}

    # ---- internal: defaults & rendering --------------------------------

    def _is_ready_for_expand(self, capture: dict[str, Any]) -> bool:
        north_star = capture.get("north_star") or {}
        if not (north_star.get("one_sentence_pitch") or "").strip():
            return False
        decisions = capture.get("decisions") or []
        return bool(decisions)

    def _default_capture(
        self,
        *,
        session_name: str,
        transcript_path: str | None,
        project_scope: str,
        canon_status: str | None,
        series_id: str | None,
        book_number: int | None,
        cosmology_id: str | None,
        source_franchise: str | None,
        source_work: str | None,
        parent_project: str | None,
        branch_point: str | None,
        base_source: str | None,
    ) -> dict[str, Any]:
        relationship = {
            "project_scope": project_scope,
            "canon_status": canon_status,
            "series_id": series_id,
            "book_number": book_number,
            "cosmology_id": cosmology_id,
            "source_franchise": source_franchise,
            "source_work": source_work,
            "parent_project": parent_project,
            "branch_point": branch_point,
            "base_source": base_source,
        }
        return {
            "surface": "idea-session-capture",
            "schema_version": "1.0",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "project": {
                "title": self.title,
                "franchise": self.franchise,
                "book_slug": self.book_slug,
                "franchise_slug": self.franchise_slug,
                "session_name": session_name,
            },
            "relationship": relationship,
            "source": {
                "transcript_path": transcript_path,
                "raw_transcript_file": (
                    RAW_TRANSCRIPT_FILENAME if transcript_path else None
                ),
            },
            "north_star": {
                "one_sentence_pitch": "",
                "reader_promise": "",
                "emotional_core": "",
                "author_intent": "",
                "non_negotiables": [],
                "avoid": [],
            },
            "depth_ladder": [
                {
                    "stage": "spark",
                    "goal": "Find the idea, promise, and emotional pressure.",
                    "status": "open",
                },
                {
                    "stage": "foundation",
                    "goal": "Set universe, continuity, tone, premise, conflict, and theme.",
                    "status": "open",
                },
                {
                    "stage": "deepening",
                    "goal": "Develop characters, setting logic, voice, structure, and recurring choices.",
                    "status": "open",
                },
                {
                    "stage": "production_handoff",
                    "goal": "Turn settled decisions into six workflow-kit surfaces.",
                    "status": "open",
                },
            ],
            "decisions": [],
            "open_questions": [],
            "surface_handoffs": {
                surface: {
                    "status": "not_started",
                    "settled_inputs": [],
                    "questions_to_resolve": [],
                    "notes": "",
                }
                for surface in SURFACES
            },
            "parking_lot": [],
            "next_steps": [
                "Fill session.md during the idea chat.",
                "Move settled notes into capture.json decisions and surface_handoffs.",
                "Run `python scripts/idea_session_capture.py expand` to pre-seed the six surfaces.",
                "Author the six workflow-kit surfaces from the seeded drafts.",
                "Run scripts/compile_bundle.py after the six surfaces are ready.",
            ],
        }

    def _session_markdown(self) -> str:
        return dedent(
            f"""\
            # Idea Session - {self.title}

            Franchise / universe: {self.franchise}

            ## Relationship To Existing Work

            - Project scope:
            - Canon status:
            - Series ID / book number:
            - Shared cosmology ID:
            - Source franchise / source work:
            - Parent project:
            - Branch point:
            - Base source:

            ## North Star

            - One-sentence pitch:
            - Reader promise:
            - Emotional core:
            - Author intent:
            - Non-negotiables:
            - Avoid:

            ## Session Ladder

            ### 1. Spark

            What is the first image, dilemma, relationship, or question that makes this book feel alive?

            ### 2. Foundation

            What must be true about the setting, timeline, canon status, tone, premise, conflict, and theme?

            ### 3. Deepening

            What does the book become when we push on character wounds, contradictions, setting pressures, and moral cost?

            ### 4. Production Handoff

            Which decisions are settled enough to hand to universe, canon, voice, characters, outline, and scene cards?

            ## Settled Decisions

            -

            ## Open Questions

            -

            ## Surface Notes

            ### Universe

            ### Canon

            ### Voice

            ### Characters

            ### Outline

            ### Scene Cards

            ## Parking Lot

            -
            """
        )

    def _readme_text(self) -> str:
        return dedent(
            """\
            # Idea Session Capture

            This folder is the author-facing front door for planning. It is
            not read by `compile_bundle.py`. Use it to hold chat notes,
            settled decisions, open questions, and handoffs into the six
            workflow-kit surfaces.

            ## Files

            - `capture.json` — machine-readable session state (mutated by
              both Claude Code and Codex through `IdeaSessionCapture`).
            - `session.md` — live planning notes; free-form.
            - `raw_transcript.md` — optional pasted/exported chat transcript.
            - `surface_handoffs/*.md` — per-surface notes the downstream
              surface session inherits.

            ## Workflow

            1. Run a planning chat (Claude Code skill `idea-session-capture`,
               or Codex via `AGENTS.md`).
            2. Mutate state through `IdeaSessionCapture` calls; the agent
               does the conversation, the api does the writes.
            3. When north-star is settled and you have at least a few
               decisions, run:
               ```bash
               python scripts/idea_session_capture.py expand --title "<title>" --franchise "<franchise>"
               ```
               This pre-seeds the six workflow-kit surface artifacts.
            4. Author each surface from its seeded draft.
            5. Compile with `python scripts/compile_bundle.py`.
            """
        )

    def _surface_handoff_markdown(self, surface: str) -> str:
        titles = {
            "universe": "Universe Builder",
            "canon": "Canon Drafter",
            "voice": "Voice Discovery",
            "characters": "Character Forge",
            "outline": "Outline Planner",
            "scene_cards": "Scene Card Authoring",
        }
        prompts = {
            "universe": "Premise, conflict, theme, setting scope, canon status, era, tone, target shape.",
            "canon": "Continuity rules, constraints, terminology, allowed references, mechanics.",
            "voice": "POV, register, prose rules, anti-patterns, dialogue texture, character voices.",
            "characters": "Cast, wants, needs, wounds, contradictions, relationships, arc types (Weiland: lie/ghost/want/need/arc_type).",
            "outline": "Brooks four-part beat map, promises, reveals, reversals, subplots, chapter turns. Chapters carry as many or as few scenes as the dramatic need calls for.",
            "scene_cards": "Per-scene beats, POV, characters present, turning points, hooks. Less is more — only split a chapter into multiple scenes when each scene carries its own load-bearing turning point.",
        }
        return dedent(
            f"""\
            # {titles[surface]} Handoff

            Purpose: {prompts[surface]}

            ## Settled Inputs

            -

            ## Open Questions

            -

            ## Must Preserve

            -

            ## Avoid

            -

            ## Notes For Surface Session

            """
        )

    def _scene_cards_intent(self, capture: dict[str, Any]) -> str:
        north_star = capture.get("north_star") or {}
        handoff = (capture.get("surface_handoffs") or {}).get("scene_cards") or {}
        settled = handoff.get("settled_inputs") or []
        avoid = north_star.get("avoid") or []
        return dedent(
            f"""\
            # Scene Cards — Intent Brief

            Generated from idea-session capture. Read before authoring scene cards.

            ## Reader promise
            {north_star.get('reader_promise') or '(not yet set)'}

            ## Emotional core
            {north_star.get('emotional_core') or '(not yet set)'}

            ## Settled scene-level intent
            {chr(10).join(f'- {item}' for item in settled) if settled else '- (none yet)'}

            ## Anti-patterns / things to avoid
            {chr(10).join(f'- {item}' for item in avoid) if avoid else '- (none yet)'}

            ## Scene-count discipline

            Less is more. A chapter with a single load-bearing scene is healthier
            than a chapter with three scenes that share one turning point. Only
            split a chapter when each resulting scene carries its own:

            - distinct turning point (trigger / shift / cost)
            - distinct mission for the POV character
            - distinct emotional arc (start / shift / end)

            If two candidate scenes share a turning point, fold them into one.

            ## Notes from handoff

            {handoff.get('notes') or '(no notes)'}
            """
        )

    def _build_surface_draft(
        self,
        surface: str,
        capture: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a schema-valid skeleton surface artifact from capture state.

        Each skeleton passes the surface validator on write — required
        fields land with EDIT_ME placeholders that satisfy minLength /
        minItems / enum constraints. The downstream surface session
        replaces the placeholders with real content.
        """
        north_star = capture.get("north_star") or {}
        relationship = capture.get("relationship") or {}
        handoff = (capture.get("surface_handoffs") or {}).get(surface) or {}
        settled = handoff.get("settled_inputs") or []
        decisions_for_surface = [
            d
            for d in (capture.get("decisions") or [])
            if d.get("surface") == surface
        ]
        notes = handoff.get("notes") or ""
        questions = handoff.get("questions_to_resolve") or []
        common_envelope = {
            "surface": _surface_envelope_name(surface),
            "schema_version": "1.0",
            "_seeded_from_idea_session": {
                "session": (capture.get("project") or {}).get("session_name"),
                "captured_at": capture.get("updated_at"),
                "settled_inputs": settled,
                "decisions": [
                    {
                        "topic": d.get("topic"),
                        "decision": d.get("decision"),
                        "confidence": d.get("confidence"),
                    }
                    for d in decisions_for_surface
                ],
                "open_questions": questions,
                "notes": notes,
            },
        }

        if surface == "universe":
            canon_status = _canon_status_or_default(
                relationship.get("canon_status")
            )
            meta: dict[str, Any] = {
                "project_title": self.title,
                "franchise": self.franchise,
                "canon_status": canon_status,
                "era": "<EDIT_ME>",
                "tone": "heroic_with_weight",
                "target_word_count": 80000,
            }
            project_scope = relationship.get("project_scope")
            if project_scope in {"standalone", "planned_series", "continuation"}:
                meta["project_scope"] = project_scope
            if relationship.get("series_id"):
                meta["series_id"] = relationship["series_id"]
            if relationship.get("book_number"):
                meta["book_number"] = relationship["book_number"]
            if relationship.get("cosmology_id"):
                meta["cosmology_id"] = relationship["cosmology_id"]

            universe_meta: dict[str, Any] = {
                "universe_name": self.franchise,
                "franchise": self.franchise,
                "canon_status": canon_status,
                "commercial_intent": "fanfiction_noncommercial",
            }
            if relationship.get("cosmology_id"):
                universe_meta["cosmology_id"] = relationship["cosmology_id"]
            if relationship.get("source_work") or relationship.get("branch_point"):
                universe_meta["branch_point"] = {
                    "source_canon": relationship.get("source_franchise") or "",
                    "divergence_point": relationship.get("branch_point") or "",
                    "divergence_description": relationship.get("base_source") or "",
                }

            artifact: dict[str, Any] = {**common_envelope}
            artifact["meta"] = meta
            artifact["universe_meta"] = universe_meta
            # Optional sections — fill only when the capture has content.
            if north_star.get("one_sentence_pitch"):
                artifact["premise"] = {
                    "what_if": (
                        f"<EDIT_ME — restate as a >=50-char 'What if' premise. "
                        f"Seed: {north_star['one_sentence_pitch']}"
                    ),
                    "logline": north_star["one_sentence_pitch"],
                }
            if north_star.get("emotional_core") or north_star.get("author_intent"):
                artifact["theme"] = {}
                if north_star.get("emotional_core"):
                    artifact["theme"]["thematic_premise"] = north_star["emotional_core"]
            if north_star.get("non_negotiables") or north_star.get("avoid"):
                artifact["extended_metadata"] = {}
                if north_star.get("non_negotiables"):
                    artifact["extended_metadata"]["non_negotiables"] = list(
                        north_star["non_negotiables"]
                    )
                if north_star.get("avoid"):
                    artifact["extended_metadata"]["avoid"] = list(north_star["avoid"])
            return artifact

        if surface == "canon":
            artifact = {**common_envelope}
            artifact["canon_constraints"] = {
                "continuity": "<EDIT_ME — describe continuity stance for this book>",
                "canon_preserved": [],
                "style_constraints": [],
            }
            artifact["canon_profile"] = {
                "franchise": self.franchise,
            }
            if relationship.get("canon_status"):
                artifact["canon_profile"]["continuity"] = relationship[
                    "canon_status"
                ]
            if relationship.get("source_work"):
                artifact["canon_profile"]["franchise_terminology_notes"] = (
                    f"Source work: {relationship['source_work']}"
                )
            artifact["force_mechanics"] = {}
            artifact["terminology_registry"] = []
            return artifact

        if surface == "voice":
            artifact = {**common_envelope}
            voice_def: dict[str, Any] = {
                "pov_approach": "<EDIT_ME — e.g., 'close third, single POV, past tense'>",
                "prose_register": "<EDIT_ME — e.g., 'literary thriller; sentence-level rhythm'>",
                "reference_authors": [],
                "character_voices": {},
                "anti_slop_rules": [],
                "anti_patterns": [],
            }
            if north_star.get("author_intent"):
                voice_def["narrative_voice_notes"] = north_star["author_intent"]
            artifact["voice_definition"] = voice_def
            return artifact

        if surface == "characters":
            artifact = {**common_envelope}
            placeholder_three_dim = {
                "surface": (
                    "<EDIT_ME — describe how this character presents to "
                    "the world; >=50 chars. Replace placeholder.>"
                ),
                "backstory_inner_demons": (
                    "<EDIT_ME — describe the wound, ghost, or contradiction "
                    "this character carries; >=50 chars.>"
                ),
                "action_under_pressure": (
                    "<EDIT_ME — describe what this character does when forced "
                    "to choose under stakes; >=50 chars.>"
                ),
            }
            artifact["ensemble_cast"] = [
                {
                    "name": "<EDIT_ME — Protagonist Name>",
                    "role": "protagonist",
                    "three_dimensions": dict(placeholder_three_dim),
                },
                {
                    "name": "<EDIT_ME — Antagonist or Co-Lead Name>",
                    "role": "antagonist",
                    "three_dimensions": dict(placeholder_three_dim),
                },
            ]
            artifact["referenced_characters"] = []
            artifact["relationship_arcs"] = []
            artifact["_weiland_notes"] = (
                "Each main character needs lie_believed, ghost, want, need, "
                "arc_type, and an arc_phase_map keyed by chapter or scene id. "
                "Reference: K.M. Weiland's character arc framework."
            )
            return artifact

        if surface == "outline":
            artifact = {**common_envelope}
            artifact["structural_notes"] = {
                "brooks_alignment": {
                    "part_1_setup": "",
                    "inciting_incident": "",
                    "first_plot_point": "",
                    "part_2_response": "",
                    "first_pinch_point": "",
                    "midpoint": "",
                    "part_3_attack": "",
                    "second_pinch_point": "",
                    "second_plot_point": "",
                    "part_4_resolution": "",
                    "climax": "",
                },
                "_scene_count_discipline": (
                    "Chapters carry as many or as few scenes as the dramatic "
                    "need requires. A chapter with a single load-bearing scene "
                    "is healthier than a chapter padded with redundant beats. "
                    "Only split when each resulting scene has a distinct "
                    "turning point, mission, and emotional arc."
                ),
            }
            artifact["outline"] = [
                {
                    "chapter_number": 1,
                    "chapter_title": "<EDIT_ME — Chapter 1 title>",
                    "synopsis": (
                        "<EDIT_ME — replace this placeholder with a real "
                        "chapter-1 synopsis. Add additional chapters to fill "
                        "the four-part Brooks beat map.>"
                    ),
                    "structural_phase": "setup",
                }
            ]
            artifact["subplots"] = []
            artifact["hooks"] = []
            artifact["revelation_schedule"] = []
            artifact["promise_payoff_ledger"] = []
            artifact["arc_phase_maps"] = {}
            return artifact

        # default empty draft
        return {**common_envelope}

    # ---- low-level helpers --------------------------------------------

    def _write_json(
        self,
        path: Path,
        payload: dict[str, Any],
        *,
        force: bool,
    ) -> bool:
        if path.exists() and not force:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True

    def _write_text(self, path: Path, text: str, *, force: bool) -> bool:
        if path.exists() and not force:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True


def _surface_envelope_name(surface: str) -> str:
    """Map our internal surface keys to the artifact envelope names."""
    return {
        "universe": "universe-builder",
        "canon": "canon-drafter",
        "voice": "voice-discovery",
        "characters": "character-forge",
        "outline": "outline-planner",
        "scene_cards": "scene-card-authoring",
    }.get(surface, surface)


_VALID_CANON_STATUSES = {"canon_compliant", "AU", "original"}


def _validate_surface_draft(surface: str, draft: dict[str, Any]) -> list[str]:
    """Validate an expand-time skeleton against its surface schema.

    Returns the list of validation errors (empty when valid). The
    expand path raises if this returns non-empty so a schema/expand
    drift never silently writes a broken skeleton.
    """
    import importlib

    module_for_surface = {
        "universe": "workflows.universe_builder.validate",
        "canon": "workflows.canon_drafter.validate",
        "voice": "workflows.voice_discovery.validate",
        "characters": "workflows.character_forge.validate",
        "outline": "workflows.outline_planner.validate",
    }
    module_name = module_for_surface.get(surface)
    if module_name is None:
        return []
    module = importlib.import_module(module_name)
    return module.validate(draft)


def _canon_status_or_default(value: str | None) -> str:
    """Map a capture canon_status into the universe schema enum.

    The capture surface stores `canon_status` as a free-form string; the
    universe schema constrains it to {canon_compliant, AU, original}.
    Anything outside that enum (including None or empty) collapses to
    "original" — the safest default for a brand-new project.
    """
    if value in _VALID_CANON_STATUSES:
        return value
    return "original"
