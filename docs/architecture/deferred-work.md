# Deferred work

Items that were explicitly scoped out of the measurement/plumbing/revision-contract plan (tracked in `.claude/plans/delegated-purring-koala.md`) but remain defensible recommendations for follow-up work. Each section below names the change, the empirical/architectural motivation, known constraints, a rough effort estimate, and dependencies on other items here.

Effort scale: **S** = a day or less of focused work; **M** = a few days, multi-file; **L** = multi-week, touches the planning layer or schema.

---

## 1. Typed planner→drafter brief — **M**

Replace the 11-section free-form prose brief emitted by `src/agents/plot_architect.py:45-59` with a structured artifact (JSON or typed dataclass) that the Prose Stylist consumes programmatically rather than parsing out of natural language.

**Why it matters.** The drafter's behavior currently depends on the Plot Architect's exact prose phrasing. The reproducibility-snapshot fix (runs now capture prompt files and CLI flags) makes this visible but doesn't eliminate it — two runs with identical snapshots can still produce different drafts because the *architect's output* is free text and varies by model sampling. A typed brief turns that variance into structured fields that can be diffed across runs.

**Known constraints.** Needs to preserve enough flexibility that the planner can still convey "how to open" and "voice guidance" as free text where free text is genuinely the right form. Suggested shape: typed outer structure (`scene_objective`, `opening_beat`, `key_beats: list`, `closing_beat`, etc.) with free-text strings as leaf values.

**Dependencies.** None hard. Benefits most once the reproducibility snapshot is already live (which it now is).

---

## 2. `chapter_blueprint` artifact — **L**

Add a planning layer between the concept seed and scene cards. The blueprint captures chapter mission, reveal payload, subplot obligations, relationship turns, hook movement, pacing shape, and target chapter length.

**Why it matters.** The pipeline has macro-level planning (concept seed) and scene-local planning (scene cards) but no middle layer. Commercial novels usually need explicit chapter-level orchestration. Scene cards already carry `structural_phase`, so the blueprint is partly a reduction over existing scene-card data plus a handful of chapter-level fields — it's not a from-scratch artifact, but it does need a generator and a consumer.

**Known constraints.** Requires updating the Plot Architect's context assembly to include the blueprint, and probably a new `ChapterPlanner` agent to produce it. The existing `outline_planner` agent may be the right place to extend.

**Dependencies.** Item 4 (relationship arcs) benefits from this artifact being in place first.

---

## 3. Centralize register contract — **S**

The Zahn/Allston/Golden commercial-register directive is duplicated across `prompts/agent_system_prompts/prose_stylist.md:46`, `prompts/agent_system_prompts/plot_architect.md:78,80`, and `prompts/revision_prompts/scene_emotion.md:39` (4 duplicated lines across 3 files). Move to a single shared source (e.g. `prompts/shared/commercial_register.md`) that all three agents reference, so edits propagate atomically.

**Why it matters.** The duplication already diverged once: after Phase 4 rewired the dialogue-expectation proxy, the three files had to be edited separately to replace "2+ characters present" with the new field-aware language. Drift is expected unless the source is shared.

**Known constraints.** Each agent prompt currently loads from a single `.md` file via `Path(prompts/...).read_text()`. Need a small inclusion/assembly mechanism (templating, or explicit compose-at-load-time). Keep it simple: a Markdown `include` convention processed by BaseAgent, or a per-agent compose step.

**Dependencies.** Low. Could land in a small follow-up PR.

---

## 4. Relationship-arc planning — **M**

Scene cards track relationships at runtime but do not plan dyadic change with the rigor of character arcs. Add a `relationship_arc` planning artifact parallel to character arcs, capturing how each important pairing evolves across the book.

**Why it matters.** Commercial fiction depends heavily on relationship turns (the mentor scene, the betrayal, the reconciliation). Without explicit planning, these land accidentally or not at all.

**Known constraints.** Requires extending the concept-seed schema, the outline planner's brief, and the scene-card context to reference relationship-arc phases the same way scenes currently reference character arcs.

**Dependencies.** Benefits from item 2 (chapter blueprint) being in place, so relationship turns can be scheduled at the chapter layer.

---

## 5. `concept_seed` authoring/compilation split — **L**

The current concept seed holds premise, cast, arcs, voice, revelations, terminology, subplots, hooks, scene cards, promise ledger, canon profile, and overrides in one monolithic object. Split authoring into multiple source documents (story core, plot/hook/reveal bible, voice/register bible, canon/world bible) that compile into a single runtime `concept_seed.json`.

**Why it matters.** Improves authoring ergonomics — currently even small edits require navigating a very large JSON file. Runtime behavior would be unchanged because the compiled artifact is what the pipeline loads.

**Known constraints.** Requires a compiler step and a migration tool for existing concept seeds. The compiled runtime artifact should remain stable so the rest of the pipeline doesn't care about the split.

**Dependencies.** None hard. Can land independently.

---

## 6. Event-density comment update — **S**

`src/quality/pacing_analyzer.py:7-12` describes "character-driven literary fiction" while the actual target is commercial SW EU. Numeric ranges are broad enough that the mismatch is rhetorical more than mechanical — the metric still behaves reasonably — but the comment is misleading for new readers of the code.

**Why it matters.** Cosmetic documentation fix, but low cost and aids onboarding.

**Known constraints.** None. Pure comment edit.

**Dependencies.** None.

---

## 7. Kimi K2 style-drift monitoring — **S** (recurring)

`config/settings.yaml` routes `craft_editor`, `scene_emotion_reviewer`, and `dialogue_polish_editor` to Kimi K2, which is a different prose family than the drafter (Claude Sonnet 4.6). Cumulative style drift across bands is a plausible risk.

**Why it matters.** No code fix required, but it is worth establishing a monitoring practice — periodic A/B spot-checks of intermediate band outputs for stylistic tells (word choice, rhythm, punctuation preferences) that reveal cross-model drift.

**Known constraints.** This is recurring operational work, not a one-time fix. Benefits from item 10 (ledger preserves intermediate band prose) landing first — otherwise the A/B data has to be produced by running new work rather than reviewing existing runs.

**Dependencies.** Item 10 enables easier diagnostics.

---

## 8. Preview Gemini model ID drift — **S** (recurring)

`config/settings.yaml:17-18` pins `google/gemini-3.1-pro-preview` and `google/gemini-3-flash-preview`. Preview model IDs can behave differently over time without the ID changing (the provider updates the underlying model under a stable slug).

**Why it matters.** Makes "reproduce this run exactly" impossible across days even with identical prompt files and configs. Monitoring, not a fix.

**Known constraints.** Nothing to do in the code unless OpenRouter adds stable-version pinning. Action item is to prefer stable model IDs over preview IDs when available.

**Dependencies.** None.

---

## 9. Switch off `embeddings.use_mock` and regression-test memory — **M**

`config/settings.yaml:108` has `embeddings.use_mock: true`, which disables real semantic retrieval in the memory layer. Long-form continuity/memory is therefore effectively untested under real retrieval conditions.

**Why it matters.** Before any confidence claim about "commercial novel quality" past chapter 1, the embeddings path needs to be exercised on a full-book regression to characterize actual retrieval behavior, continuity accuracy, and context-assembly token budget under realistic conditions.

**Known constraints.** Requires real embedding model (likely `sentence-transformers` with the already-configured `nomic-embed-text-v1.5`), compute budget for embedding generation across a full manuscript, and a regression harness that can compare with/without retrieval.

**Dependencies.** None hard, but benefits from a completed chapter so there's actually meaningful context to retrieve from.

---

## 10. Ledger preservation of intermediate band prose — **M**

`src/revision/pipeline.py:130-135` currently logs per-band events with `{band_name, duration_ms, input_words, output_words}` — word counts only, no actual prose. Extend the ledger schema to preserve the pre-band and post-band prose text for each band in each scene.

**Why it matters.** Enables post-hoc diagnostics that are currently impossible without re-running: per-band compression contribution (which band actually removed the words?), per-band style drift (do any bands introduce Kimi-flavored phrasings?), per-band register adherence (does Band 3 polish break the commercial register the drafter established?). The Phase 0 diagnostic in the current plan was blocked because run14's ledger didn't preserve this.

**Known constraints.** Ledger schema change (add a nullable `prose_text` column or a sibling table). Disk footprint grows — for a 50k-word book with 3 bands per scene, that's ~450k words of intermediate text, which is small but non-trivial. Consider gating by a `--preserve-band-prose` CLI flag so runs can opt in.

**Dependencies.** None hard. Enables items 7 (Kimi drift monitoring) and downstream diagnostics.
