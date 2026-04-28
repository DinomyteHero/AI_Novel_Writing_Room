# New Manuscript Workflow

This is the recommended workflow for starting the next book after the Ruusan production run.

The principle is simple: author the book first, then let the pipeline execute. The early chat should capture taste, intent, unresolved questions, and the emotional promise before any scene cards are generated.

## Overview

```text
idea session
  -> six workflow surfaces
  -> compile bundle
  -> preflight
  -> lean production
  -> full manuscript review
  -> targeted revision
  -> targeted cleanup
  -> final validation
  -> export
```

## 1. Start With Idea Session Capture

Create a front-door planning workspace:

```bash
python scripts/idea_session_capture.py init \
  --title "My Novel" \
  --franchise "My Franchise"
```

For relationship-heavy projects, add the relevant flags:

```bash
python scripts/idea_session_capture.py init \
  --title "Spinoff Title" \
  --franchise "Shared Franchise" \
  --project-scope spinoff \
  --series-id "mainline-series" \
  --book-number 1 \
  --parent-project "Parent Book" \
  --source-franchise "Shared Franchise" \
  --source-work "Original Source"
```

Useful relationship flags:

- `--project-scope standalone|planned_series|continuation|spinoff|shared_universe_entry|alternate_universe|anthology_entry`
- `--canon-status canon_compliant|AU|original`
- `--series-id <id>` and `--book-number <n>`
- `--cosmology-id <id>` for shared-universe planning
- `--source-franchise <name>` and `--source-work <name>` for spinoffs, continuations, or adaptations
- `--parent-project <title>` for direct spinoffs and continuations
- `--branch-point <description>` for alternate universes
- `--base-source <description>` when different universes draw from the same root source

The command creates:

```text
data/franchises/<franchise>/books/<book>/workflows/idea_session/
  capture.json
  session.md
  README.md
  raw_transcript.md                 # optional, when --from-transcript is used
  surface_handoffs/
    universe.md
    canon.md
    voice.md
    characters.md
    outline.md
    scene_cards.md
```

Use `session.md` during the chat. Use `capture.json` and the handoff files once decisions are settled enough to carry forward.

Check readiness:

```bash
python scripts/idea_session_capture.py status \
  --title "My Novel" \
  --franchise "My Franchise"
```

## 2. Deepen The Six Workflow Surfaces

Once the idea session has a strong north star, author the standard workflow-kit surfaces:

| Surface | Owns |
|---|---|
| `universe` | project meta, premise, conflict, theme, tone, target shape |
| `canon` | continuity rules, canon profile, mechanics, terminology |
| `voice` | POV, register, anti-slop rules, character voices |
| `characters` | cast, arcs, wounds, relationships, referenced characters |
| `outline` | structure, subplots, hooks, reveals, promises |
| `scene_cards` | scene-by-scene production contracts |

The handoff files from `workflows/idea_session/surface_handoffs/` should guide these sessions. The six surface artifacts remain the compiler inputs; idea-session notes are not compiled directly.

### Compile-readiness checklist

The per-surface schemas are intentionally permissive so an author can iterate. The **compile-bundle** step has stricter requirements that pull from across surfaces — a surface can validate alone but still leave a gap that fails compile. Fill these explicit fields before running compile to avoid round-tripping back to the surface chats:

- **universe**:
  - `meta.pov_structure` (compliance critical) — e.g. `"Single POV close-third on Joren Vass."`
  - `premise.central_dramatic_question` (concept_seed schema) — required *in addition to* `premise.what_if`
  - `theme.thematic_argument` (≥100 chars) and `theme.how_each_arc_tests_theme` (object keyed by character)
  - `protagonist_arc_type` — one of `change`, `steadfast`, `fall`, `rise`
  - `stress_test_scores` with a non-null `overall` (compliance critical)
- **characters**:
  - Each cast member needs `age` (compliance critical even though the surface schema marks it optional)
  - All three `three_dimensions` fields must hit ≥50 characters
- **outline**:
  - `subplots`, `hooks`, `revelation_schedule`, `promise_payoff_ledger` are each compliance-critical at the concept_seed level — at least one entry each, even if minimal
- **scene_cards**:
  - Every card needs a non-empty `conflict` (schema required) and a `why_now` (physics required)
  - `mission` and `turning_point` must be non-empty

The surface validator catches the per-surface required fields; the compile-bundle errors and `compile_report.json` catch the cross-surface and concept_seed requirements above.

## 3. Compile The Bundle

Compile the authored surfaces into production inputs:

```bash
python scripts/compile_bundle.py \
  --franchise <franchise-slug> \
  --book <book-slug>
```

This writes:

```text
data/franchises/<franchise>/books/<book>/
  concept_seed.json
  compile_report.json
  scene_cards/
    chapter_NN_scene_NN.json
```

Treat `compile_report.json` as the first quality gate. Fix missing surfaces, schema errors, reference errors, or semantic warnings before drafting.

## 4. Preflight Before Spending Tokens

Run deterministic preflight checks before production:

```bash
python scripts/preflight_run.py \
  --franchise <franchise-slug> \
  --book <book-slug>
```

Do not start production if the inputs still contain placeholders, missing cast references, unresolved continuity questions, or scene-card gaps that should have been authored.

## 5. Run Lean Production

The current production default is lean mode:

```text
PlotArchitect -> ProseStylist -> LineWriter -> save
```

Run production with the normal CLI for the book. The `LineWriter` step runs only while `runtime.lean_prose_only.line_edit.enabled` is true and `agent_routing.line_writer` is configured. Keep broad gates, per-scene quality polish, save-blockers, post-save LLM analysis, and full literary copy passes as opt-in diagnostics rather than the default drafting path.

## 6. Export The Manuscript

After the run finishes, stitch the manuscript:

```bash
python scripts/manuscript_export.py \
  --seed data/franchises/<franchise>/books/<book>/concept_seed.json \
  --run-dir output/<franchise>/<book>/runs/<run-id> \
  --export-dir output/<franchise>/<book>/export/<export-name>
```

## 7. Review, Revise, And Clean Up

Use the validated post-Ruusan lifecycle:

1. Run GPT-5.4 full manuscript review.
2. Turn the review into a concrete docket.
3. Apply targeted revisions, including early chapters when you want a clean baseline.
4. Run targeted cleanup as the default final polish branch.
5. Run full literary polish only as a donor/comparison branch.
6. Cherry-pick safe line-level improvements manually.
7. Apply the final docket pass.

Targeted cleanup is the production base unless a manual comparison gives a specific reason to choose otherwise.

## 8. Validate Final Candidate

Before export, validate the final manuscript:

```bash
python scripts/manuscript_final_validation.py \
  --manuscript output/<franchise>/<book>/export/<candidate>/manuscript_final_candidate.md \
  --expected-chapters <n> \
  --expected-scenes <n> \
  --out .tmp/final-validation.json
```

The validator checks chapter count, scene count, hard assistant artifacts, and meta/process language. Motif counts are reported for human review.

## Folder Structure Recommendation

Do not do a broad folder reorg right now. The current split is workable:

```text
workflows/                         # repo-level workflow surface definitions
data/franchises/.../books/...      # book-specific planning inputs
output/...                         # generated runs and exports
docs/                              # operator and architecture docs
scripts/                           # CLI tools
```

The important distinction is:

- Repo-level `workflows/<surface>/` defines tools, schemas, and SKILL instructions.
- Book-level `data/franchises/<franchise>/books/<book>/workflows/` stores authored planning artifacts.

Documentation convention:

- Keep new operator workflows under `docs/user-guide/`.
- Keep architectural rationale under `docs/architecture/`.
- Keep historical routing/cost notes clearly marked as historical or move them into `docs/archive/` after the current cycle.

Avoid moving `data/`, `output/`, or `workflows/` until the next manuscript has gone through the new idea-session path. The first real use will show whether the structure feels natural or whether we need a UI-facing reorganization.
