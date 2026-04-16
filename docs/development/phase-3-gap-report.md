# Phase 3 Gap Report

**Date:** 2026-04-16
**Scope:** Drift and loose ends found after Phase 3 (Generic Bootstrap) closure and the comprehensive scene card refresh.
**Source evidence:** Direct reads of the files listed inline. All claims are code-verified, not inferred.

Phase 3 shipped correctly. The generic installer, templates, and 87-card scene refresh all work as designed. This report catalogs the *residue* — docs, config, UI, and data that didn't get updated alongside the runtime changes.

---

## Priority legend

- **P0** — Actively misleading or wrong. Will cause a user or maintainer to do the wrong thing.
- **P1** — Stale but not dangerous. Creates confusion but won't break anything.
- **P2** — Nice-to-have polish. Skip until P0/P1 are clear.

---

## P0 — Actively misleading

### P0-1. README.md describes the dead 3-band revision pipeline as the live system

**Evidence:** [README.md:73-74](../../README.md) says:
> 5. **CraftEditor** applies non-blocking polish improvements
> 6. **RevisionPipeline** runs up to 5 revision passes (structural continuity, scene emotion, line copy, dialogue polish, worldbuilding coherence)

Neither step exists in the live orchestrator ([orchestrator.py:3-5](../../src/orchestrator.py)). CraftEditor was replaced by QualityPolish + compression guard + FinalGate. The 5-pass revision pipeline is dead — [gate_critic.py:70-71](../../src/agents/gate_critic.py) confirms: *"fail_polish no longer routes to craft_edit."*

Also [README.md:83-84](../../README.md) phase matrix still advertises "3-band revision" and "adaptive revision" as Phase 3/4 features.

**Fix:** Rewrite the "how it works" section to match the actual pipeline:
`PlotArchitect → ProseStylist → GateCritic (retry) → QualityMetrics → QualityPolish → compression guard → FinalGate → save`.

**Effort:** ~30 min. One file.

---

### P0-2. `failure_codes.yaml` routing table contradicts live gate_critic behavior

**Evidence:**
- [config/failure_codes.yaml:27-30](../../config/failure_codes.yaml) still has:
  ```yaml
  routing:
    fail_structural: full_rewrite
    fail_voice: targeted_revision
    fail_polish: craft_edit
  ```
- [gate_critic.py:70-71](../../src/agents/gate_critic.py) comment: *"Post-Phase 1 pipeline redesign: fail_polish no longer routes to craft_edit."*
- Also: `CANON_VIOLATION` is categorized under `polish:` in the YAML ([failure_codes.yaml:25](../../config/failure_codes.yaml)) but treated as Structural in the live prompt ([gate_critic.py:146](../../src/agents/gate_critic.py)).

**Why P0:** Anyone reading the config to understand the pipeline will build the wrong mental model. If the config is ever re-read by code (e.g. a future router lookup), it will route wrong.

**Fix:**
- Remove `fail_polish: craft_edit` or replace with documented current behavior (fall back to gate-passed draft via compression guard / FinalGate revert).
- Move `CANON_VIOLATION` from `polish:` to `structural:` to match live prompt.

**Effort:** ~10 min.

---

### P0-3. Skip Revision checkbox is live in the UI but points to nothing

**Evidence:**
- [Pipeline.tsx:119-122](../../src/ui/frontend/src/pages/Pipeline.tsx) has an active checkbox labeled "Skip Revision" bound to `noRevision`, submitted as `no_revision` on [Pipeline.tsx:43](../../src/ui/frontend/src/pages/Pipeline.tsx).
- [pipeline.py:20](../../src/ui/routes/pipeline.py) accepts the field with comment: *"Deprecated; no-op since Phase 1 redesign."*
- [main.py:493-495](../../src/main.py) prints: *"Warning: --no-revision is deprecated. The 3-band revision pipeline has been..."*

So: CLI warns, backend accepts-and-ignores, frontend still exposes it as a toggle. A user clicking it gets no warning and no effect.

**Why P0:** Users will believe they are controlling behavior that is no longer controllable. This is worse than no control.

**Fix options (in order of increasing effort):**
1. **Minimum:** Remove the checkbox from [Pipeline.tsx:119-122](../../src/ui/frontend/src/pages/Pipeline.tsx). Leave backend field accepting for API stability.
2. **Better:** Remove checkbox + delete [Pipeline.tsx:23, 43](../../src/ui/frontend/src/pages/Pipeline.tsx) state + `no_revision` field in [client.ts:44](../../src/ui/frontend/src/api/client.ts). Deprecate the backend field with a 410/warning.
3. **Best:** Also surface the new actual controls — the compression guard and FinalGate thresholds — if they should be user-tunable.

**Effort:** Option 1 is ~5 min. Option 2 is ~20 min.

---

### P0-4. `docs/architecture/quality-and-revision.md` is a reference to a system that doesn't exist

**Evidence:** [quality-and-revision.md:1-78](../../docs/architecture/quality-and-revision.md) describes the live system as:
- "multi-band revision pipeline (LLM-powered)"
- Table of 3 bands: StructuralContinuity, SceneEmotion, LineCopy
- "Each band receives the current prose and returns revised prose"

None of this runs. The live runtime path is QualityPolish (bounded single pass) + compression guard + FinalGate revert-to-gate-passed-draft.

**Why P0:** This is the document a new contributor would read to understand the quality subsystem. It will mislead them into modifying or extending a dead code path.

**Fix:** Rewrite to describe the actual live system. Keep the detector subsections (repetition/pacing/voice/slop) — those are still live. Replace the "Revision Pipeline" sections with the QualityPolish + compression guard + FinalGate flow.

**Effort:** ~1 hour. Significant rewrite of the bottom half of the file.

---

## P1 — Stale but not dangerous

### P1-1. `workshop_runner.py` defaults to the old flat layout

**Evidence:** [workshop_runner.py:55](../../src/concept_workshop/workshop_runner.py) calls:
```python
self.project_dir = ProjectPaths(slugify_title(project_name)).project_root
```
No franchise argument. Per [project_paths.py:31](../../src/project_paths.py), `ProjectPaths(<slug>)` without a franchise resolves to `data/projects/<slug>/` — the **old flat layout**, not the Phase 2/3 canonical `data/franchises/<franchise>/books/<slug>/`.

**Why P1, not P0:** It still works. `ProjectPaths` supports both layouts. But new projects created via the workshop will land under `data/projects/`, not the franchise-scoped tree that Phase 2/3 spent effort canonicalizing. Over time this creates two parallel project trees.

**Fix:** Add `--franchise` CLI arg to [workshop_runner.py](../../src/concept_workshop/workshop_runner.py); pass it through to `ProjectPaths(franchise=..., book=...)`. Consider deprecating the no-franchise default.

**Effort:** ~30 min including a test.

---

### P1-2. `docs/architecture/system-overview.md` references dead modules

**Evidence:**
- [system-overview.md:40](../../docs/architecture/system-overview.md): `+-- fail_voice -> ProseStylist (targeted revision; rewrite loop)` — roughly accurate.
- [system-overview.md:86](../../docs/architecture/system-overview.md): `├── revision/                  # Multi-band revision pipeline` — **the `src/revision/` directory still exists** but the multi-band pipeline inside it is no longer invoked by the orchestrator.
- [system-overview.md:95](../../docs/architecture/system-overview.md): `└── revision_prompts/          # Per-band revision prompts (5 files)` — prompts exist but aren't loaded by any live agent.

**Why P1:** Not actively wrong about what's on disk — but wrong about what's *live*. Should at minimum annotate "(legacy; not invoked by current orchestrator)".

**Fix:** Either delete the `src/revision/` directory and `prompts/revision_prompts/` (if truly dead), or annotate the tree diagram in [system-overview.md](../../docs/architecture/system-overview.md) to mark them as legacy.

**Effort:** ~20 min for the doc annotation. Deleting the dead code is a separate decision.

---

### P1-3. Scene card `dialogue_expectation` field is missing on 86 of 87 cards

**Evidence:** Grep of `data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/*.json` for the key `dialogue_expectation` returns **one hit**: [chapter_01_scene_01.json:25](../../data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_01_scene_01.json).

**Important distinction from ChatGPT's report:** The field is **missing entirely**, not present-and-blank. This changes where the fix goes.

**Why P1:** Runtime has fallbacks, so it doesn't break. But `dialogue_expectation` is a field the downstream agents use to bias dialogue/narration ratio — without it, every scene gets the generic default. Given this is a single-POV character-driven novel, missing this field on 86 scenes is a meaningful authoring gap.

**Fix options:**
1. **Installer-level (preferred):** Update [scene_card_translator.py](../../src/concept_workshop/scene_card_translator.py) to always emit `dialogue_expectation` with a default inferred from `scene_type` (e.g. `action` → `action-heavy`, `sequel` → `interior`, `dialogue` → `balanced`). Re-run installer; get 87/87 coverage on next reinstall.
2. **Data-level:** Hand-author the field on 86 cards. Slow, authoritative.

Installer-level is aligned with Phase 3's "generic, reproducible" ethos.

**Effort:** Option 1 is ~45 min including test.

---

### P1-4. Phase numbering collision (orchestrator Phase 1-4 vs roadmap Phase 0-8)

**Evidence:**
- [implementation-roadmap.md](../../docs/development/implementation-roadmap.md) defines Phase 0-8 (preflight, baseline, cleanup, schema, bootstrap, workflow kit, series, lore, frontend).
- [orchestrator.py:14-24](../../src/orchestrator.py) defines Phase 1-4 (always-on, memory+summarizer, character+milestones, physics+session+judge).
- [main.py](../../src/main.py) `--phase 1..4` flag means orchestrator Phase, not roadmap Phase.
- [Pipeline.tsx:114-116](../../src/ui/frontend/src/pages/Pipeline.tsx) Phase dropdown means orchestrator Phase, not roadmap Phase.

**Why P1:** Not currently breaking anything, but a user who read the roadmap and then saw "Phase 3" in the UI will assume Character Forge / scene card authoring, not "enable character specialist + milestone gates."

**Fix:** Rename the orchestrator phases. Candidate names: `Level 1-4`, `Tier 1-4`, or functional names like `Draft / Memory / Character / Physics`. The latter is clearer but more invasive (changes CLI flag, UI label, orchestrator docstring, tests).

**Effort:** If renaming to functional names: ~2 hours with test updates. If just clarifying the docstring and UI label to say "Pipeline Depth 1-4": ~20 min.

---

### P1-5. `failure_codes.yaml` missing Phase 5 additions that the live prompt emits

**Evidence:** [gate_critic.py:144-146](../../src/agents/gate_critic.py) lists codes the critic is allowed to emit:
```
CHARACTER_ARC_STALL, HOOK_VIOLATION, SUBPLOT_DRIFT, CANON_VIOLATION,
CLOSING_HOOK_VIOLATION, CHARACTER_PRESENCE_VIOLATION, OPENING_HOOK_MISMATCH
```

[failure_codes.yaml](../../config/failure_codes.yaml) includes the first four (Phase 5 additions) but is **missing**:
- `CLOSING_HOOK_VIOLATION`
- `CHARACTER_PRESENCE_VIOLATION`
- `OPENING_HOOK_MISMATCH`

**Why P1:** The critic can emit codes that aren't in the taxonomy file. Any downstream consumer using the YAML as the source of truth for what's possible will miss these.

**Fix:** Add the three missing codes under `structural:` (they're all FinalGate/structural violations).

**Effort:** ~10 min.

---

## P2 — Polish

### P2-1. `src/revision/` may be a dead directory

If P1-2's "revision is legacy" framing is correct, the directory and its prompts should either be deleted or explicitly marked `legacy/` / gated behind a feature flag. Leaving dead-but-present code invites future maintenance waste.

**Action:** Audit call sites with `grep -r "from src.revision"` / `"src\.revision"`. If zero live callers, delete. If there are legacy flags that resurrect it, document them.

**Effort:** ~30 min audit; delete or annotate based on findings.

---

### P2-2. Auto-memory says "Phases 1-5 complete," user said "Phase 3 just complete"

Memory files [project_phase1_complete.md](../../~/.claude/memory/) through `project_phase5_complete.md` describe a different phase numbering system from the current [implementation-roadmap.md](../../docs/development/implementation-roadmap.md). Those memories appear to describe an *earlier* roadmap (Phase 1 = MVP / Phase 5 = UI) that got superseded.

**Action:** Update memory to reflect the current roadmap's Phase 0-8 numbering. Mark Phase 3 (Generic Bootstrap) complete; Phases 6-8 planned.

**Effort:** ~15 min. Memory-only — no repo change.

---

### P2-3. README.md directory tree comment claims Phase 3 advertises "3-band revision"

[README.md:83](../../README.md) phase matrix row for Phase 3 reads:
> `| 3 | Quality metrics, character specialist, 3-band revision, milestone gates |`

This conflates the old internal Phase 3 (memory-era) with the roadmap Phase 3 (Generic Bootstrap). Overlaps with P0-1 but worth calling out separately because the matrix is what someone skimming the README will land on.

**Fix:** Replace the whole matrix with the roadmap's Phase 0-8 table, or drop the matrix and link to the roadmap.

**Effort:** ~15 min. Folds into P0-1's rewrite.

---

## Not-really-gaps (intentional, skip)

- **`install/concept_seed_raw.json` + `install/workshop_patch.json` committed.** These are the raw inputs for the Ruusan reinstall regression test. Keep them.
- **87 scene cards have dense per-scene `notes` fields.** Looked like boilerplate at first glance; actually per-scene craft guidance. Keep.
- **`chapter_01_reference.md` premise differs from scene card premise.** The reference corpus is a *calibration baseline* for style, not a canonical narrative. Different premise is fine — it's prose-tone reference only.

---

## Suggested cleanup sequence

If picking one sitting (~2 hours):

1. P0-2 (failure_codes.yaml) — 10 min
2. P0-3 (Skip Revision UI) — 5-20 min
3. P1-5 (missing failure codes) — 10 min
4. P0-1 + P2-3 (README rewrite) — 30-45 min
5. P0-4 (quality-and-revision.md rewrite) — 60 min

That closes the active-misleading items (P0) plus the two small P1 completeness issues. The bigger items (P1-1 workshop_runner path, P1-3 dialogue_expectation installer fix, P1-4 phase renaming) deserve their own sessions.

---

## Verification artifacts

All claims in this report check against:
- [src/orchestrator.py:1-100](../../src/orchestrator.py)
- [src/agents/gate_critic.py:21, 68-71, 144-147](../../src/agents/gate_critic.py)
- [src/main.py:65, 365, 493-495](../../src/main.py)
- [src/ui/routes/pipeline.py:20](../../src/ui/routes/pipeline.py)
- [src/ui/frontend/src/pages/Pipeline.tsx:23, 43, 114-122](../../src/ui/frontend/src/pages/Pipeline.tsx)
- [src/ui/frontend/src/api/client.ts:44](../../src/ui/frontend/src/api/client.ts)
- [src/concept_workshop/workshop_runner.py:55](../../src/concept_workshop/workshop_runner.py)
- [src/project_paths.py:31](../../src/project_paths.py)
- [config/failure_codes.yaml](../../config/failure_codes.yaml) (full file)
- [docs/architecture/quality-and-revision.md:1-80](../../docs/architecture/quality-and-revision.md)
- [docs/architecture/system-overview.md:40, 86, 95](../../docs/architecture/system-overview.md)
- [README.md:3, 73-74, 83-84, 129](../../README.md)
- Grep of `data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/*.json` for `dialogue_expectation`
