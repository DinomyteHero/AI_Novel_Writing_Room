# Manuscript Production Lifecycle

Current default as of 2026-04-29: finish books in lean mode, then do manuscript-level review and narrow revision. The scene pipeline still creates the raw material, but the production decision now happens at the full-manuscript level.

## At A Glance

Default production path:

```text
preflight
  -> PlotArchitect
  -> ProseStylist
  -> LineWriter
  -> save scenes
  -> manuscript export
  -> manuscript_reviewer docket
  -> targeted patch/revision
  -> final validation/export
```

Standby tooling remains wired for diagnostics, bench runs, and recovery work:

- Full relay gates: `gate_critic`, `quality_polish`, `final_gate`, `canon_expert`, `presence_checker`, save blockers.
- Default-off repair and memory slices: `corrective_rerun`, `micro_repair`, `revision_debt`, `promise_ledger`, `continuity_log`, `sociogram`.
- Post-save/advisory agents: `summarizer`, `character_specialist`, `chapter_gate_critic`, `judge_evaluator`.

Do not treat standby tooling as dead code. It is intentionally outside the default path, but still useful when changing model routing, recovering a problem run, or evaluating whether a slice is ready to enable for a specific book.

## Default Flow

1. **Preflight** - validate scene cards and compile/runtime inputs before spending API credits.
2. **Lean scene production** - run `PlotArchitect -> ProseStylist -> LineWriter -> save`.
3. **Manuscript export** - stitch the run into a single `manuscript.md` plus a chapter index.
4. **Full manuscript review** - run `manuscript_reviewer` on GPT-5.4. Treat the review as an editorial docket, not as an automatic rewrite.
5. **Targeted revision** - fix docket items with bounded chapter/scene patches. Re-run early chapters too when the run needs a clean baseline; do not assume Chapters 1-5 are already settled.
6. **Targeted cleanup polish** - make a restrained pass for line discipline, repeated motifs, self-aware language, and readability. This is the default final polish path.
7. **Optional full literary polish** - run only as a comparison or donor branch. It can provide isolated sensory improvements, but should not become the master manuscript wholesale.
8. **Final docket pass** - apply concrete items from the comparison/review: remove meta phrasing, reduce motif clusters, compress repeated interpretation, preserve scene structure, and add any missing consequence beats.
9. **Micro-cleanup and validation** - make tiny hand edits or exact-span repairs, then run deterministic validation before export.
10. **Final export** - produce the shareable manuscript from the validated master candidate.

## Current Model Policy

The live config keeps production lean:

| Stage | Current role | Policy |
|---|---|---|
| Scene brief | `plot_architect` on DeepSeek V4 Flash | Cheap structured JSON pass. |
| Draft prose | `prose_stylist` on DeepSeek V4 Pro | Primary lean-mode drafter. |
| Scene line edit | `line_writer` on GPT-5.4 Mini | One bounded post-draft edit before save. |
| Manuscript review | `manuscript_reviewer` on GPT-5.4 | Produces the full-work editorial docket. |
| Targeted cleanup | GPT-5.4 export/pass tooling | Default final polish branch. |
| Full literary polish | GPT-5.4 export/pass tooling | Optional donor/comparison branch only. |

Broad scene gates, per-scene quality polish, final gates, presence checks, and chapter gates remain useful for diagnostics and experiments, but they are skipped by default when `runtime.lean_prose_only.enabled` is true. `runtime.chapter_packet.enabled` stays on because the packet is the drafter's inspectable scene contract.

## Config Shape

The production reader should start with `config/settings.yaml`. It contains only model aliases currently routed by the shipping config. Frozen comparison configs and experimental aliases live under `config/bench/`, including `config/bench/experimental-model-aliases.yaml`.

Runtime flags remain explicit advanced controls rather than one opaque mode switch. The effective default mode is lean production:

- `runtime.lean_prose_only.enabled: true`
- `runtime.lean_prose_only.line_edit.enabled: true`
- `runtime.chapter_packet.enabled: true`

Everything else that can change saved prose or stateful memory stays default-off until a book-specific parity test approves it.

## Lessons From The Ruusan Run

The targeted cleanup branch was the best value-for-money final base. It preserved the commercial Legends register, kept the prose invisible, and avoided the visible "literary pass" fingerprints.

The full literary polish cost about the same as targeted cleanup in the comparison run, but it introduced more tonal drift. It is still useful as a donor branch for individual line-level sensory upgrades after manual review.

The full manuscript review should happen before deciding whether to run a targeted cleanup or full literary polish. That gives the system a real end-to-end quality test and gives us a concrete docket instead of guessing scene by scene.

## Stop Rules

Stop broad polishing when all of these are true:

- Chapter count and scene count are preserved.
- Hard artifact scan is clean.
- Meta/process language scan is clean.
- Remaining reviewer findings are concrete tiny edits, not structural uncertainty.
- Motif density has been reviewed, especially repeated `wound`, `seal`, `chord`, `note`, `silence`, `wrongness`, `hum`, `resonance`, `weight`, and `stillness` language.

Do not keep paying for repeated full verifier calls once the remaining work is a short list of literal hand fixes. Apply the fixes and use deterministic validation.

## Validation Command

Use the final validation script on the candidate manuscript before treating it as export-ready:

```bash
python scripts/manuscript_final_validation.py \
  --manuscript output/<franchise>/<book>/export/<candidate>/manuscript_final_candidate.md \
  --expected-chapters 28 \
  --expected-scenes 87 \
  --out .tmp/final-validation.json
```

The validator fails on count mismatches, hard assistant artifacts, and manuscript-process/meta language. Motif counts are reported for review but are not blocking by themselves.

## Version Handling

Keep each major branch in its own export folder:

- `production-lean-full-*` for the original lean export.
- `*-targeted-revision-*` for structural or docket-driven revision baselines.
- `*-polish-comparison/targeted-cleanup` for the default cleanup branch.
- `*-polish-comparison/full-literary-polish` for the donor/comparison branch.
- `*-final-candidate-*` for the validated master candidate.

After signoff, move superseded outputs to archive and keep the validated master candidate plus the comparison report reachable.
