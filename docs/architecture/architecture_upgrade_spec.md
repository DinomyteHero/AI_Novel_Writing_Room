# AI Writers' Room — Architecture Upgrade Implementation Spec

**Status:** Historical implementation spec. Slices 1–6 have since landed or evolved in code; use `CLAUDE.md`, `config/settings.yaml`, and the current user-guide/reference docs for operational behavior.
**Last revised:** 2026-04-20
**Authoring context:** This document supersedes the earlier "revised phased roadmap." It consolidates the eight patch-level refinements (successor classifier, debt write-matrix, packet consistency model, promise progression semantics, gap-note lifecycle, Phase 0 JSON audit, polish bench extension, slice renumbering) into a single implementation playbook.

---

## 0. How to use this document

This spec is written to be executed slice-by-slice by Claude Code sessions. It is deliberately prescriptive: concrete file paths, class names, schema JSON, feature-flag keys, migration scripts, acceptance tests.

**Before starting any slice**, re-read:
- `CLAUDE.md` (project-root) — load-bearing architectural invariants.
- `§3 Architecture invariants` below — what must not change.
- `§4 Feature-flag strategy` below — the mechanism that protects current Ruusan and Betrayal output while new systems come online.
- The go/no-go checklist for the slice in question (`§5.7`, `§6.8`, `§7.5`, `§8.6`, `§9.6`).

**Every slice follows the same pattern:**
1. Add schemas (if any) under `schemas/`.
2. Add feature flags in `config/settings.yaml` (default off).
3. Implement new code under `src/` behind flags.
4. Write unit tests.
5. Write a parity test against Ruusan ch01 + Betrayal ch01.
6. Write migration if durable state changes.
7. Run the slice's acceptance gate.
8. Only when the gate passes, consider flipping flags on.

**Do not merge a slice without:**
- All unit tests passing (`pytest -q`).
- Ruusan/Betrayal parity test showing no prose delta when flags are off.
- Updated CLAUDE.md section if behavior-facing.
- Go/no-go checklist filled in.

---

## Table of contents

1. Executive framing
2. Repo-grounded baseline
3. Architecture invariants (never break)
4. Feature-flag strategy (how we ship safely)
5. **Slice 1** — Diagnostic gate + state firewall
6. **Slice 2** — Chapter packet + revision debt
7. **Slice 3** — Promise ledger
8. **Slice 4** — Continuity event log
9. **Slice 5** — Sociogram
10. **Slice 6** — Manuscript lifecycle design
11. Cross-cutting workstreams
    - 11.1 CanonExpert relocation + local_fixes (feature-flagged)
    - 11.2 Polish benchmark harness extension
    - 11.3 Fanfic mode policy matrix
    - 11.4 Ledger event-type additions
    - 11.5 Migration playbook
    - 11.6 Test strategy
12. Appendices
    - A. New schema files
    - B. New configuration keys
    - C. File/directory layout deltas
    - D. Ledger event inventory
    - E. Rollback procedures

---

## 1. Executive framing

The architectural direction set by the revised design is correct:

- Forward-only scene drafting (retries remain pinned to 0).
- One primary prose pen per scene in the default relay.
- Deterministic metrics service stays independent of reviewer agents.
- A typed chapter packet replaces the current flat markdown context blob.
- Chapter, act, and manuscript review sit above scene-level drafting.
- Advisories land in a durable editorial debt store; blockers are isolated, not fatal to the run.
- Stateful-memory artifacts (promise ledger, continuity log, sociogram) are each risky enough to warrant their own shippable slice with its own evaluation harness.

What changes from the prior plan is sequencing and safety:
- Phase 0 is a real, gateable diagnostic audit — it may pause subsequent work.
- The state firewall ships before inferred memory.
- Each new state artifact is an independently-shippable product, not a bundle.
- Every behavior change is feature-flagged. Ruusan and Betrayal stay on the old path until a per-book flip is approved.

---

## 2. Repo-grounded baseline

Confirmed state of the repository at the time of writing (verify again before each slice):

| Claim | Current state | Reference |
|---|---|---|
| Retries are pinned to zero | True | [config/settings.yaml:133-134](../../config/settings.yaml) |
| Save blockers currently abort the whole run | True | [src/pipeline/save_blockers.py](../../src/pipeline/save_blockers.py), [src/orchestrator.py:308](../../src/orchestrator.py) |
| Status vocabulary is three-valued | True | [src/memory/story_state.py:280-285](../../src/memory/story_state.py) |
| `metrics_dashboard.py` already independent | True | [src/quality/metrics_dashboard.py:15](../../src/quality/metrics_dashboard.py) |
| `prompts_snapshot/` already captures prompts | True | [src/main.py:57-81](../../src/main.py) |
| CanonExpert runs post-polish | True | Orchestrator stage order |
| `chapter_packet`, `promise_ledger`, `continuity_log`, `sociogram`, `revision_debt` | Do not exist as artifacts | grep confirmed |
| Scene card has `promises_planted` / `promises_paid` | True | [schemas/scene_card.json:50-51](../../schemas/scene_card.json) |
| Scene card has `depends_on` | **False** — to be added in Slice 1 | [schemas/scene_card.json](../../schemas/scene_card.json) |
| Scene card has `promises_progressed` | **False** — to be added in Slice 3 | [schemas/scene_card.json](../../schemas/scene_card.json) |
| `bench_prose_models.py` is scene-level only | True | [scripts/bench_prose_models.py](../../scripts/bench_prose_models.py) |
| Phase 0 machine-readable audit output | Does not exist | — |
| `docs/audits/` directory | Does not exist | — |

---

## 3. Architecture invariants (never break)

These are load-bearing. Every slice must preserve them.

### 3.1 Forward-only scene runtime
No intra-scene retry loops. `max_structural_retries` and `max_voice_retries` stay at `0`. Stages run once, in order, and prose always advances. The only hard-failure path is the save-blocker layer.

### 3.2 Trusted state is protected
A scene written to disk after blocker isolation (Slice 1) does **not** silently become trusted continuity, promise payoff evidence, sociogram source, or retrieval state. Every new state artifact must expose a clean boundary: "inputs come from trusted scenes only."

### 3.3 Advisories are structured, not vibes
Every advisory produced by the pipeline (from CanonExpert, GateCritic, FinalGate, MetricsDashboard, PresenceChecker near-misses, compression guard, word-count telemetry, SceneReviewer once it lands) writes a row to the revision debt store (Slice 2). Silent debt is a bug.

### 3.4 Measurement stays deterministic
`src/quality/metrics_dashboard.py` remains an independent service. Reviewer agents consume its outputs; they do not replace them. No "SceneReviewer subsumes QualityMetrics" refactor.

### 3.5 Bounded prose writers
`ProseStylist` remains the drafter. The current lean production path also runs one bounded `LineWriter` pass when `runtime.lean_prose_only.line_edit.enabled` is true. No other agent is granted write authority over scene prose without a specific feature flag.

### 3.6 No hidden ambient context
Once Slice 2 ships, agents consume an inspectable chapter packet + explicit typed retrieval. `LineWriter` already follows this rule; new agents must follow it too. `ContextAssembler.assemble()`'s flat-markdown path remains available during Slices 1–2 as a fallback.

### 3.7 Production planning is binding
Autonomous drafting in production mode requires: validated scene cards, a chapter blueprint for the chapter being drafted, a clean strict-compile report from `scripts/compile_bundle.py --strict`, and all planning workflows present.

---

## 4. Feature-flag strategy (how we ship safely)

The single most important decision in this spec: **every behavior change lands behind a feature flag, default off, with a per-book override mechanism.**

This is the only way to land new architecture while keeping Ruusan and Betrayal on the path that is currently producing prose we want to keep.

### 4.1 Flag hierarchy

Flags are evaluated in this order, first match wins:

1. **CLI override** via `--runtime-flag key=value` (comma-separated list).
2. **Per-book override** at `data/franchises/<franchise>/books/<book>/runtime_overrides.yaml` (if present).
3. **Per-franchise override** at `data/franchises/<franchise>/runtime_overrides.yaml` (if present).
4. **Global default** in `config/settings.yaml` under the `runtime:` top-level key.

The resolver lives in a new module `src/runtime_flags.py`. Signature:

```python
def resolve_flag(key: str, *, concept_seed: dict | None = None,
                 cli_overrides: dict | None = None,
                 settings: dict | None = None) -> Any: ...
```

### 4.2 Flag inventory

All flags default to **False** or their safest value when first introduced. Adding a flag without default=safe is a review-blocker. Once a flag's parity test passes on Ruusan and Betrayal it can be promoted to a shipping default; the table below reflects the current shipping defaults, not the slice-introduction defaults.

| Flag key | Slice | Default | Purpose |
|---|---|---|---|
| `runtime.firewall.enabled` | 1 | `false` | Switch from run-abort to isolate-and-continue on save-blockers. |
| `runtime.firewall.successor_classifier.enabled` | 1 | `false` | Enable dependency classifier. When off, every successor scene soft-halts conservatively. |
| `runtime.firewall.successor_classifier.jaccard_threshold` | 1 | `0.5` | Character-overlap threshold for soft-halt classification. |
| `runtime.phase0_audit.enabled` | 1 | `false` | Emit `phase0_audit.json` alongside the run. |
| `runtime.chapter_packet.enabled` | 2 | `true` (D4a) | Use `ChapterPacketCompiler` instead of `ContextAssembler.assemble()`. Promoted to shipping default after Ruusan and Betrayal parity tests passed. |
| `runtime.chapter_packet.fallback_on_error` | 2 | `true` | If packet compilation raises, fall back to flat assembly for that scene. |
| `runtime.revision_debt.enabled` | 2 | `false` | Write structured debt rows to SQLite. When off, advisories remain ledger-only. |
| `runtime.canon_expert.early_position` | 11.1 | `false` | Run CanonExpert before QualityPolish instead of after. |
| `runtime.canon_expert.apply_local_fixes` | 11.1 | `false` | Allow QualityPolish to apply CanonExpert's whitelisted local_fixes. |
| `runtime.canon_expert.local_fixes_whitelist` | 11.1 | `[]` | Closed set of substitution categories allowed; empty means none. |
| `runtime.promise_ledger.enabled` | 3 | `false` | Populate and consult the promise ledger. |
| `runtime.continuity_log.enabled` | 4 | `false` | Run continuity extractor and include in overlay. |
| `runtime.continuity_log.min_confidence` | 4 | `0.85` | Trust threshold for inclusion in packet overlay. |
| `runtime.sociogram.enabled` | 5 | `false` | Populate and consult the sociogram. |

### 4.3 Per-book override file format

`data/franchises/<franchise>/books/<book>/runtime_overrides.yaml` (optional):

```yaml
# Runtime flag overrides for this book.
# Inherit global defaults except where listed.
runtime:
  chapter_packet:
    enabled: true   # This book has had a parity test and packet mode is approved.
  canon_expert:
    early_position: false    # Keep late-position CanonExpert for Ruusan (current behavior).
    apply_local_fixes: false # Do not apply local_fixes for this book.
```

### 4.4 Ruusan + Betrayal protection policy

Until each slice has passed a per-book parity test (defined in `§11.6.3`):

- No `runtime_overrides.yaml` is created for Ruusan or Betrayal.
- All global defaults stay at their safe values.
- Any new feature that touches drafter input, polish behavior, or save routing is gated behind a flag that is off for these two books.

The first book onto each new flag is **not** Ruusan or Betrayal — it is a lower-stakes test book (or a dedicated `test-bench/` project under `data/franchises/`) that can absorb quality regressions.

---

## 5. Slice 1 — Diagnostic gate + state firewall

**Goal:** Prove that declared drafter inputs reach the drafter prompt; stop killing 40-scene runs on a single canon blocker.

**Deliverables bundle:** Phase 0 audit (human + JSON) + state firewall + successor classifier + gap-note lifecycle scaffolding.

**Does this slice change current Ruusan/Betrayal output?** No — the firewall code path only fires on blockers, and Ruusan/Betrayal are not currently hitting save-blockers. Phase 0 is read-only.

### 5.1 Phase 0 diagnostic audit

#### 5.1.1 New script: `scripts/audit_phase0.py`

Purpose: run one chapter of the target book through the pipeline with a special flag that dumps every drafter/reviewer prompt to disk, then produce a six-criteria report.

CLI:
```
py -3 scripts/audit_phase0.py \
  --concept-seed data/franchises/<franchise>/books/<book>/concept_seed.json \
  --chapter 1 \
  --run-label phase0_$(date +%F)
```

Writes to `output/<franchise>/<book>/runs/<run_id>/`:
- `phase0_audit.json` — machine-readable gate
- `phase0_debug/` — one subdir per scene:
  - `01_plot_architect_prompt.txt`
  - `02_prose_stylist_prompt.txt`
  - `03_line_writer_prompt.txt` (if LineWriter enabled)
  - `04_gate_critic_prompt.txt`
  - `05_quality_polish_prompt.txt`
  - `06_final_gate_prompt.txt`
  - `07_canon_expert_prompt.txt`
  - Rendered brief (`brief.json`), rendered packet (when Slice 2 lands), pre/post-polish prose, ledger extract for the scene.

Also writes `docs/audits/phase0_<date>_<book>.md` — the human-readable summary referenced by the JSON gate via `evidence` paths.

#### 5.1.2 `phase0_audit.json` schema

Create `schemas/phase0_audit.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Phase0Audit",
  "type": "object",
  "required": ["run_id", "git_sha", "dirty", "generated_at", "criteria", "overall_pass"],
  "properties": {
    "run_id": { "type": "string" },
    "git_sha": { "type": "string" },
    "dirty": { "type": "boolean" },
    "generated_at": { "type": "string", "format": "date-time" },
    "franchise": { "type": "string" },
    "book": { "type": "string" },
    "chapter_audited": { "type": "integer" },
    "criteria": {
      "type": "object",
      "required": [
        "voice_rules_reach_drafter",
        "scene_contract_reaches_drafter",
        "constraints_survive_assembly",
        "cross_scene_feedback_real",
        "register_policy_single_source",
        "audit_report_exists"
      ],
      "additionalProperties": false,
      "patternProperties": {
        "^[a-z_]+$": {
          "type": "object",
          "required": ["pass", "evidence"],
          "properties": {
            "pass": { "type": "boolean" },
            "evidence": { "type": "string", "description": "Relative path + line range, or free-text explanation of why this is pass/fail." },
            "notes": { "type": "string" }
          }
        }
      }
    },
    "overall_pass": { "type": "boolean" }
  }
}
```

#### 5.1.3 Six audit criteria (the gate)

For each criterion, `audit_phase0.py` emits `{pass, evidence}`:

| Criterion key | Pass condition | Evidence form |
|---|---|---|
| `voice_rules_reach_drafter` | Voice rules from `voice.json` appear in the rendered prose_stylist prompt, with no silent truncation. | `phase0_debug/ch01_sc01/02_prose_stylist_prompt.txt:L142-L178` |
| `scene_contract_reaches_drafter` | Scene card's `mission`, `turning_point`, `pov_character`, `characters_present`, and `closing_hook` all appear intact. | Path + line range, or a diff snippet |
| `constraints_survive_assembly` | `negative_constraints` / anti-pattern lists are present in full, not truncated by token budget. | Path + line range |
| `cross_scene_feedback_real` | For chapter N scene 2+, the rendered prompt contains concrete references to scene 1 outcomes (pressure carry-forward, revealed information). | Diff between sc01 and sc02 prompts showing the carry-over |
| `register_policy_single_source` | Voice register policy is identical across `voice.json`, `prose_stylist` prompt, and `voice_checker` prompt — no contradiction. | Three-way text comparison summary |
| `audit_report_exists` | `docs/audits/phase0_<date>_<book>.md` exists and is non-empty, keyed to the other five criteria. | File path |

`overall_pass` is `true` **only** when all six criteria are `pass: true`.

#### 5.1.4 Gate enforcement

Add to `CLAUDE.md` under a new section, and enforced via a pre-merge check:

> Slice 2 implementation (chapter packet) is blocked until a Phase 0 audit with `overall_pass: true` exists at `output/<franchise>/<book>/runs/phase0_<latest>/phase0_audit.json` for **both** Ruusan and Betrayal.

The enforcement is social (PR review) in v1. A future hook can wire this to `scripts/compile_bundle.py` preflight.

#### 5.1.5 If Phase 0 fails

If any criterion is `pass: false`, work pivots to plumbing. Do **not** proceed to Slice 2. Typical fixes:
- Prompt truncation: adjust token budgets in `context_assembler.py`.
- Silent drops: trace `_assemble_phase1` vs `_assemble_phase2` divergence.
- Voice rules never wired: check `voice_rules` → `ProseStylist.run()` ingestion path.

Only after re-running `audit_phase0.py` with all six `pass: true` does Slice 2 open.

### 5.2 State firewall

#### 5.2.1 New module: `src/pipeline/state_firewall.py`

Replaces the "raise `SaveBlockedError` and abort" path in `src/pipeline/save_blockers.py` for blocked scenes when `runtime.firewall.enabled: true`. Leaves existing behavior untouched when flag is off.

Class skeleton:

```python
class StateFirewall:
    def __init__(self, *, project_paths: ProjectPaths, story_state: StoryState,
                 classifier: SuccessorClassifier, ledger: RunLedger,
                 runtime_flags: dict) -> None: ...

    def handle_blocker(self, *, scene_card: dict, prose: str, brief: dict,
                       blockers: list[Blocker], subsequent_scenes: list[dict]
                       ) -> FirewallDecision: ...
```

Where `FirewallDecision` is:

```python
@dataclass(frozen=True)
class FirewallDecision:
    isolated: bool                 # always True when blockers non-empty
    gap_id: str                    # assigned gap id
    continue_run: bool             # False means soft-halt the whole run
    soft_halted_scenes: list[str]  # scene_ids that the classifier flagged unsafe
    continue_with_gap_note: list[str]  # scene_ids that can proceed with gap note
    ledger_events: list[dict]      # events to be emitted by caller
```

#### 5.2.2 Isolation on disk

When a blocker fires and the flag is on, the firewall:

1. Writes scene artifacts to `output/<franchise>/<book>/quarantine/ch<NN>_sc<MM>/` (unchanged path — matches current `save_blockers.py` behavior).
2. Also writes a `gap_manifest.json` beside the quarantined scene, containing the gap record (see `§5.4`).
3. Records the gap in a new `gap_notes` SQLite table (see `§5.2.4`).
4. Marks the scene's `revision_status` as `quarantined` in `story_state.db` (existing vocabulary — no new status).
5. **Does not** write to `chapter_log`, `scene_log`, or any trusted-state table for this scene.
6. Emits ledger event `scene_isolated` (new event type — see `§11.4`).

#### 5.2.3 Continue-vs-halt decision

The firewall asks the `SuccessorClassifier` (`§5.3`) whether each unfinished scene in the current chapter (and the first scene of the next chapter, if we are at a chapter boundary) should:
- `continue_with_gap_note` — run the scene, surface the gap in its overlay (Slice 2) or as inline prompt text (Slice 1 fallback).
- `soft_halt` — stop the run, surface the gap to the user.

If **any** scene in the remainder of the chapter is classified soft-halt, `continue_run = False`.

If `runtime.firewall.successor_classifier.enabled: false`, the firewall defaults to soft-halting on the first blocker (conservative) — but still isolates the scene rather than raising `SaveBlockedError`. This means partial progress is preserved even when the classifier is untrusted.

#### 5.2.4 New SQLite table: `gap_notes`

Created by a migration script (see `§5.5`). Lives in `output/<franchise>/<book>/state/story_state.db`.

```sql
CREATE TABLE IF NOT EXISTS gap_notes (
    gap_id TEXT PRIMARY KEY,
    isolated_scene TEXT NOT NULL,            -- "ch04_sc07"
    blocker_categories TEXT NOT NULL,        -- JSON array
    created_at TEXT NOT NULL,                -- ISO8601
    affected_scenes TEXT NOT NULL,           -- JSON array of scene_ids
    status TEXT NOT NULL CHECK(status IN ('open','resolved','overruled')),
    resolved_by TEXT,                        -- 'human_patch_accept' | 'human_replace' | 'overrule' | NULL
    resolved_at TEXT,
    resolution_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_gap_notes_status ON gap_notes(status);
CREATE INDEX IF NOT EXISTS idx_gap_notes_isolated_scene ON gap_notes(isolated_scene);
```

New methods on `StoryState`:
- `record_gap(gap: dict) -> str` — returns `gap_id`.
- `list_open_gaps(*, chapter_number: int | None = None) -> list[dict]`.
- `resolve_gap(gap_id: str, *, resolved_by: str, notes: str) -> None`.
- `list_gaps_affecting(scene_id: str) -> list[dict]`.

#### 5.2.5 Modifications to `src/pipeline/save_blockers.py`

Do not delete existing code. Instead:

- Keep `check_save_blockers()`, `SaveBlockedError`, and quarantine writes as-is.
- At the module level, add a `should_abort_run(runtime_flags) -> bool` helper that returns `not runtime_flags.get("runtime", {}).get("firewall", {}).get("enabled", False)`.
- Modify `src/orchestrator.py` to route through the firewall when the flag is on:

```python
try:
    check_save_blockers(...)
except SaveBlockedError as exc:
    if should_abort_run(runtime_flags):
        raise  # existing behavior
    decision = state_firewall.handle_blocker(
        scene_card=scene_card, prose=prose, brief=brief,
        blockers=exc.blockers,
        subsequent_scenes=remaining_cards_in_chapter,
    )
    if not decision.continue_run:
        logger.warn("state_firewall soft-halted run", extra={"gap_id": decision.gap_id})
        break  # exit scene loop cleanly; don't raise
    # else: continue to next scene
```

### 5.3 Successor classifier (Patch 1)

#### 5.3.1 New module: `src/pipeline/successor_classifier.py`

Deterministic heuristic. No LLM inference in v1.

```python
class SuccessorClassifier:
    def __init__(self, *, jaccard_threshold: float = 0.5,
                 adjacency_max_for_continue: int = 1) -> None: ...

    def classify(self, *, blocked_scene: dict,
                 candidate_scene: dict,
                 chapter_index: dict) -> SuccessorDecision: ...
```

Where:

```python
@dataclass(frozen=True)
class SuccessorDecision:
    scene_id: str
    class_label: Literal[
        "immediate_sequel",
        "same_pov_continuation",
        "same_turn_escalation",
        "transitional_with_gap",
        "loose_downstream",
        "parallel_weak_dependence",
    ]
    recommendation: Literal["soft_halt", "continue_cautiously", "continue_with_note"]
    reasons: list[str]       # which heuristic inputs fired
    scores: dict[str, Any]   # jaccard, adjacency, etc.
```

#### 5.3.2 Classification rules (first match wins)

Inputs: both scene cards + their chapter indices.

1. **Immediate sequel** — `candidate_scene.depends_on` contains `blocked_scene_id`. → `soft_halt`.
2. **Same-POV continuation** — `candidate.pov_character == blocked.pov_character` AND candidate is the next scene in the same chapter. → `soft_halt`.
3. **Same-turn escalation** — both scenes carry the same `structural_phase` AND candidate is within the same chapter or the first scene of the next chapter. → `soft_halt`.
4. **Transitional with gap** — `jaccard(characters_present) >= threshold` AND candidate is the next scene in the same chapter. → `continue_cautiously`.
5. **Loose downstream** — `jaccard(characters_present) < threshold` OR candidate is more than one scene away. → `continue_with_note`.
6. **Parallel weak dependence** — fallback. → `continue_with_note`.

Jaccard uses `characters_present` arrays (lowercase, de-duplicated).

#### 5.3.3 New scene-card field: `depends_on`

Add to `schemas/scene_card.json`:

```json
"depends_on": {
  "type": "array",
  "items": { "type": "string", "pattern": "^ch\\d{2}_sc\\d{2}$" },
  "description": "Scene IDs (format chNN_scMM) that this scene directly depends on. Used by SuccessorClassifier to classify follow-on scenes as soft-halt when a predecessor is isolated. Authors may set this manually; no auto-inference in v1."
}
```

Do **not** backfill existing scene cards. The field is optional; missing = classifier falls through rule 1 and uses only heuristic rules 2–6.

#### 5.3.4 Acceptance test for the classifier

New file: `tests/test_successor_classifier.py`.

Hand-label 30 `(blocked_scene, candidate_scene)` pairs drawn from Ruusan and Betrayal scene graphs (see `§5.6` for authoring). Required: ≥ 27 of 30 (90%) agreement between classifier output and human label. Label source committed at `tests/data/successor_classifier_labels.json`:

```json
{
  "labels": [
    {
      "blocked": "ch04_sc07",
      "candidate": "ch04_sc08",
      "expected_class": "same_pov_continuation",
      "expected_recommendation": "soft_halt",
      "rationale": "sc08 opens with POV responding to sc07's reveal"
    },
    ...
  ]
}
```

Below 90% agreement, the classifier is **not** trusted — the firewall defaults to soft-halting on any blocker regardless of candidate, but still isolates rather than aborting. Flip `runtime.firewall.successor_classifier.enabled` on only after the test passes.

### 5.4 Gap-note lifecycle (Patch 5, scaffolding only in Slice 1)

Slice 1 lands the gap-note record (`§5.2.4`) and writes it at isolation time. Full propagation into chapter-packet overlays and patch-accept back-fill ship with Slice 2 (for overlay integration) and Slice 6 (for back-fill workflow). In Slice 1:

- Gaps are written to SQLite and to the ledger.
- They surface in run summary at end of a run (added to `src/main.py`'s end-of-run printout).
- `chapter_close_memo` is not yet implemented (Slice 2).

Acceptance: after a blocked run, `StoryState.list_open_gaps()` returns the gap record with correct `isolated_scene`, `blocker_categories`, and `affected_scenes`.

### 5.5 Migration: `scripts/migrations/migrate_gap_notes.py`

Idempotent. Creates the `gap_notes` table on existing `story_state.db` files. Pattern matches `scripts/migrations/migrate_status_vocab.py`.

```python
def migrate(db_path: Path) -> MigrationResult:
    with sqlite3.connect(db_path) as conn:
        conn.execute(GAP_NOTES_DDL)  # from §5.2.4
        # Create indexes
        conn.commit()
    return MigrationResult(tables_added=["gap_notes"], rows_migrated=0)
```

CLI:
```
py -3 scripts/migrations/migrate_gap_notes.py --base-dir .
```

Walks all `output/<franchise>/<book>/state/story_state.db` and applies. Idempotent (CREATE IF NOT EXISTS).

### 5.6 Authoring: successor classifier labels

Before flipping `runtime.firewall.successor_classifier.enabled: true`, author the 30-label validation set.

**Procedure:**
1. Enumerate (blocked, candidate) pairs from Ruusan ch01–ch05 and Betrayal ch01–ch02 where blocked has at least two downstream scenes in the same chapter or the first of the next chapter. Target: 30 pairs.
2. For each pair, a human labels `expected_class` and `expected_recommendation`.
3. Commit to `tests/data/successor_classifier_labels.json`.
4. Run `pytest tests/test_successor_classifier.py -v`. Require ≥ 27/30 pass.

Re-author the label set when the classifier heuristic changes.

### 5.7 Slice 1 go/no-go checklist

Before declaring Slice 1 done:

- [ ] `schemas/phase0_audit.json` lands.
- [ ] `scripts/audit_phase0.py` produces both `phase0_audit.json` and `docs/audits/phase0_<date>_<book>.md` for Ruusan ch01 and Betrayal ch01.
- [ ] Both audits show `overall_pass: true`. If not, Slice 2 is blocked and plumbing fixes are scheduled instead.
- [ ] `src/pipeline/state_firewall.py` implemented, tested.
- [ ] `src/pipeline/successor_classifier.py` implemented, with labels committed and ≥ 90% agreement.
- [ ] `gap_notes` table migration runs cleanly on all existing book DBs.
- [ ] `scene_card.json` schema has optional `depends_on`.
- [ ] `runtime.firewall.enabled: false` in `config/settings.yaml` (default off).
- [ ] `tests/test_state_firewall.py` covers: isolation writes correct files; soft-halt correctly exits loop; continue-with-note correctly proceeds.
- [ ] `tests/test_pipeline_regression_ruusan.py::test_ch01_flag_off_parity` passes (no prose delta vs pre-Slice-1 baseline).
- [ ] Updated `CLAUDE.md` section mentioning the firewall and Phase 0 gate.
- [ ] Ledger event types `scene_isolated` and `gap_note_recorded` added to `§D` inventory.

---

## 6. Slice 2 — Chapter packet + revision debt

**Goal:** Give the drafter a single inspectable runtime contract. Make advisories durable and categorizable.

**Prerequisite:** Slice 1 go/no-go checklist complete, both Phase 0 audits green.

**Does this slice change current Ruusan/Betrayal output?** Potentially — the packet changes what the drafter sees. This is mitigated by `runtime.chapter_packet.enabled: false` default, the fallback path, and a parity test before flipping the flag per book.

### 6.1 Chapter packet architecture

#### 6.1.1 Consistency model (Patch 3)

**Base + overlay.** Base is compiled once at chapter start from planning artifacts + trusted state as of the chapter's first scene. Immutable for the remainder of the chapter. Overlay is compiled per scene from trusted-state changes accumulated since chapter start (continuity log from Slice 4, promise ledger updates from Slice 3, sociogram deltas from Slice 5). Drafter receives base + overlay concatenated at scene-draft time.

Rationale: single inspectable contract per chapter for debugging, plus per-scene trusted-state currency, without cost of full packet rebuild per scene.

Persistence:
- Base: `output/<franchise>/<book>/runs/<run_id>/chapter_packets/chapter_NN.json` (written once per chapter).
- Overlay: `output/<franchise>/<book>/runs/<run_id>/chapter_packets/chapter_NN_sc_MM_overlay.json` (one per scene).

Both have an `overlay_version: int` field to catch stale-overlay bugs. Overlay writes emit a ledger event `packet_overlay_written` with the version.

#### 6.1.2 New module: `src/pipeline/chapter_packet.py`

```python
@dataclass
class ChapterPacket:
    chapter_number: int
    overlay_version: int          # 0 on base; increments per overlay
    mission: str
    chapter_turn: str
    pressure_ladder: list[dict]
    pov_arc_pressure: dict
    next_scene_obligations: list[dict]
    active_promises: list[dict]    # trusted-state only; empty until Slice 3
    reveal_deadlines: list[dict]
    canon_slices: list[dict]
    relationship_context: dict     # empty until Slice 5
    exit_vector: dict
    trusted_state_gap_notes: list[dict]   # from StoryState.list_open_gaps
    exemplar_snippets: list[dict]         # optional; from voice.json
    anti_exemplar_snippets: list[dict]    # optional
    continuity_events: list[dict]         # empty until Slice 4

    def render_markdown(self) -> str: ...
    def to_json(self) -> dict: ...

class ChapterPacketCompiler:
    def __init__(self, *, assembler: ContextAssembler, story_state: StoryState,
                 concept_seed: dict, blueprint: dict,
                 promise_ledger: PromiseLedger | None = None,   # Slice 3
                 continuity_log: ContinuityLog | None = None,   # Slice 4
                 sociogram: Sociogram | None = None) -> None: ...  # Slice 5

    def compile_base(self, *, chapter_number: int) -> ChapterPacket: ...
    def compile_overlay(self, *, base: ChapterPacket,
                        scene_card: dict,
                        trusted_state_snapshot: dict) -> ChapterPacket: ...
```

The overlay compilation **never modifies** the base; it returns a new `ChapterPacket` with merged fields and incremented `overlay_version`.

#### 6.1.3 Schema: `schemas/chapter_packet.json`

Draft-07 JSON Schema covering the dataclass shape above. Strict types for promise/event/gap-note sub-shapes. Required fields: `chapter_number`, `overlay_version`, `mission`, `chapter_turn`. Everything else optional to allow gradual rollout.

#### 6.1.4 Wiring into the drafter

Modify `src/agents/prose_stylist.py` to accept either `assembled_context` (string, current path) or `chapter_packet` (dict, new path). Precedence: if both are supplied and `runtime.chapter_packet.enabled: true`, use packet; else fall back to `assembled_context`.

```python
async def run(self, context: dict) -> dict:
    packet = context.get("chapter_packet")
    use_packet = context.get("runtime_flags", {}).get("runtime", {}).get("chapter_packet", {}).get("enabled", False)
    if use_packet and packet is not None:
        rendered = packet["rendered_markdown"]   # or pass packet to a dedicated renderer
    else:
        rendered = context["assembled_context"]
    ...
```

Orchestrator change in `src/orchestrator.py`:
- At chapter start, if the flag is on, `ChapterPacketCompiler.compile_base(chapter_number=N)` and cache the base.
- At each scene, `compile_overlay(base=..., scene_card=..., trusted_state_snapshot=...)`; pass overlay (which contains the base by composition) to drafter via `context["chapter_packet"]`.
- Also call `assembler.assemble(scene_card)` and pass as `context["assembled_context"]` for the fallback.
- If `compile_overlay` raises and `runtime.chapter_packet.fallback_on_error: true`, log a warn event, skip packet, use flat assembly.

#### 6.1.5 Parity test (Ruusan/Betrayal protection)

Before any `runtime_overrides.yaml` sets `runtime.chapter_packet.enabled: true` for Ruusan or Betrayal, a side-by-side parity test must pass:

New test: `tests/test_packet_parity.py::test_ruusan_ch01_packet_is_flat_superset`.

Logic:
1. Compile flat context for Ruusan ch01 sc01 using `ContextAssembler.assemble()`.
2. Compile base + overlay packet for the same scene; render to markdown.
3. Tokenize both (whitespace + punctuation split).
4. Every token present in flat must be present in packet. The reverse is **not** required (packet may add fields).
5. Additionally: section order check — voice rules must appear before scene card fields; exemplars must appear before drafter instructions. Order-sensitive assertions encoded in the test.

If parity fails, the packet renderer is bugged; fix before enabling.

Also run a **bench parity** test:
- Run Ruusan ch01 sc01 through `bench_prose_models.py` once with `runtime.chapter_packet.enabled: false` (flat context) and once with `true` (packet).
- Manually review the prose diff. If voice texture or scene-contract fidelity regresses subjectively, fix and retry. This is a judgment call, not an automated gate — but it is a required step before flipping the flag per book.

### 6.2 Revision debt store

#### 6.2.1 Write-matrix (Patch 2)

Closed set of categories. No stage writes debt unless there is a matching row here.

| Producer | Condition | Category | Default severity |
|---|---|---|---|
| `CanonExpert` | `advisory_notes[*]` emitted | `canon` | from advisory |
| `CanonExpert` | `local_fixes` rejected by whitelist (Slice 11.1) | `canon_fix_rejected` | `low` |
| `GateCritic` | `failure_codes` with `severity: non_blocking` | `editorial.gate_advisory` | from failure |
| `FinalGate` | Any output (always advisory) | `editorial.final_gate_advisory` | from failure |
| `QualityMetrics` (MetricsDashboard) | Any metric exceeds threshold in `config/quality_thresholds.yaml` | `metric` | `low` if within 1 band of threshold; `medium` beyond |
| `PresenceChecker` | Confidence in `[0.5, blocker_threshold)` | `presence_near_miss` | `low` |
| `StateFirewall` | Scene isolated | `blocker_record` | `high` (pinned) |
| `word_count_telemetry` | Drift outside ±15% | `wordcount_drift` | `low` if < 30%, `medium` if > 30% |
| `compression_guard` | Polish shrinks below 60% of pre-polish word count | `compression_advisory` | `medium` |
| `SceneReviewer` (future) | Any categorical finding | `editorial.scene_reviewer` | from finding |

Rules:
- `SceneReviewer` free-text notes that don't fit a category write as `editorial.other` with an explicit `note: "uncategorized"` field.
- The category list is **closed** — new categories require a schema bump.
- `owner_or_reviewer_notes` is human-only; no agent writes to it.
- Severity values: `{low, medium, high}` only.

#### 6.2.2 Schema: `schemas/revision_debt.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "RevisionDebtEntry",
  "type": "object",
  "required": ["debt_id", "created_at", "producer", "scope", "category", "severity", "status"],
  "properties": {
    "debt_id": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "producer": { "type": "string" },
    "scope": {
      "type": "object",
      "required": ["level"],
      "properties": {
        "level": { "enum": ["scene", "chapter", "act", "manuscript"] },
        "chapter_number": { "type": "integer" },
        "scene_number": { "type": "integer" },
        "scene_id": { "type": "string" }
      }
    },
    "category": { "enum": [
      "canon", "canon_fix_rejected",
      "editorial.gate_advisory", "editorial.final_gate_advisory",
      "editorial.scene_reviewer", "editorial.other",
      "metric", "presence_near_miss",
      "blocker_record", "wordcount_drift", "compression_advisory"
    ]},
    "severity": { "enum": ["low", "medium", "high"] },
    "summary": { "type": "string" },
    "details": { "type": "object" },
    "fix_scope": { "enum": ["local", "scene", "chapter", "manuscript"] },
    "status": { "enum": ["open", "deferred", "resolved", "overruled"] },
    "resolved_at": { "type": "string", "format": "date-time" },
    "resolution_notes": { "type": "string" },
    "owner_or_reviewer_notes": { "type": "string" }
  }
}
```

#### 6.2.3 New module: `src/pipeline/revision_debt.py`

```python
class RevisionDebtStore:
    def __init__(self, *, db_path: Path) -> None: ...
    def add(self, entry: dict) -> str: ...        # returns debt_id
    def list_open(self, *, scope: dict | None = None) -> list[dict]: ...
    def update_status(self, debt_id: str, *, status: str,
                      resolution_notes: str | None = None) -> None: ...
    def summarize_for_chapter(self, chapter_number: int) -> dict: ...
    def summarize_for_book(self) -> dict: ...
```

SQLite-backed at `output/<franchise>/<book>/state/revision_debt.db` (separate from `story_state.db` to keep that file's migration surface stable).

#### 6.2.4 Producer wiring

Each producer gets a tiny wrapper in `src/pipeline/revision_debt_producers.py`:

```python
def emit_canon_advisory(store: RevisionDebtStore, *, scope: dict,
                        advisory: dict) -> str: ...

def emit_gate_critic_advisory(store: RevisionDebtStore, *, scope: dict,
                              verdict: dict) -> str: ...

# ... one per row in the write-matrix
```

These wrappers are called from the orchestrator at the appropriate stage. They are the **only** write path. Orchestrator does not call `store.add()` directly.

When `runtime.revision_debt.enabled: false`, wrappers short-circuit to noop and emit the advisory to the ledger only (existing behavior).

#### 6.2.5 Migration: `scripts/migrations/migrate_revision_debt.py`

Creates `revision_debt.db` alongside `story_state.db` in every `output/<franchise>/<book>/state/` directory. Idempotent.

### 6.3 Chapter-close and milestone memos

#### 6.3.1 New module: `src/pipeline/chapter_memos.py`

```python
class ChapterCloseMemoGenerator:
    def __init__(self, *, debt_store: RevisionDebtStore,
                 story_state: StoryState,
                 promise_ledger: PromiseLedger | None = None) -> None: ...

    def generate(self, *, chapter_number: int) -> ChapterCloseMemo: ...

class MilestoneMemoGenerator:
    def generate(self, *, through_chapter: int) -> MilestoneMemo: ...
```

#### 6.3.2 Schema: `schemas/chapter_memo.json`

Chapter-close memo fields:
- `chapter_number`, `generated_at`
- `debt_summary`: counts by category + severity, list of open debt ids
- `gap_notes`: open gaps affecting this or downstream chapters
- `pending_promises`: promises planted but not yet paid (empty until Slice 3)
- `presence_near_misses`, `compression_events`, `word_count_drift`
- `human_attention_items`: a synthesis bullet list, pre-formatted markdown

Milestone memo fields (same shape but aggregates across chapters):
- `through_chapter`, `generated_at`
- `debt_trend`: severity counts by chapter
- `gap_resolution_rate`, `open_gap_count`
- `recommended_review_chapters`

Both written to `output/<franchise>/<book>/runs/<run_id>/memos/`.

#### 6.3.3 UI/CLI surfacing

Slice 2 ships a CLI: `py -3 scripts/debt_cli.py`:
- `list --status open --chapter 4`
- `update <debt_id> --status resolved --notes "..."`
- `memo chapter --chapter 4`
- `memo milestone --through-chapter 10`

UI integration (if FastAPI is running): add `/api/debt` endpoints. Not required for Slice 2 completion; can ship in a follow-up.

### 6.4 Overlay integration with gap notes

Slice 1 writes gap notes but only surfaces them at end-of-run printout. In Slice 2, overlay compilation pulls open gap notes that affect the current chapter into `trusted_state_gap_notes` and the drafter sees them in the rendered packet.

Gap-note phrasing in overlay is a prompt-design concern. Initial template:

> **Narrative continuity gaps**
> The following predecessor scenes were isolated and are not part of trusted continuity. Treat their referenced facts as unknown:
> - Scene ch04_sc07 (canon violation; isolated 2026-04-18). Do not assume any facts from this scene are in effect.
>
> If your scene would naturally reference events from an isolated scene, write around them — summarize the gap narratively (e.g., "something had happened, but the details remained unclear to her") rather than invent specifics.

Test: a drafter run on a scene flagged `continue_with_note` produces prose that does **not** reference specific facts invented for the isolated scene. Measured by: if isolated scene's `turning_point` or `revelations[]` text appears verbatim in successor prose, test fails.

### 6.5 Updated stage order

With Slice 2 live (flag on), chapter-level stage order becomes:

```
[Chapter start]
  ChapterPacketCompiler.compile_base(chapter_number=N)  # once per chapter

[Scene start]
  ChapterPacketCompiler.compile_overlay(base, scene_card, trusted_state_snapshot)
  PlotArchitect
  ProseStylist (receives packet)
  [LineWriter if enabled]
  GateCritic
  QualityMetrics
  QualityPolish
  FinalGate
  CanonExpert  # still late-position in Slice 2; relocation is Slice 11.1
  save_blocker layer → StateFirewall if runtime.firewall.enabled
  save | isolate

[Scene end]
  Producers call revision_debt_producers.* for any advisories fired this scene
  Ledger event packet_overlay_written

[Chapter end]
  ChapterCloseMemoGenerator.generate(chapter_number=N)
```

### 6.6 Token-budget measurement (critical for Ruusan)

Before Slice 2's flag is flipped on for Ruusan, measure:

```
flat_context_tokens  = tokens(ContextAssembler.assemble(scene_card))
packet_base_tokens   = tokens(ChapterPacket.render_markdown() for base)
packet_overlay_tokens = tokens(ChapterPacket.render_markdown() for each overlay)
```

Record in `output/<franchise>/<book>/runs/<run_id>/packet_budget_report.md`. If packet total exceeds flat by > 20% and the drafter context is already near its limit (check `config/settings.yaml` max_tokens for `prose_stylist`, currently 8192), identify which fields to trim (gap-note verbose template, exemplar snippets are likely candidates) or shift to on-demand retrieval.

### 6.7 Tests added

- `tests/test_chapter_packet.py` — base/overlay compilation, overlay version monotonic, immutability of base.
- `tests/test_packet_parity.py` — Ruusan/Betrayal ch01 parity, token-set superset.
- `tests/test_revision_debt.py` — write-matrix enforcement (producer X with condition Y writes row Z); closed-category enforcement.
- `tests/test_chapter_memos.py` — memo synthesis from debt + gap records.
- `tests/test_packet_gap_note_propagation.py` — gap note appears in overlay for flagged successor scene.

### 6.8 Slice 2 go/no-go checklist

- [ ] Phase 0 audits for Ruusan and Betrayal are green (Slice 1 prerequisite).
- [ ] `schemas/chapter_packet.json` and `schemas/revision_debt.json` land.
- [ ] `src/pipeline/chapter_packet.py`, `revision_debt.py`, `chapter_memos.py` implemented.
- [ ] `tests/test_packet_parity.py` passes for Ruusan and Betrayal.
- [ ] Token-budget measurement reports within +20% of flat for both books (or a trim plan is adopted and re-measured).
- [ ] Write-matrix enforced: every existing advisory stage produces debt rows correctly.
- [ ] Closed-category enforcement: attempts to add unknown categories raise `ValueError`.
- [ ] `scripts/migrations/migrate_revision_debt.py` runs cleanly on all books.
- [ ] `runtime.chapter_packet.enabled` and `runtime.revision_debt.enabled` both default `false` in `config/settings.yaml`.
- [ ] At least one lower-stakes book (or `test-bench/`) has both flags flipped on via `runtime_overrides.yaml` and produces prose that subjectively matches or exceeds the flat-context baseline.
- [ ] Ruusan and Betrayal still default-off; their parity tests still pass.
- [ ] CLAUDE.md updated with packet/debt section and the "one chapter packet contract" invariant.

---

## 7. Slice 3 — Promise ledger

**Goal:** First trusted stateful-memory artifact. Declaration-driven. No inference.

**Prerequisite:** Slice 2 shipped with `runtime.chapter_packet.enabled: true` on at least one book (packet has a slot for `active_promises`).

**Does this slice change current Ruusan/Betrayal output?** No while `runtime.promise_ledger.enabled: false`. When enabled for a book, the `active_promises` field of the overlay populates and the drafter sees urgency-filtered promises — this can produce more focused prose but can also induce forced payoff. See `§7.3` for mitigation.

### 7.1 Trust model (Patch 4)

**Declarative-with-defaults.** The ledger is populated from planning artifacts and scene-card declarations. LLM inference does **not** change ledger entries in v1.

- A promise in `active_promises` defaults to `status: progressing` between `setup_scene` and `payoff_scene`.
- Scene cards may declare `promises_progressed: [<promise_id>]` to mark explicit progression beats. Each appends one entry to `promise.progression_log` at save time with `source: "scene_card"`.
- `SceneReviewer` may *suggest* progression beats, but those land as `editorial.promise_progression_suggestion` entries in revision debt, **not** as ledger updates.
- `overdue` is derived, not stored. A promise is overdue when the current scene index has passed `promise.due_by_scene` without a `payoff_scene` being set.

### 7.2 Schema and storage

#### 7.2.1 Schema: `schemas/promise_ledger_entry.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PromiseLedgerEntry",
  "type": "object",
  "required": ["promise_id", "description", "setup_scene", "status"],
  "properties": {
    "promise_id": { "type": "string" },
    "description": { "type": "string" },
    "promise_type": { "enum": ["plot", "character", "thematic", "mystery", "romance", "other"] },
    "setup_scene": { "type": "string", "pattern": "^ch\\d{2}_sc\\d{2}$" },
    "payoff_scene": { "type": "string", "pattern": "^ch\\d{2}_sc\\d{2}$" },
    "due_by_scene": { "type": "string", "pattern": "^ch\\d{2}_sc\\d{2}$" },
    "status": { "enum": ["planted", "progressing", "paid", "broken", "retired"] },
    "progression_log": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["scene_id", "source", "timestamp"],
        "properties": {
          "scene_id": { "type": "string" },
          "source": { "enum": ["scene_card", "manual", "planning"] },
          "note": { "type": "string" },
          "timestamp": { "type": "string", "format": "date-time" }
        }
      }
    },
    "created_at": { "type": "string", "format": "date-time" },
    "updated_at": { "type": "string", "format": "date-time" }
  }
}
```

#### 7.2.2 New scene-card field: `promises_progressed`

Add to `schemas/scene_card.json`:

```json
"promises_progressed": {
  "type": "array",
  "items": { "type": "string" },
  "description": "Promise IDs this scene advances without paying off. Used by the promise ledger to record progression beats. Optional."
}
```

#### 7.2.3 New module: `src/memory/promise_ledger.py`

```python
class PromiseLedger:
    def __init__(self, *, db_path: Path) -> None: ...

    def initialize_from_planning(self, *, concept_seed: dict,
                                  scene_cards: list[dict]) -> int:
        """Seed promises from story_physics.promise_payoff_ledger and
        scene_cards[*].promises_planted. Returns count inserted."""
        ...

    def record_progression(self, *, promise_id: str, scene_id: str,
                           source: str, note: str = "") -> None: ...

    def record_payoff(self, *, promise_id: str, scene_id: str) -> None: ...

    def record_broken(self, *, promise_id: str, scene_id: str,
                      reason: str) -> None: ...

    def list_active(self, *, at_scene: str) -> list[dict]:
        """Return promises where setup_scene <= at_scene < payoff_scene
        (or payoff_scene is None). Includes progression_log."""
        ...

    def list_overdue(self, *, at_scene: str) -> list[dict]: ...

    def list_top_urgent(self, *, at_scene: str, n: int = 5) -> list[dict]:
        """Sort by due_by_scene proximity ascending; cap at n.
        Used by chapter packet to prevent packet dilution."""
        ...
```

SQLite-backed at `output/<franchise>/<book>/state/promise_ledger.db`.

### 7.3 Packet integration (dilution prevention)

In `ChapterPacketCompiler.compile_overlay`, when `runtime.promise_ledger.enabled: true`:

- Pull `list_top_urgent(at_scene=scene_id, n=5)` for the `active_promises` field.
- Include a tail `active_promises_total_count` integer for drafter awareness without dilution.
- Overdue promises are included but flagged `status: overdue` AND a per-overdue-promise text field `rendering_hint: "advisory — do not force payoff"` is appended.

Renderer in `ChapterPacket.render_markdown` emits them as:

```markdown
**Active promises (5 of 23 open; sorted by urgency)**
- [plot] The informant will expose Jora (due by ch05_sc02; planted ch03_sc04, progressing)
- [character] Hunter's resolve tested (due by ch04_sc09; progressing)
- ...

**Overdue promises (advisory only — do not force payoff in this scene):**
- [mystery] The missing datacube (due by ch04_sc06; 2 scenes overdue)
```

### 7.4 Initialization from existing planning

#### 7.4.1 Migration: `scripts/migrations/migrate_promise_ledger.py`

For each book:
1. Open `concept_seed.json`; find `story_physics.promise_payoff_ledger` (if present).
2. Walk all scene cards in `data/franchises/<franchise>/books/<book>/scene_cards/`.
3. For each `promises_planted[i]` on a scene card, create/update a ledger entry with `setup_scene = that_scene_id`.
4. For each `promises_paid[i]`, set `payoff_scene = that_scene_id`.
5. Compute `due_by_scene` from planning (see `§7.4.2`) if available; else leave null.
6. Status derived: if `payoff_scene` set → `paid`; else → `planted`.

Idempotent: re-running updates in place.

#### 7.4.2 Where `due_by_scene` comes from

Planning-driven. Does not infer. Sources, in order:
1. `concept_seed.story_physics.promise_payoff_ledger[*].payoff_chapter` (existing field). Convert to `chNN_sc99` convention (end of chapter) if no more specific scene given.
2. Chapter blueprint: if `chapter_blueprint.scene_plan[*]` references the promise by ID with a "pay here" annotation, use that scene ID.
3. Author override via `data/franchises/<franchise>/books/<book>/promise_due_overrides.yaml` (optional hand-authored file).

If none of the above, `due_by_scene` stays null and `list_overdue` never returns the promise.

### 7.5 Slice 3 go/no-go checklist

- [ ] `schemas/promise_ledger_entry.json` lands.
- [ ] `schemas/scene_card.json` has `promises_progressed` optional field.
- [ ] `src/memory/promise_ledger.py` implemented.
- [ ] `scripts/migrations/migrate_promise_ledger.py` runs on Ruusan and Betrayal; produces reasonable ledgers (human spot-check, not automated).
- [ ] `runtime.promise_ledger.enabled: false` default.
- [ ] Unit tests cover: `list_active` correct at arbitrary scene ids; `list_overdue` only returns with due_by_scene set; `record_payoff` moves status to `paid`; `list_top_urgent` respects `n` cap.
- [ ] Packet integration test: when flag on, `active_promises` field of overlay is non-empty and capped at 5 with `active_promises_total_count` reflecting true total.
- [ ] Parity test for Ruusan/Betrayal still default-off, no prose delta.
- [ ] CLAUDE.md updated with promise-ledger section.

---

## 8. Slice 4 — Continuity event log

**Goal:** Trusted log of "what happened" events extracted from saved prose, available in packet overlays.

**This is the risky slice.** LLM fact extraction is unreliable. The gate is a labeled eval harness, not sprint completion.

**Prerequisite:** Slice 3 shipped. `runtime.promise_ledger.enabled: true` on at least one book, working well.

**Does this slice change Ruusan/Betrayal output?** Yes, when enabled. Extractor errors can poison future packets. Mitigations: narrow event schema, high confidence threshold, suppression of low-confidence events, labeled eval harness with precision target.

### 8.1 Event schema (narrow by design)

Start with five tightly-defined event types. Nothing interpretive.

```json
{
  "event_type": "location_change | injury_state | possession | revelation | status_change",
  "event_id": "evt_NNNN",
  "scene_id": "chNN_scMM",
  "subject": "character_or_entity_name",
  "details": { ... },                        // type-specific
  "confidence": 0.0,                         // 0-1
  "extractor_version": "v0.1",
  "human_verified": false
}
```

Type-specific `details`:

| event_type | Required details fields |
|---|---|
| `location_change` | `from_location`, `to_location` |
| `injury_state` | `severity` ∈ {minor, moderate, severe, mortal}, `body_part`, `mechanism` |
| `possession` | `item`, `action` ∈ {acquired, lost, transferred}, `counterparty` (optional) |
| `revelation` | `revelation_id` (must match `concept_seed.revelation_schedule`), `recipient` |
| `status_change` | `status_id` (must match a planned status in planning), `new_value` |

Deliberately excluded from v1: emotional shifts, relationship-interpretation events, thematic observations. Those belong to sociogram (Slice 5) or to revision debt suggestions, not the continuity log.

### 8.2 Schema: `schemas/continuity_event.json`

JSON Schema Draft-07 covering the above with `oneOf` discriminating on `event_type`.

### 8.3 Extractor agent

#### 8.3.1 New agent: `src/agents/continuity_extractor.py`

Model: Haiku (temperature 0.0, max_tokens 2048). Cheap, structured output.

```python
class ContinuityExtractor:
    async def extract(self, *, prose: str, scene_card: dict,
                      concept_seed: dict) -> list[dict]:
        """Returns list of continuity events with confidence scores."""
        ...
```

Prompt (stored at `prompts/continuity_extractor.md`):
- Gives the five event types with explicit field requirements.
- Provides the scene's `characters_present`, `setting`, planned `revelations`, `canon_elements_needed` as context.
- Explicitly instructs: "If you are not sure whether an event fits one of these types, do not include it. Err on the side of missing events."
- Output structured JSON; self-score confidence per event.

#### 8.3.2 Wiring: post-save extraction

Orchestrator change, after a scene is saved clean (not for isolated/quarantined scenes):

```python
if runtime_flags.get("runtime.continuity_log.enabled"):
    events = await continuity_extractor.extract(prose=final_prose,
                                                 scene_card=scene_card,
                                                 concept_seed=concept_seed)
    threshold = runtime_flags.get("runtime.continuity_log.min_confidence", 0.85)
    trusted = [e for e in events if e["confidence"] >= threshold]
    suppressed = [e for e in events if e["confidence"] < threshold]
    for e in trusted:
        continuity_log.append(e)
    if suppressed:
        emit_ledger_warn("continuity_events_suppressed", payload={"count": len(suppressed)})
```

**Trusted events go to the log.** Suppressed events go **nowhere** — not packet, not ledger as content, just a count warning. This prevents hallucinated events from ever reaching the drafter.

### 8.4 Eval harness (Patch 7B prerequisite)

#### 8.4.1 Labeled validation set

Authored as a one-time workstream at the start of Slice 4.

**Source prose:** 30 already-accepted scenes from Ruusan (balanced across ch01–ch10).

**Labeling:** A human reads each scene and produces a `ground_truth_events.json` listing the continuity events that should be extracted. Committed at `tests/data/continuity_eval_set.json`:

```json
{
  "version": "2026-04-20",
  "scenes": [
    {
      "scene_id": "ch01_sc01",
      "prose_path": "output/.../chapters/chapter_01_scene_01.md",
      "ground_truth_events": [
        {
          "event_type": "location_change",
          "subject": "Hunter",
          "details": { "from_location": "family_estate", "to_location": "Coruscant_spaceport" }
        },
        ...
      ]
    }
  ]
}
```

#### 8.4.2 Eval script: `scripts/eval_continuity_extractor.py`

Runs the extractor on each labeled scene and computes:
- **Precision:** of the events the extractor emitted at ≥ `min_confidence`, how many match a ground-truth event (same type, same subject, compatible details).
- **Recall:** of the ground-truth events, how many did the extractor emit at ≥ `min_confidence`.
- **False positive rate:** events emitted at ≥ `min_confidence` with no ground-truth match.

Match criterion for "compatible details" is type-specific and hand-coded per event type.

Writes `output/eval/continuity_extractor/<date>.json`:

```json
{
  "extractor_version": "v0.1",
  "min_confidence": 0.85,
  "n_scenes": 30,
  "precision": 0.91,
  "recall": 0.64,
  "false_positive_count": 4,
  "per_scene": [...]
}
```

#### 8.4.3 Trust threshold policy

**Gate for `runtime.continuity_log.enabled: true` on any book:**

- Precision ≥ 0.90 on the labeled set.
- False positive count ≤ 5% of emitted events.
- Recall ≥ 0.60 (this is the weaker target — missing events is safer than inventing them).

Below these, the extractor is tuned or the threshold raised. Do not ship.

For Ruusan specifically, require precision ≥ 0.95 before enabling (canon density makes false positives especially harmful).

### 8.5 Storage

SQLite at `output/<franchise>/<book>/state/continuity_log.db`. Table `continuity_events` plus index on `(scene_id, event_type, subject)`.

`src/memory/continuity_log.py`:

```python
class ContinuityLog:
    def append(self, event: dict) -> str: ...     # returns event_id
    def list_relevant_to_chapter(self, chapter_number: int) -> list[dict]: ...
    def list_events_for_subject(self, subject: str,
                                 before_scene: str) -> list[dict]: ...
    def mark_human_verified(self, event_id: str) -> None: ...
    def redact(self, event_id: str, reason: str) -> None: ...
```

Redaction writes a `redacted: true` flag rather than deleting, so audit trails stay intact.

### 8.6 Slice 4 go/no-go checklist

- [ ] `schemas/continuity_event.json` lands with strict `oneOf` discriminator.
- [ ] `tests/data/continuity_eval_set.json` authored (30 labeled scenes).
- [ ] `scripts/eval_continuity_extractor.py` produces report.
- [ ] Eval report shows precision ≥ 0.90 (≥ 0.95 for Ruusan use), recall ≥ 0.60, false positive rate ≤ 5%.
- [ ] `src/memory/continuity_log.py` and `src/agents/continuity_extractor.py` implemented.
- [ ] Suppression of sub-threshold events is tested and confirmed no-op on packet.
- [ ] `runtime.continuity_log.enabled: false` default.
- [ ] Ruusan/Betrayal parity test still green default-off.
- [ ] CLAUDE.md updated with continuity log section including "extractor is advisory-to-trusted; threshold-gated" invariant.

---

## 9. Slice 5 — Sociogram

**Goal:** Trusted character-relationship state, available in packet overlays.

**Highest inference risk in the stateful-memory family.** Strong bias toward declarative updates.

**Prerequisite:** Slice 4 shipped and stable for at least one completed book (not Ruusan/Betrayal yet).

### 9.1 Trust model

Hybrid, leaning declarative:

- Primary source: **planning-time** relationship intent from `concept_seed.ensemble_cast[*].relationships` (existing field).
- Secondary source: **scene-card declarations** of relationship deltas (new field `relationship_deltas`).
- Tertiary (optional, off by default): an assisted-suggestion mode where an extractor proposes deltas, a human accepts, and only then do they enter trusted state. No auto-trusted inferred deltas in v1.

### 9.2 Schema: `schemas/sociogram_edge.json`

```json
{
  "title": "SociogramEdge",
  "type": "object",
  "required": ["edge_id", "subject", "object", "arc_type", "current_state"],
  "properties": {
    "edge_id": { "type": "string" },
    "subject": { "type": "string" },
    "object": { "type": "string" },
    "arc_type": {
      "enum": ["allies_to_enemies", "enemies_to_allies", "lovers_to_strangers",
               "strangers_to_found_family", "mentor_to_peer", "stable_opposition",
               "stable_alliance", "one_sided", "convergent", "divergent", "other"]
    },
    "current_state": {
      "type": "object",
      "required": ["trust", "warmth", "power_balance", "updated_at_scene"],
      "properties": {
        "trust": { "type": "number", "minimum": -1, "maximum": 1 },
        "warmth": { "type": "number", "minimum": -1, "maximum": 1 },
        "power_balance": { "type": "number", "minimum": -1, "maximum": 1 },
        "updated_at_scene": { "type": "string" }
      }
    },
    "history": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "scene_id": { "type": "string" },
          "trust_delta": { "type": "number" },
          "warmth_delta": { "type": "number" },
          "power_balance_delta": { "type": "number" },
          "source": { "enum": ["planning", "scene_card", "human_accepted_suggestion"] },
          "note": { "type": "string" }
        }
      }
    }
  }
}
```

Three-axis scalar encoding (trust/warmth/power_balance) is deliberately simple. Not: emotion histograms, not communication modalities, not conflict-style. Start narrow, expand if needed.

### 9.3 New scene-card field: `relationship_deltas`

```json
"relationship_deltas": {
  "type": "array",
  "items": {
    "type": "object",
    "required": ["subject", "object"],
    "properties": {
      "subject": { "type": "string" },
      "object": { "type": "string" },
      "trust_delta": { "type": "number", "minimum": -0.5, "maximum": 0.5 },
      "warmth_delta": { "type": "number", "minimum": -0.5, "maximum": 0.5 },
      "power_balance_delta": { "type": "number", "minimum": -0.5, "maximum": 0.5 },
      "note": { "type": "string" }
    }
  }
}
```

Per-scene deltas capped at ±0.5 to prevent runaway. Authors set manually or via the assisted-suggestion flow.

### 9.4 Suggestion mode (optional, human-gated)

If `runtime.sociogram.suggest_mode: true`:
- After a scene is saved clean, an LLM agent proposes `relationship_deltas` based on the prose.
- Proposals land in `revision_debt` as `editorial.sociogram_suggestion` entries.
- Human accepts via CLI or UI; accepted entries become scene-card declarations in a patch commit.
- **No automatic trust pathway.** Suggestions never enter the sociogram directly.

### 9.5 Packet integration

`ChapterPacket.relationship_context` is populated from the sociogram when flag on:

- For each character pair in the scene's `characters_present`, include the current edge state.
- Tail: count of edges not shown (to prevent dilution).

Rendered as:

```markdown
**Relationship context (current state as of ch04_sc02)**
- Hunter / Jora: trust -0.3 (falling), warmth -0.1, power_balance +0.2 (H dominant)
- Hunter / Leia: trust +0.6 (rising), warmth +0.5, power_balance 0.0
```

### 9.6 Slice 5 go/no-go checklist

- [ ] `schemas/sociogram_edge.json` and `schemas/scene_card.json` additions land.
- [ ] `src/memory/sociogram.py` implemented.
- [ ] Planning-time initialization from `ensemble_cast.relationships` works.
- [ ] Scene-card declaration pathway tested.
- [ ] Suggestion mode, if shipped, routes through revision_debt and never auto-trusts.
- [ ] `runtime.sociogram.enabled: false` default.
- [ ] Packet integration tested; dilution cap enforced.
- [ ] At least one non-Ruusan/Betrayal book has the feature flipped on and produces relationally-grounded prose without relationship drift.

---

## 10. Slice 6 — Manuscript lifecycle design

**Goal:** A written design doc for manuscript-level review (developmental / line / copy / proof) that does not collapse into scene-level drafting.

**This slice's deliverable is documentation, not code.**

**Prerequisite:** Slices 1–5 shipped, scene-level system stable, at least one book completed end-to-end with all flags on.

### 10.1 Scope

Deliverable: `docs/architecture/manuscript_lifecycle_design.md`. Must cover:

1. **Developmental pass** — structural/thematic review, act-level pacing, arc completion. Inputs: full manuscript + planning artifacts. Output: developmental report + patch set for scene-card revisions (not prose edits).
2. **Line pass** — sentence-level rhythm/voice on full manuscript. Must respect the forward-only invariant: line-pass edits are patches that go through `patch_workflow.py` (see `§10.2`), not in-place prose mutations during a drafting run.
3. **Copy pass** — grammar/punctuation/consistency. Same patch-based flow.
4. **Proof pass** — final typography, formatting. Same.
5. **Optional streams** — beta reader synthesis, fandom authenticity review, sensitivity review. Each is its own advisory pass.
6. **Patch routing** — how accepted manuscript-level patches flow back into per-scene files without violating the forward-only runtime.

### 10.2 Required policy: patch workflow (enables back-fill from gap resolution)

Slice 1 established gap notes. Slice 6 must define how a human accepts an isolated scene or a manuscript-level suggested revision without breaking the runtime.

Specify:

1. New CLI: `py -3 scripts/patch_workflow.py`.
2. Subcommands:
   - `accept-isolated <scene_id>` — promotes isolated scene to trusted; triggers replay (`§10.3`).
   - `replace <scene_id> --from <path>` — replaces saved prose with human-edited version; triggers replay.
   - `overrule <gap_id>` — marks gap resolved without changing prose; records rationale.
   - `apply-manuscript-patch <patch_path>` — applies a manuscript-level patch (JSON describing edits per scene); triggers replay for affected scenes.

### 10.3 Replay semantics

When `patch_workflow.py` changes a saved scene:

1. Run continuity extractor (if Slice 4 enabled) against the new prose.
2. Replay promise-ledger declarations from scene card.
3. Replay sociogram deltas.
4. Walk downstream chapters: for every chapter that contains scenes in `gap.affected_scenes` (Slice 1 gap records), **mark their overlays as stale**.
5. On next drafting run, stale overlays rebuild before use.
6. **Already-drafted downstream scenes are not regenerated.** They stay on disk. The next chapter-close memo flags them for human review with an "affected by ch04_sc07 resolution" note.

This is the bridge between forward-only runtime (Slices 1–5) and a coherent manuscript (Slice 6).

### 10.4 Non-goal

Do not implement the manuscript passes in Slice 6. The deliverable is design. Implementation is a post-spec decision.

### 10.5 Slice 6 go/no-go checklist

- [ ] `docs/architecture/manuscript_lifecycle_design.md` landed.
- [ ] Patch workflow CLI specified (not necessarily implemented in Slice 6 — that can split into Slice 6a implementation).
- [ ] Replay semantics defined.
- [ ] Review has validated that manuscript-level passes do not violate forward-only runtime.
- [ ] Sign-off from user.

---

## 11. Cross-cutting workstreams

### 11.1 CanonExpert relocation + local_fixes (feature-flagged)

This is the cross-cutting change with the most direct risk to current Ruusan output. Ship with maximum caution.

#### 11.1.1 Current behavior

- CanonExpert runs late (post-polish).
- When verdict = `fail` at critical/moderate, it triggers a save-blocker.
- `corrected_prose` field is emitted but currently used to regenerate via `QualityPolish` as a HARD CONSTRAINT (per the grounded audit in `§2`).

#### 11.1.2 Target behavior

- CanonExpert runs earlier (before `QualityPolish`), when `runtime.canon_expert.early_position: true`.
- When CanonExpert emits `local_fixes` AND `runtime.canon_expert.apply_local_fixes: true` AND the fix category is in `runtime.canon_expert.local_fixes_whitelist`, `QualityPolish` applies the substitution before its own polish pass.
- A **second, cheaper CanonExpert pass** runs after polish to catch drift reintroduced by the polish temperature. This second pass stays advisory-only (no blocker re-raise).

#### 11.1.3 Whitelist of allowed local_fix categories

Initial whitelist (config default empty):

```yaml
runtime:
  canon_expert:
    local_fixes_whitelist:
      - terminology_registry_swap   # only exact matches from franchise terminology registry
      - rank_title_normalization    # "Jedi Master" vs "Master Jedi" normalized to franchise-canonical form
      - era_label_normalization     # "Clone Wars era" vs "Clone War" normalized
      - style_guide_mapping         # exact mappings from style guide (single value → single value)
```

Anything outside the whitelist stays advisory (written to revision_debt as `canon` entry) even when `apply_local_fixes: true`.

Rejected local_fixes emit `canon_fix_rejected` debt entries (per the write-matrix in `§6.2.1`).

#### 11.1.4 Per-book flag defaults

`config/settings.yaml`:
```yaml
runtime:
  canon_expert:
    early_position: false         # global default
    apply_local_fixes: false      # global default
    local_fixes_whitelist: []     # global default — empty means zero fixes applied
```

For Ruusan (critical Legends-EU canon density), keep all three at global defaults. Do **not** author a `runtime_overrides.yaml` that enables any of them until:
1. A full chapter is audited with `early_position: true` on a lower-stakes book.
2. Whitelist is iterated based on actual proposed local_fixes.
3. User manually reviews and approves each whitelist category.

#### 11.1.5 Second CanonExpert pass

When `early_position: true`, QualityPolish's output feeds into a second CanonExpert invocation. This pass:
- Reuses the same agent with the same settings.
- Emits only advisories (never raises blockers, regardless of severity).
- Writes `editorial.canon_polish_drift` to revision debt if it finds canon drift reintroduced by polish.

This closes the "polish reintroduces drift on fixed text" hole from the original critique.

#### 11.1.6 Tests

- `tests/test_canon_expert_positioning.py` — with flag off, CanonExpert still runs in late position; with flag on, it runs early + a second late pass fires.
- `tests/test_canon_local_fixes_whitelist.py` — proposed fixes outside whitelist are rejected and debt entry emitted.
- `tests/test_canon_polish_drift_detection.py` — synthetic case where polish reintroduces canon drift; second pass catches it.

#### 11.1.7 Ruusan-specific rollout

1. Author a `test-bench/` franchise + book with fabricated but canon-like content.
2. Enable `early_position: true` and `apply_local_fixes: true` with a minimal whitelist there.
3. Hand-audit a chapter's worth of scenes: proposed local_fixes, rejected fixes, polish-drift events.
4. Iterate whitelist until audit surfaces no wrong-direction substitutions.
5. **Still do not** enable on Ruusan/Betrayal. Before considering those, user approves each whitelist category in writing (in the book's `runtime_overrides.yaml` or an adjacent `canon_fix_audit.md`).

### 11.2 Polish benchmark harness extension (Patch 7)

#### 11.2.1 Extend `scripts/bench_prose_models.py`

Add a new mode `--polish-only`:

```
py -3 scripts/bench_prose_models.py \
  --polish-only \
  --fixed-draft output/.../runs/<prior>/chapters/chapter_01_scene_01.md \
  --scene-card data/.../scene_cards/chapter_01_scene_01.json \
  --concept-seed data/.../concept_seed.json \
  --polish-configs config/bench_polish_configs.yaml \
  --run-label polish-ab-$(date +%F)
```

In this mode:
- Skip `PlotArchitect` and `ProseStylist`.
- Load fixed draft from `--fixed-draft`.
- Run N polish configurations (each with its own model/temperature/instructions).
- Record per-configuration: word-count retention ratio, voice-drift indicator (simple Jaccard of salient n-grams), canon-term preservation count, repetition delta, reviewer categorical verdict (advisory).
- Output: `output/<franchise>/<book>/runs/bench-polish-<date>/polish_ab.md`.

#### 11.2.2 "Benchmarked policy" gate

Until the following artifacts exist at `output/bench-polish/`:
- At least 3 polish configurations benched on ≥ 5 accepted scenes from a non-bench run.
- A written decision rule in `docs/architecture/polish_routing_decision.md` describing when to choose same-family vs cross-family polish based on scene characteristics.

...the language "benchmarked polish policy" is prohibited. The default in `config/settings.yaml` stays `quality_polish` on `gpt54_mini` (same family as `line_writer` on `gpt54`), which is doctrinal (matching the drafter's family), not benchmarked.

### 11.3 Fanfic mode policy matrix

Canonicalize at `config/fanfic_modes.yaml`:

```yaml
modes:
  strict_canon:
    description: "Canonical ingestion. AU divergence is a violation."
    retrieval:
      policy: canon_first
      suppress_divergent_au: true
    continuity_strictness: highest
    blocker_routing:
      cross_continuity: blocker  # fail-severity treated as blocker
      anachronism: blocker
      post_divergence_drift: blocker
      franchise_voice: advisory

  branch_point_au:
    description: "AU that diverges at a defined branch point. Pre-branch canon is strict; post-branch is flexible."
    retrieval:
      policy: branch_aware
      prioritize_after_branch: true
      suppress_divergent_au: false
    continuity_strictness: mixed
    blocker_routing:
      cross_continuity: blocker_if_pre_branch_else_advisory
      anachronism: blocker_if_pre_branch_else_advisory
      post_divergence_drift: advisory
      franchise_voice: advisory

  canon_inspired_voice:
    description: "Uses franchise style and terminology; does not require strict factual canon."
    retrieval:
      policy: style_first
    continuity_strictness: lower
    blocker_routing:
      cross_continuity: advisory
      anachronism: advisory
      post_divergence_drift: advisory
      franchise_voice: blocker  # voice drift is the only blocker
```

Mode selection per book:
- `concept_seed.meta.fanfic_mode: strict_canon | branch_point_au | canon_inspired_voice` (new optional field).
- Default: `strict_canon` (matches current behavior).

`src/agents/canon_expert.py` consults `fanfic_mode` when computing verdict severity. Matrix is the single source of truth — no hardcoded mode logic elsewhere.

Tests: `tests/test_fanfic_modes.py` — each mode applied, blocker routing matches matrix for each violation category.

### 11.4 Ledger event-type additions

Add to `src/run_ledger.py`:

| Event type | Level | When | Payload |
|---|---|---|---|
| `scene_isolated` | error | State firewall isolates a scene | `{scene_id, blocker_categories, gap_id}` |
| `gap_note_recorded` | warn | Gap note written to SQLite | `{gap_id, isolated_scene, affected_scenes}` |
| `gap_note_resolved` | info | Gap resolved via patch_workflow | `{gap_id, resolved_by, scene_id}` |
| `packet_base_compiled` | info | Chapter packet base built | `{chapter_number, token_count}` |
| `packet_overlay_written` | info | Per-scene overlay built | `{chapter_number, scene_number, overlay_version, token_count}` |
| `packet_fallback_flat` | warn | Packet compilation failed; fell back to flat assembly | `{chapter_number, scene_number, error}` |
| `revision_debt_added` | info | New debt row | `{debt_id, category, severity, scope}` |
| `revision_debt_updated` | info | Debt status changed | `{debt_id, old_status, new_status}` |
| `promise_planted` | info | Promise ledger entry created | `{promise_id, setup_scene}` |
| `promise_progressed` | info | Progression recorded | `{promise_id, scene_id, source}` |
| `promise_paid` | info | Payoff recorded | `{promise_id, scene_id}` |
| `promise_overdue` | warn | Detected at overlay-compile time | `{promise_id, due_by_scene, current_scene}` |
| `continuity_event_recorded` | info | Trusted event appended | `{event_id, event_type, confidence}` |
| `continuity_events_suppressed` | warn | Sub-threshold events dropped | `{count, scene_id}` |
| `sociogram_delta_applied` | info | Edge updated | `{edge_id, source}` |
| `sociogram_suggestion_recorded` | info | Suggested delta in debt | `{suggestion_id, edge_id}` |
| `canon_early_pass_fired` | info | Early-position pass (Slice 11.1) | `{scene_id, violations_count}` |
| `canon_polish_drift_detected` | warn | Second pass found reintroduced drift | `{scene_id, drift_count}` |
| `canon_fix_applied` | info | Whitelisted local_fix applied | `{scene_id, category, from_text, to_text}` |
| `canon_fix_rejected` | warn | Fix outside whitelist | `{scene_id, category, reason}` |
| `phase0_audit_emitted` | info | Audit complete | `{overall_pass, n_pass, n_fail}` |

### 11.5 Migration playbook

Every new durable state artifact gets a migration. All migrations are idempotent and can re-run safely.

| Slice | Migration script | Creates |
|---|---|---|
| 1 | `scripts/migrations/migrate_gap_notes.py` | `gap_notes` table in `story_state.db` |
| 2 | `scripts/migrations/migrate_revision_debt.py` | `revision_debt.db` |
| 3 | `scripts/migrations/migrate_promise_ledger.py` | `promise_ledger.db`, seeded from planning |
| 4 | `scripts/migrations/migrate_continuity_log.py` | `continuity_log.db` (empty until extractor runs) |
| 5 | `scripts/migrations/migrate_sociogram.py` | `sociogram.db`, seeded from `ensemble_cast.relationships` |

All migrations invoked via a wrapper: `py -3 scripts/migrations/migrate_all.py --base-dir .`. Each migration reports `{tables_added, rows_migrated, errors}` and the wrapper fails fast on any error.

### 11.6 Test strategy

#### 11.6.1 Unit tests per slice

As specified in each slice's go/no-go checklist.

#### 11.6.2 Schema validation tests

Every new schema lives at `schemas/`. Add `tests/test_schemas.py` cases that:
- Validate known-good examples.
- Validate known-bad examples fail for the expected reasons.

#### 11.6.3 Ruusan/Betrayal parity tests

This is the single most important test category for protecting current output.

New file: `tests/test_pipeline_regression_ruusan.py`.

```python
def test_ch01_flag_off_parity():
    """With all runtime.* flags at default (false), Ruusan ch01 sc01
    should produce byte-identical prose to the pre-Slice-1 baseline.
    Baseline is committed at tests/baselines/ruusan_ch01_sc01.md."""
    ...

def test_ch01_no_packet_no_firewall_no_early_canon():
    """Same but per-flag: assert each flag individually false
    produces the baseline. Protects against implicit default drift."""
    ...
```

Same for Betrayal: `tests/test_pipeline_regression_betrayal.py`.

**Baseline discipline:** before starting any slice, snapshot current Ruusan and Betrayal ch01 sc01 outputs. Commit under `tests/baselines/`. Each slice's parity test runs against these frozen baselines.

If a slice's code changes do cause a flag-off prose delta — even though flags are supposedly isolating the new code — that delta is a bug. Fix before shipping the slice.

#### 11.6.4 Bench parity (manual but required)

Before flipping any flag on for Ruusan or Betrayal:

1. Run that book's ch01 sc01 through `bench_prose_models.py` with flag off.
2. Run again with flag on.
3. Human reads both outputs side-by-side.
4. If subjective prose quality on the "flag on" side is not at least equal to "flag off," block the flag flip. Iterate the implementation. Don't accept soft regressions on the two books we care most about.

This is a judgment call — intentionally so. Automated gates protect against hard breakage; bench parity protects against quality loss the metrics can't see.

---

## 12. Appendices

### A. New schema files

| File | Slice | Purpose |
|---|---|---|
| `schemas/phase0_audit.json` | 1 | Machine-readable Phase 0 audit gate |
| `schemas/chapter_packet.json` | 2 | Chapter packet shape (base + overlay) |
| `schemas/revision_debt.json` | 2 | Revision debt entry |
| `schemas/chapter_memo.json` | 2 | Chapter-close + milestone memo shapes |
| `schemas/promise_ledger_entry.json` | 3 | Promise ledger row |
| `schemas/continuity_event.json` | 4 | Continuity event with `oneOf` discriminator |
| `schemas/sociogram_edge.json` | 5 | Sociogram edge |

Scene card schema (`schemas/scene_card.json`) gets three new optional fields across slices:
- `depends_on` (Slice 1).
- `promises_progressed` (Slice 3).
- `relationship_deltas` (Slice 5).

### B. New configuration keys

All under the `runtime` top-level key in `config/settings.yaml`. The block below is the slice-introduction shape (every flag default-safe). For current shipping defaults, see §4.2 and `config/settings.yaml` directly — `runtime.chapter_packet.enabled` has since been promoted to `true`.

```yaml
runtime:
  phase0_audit:
    enabled: false
  firewall:
    enabled: false
    successor_classifier:
      enabled: false
      jaccard_threshold: 0.5
      adjacency_max_for_continue: 1
  chapter_packet:
    enabled: false
    fallback_on_error: true
  revision_debt:
    enabled: false
  canon_expert:
    early_position: false
    apply_local_fixes: false
    local_fixes_whitelist: []
  promise_ledger:
    enabled: false
  continuity_log:
    enabled: false
    min_confidence: 0.85
  sociogram:
    enabled: false
    suggest_mode: false
```

Plus new structured config files:
- `config/fanfic_modes.yaml` (Slice 11.3).
- `config/quality_thresholds.yaml` (referenced by write-matrix in Slice 2; may exist already — verify and extend).
- `config/bench_polish_configs.yaml` (Slice 11.2).

### C. File/directory layout deltas

New runtime artifacts under `output/<franchise>/<book>/`:

```
output/<franchise>/<book>/
├── runs/
│   └── <run_id>/
│       ├── phase0_audit.json                    [Slice 1]
│       ├── phase0_debug/                        [Slice 1]
│       ├── chapter_packets/                     [Slice 2]
│       │   ├── chapter_01.json
│       │   ├── chapter_01_sc_01_overlay.json
│       │   ├── chapter_01_sc_02_overlay.json
│       │   └── ...
│       ├── packet_budget_report.md              [Slice 2]
│       └── memos/                               [Slice 2]
│           ├── chapter_01_close.md
│           └── milestone_through_ch10.md
├── state/
│   ├── story_state.db                    (existing; +gap_notes table, Slice 1)
│   ├── revision_debt.db                         [Slice 2]
│   ├── promise_ledger.db                        [Slice 3]
│   ├── continuity_log.db                        [Slice 4]
│   └── sociogram.db                             [Slice 5]
└── quarantine/                          (existing; +gap_manifest.json per isolated scene, Slice 1)
```

New doc/audit locations:

```
docs/
├── architecture/
│   ├── architecture_upgrade_spec.md     [this file]
│   ├── manuscript_lifecycle_design.md           [Slice 6]
│   └── polish_routing_decision.md               [Slice 11.2]
└── audits/                                      [Slice 1]
    ├── phase0_2026-04-<nn>_ruusan-atonement.md
    └── phase0_2026-04-<nn>_legacy-of-the-force-betrayal.md
```

Existing `tests/` additions:

```
tests/
├── baselines/
│   ├── ruusan_ch01_sc01.md                      [Slice 1 preflight]
│   └── betrayal_ch01_sc01.md                    [Slice 1 preflight]
├── data/
│   ├── successor_classifier_labels.json         [Slice 1]
│   └── continuity_eval_set.json                 [Slice 4]
├── test_state_firewall.py                       [Slice 1]
├── test_successor_classifier.py                 [Slice 1]
├── test_chapter_packet.py                       [Slice 2]
├── test_packet_parity.py                        [Slice 2]
├── test_revision_debt.py                        [Slice 2]
├── test_chapter_memos.py                        [Slice 2]
├── test_packet_gap_note_propagation.py          [Slice 2]
├── test_promise_ledger.py                       [Slice 3]
├── test_continuity_extractor.py                 [Slice 4]
├── test_sociogram.py                            [Slice 5]
├── test_canon_expert_positioning.py             [Slice 11.1]
├── test_canon_local_fixes_whitelist.py          [Slice 11.1]
├── test_canon_polish_drift_detection.py         [Slice 11.1]
├── test_fanfic_modes.py                         [Slice 11.3]
├── test_pipeline_regression_ruusan.py           [Slice 1 preflight]
├── test_pipeline_regression_betrayal.py         [Slice 1 preflight]
└── test_schemas.py                              [incremental per slice]
```

### D. Ledger event inventory

(Consolidated from `§11.4`. This is the canonical list for Slices 1–5 + cross-cutting. Additional events can be added as needed; update this table in each PR.)

### E. Rollback procedures

Every slice has a rollback path that does not lose data.

#### E.1 Feature-flag rollback

The primary rollback is flipping the relevant `runtime.*` flag to `false`. This works for every slice because all new code is gated.

- `runtime.firewall.enabled: false` → system reverts to run-abort on blocker (current behavior). Gaps already recorded in SQLite remain; they're just not consulted.
- `runtime.chapter_packet.enabled: false` → drafter receives `assembled_context` (flat) again. Packets on disk remain as artifacts.
- `runtime.revision_debt.enabled: false` → producer wrappers noop to ledger only. Debt DB remains.
- `runtime.canon_expert.early_position: false` → CanonExpert runs late again. Second pass doesn't fire.
- `runtime.canon_expert.apply_local_fixes: false` → fixes stay advisory.
- `runtime.promise_ledger.enabled: false` → packet's `active_promises` is empty. Ledger DB remains.
- `runtime.continuity_log.enabled: false` → extractor doesn't run. Log DB remains.
- `runtime.sociogram.enabled: false` → packet's `relationship_context` is empty. DB remains.

#### E.2 Schema rollback

Scene-card schema additions (`depends_on`, `promises_progressed`, `relationship_deltas`) are all optional. Rolling back the schema change does not break scene cards that included the new fields — the fields are simply unused.

#### E.3 Migration rollback

Migrations are additive (CREATE IF NOT EXISTS) and never drop tables. To "rollback" a migration, the application code stops reading from the new tables (via feature flag). The tables can be left in place without harm. For hard removal (not recommended), a manual `DROP TABLE` against the SQLite file is safe because each new feature has its own DB file, separate from `story_state.db`.

#### E.4 Pipeline code rollback

If a slice's code has a subtle bug that breaks prose even with its flag off (should never happen, but the parity tests in `§11.6.3` exist to detect exactly this), the rollback is:

1. Revert the merge commit for the offending slice.
2. Re-run the parity test to confirm baseline restored.
3. Keep the schemas and migrations; they're non-breaking.
4. Investigate the flag-gating defect before re-attempting the slice.

#### E.5 Per-book opt-out

The `runtime_overrides.yaml` mechanism means a book that starts producing worse output after a slice ships can be put back on the old path without global impact:

```yaml
# data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/runtime_overrides.yaml
runtime:
  chapter_packet:
    enabled: false   # force-disable for this book, regardless of any higher-level flip
  firewall:
    enabled: false
  canon_expert:
    early_position: false
```

This is the escape valve that keeps Ruusan's current prose quality safe while new books explore new architecture.

---

## 13. One-line summary

Ship the architecture upgrade as six gated slices, each feature-flagged, each preceded by a parity test against Ruusan and Betrayal, with stateful-memory systems (promise ledger, continuity log, sociogram) arriving one at a time with their own evaluation harnesses — and keep the current prose path available as a fallback until every new system has earned its way onto each book individually.
