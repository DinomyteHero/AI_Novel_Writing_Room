# Forward Relay v4 — Use the Advice, Diversify the Judges

**Status:** proposed & implementing (this branch)
**Author:** Louis Bouwer + AI collaborators
**Date:** 2026-04-21

## TL;DR

The current pipeline generates a lot of editorial advice and then ignores it. Three writing agents (Claude Sonnet drafter → GPT-5.4 line editor → GPT-5.4-mini polisher) touch every scene before save, while `failure_context` plumbing sits wired-but-unused in `ProseStylist` and `Orchestrator._format_failure_context`. Three judges (GateCritic, FinalGate, PresenceChecker) all check character presence despite PresenceChecker being the only one that can block. All three judges run on Haiku while the drafter is Sonnet — same-family homogeneity.

Forward Relay v4 fixes the advice-ignored problem first, diversifies the judges second, and only then touches the drafter model. Six changes, three shipping in this PR chain as default-on, two behind new runtime flags (default-off on Ruusan/Betrayal), one deferred to a follow-up bench.

## The forward-only tension

CLAUDE.md is explicit: *"The relay is forward-only — do not re-introduce retries."* A corrective rerun is, technically, a retry branch. We reconcile this by:

1. **Bounded to exactly one attempt.** Not a loop, not a counter that could climb. `max_structural_retries` / `max_voice_retries` stay pinned at 0 for the legacy path.
2. **Behind a runtime flag.** `runtime.corrective_rerun.enabled: false` is the default; shipping-book guards protect Ruusan + Betrayal until per-book parity tests land.
3. **Narrow trigger rules.** Only `MISSING_TURNING_POINT` or `CLOSING_HOOK_VIOLATION` from GateCritic — both hard contract misses, both easy for the drafter to act on with structured `failure_context`.
4. **Confusion-aware skip.** If the first draft emitted >3 failure codes OR came in under 50% of target word count, we do NOT rerun — those signal drafter confusion, not recoverable error.
5. **Single-shot.** After the rerun, downstream runs (gate, polish, final gate, canon) proceed normally. No "rerun of a rerun."

This is a bounded, legible, default-off escape hatch — not the old retry loop.

## Six changes

### 1. Disable LineWriter by default (ships default-on)

LineWriter (`openai/gpt-5.4` @ t=0.8) currently runs between the drafter and GateCritic in live runs (per `src/main.py:916` — conditional on `config.agent_routing.line_writer` being present). With a corrective rerun available for structural misses and QualityPolish still handling voice/expression, the line-edit pass is the duplicated cost center Codex called correctly.

**Change:** comment out the `line_writer:` entry under `agent_routing` in `config/settings.yaml`. `main.py` already guards with `if config.get("agent_routing", {}).get("line_writer")`, so the orchestrator receives `line_writer=None` and the path at `src/orchestrator.py:680` becomes a no-op. Bench configs that want to re-enable LineWriter can set it explicitly in their own overlay YAML.

Expected savings: ~$0.04–0.08/scene (GPT-5.4 at t=0.8, ~12k output tokens per scene).

### 2. Collapse the presence triple-check (ships default-on)

Today: GateCritic, FinalGate, AND PresenceChecker all emit on `CHARACTER_PRESENCE_VIOLATION`. Only PresenceChecker is the actual save-blocker. The gates are pure redundancy for this specific check.

**Change:**
- Remove `CHARACTER_PRESENCE_VIOLATION` from `GateCritic.STRUCTURAL_CODES` and from GateCritic's prompt check list.
- Remove `CHARACTER_PRESENCE_VIOLATION` from `FinalGate.FINAL_GATE_CODES` and from FinalGate's prompt.
- PresenceChecker remains sole authority — no change there.

Turning-point and closing-hook stay in both gates. Codex's nuance: GateCritic sees pre-polish, FinalGate sees post-polish, so the duplicate is regression protection against polish-induced drift, not pure duplication.

### 3. Move GateCritic off Haiku (ships default-on)

Three Anthropic judges (GateCritic, FinalGate, PresenceChecker) rating a Claude Sonnet draft creates same-family bias. Codex's sequencing argument: GateCritic is the advice source for the rerun (change 4), so its family bias has the most leverage. FinalGate is narrower / more contract-like — same-family matters less there.

**Change:** swap GateCritic's routing from `haiku` to `grok41fast` in `config/settings.yaml`. Grok 4.1 Fast is already in the stack (used for `orchestrator` role) and is documented as a decision-making model. Keep FinalGate and PresenceChecker on Haiku.

#### Alternatives considered (for future benching)

Initial pick is Grok 4.1 Fast because it is the lowest-friction change: already in our OpenRouter aliases, proven on the `orchestrator` role, cheap, and truly cross-family from both Anthropic (drafter) and OpenAI (polish). But there are better-diversity candidates worth benching:

| Candidate | OpenRouter ID | Family | Notes |
|-----------|---------------|--------|-------|
| **Gemini 3 Flash** | `google/gemini-3-flash-preview` | Google | Fast, cheap, excellent structured output. Already in stack as `gemini_flash`. |
| **Qwen 3.6 Plus** | `qwen/qwen3.6-plus` | Alibaba | Genuinely different training. Strong instruction following. Cheapest of the shortlist. Already in stack as `qwen` but not currently judging anywhere. |
| **DeepSeek V3.2** | `deepseek/deepseek-v3.2` | DeepSeek | Already used for utility roles; extending it to gate is a small reach. |
| **Kimi K2.x** | `moonshotai/kimi-k2.5` (K2.6 if/when OpenRouter lists it) | Moonshot | Long-context specialist. CLAUDE.md already warns about long-scene risk for Kimi as a drafter — but that was for *writing*, not *judging*, so the gate role might still work well. |
| **MiniMax M2.7** | `minimax/minimax-m2.7` | MiniMax | Newer; unknown structured-JSON reliability in our stack. |
| **Mistral Small 2603** | `mistralai/mistral-small-2603` | Mistral | Cheap, European alternative. |

Recommended next benches after Grok lands: Gemini 3 Flash first (lowest risk), then Qwen 3.6 Plus (maximum family diversity from current stack). Qwen specifically is the candidate that would give us a non-US, non-European family in the judging stack — valuable for diversity if it produces reliable structured output.

If structured-JSON reliability regresses with Grok, fallback is `glm` (z-ai/glm-5.1) or Gemini 3 Flash.

### 4. Smart corrective rerun (ships flag-gated, default off)

Wire the latent `failure_context` infrastructure into a single corrective pass.

**Flag:** `runtime.corrective_rerun.enabled` (default `false`).

**Trigger rules (all must hold):**
- Flag is on for the book.
- `GateCritic.verdict == "fail_structural"`.
- `failure_codes` intersect `{MISSING_TURNING_POINT, CLOSING_HOOK_VIOLATION}` — the narrow trigger set.
- `len(failure_codes) <= 3` — skip if the drafter is confused (>3 structured misses means the brief isn't landing and a rerun won't help).
- `len(prose.split()) >= 0.5 * scene_card.target_word_count` — skip if the draft collapsed (different failure mode; rerun won't help).
- Scene has not already been rerun this chapter.

**Flow when triggered:**
1. Emit `corrective_rerun_fired` info event with `trigger_codes`.
2. Format the GateCritic evaluation via `_format_failure_context(evaluation)` (already exists).
3. Call `_run_prose_stylist(scene_card, generation_brief, failure_context=...)`.
4. Replace `prose` with the rerun output; downstream stages (quality metrics, polish, final gate, canon, save-blockers) proceed as normal.
5. Emit `corrective_rerun_complete` with before/after word counts.

**Not triggered by:** FinalGate verdict (post-polish, too expensive), voice failures (go to polish), polish failures (advisory), canon failures (handled by change 5).

### 5. Slice 11.1 — narrow canon repair (ships flag-gated, default off)

Instead of sending moderate canon findings through a full ProseStylist re-draft, apply whitelisted string-substitution fixes emitted by CanonExpert directly.

**Flags (already in `config/settings.yaml`):**
- `runtime.canon_expert.apply_local_fixes: false`
- `runtime.canon_expert.local_fixes_whitelist: []`

**Change:**
- `CanonExpert._normalize_output` emits a `local_fixes: [{category, pattern, replacement, reason}]` list when violations are in whitelisted categories. The model already identifies `suggestion` per violation — we just structure it for machine consumption.
- `Orchestrator._maybe_apply_canon_local_fixes` runs after CanonExpert in the existing late position, before the save-blocker check. When the flag is on AND the category is in the whitelist, it applies `prose.replace(pattern, replacement)` as a literal substitution. Regex is NOT supported — safety-first.
- Each applied fix emits `canon_local_fix_applied` (info) with `{category, pattern_preview, replacement_preview}`. Each fix also writes a debt row via `emit_canon_advisory`.
- Non-whitelist findings stay advisory (unchanged).

**Initial whitelist (empty in default config; flip per-book):**
- `anachronism` — term substitution from `canon_profile.anachronistic_terms`.
- `terminology_registry_swap` — swap to canonical form per `terminology_registry`.

### 6. Cheaper drafter bench (deferred; out of scope for this PR)

Only after changes 1–5 land and the rerun rate is measured. First candidate: `gpt54_mini`. Promote only if (a) word-count discipline survives on the climax bench and (b) rerun rate stays under ~20%. Otherwise cheap-draft + rerun converges on Sonnet cost.

## Sequencing

1. **Phase 1 (this PR, default-on):** line_writer off, presence collapse, GateCritic → Grok 4.1 Fast.
2. **Phase 2 (this PR, flag-gated):** corrective_rerun + Slice 11.1.
3. **Phase 3 (follow-up):** per-book flag-flip for test-bench; then parity tests for Ruusan + Betrayal.
4. **Phase 4 (follow-up):** drafter-swap bench once Phase 3 data is in.

## Rollback plan

Each change has an explicit rollback:

| Change | Rollback |
|--------|----------|
| LineWriter off | Uncomment `line_writer:` entry in `config/settings.yaml` |
| Presence collapse | Re-add `CHARACTER_PRESENCE_VIOLATION` to `GateCritic.STRUCTURAL_CODES` and `FinalGate.FINAL_GATE_CODES` + prompts |
| GateCritic model swap | Revert `gate_critic: {model: haiku}` in `config/settings.yaml` |
| Corrective rerun | `runtime.corrective_rerun.enabled: false` (already default) |
| Slice 11.1 | `runtime.canon_expert.apply_local_fixes: false` (already default) |

## Test plan

- **Unit:** GateCritic test drops `CHARACTER_PRESENCE_VIOLATION` from `STRUCTURAL_CODES`; FinalGate test drops it from `FINAL_GATE_CODES`. PresenceChecker tests unchanged.
- **Orchestrator:** new `test_corrective_rerun_fires_on_structural.py` — mocks GateCritic to return `fail_structural` with `MISSING_TURNING_POINT`, asserts `_run_prose_stylist` is called twice and the second call receives non-empty `failure_context`. Sibling tests assert the confusion-skip rules: 4+ codes → no rerun; <50% target WC → no rerun.
- **Slice 11.1:** `test_canon_local_fixes_applied.py` — stubs CanonExpert to return `local_fixes` with a category in the whitelist, asserts the prose has the substitution before save.
- **Runtime flags:** extend `tests/test_runtime_flags.py` with `test_shipping_books_keep_corrective_rerun_off` parametrized over Ruusan + Betrayal. Extend `test_shipping_defaults_all_safe` with the new key.
- **Full suite:** `pytest -q` must pass.

## What this does NOT change

- Save-blocker layer semantics (PresenceChecker + CanonExpert critical/moderate) remain the sole hard-failure path.
- FinalGate and compression guard stay advisory-only.
- `max_structural_retries` / `max_voice_retries` stay pinned at 0.
- Sonnet 4.6 remains the default drafter until change 6 lands.
