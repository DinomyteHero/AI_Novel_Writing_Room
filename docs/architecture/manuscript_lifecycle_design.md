# Manuscript lifecycle design (Slice 6)

> Status: design doc — ships alongside a minimal implementation of the patch-workflow CLI (§3). Full manuscript-pass implementations are a post-spec decision.
>
> Prerequisite: Slices 1–5 shipped; scene-level runtime stable. This doc is the bridge between the forward-only scene runtime (Slices 1–5) and a coherent manuscript (editorial passes below).

## 1. Four manuscript-level passes

Current production update (2026-04-26): the operator-facing lifecycle now lives in [Manuscript Production Lifecycle](manuscript-production-lifecycle.md). This document remains the lower-level patch-workflow design reference.

Each pass runs **after** the scene-level pipeline has produced a full manuscript. They are editorial, not drafting — they **never rewrite prose in place** during a run. Outputs route through the patch workflow (§3) so every mutation is human-gated and the forward-only invariant holds.

### 1.1 Developmental pass

- **Scope.** Structural / thematic review: act-level pacing, arc completion, promise/payoff balance, relationship-graph shape.
- **Inputs.** Full manuscript (all saved `chapter_XX_scene_YY.md`), planning artifacts (`concept_seed.json`, `chapter_blueprints/`), the four stateful stores (`story_state.db`, `promise_ledger.db`, `continuity_log.db`, `sociogram.db`).
- **Output.** `output/<franchise>/<book>/export/developmental_report.md` + a **patch set** for scene-card revisions (not prose). Patch shape: JSON matching `schemas/manuscript_patch.json` (see §4).
- **Implementation.** Deferred. Likely agent: LLM with the full manuscript in context (opus/sonnet-class), emitting structured findings. NOT a drafter — it never returns replacement prose.

### 1.2 Line pass

- **Scope.** Sentence-level rhythm / voice on the completed manuscript.
- **Invariant.** Line-pass edits are patches that go through `patch_workflow.py replace` or `apply-manuscript-patch`. The pass must **not** mutate prose in-place during a drafting run; that breaks the forward-only relay.
- **Output.** A patch set keyed by `scene_id → suggested_prose`. Each entry is a full scene rewrite; no partial in-file edits (prevents patch merge pain and keeps the replay semantics simple).
- **Implementation.** Deferred. Likely agent: GPT-5.4 (line-editor family) with each scene's prose + scene card; output paired with the original for human diff review.

### 1.3 Copy pass

- **Scope.** Grammar, punctuation, consistency (numerals, hyphenation, quoted-speech formatting, timeline/character-name spelling against `canonical_terminology` in `concept_seed`).
- **Output.** Patch set (same shape as §1.2). Copy-pass patches are allowed to make very small in-scene character-level diffs; the human-review UI should show per-line changes rather than full-scene rewrites.
- **Implementation.** Deferred. Deterministic linters (spelling / canonical-terminology) land here first; the LLM pass is additive.

### 1.4 Proof pass

- **Scope.** Final typography: em-dashes, ellipses, smart quotes, chapter heading styles, epub/pdf export formatting.
- **Output.** Export artifacts under `output/<franchise>/<book>/export/` (e.g. `manuscript.md`, `manuscript.epub`). The source `chapter_XX_scene_YY.md` files stay unchanged; proof is a *rendering* step, not a mutation.
- **Implementation.** Deferred, but **export scaffolding lands now** (§5). Proof-pass output consumes a concatenated manuscript; the export helper already produces one.

### 1.5 Optional streams (each advisory, each its own pass)

- **Beta-reader synthesis.** Summarize feedback from multiple readers into themed clusters. Output: revision-debt rows at `editorial.other` scope=manuscript.
- **Fandom authenticity review.** Franchise-scoped (`prompts/franchise_profiles/<slug>.md` already carries authenticity rules). Output: revision-debt rows at `canon` or `editorial.canon_polish_drift`.
- **Sensitivity review.** Human-primary; agents triage rather than decide.

All optional passes must emit advisories through the existing revision-debt producers (`src/pipeline/revision_debt_producers.py`) — no new write paths.

## 2. Forward-only invariant

The manuscript-level passes **do not** run inside the scene-drafting pipeline. They are invoked by the human operator between drafting runs:

```
run drafting pipeline → write scenes → human reviews → run manuscript pass →
patches land → patch_workflow.py accept → stale overlays marked → next run refreshes
```

This is the only place where a manuscript-level concern can route back into scene state. Manuscript passes never:

- Regenerate prose in place.
- Write to `promise_ledger.db`, `sociogram.db`, or `continuity_log.db` directly — only the scene-save path and the patch workflow do.
- Touch `chapter_XX_scene_YY.md` without going through `patch_workflow.py replace`.

## 3. Patch workflow CLI

### 3.1 Entry point

`scripts/patch_workflow.py` — resolves patches against a specific book via `--seed <concept_seed.json>` (pipes into `ProjectPaths.from_concept_seed_path`).

### 3.2 Subcommands

All subcommands emit the existing ledger events (`gap_note_resolved`, `revision_debt_updated`, etc.) through the run ledger. None swallows errors silently.

- `accept-isolated <scene_id>`
  - Expected: the scene is currently quarantined at `<project>/quarantine/chNN_scMM/prose.md` with a gap note open.
  - Action: move prose into the run manuscripts directory as a trusted scene, call `StoryState.resolve_gap(gap_id, resolved_by="human_patch_accept", notes=...)` for every gap whose `isolated_scene == scene_id`, emit `gap_note_resolved`, and mark all `affected_scenes` overlays stale (§4).

- `replace <scene_id> --from <path> [--gap <gap_id>]`
  - Expected: `<path>` is a human-edited prose file; the scene may or may not have a gap note.
  - Action: overwrite `chNN_scMM.md` with the new prose, replay declarative state (§3.3), resolve a specific gap if `--gap` is supplied, mark downstream overlays stale.

- `overrule <gap_id> [--notes <text>]`
  - Action: mark gap resolved without changing prose; records `resolved_by="overrule"` + notes. Emits `gap_note_resolved` with an overrule flag in the payload.

- `apply-manuscript-patch <patch_path>`
  - Expected: JSON matching `schemas/manuscript_patch.json` — an array of `{scene_id, action, ...}` rows.
  - Action: dispatches each row through the matching subcommand.

### 3.3 Declarative state replay

When `accept-isolated` / `replace` lands:

1. **Scene card reread.** The authoritative card at `data/franchises/<franchise>/books/<book>/scene_cards/chapter_NN_scene_MM.json` is re-parsed.
2. **Promise ledger.** `record_progression` for every `promises_progressed` ID; `record_payoff` for every `promises_paid` ID. Source is `scene_card`; the ledger's progression_log row is stamped with the current save timestamp so replays are visible in audit.
3. **Sociogram.** `apply_scene_deltas(scene_card=…)` re-applies `relationship_deltas`. The sociogram's history appends a new row with `source="scene_card"`; earlier entries are **not** replaced — the graph is append-only.
4. **Gap note resolution.** `StoryState.resolve_gap(gap_id, resolved_by=..., notes=...)` marks the gap closed; emits `gap_note_resolved` (info).
5. **Stale overlay markers.** For every downstream scene ID in `gap.affected_scenes`, write an empty marker file at `<run_dir>/chapter_packets/chapter_NN_sc_MM_overlay.STALE`. On the next drafting run `ChapterPacketCompiler.compile_overlay` recomputes the overlay instead of reusing the cached base (Slice 2 base is immutable; only overlays rebuild).

### 3.4 What is NOT replayed

- **Continuity extraction.** The extractor needs a router + credits. `patch_workflow.py` can re-extract on demand via `--reextract` but by default it writes a marker at `<run_dir>/continuity_log.STALE` and the next drafting run recomputes. This keeps the CLI offline by default.
- **Already-drafted downstream scenes.** They stay on disk. The next chapter-close memo flags them with an "affected by ch04_sc07 resolution" note (ChapterCloseMemoGenerator reads the fresh gap_notes state via `StoryState.list_gaps_affecting`).

## 4. Patch schema

`schemas/manuscript_patch.json` (lands in Slice 6 alongside the CLI). Shape:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ManuscriptPatch",
  "type": "object",
  "required": ["version", "entries"],
  "properties": {
    "version": { "type": "string" },
    "generated_at": { "type": "string", "format": "date-time" },
    "source_pass": { "enum": ["developmental", "line", "copy", "proof", "manual"] },
    "entries": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["action"],
        "properties": {
          "action": { "enum": ["accept-isolated", "replace", "overrule"] },
          "scene_id": { "type": "string", "pattern": "^ch\\d{2}_sc\\d{2}$" },
          "prose_path": { "type": "string" },
          "gap_id": { "type": "string" },
          "notes": { "type": "string" }
        }
      }
    }
  }
}
```

## 5. Export scaffolding

`scripts/manuscript_export.py` (lands in Slice 6 as a thin stitcher, not a full proof pipeline):

- Walks `<run_dir>/chapters/` and concatenates saved scenes into a single `output/<franchise>/<book>/export/manuscript.md`.
- Preserves scene order by `(chapter_number, scene_number)`.
- Writes a `chapter_index.md` with total word count per chapter.
- Formats: currently markdown only. EPUB / PDF passes can wrap this output; they are deferred.

## 6. Replay semantics summary

```
patch_workflow.py replace ch04_sc07 --from fixtures/ch04_sc07_edited.md
  1. write prose file                            (human edit is now on disk)
  2. resolve gap(s) where isolated_scene=ch04_sc07   (StoryState.resolve_gap)
  3. re-apply promise + sociogram deltas from card    (deterministic replay)
  4. mark stale overlays for affected_scenes         (file marker)
  5. emit gap_note_resolved info event               (audit trail)

next drafting run:
  - ChapterPacketCompiler sees the STALE marker, rebuilds the overlay.
  - ChapterCloseMemoGenerator surfaces "affected by ch04_sc07 resolution".
  - Downstream scenes stay on disk; human decides whether to replace them next.
```

## 7. What this does not solve

- **No whole-book prose regeneration.** Intentional. The forward-only runtime is the protection against cascading rewrites; manuscript passes live outside it.
- **No auto-accepted suggestions.** Every manuscript-level mutation is human-initiated through `patch_workflow.py`.
- **No merge conflict resolution.** If two passes both propose changes to the same scene, the human picks one and applies it; the CLI rejects conflicting `action=replace` entries that touch the same `scene_id` in a single batch.

## 8. Sign-off checklist (spec §10.5)

- [x] Design doc landed at this path.
- [x] Patch workflow CLI specified (§3).
- [x] Replay semantics defined (§3.3, §6).
- [ ] Review validates manuscript-level passes do not violate forward-only runtime — open for user sign-off.
- [ ] Sign-off from user.
