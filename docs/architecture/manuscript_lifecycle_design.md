# Manuscript lifecycle design (Slice 6)

> Status: design reference for the manuscript-level editorial passes and the patch-workflow CLI. The operator-facing production sequence lives in [Manuscript Production Lifecycle](manuscript-production-lifecycle.md); this document is the lower-level patch-workflow design reference.
>
> Context: the per-scene runtime is a single **lean forward pass** (`PlotArchitect → ProseStylist → [LineWriter] → save`). This document is the bridge between that scene runtime and a coherent manuscript — the editorial passes below run *after* drafting and route every mutation through `scripts/patch_workflow.py`.

## 1. Four manuscript-level passes

Each pass runs **after** the scene-level pipeline has produced a full manuscript. They are editorial, not drafting — they **never rewrite prose in place** during a drafting run. Outputs route through the patch workflow (§3) so every mutation is human-gated and the lean-forward-pass invariant holds.

### 1.1 Developmental pass

- **Scope.** Structural / thematic review: act-level pacing, arc completion, promise/payoff balance.
- **Inputs.** Full manuscript (all saved `chapter_NN_scene_MM.md`), planning artifacts (`concept_seed.json`, `chapter_blueprints/`), and the stateful stores (`story_state.db`, `promise_ledger.db`, `revision_debt.db`).
- **Output.** A developmental report under `output/<franchise>/<book>/export/` plus a **patch set** — JSON matching `schemas/manuscript_patch.json` (see §4). It never returns replacement prose itself.
- **Implementation.** `src/agents/manuscript_reviewer.py` is the live developmental reviewer; it emits findings into revision-debt rows for human triage.

### 1.2 Line pass

- **Scope.** Sentence-level rhythm / voice on the completed manuscript.
- **Invariant.** Line-pass edits are patches that go through `patch_workflow.py replace` or `apply-manuscript-patch`. The pass must **not** mutate prose in place during a drafting run; that breaks the lean-forward-pass invariant.
- **Output.** A patch set keyed by `scene_id → suggested_prose`. Each entry is a full scene rewrite; no partial in-file edits (keeps replay semantics simple).
- **Implementation.** `src/agents/literary_polish.py` + `src/pipeline/final_copy.py` are the post-production line-level passes; output is paired with the original for human diff review.

### 1.3 Copy pass

- **Scope.** Grammar, punctuation, consistency (numerals, hyphenation, quoted-speech formatting, character-name spelling against `canonical_terminology` in `concept_seed`).
- **Output.** Patch set (same shape as §1.2).
- **Implementation.** Deterministic linters land here first; an LLM pass is additive.

### 1.4 Proof pass

- **Scope.** Final typography: em-dashes, ellipses, smart quotes, chapter heading styles, EPUB/PDF export formatting.
- **Output.** Export artifacts under `output/<franchise>/<book>/export/`. The source `chapter_NN_scene_MM.md` files stay unchanged; proof is a *rendering* step, not a mutation.
- **Implementation.** Export scaffolding ships now (§5); EPUB/PDF wrapping is deferred.

### 1.5 Optional streams (each advisory, each its own pass)

- **Beta-reader synthesis.** Summarize multi-reader feedback into themed clusters.
- **Fandom authenticity review.** Franchise-scoped authenticity check.
- **Sensitivity review.** Human-primary; agents triage rather than decide.

All optional passes emit advisories through the existing revision-debt producers (`src/pipeline/revision_debt_producers.py`) — no new write paths.

## 2. The lean-forward-pass invariant

The manuscript-level passes **do not** run inside the scene-drafting pipeline. The lean per-scene pipeline is a single forward pass; manuscript passes are invoked by the human operator between drafting runs:

```
run drafting pipeline → write scenes → human reviews → run manuscript pass →
patch produced → patch_workflow.py applies it → stale overlays marked → next run refreshes
```

This is the only place where a manuscript-level concern can route back into scene state. Manuscript passes never:

- Regenerate prose in place.
- Write to `promise_ledger.db` directly — only the scene-save path and the patch workflow do.
- Touch a saved `chapter_NN_scene_MM.md` without going through `patch_workflow.py replace`.

## 3. Patch workflow CLI

### 3.1 Entry point

`scripts/patch_workflow.py` — resolves patches against a specific book via `--seed <concept_seed.json>` (pipes into `ProjectPaths.from_concept_seed_path`).

### 3.2 Subcommands

All subcommands emit ledger events (`packet_overlay_written`, `revision_debt_updated`, etc.) through the run ledger. None swallows errors silently.

- `replace <scene_id> --from <path>`
  - Expected: `<path>` is a human-edited prose file.
  - Action: overwrite `chapter_NN_scene_MM.md` with the new prose, replay declarative state from the scene card (§3.3), and mark downstream overlays stale.

- `apply-manuscript-patch <patch_path>`
  - Expected: JSON matching `schemas/manuscript_patch.json` — an array of `{action, scene_id, ...}` rows.
  - Action: dispatches each row. Duplicate `replace` entries for the same `scene_id` are rejected **before any mutation**, so a conflicting batch fails atomically.

### 3.3 Declarative state replay

When `replace` lands:

1. **Scene card reread.** The authoritative card at `data/franchises/<franchise>/books/<book>/scene_cards/chapter_NN_scene_MM.json` is re-parsed.
2. **Promise ledger.** `record_progression` for every `promises_progressed` ID; `record_payoff` for every `promises_paid` ID. Source is `scene_card`. The ledger converges to the scene card's declaration — replays are idempotent against the card.
3. **Stale overlay markers.** A marker file `<run_dir>/chapter_packets/chapter_NN_sc_MM_overlay.STALE` is written for affected scenes. On the next drafting run `Orchestrator._maybe_compile_overlay` notices the marker, emits a `packet_overlay_written` info event with `stale_marker_cleared=true`, and deletes it. Overlays already rebuild every scene, so the marker is a human-audit trail, not a cache-invalidation signal.

### 3.4 What is NOT replayed

- **Post-save memory.** Summary, state diff, contradiction scan, and worldbuilding extraction are not re-run by the patch CLI — they recompute on the next drafting run, keeping the CLI offline by default.
- **Already-drafted downstream scenes.** They stay on disk. The human decides whether to `replace` them in a later pass.

## 4. Patch schema

`schemas/manuscript_patch.json` defines the batch shape: a `version`, an optional `generated_at`, an optional `source_pass` (`developmental` / `line` / `copy` / `proof` / `manual`) that tags each mutation with its originating pass, and an `entries` array. Each entry carries an `action`, a `scene_id` matching the pattern `^ch\d{2}_sc\d{2}$`, and optional `prose_path` / `notes`. The action enum is closed; the lean patch workflow dispatches `replace`. (Earlier `accept-isolated` / `overrule` actions belonged to the pre-teardown quarantine + gap-note design and are no longer wired.)

## 5. Export scaffolding

`scripts/manuscript_export.py` is a thin stitcher, not a full proof pipeline:

- Walks `<run_dir>/chapters/` and concatenates saved scenes into a single `output/<franchise>/<book>/export/manuscript.md`.
- Preserves scene order by `(chapter_number, scene_number)`.
- Writes a `chapter_index.md` with total word count per chapter.
- Markdown only. EPUB / PDF passes can wrap this output; they are deferred.

## 6. Replay semantics summary

```
patch_workflow.py replace ch04_sc07 --from fixtures/ch04_sc07_edited.md
  1. write prose file                              (human edit is now on disk)
  2. re-apply promise deltas from the scene card   (deterministic replay)
  3. mark stale overlays for downstream scenes     (file marker)
  4. emit ledger events                            (audit trail)

next drafting run:
  - ChapterPacketCompiler sees the STALE marker, rebuilds the overlay.
  - Downstream scenes stay on disk; the human decides whether to replace them next.
```

## 7. What this does not solve

- **No whole-book prose regeneration.** Intentional. Manuscript passes live outside the scene runtime.
- **No auto-accepted suggestions.** Every manuscript-level mutation is human-initiated through `patch_workflow.py`.
- **No merge conflict resolution.** If two passes both propose changes to the same scene, the human picks one; the CLI rejects conflicting `replace` entries that touch the same `scene_id` in a single batch.
