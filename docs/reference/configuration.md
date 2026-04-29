# Configuration

All configuration files are in the `config/` directory.

> **Current production note (2026-04-26):** `config/settings.yaml` now defaults to lean manuscript production. The live scene path is `PlotArchitect -> ProseStylist -> LineWriter -> save`, with `prose_stylist` on DeepSeek V4 Pro, `line_writer` on GPT-5.4 Mini, and `manuscript_reviewer` on GPT-5.4. Targeted cleanup is the default final polish branch; full literary polish is an opt-in donor/comparison branch.

## settings.yaml

The main configuration file. Controls deployment mode, model routing, and pipeline behavior.

### Deployment Mode

```yaml
deployment_mode: cloud  # local | cloud | hybrid
```

### Local Models

When `deployment_mode: local` (or `hybrid` with specific agents on the local backend), the router talks to a local `llama-server` instance via its OpenAI-compatible API. Populate `models.local.models` with your installed quantized checkpoints and point `base_url` at the server:

```yaml
models:
  local:
    inference_backend: llama-server
    base_url: http://localhost:8080/v1
    timeout_seconds: 300
    models: {}          # {short_alias: full_model_filename} — filled by the operator
    default_params: {}  # {short_alias: {temperature: ..., max_tokens: ...}}
```

The shipped cloud-mode `config/settings.yaml` leaves `models.local` empty; the local map is only populated on machines that run inference locally.

### Cloud Models

```yaml
models:
  cloud:
    provider: openrouter
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY    # Environment variable name
    timeout_seconds: 300
    models:
      # Short alias -> full OpenRouter slug
      gemini:         google/gemini-3.1-pro-preview
      deepseek:       deepseek/deepseek-v4-flash
      deepseekpro:    deepseek/deepseek-v4-pro
      claude:         anthropic/claude-sonnet-4.6
      grok420:        x-ai/grok-4.20
      grok41fast:     x-ai/grok-4.1-fast
      mistral_small4: mistralai/mistral-small-2603
      gpt54:          openai/gpt-5.4           # manuscript review, optional literary donor pass
      gpt54_mini:     openai/gpt-5.4-mini      # lean line edit, optional quality polish
    default_params:
      # Per-alias defaults (temperature, max_tokens) applied when an agent
      # routing entry does not override them.
      gemini:         { temperature: 0.6, max_tokens: 8192 }
      deepseek:       { temperature: 0.3, max_tokens: 4096 }
      deepseekpro:    { temperature: 0.3, max_tokens: 8192 }
      claude:         { temperature: 0.4, max_tokens: 8192 }
      grok420:        { temperature: 0.3, max_tokens: 8192 }
      grok41fast:     { temperature: 0.3, max_tokens: 8192 }
      mistral_small4: { temperature: 0.3, max_tokens: 4096 }
      gpt54:          { temperature: 0.8, max_tokens: 12000 }
      gpt54_mini:     { temperature: 0.5, max_tokens: 8192 }
      # ...
```

The shipped config keeps only aliases referenced by `agent_routing`. Bench-only aliases such as `qwen`, `minimax`, `haiku`, `glm`, `kimi`, and `gemini_flash` live in `config/bench/experimental-model-aliases.yaml` or in frozen bench snapshots.

### Timeout Settings

Both local and cloud model sections accept a `timeout_seconds` field controlling the HTTP client timeout for API calls:

```yaml
models:
  local:
    timeout_seconds: 300   # Default: 300 seconds
  cloud:
    timeout_seconds: 300   # Default: 300 seconds
```

Increase this value if you experience timeouts during large requests (e.g., scene card generation for novels with 25+ chapters). The cloud timeout was previously hardcoded at 120 seconds, which was insufficient for multi-scene outline generation.

### Agent Routing

Maps each agent role to a backend, model tier, and optional parameter overrides. The live production routing in `config/settings.yaml` uses a mixed-model strategy informed by the prose-model bench (see [Benchmarking](../development/benchmarking.md)):

```yaml
agent_routing:
  # PROSE — drafter + optional line-editor relay
  prose_stylist: { backend: cloud, model: deepseekpro, params: { temperature: 0.70, max_tokens: 8192 } }
  line_writer:   { backend: cloud, model: gpt54_mini, params: { temperature: 0.35, max_tokens: 8192 } }

  # GATES / EVAL
  gate_critic:          { backend: cloud, model: grok41fast, params: { temperature: 0.3 } }
  chapter_gate_critic:  { backend: cloud, model: grok41fast, params: { temperature: 0.3 } }
  final_gate:           { backend: cloud, model: grok41fast, params: { temperature: 0.2 } }
  presence_checker:     { backend: cloud, model: grok41fast, params: { temperature: 0.1, max_tokens: 1000 } }
  continuity_extractor: { backend: cloud, model: grok41fast, params: { temperature: 0.0, max_tokens: 2048 } }
  judge_evaluator:      { backend: cloud, model: grok420, params: { temperature: 0.2 } }
  manuscript_reviewer:  { backend: cloud, model: gpt54, params: { temperature: 0.3, max_tokens: 16000 } }

  # PLANNING — Gemini Pro for long-context one-off authoring;
  # DeepSeek V4 Flash for the per-scene plot_architect structured JSON pass.
  concept_workshop:              { backend: cloud, model: gemini, params: { temperature: 0.7, max_tokens: 8192 } }
  outline_planner:               { backend: cloud, model: gemini, params: { temperature: 0.5, max_tokens: 32768 } }
  seed_builder:                  { backend: cloud, model: gemini, params: { temperature: 0.3, max_tokens: 16384 } }
  plot_architect:                { backend: cloud, model: deepseek, params: { temperature: 0.4, max_tokens: 4096 } }
  chapter_blueprint_synthesizer: { backend: cloud, model: gemini, params: { temperature: 0.4, max_tokens: 8192 } }

  # POLISH — GPT 5.4-mini matches line_writer's family (gpt-5.4) for style consistency.
  # Skipped by default while lean_prose_only is enabled.
  quality_polish:      { backend: cloud, model: gpt54_mini, params: { temperature: 0.5, max_tokens: 8192 } }

  # EDITORIAL / REVISION / UTILITY
  editorial_consultant: { backend: cloud, model: claude,         params: { temperature: 0.4, max_tokens: 16384 } }
  voice_checker:        { backend: cloud, model: mistral_small4, params: { temperature: 0.3 } }
  stress_test:          { backend: cloud, model: deepseek,       params: { temperature: 0.5 } }
  orchestrator:         { backend: cloud, model: grok41fast }
  canon_expert:         { backend: cloud, model: grok420, params: { temperature: 0.2 } }
  summarizer:           { backend: cloud, model: deepseek, params: { temperature: 0.2 } }
  character_specialist: { backend: cloud, model: deepseek, params: { temperature: 0.3 } }
  lore_extractor:       { backend: cloud, model: deepseek, params: { temperature: 0.2, max_tokens: 8192 } }
  worldbuilding_coherence_reviewer: { backend: cloud, model: grok420, params: { temperature: 0.3 } }
```

**Deployment mode override**: When `deployment_mode` is `cloud`, the `backend` field on every agent routing entry is overridden — all agents use cloud models. When `local`, all use local. `hybrid` is the only mode that honours the per-agent `backend` field.

Current manuscript production uses `manuscript_reviewer` for the GPT-5.4 full-book docket. Targeted cleanup is the default final polish branch. `literary_polish` is available for an opt-in full-literary donor/comparison branch, but should not replace the targeted-cleanup master without manual review.

**There is no `craft_editor` role.** The 3-band revision pipeline was collapsed into a single `quality_polish` agent in the [pipeline redesign](../architecture/pipeline-redesign.md). Any `craft_editor` routing entry inherited from an older config is ignored.

### Prompt Caching

Anthropic prompt caching is enabled by default for supported providers:

```yaml
pipeline:
  prompt_caching:
    enabled: true
    anthropic_ttl: 1h  # "5m" (1.25x write cost) or "1h" (2x write, cheaper for sequential pipelines)
```

The 1h TTL is the right choice for chapter-level batches — the `anthropic` provider amortizes the Sonnet input cost across many scene-level calls within a run.

### Bench Configs

Frozen routing snapshots live under `config/bench/` for benchmarking:

- `config/bench/settings.bench.sonnet.yaml` — `prose_stylist` on Sonnet 4.6 @ t=0.70, `plot_architect` on Grok 4.20, `quality_polish` on Haiku 4.5.
- `config/bench/settings.bench.gpt.yaml` — same pipeline but `prose_stylist` on GPT 5.4 @ t=0.70, and registers `gpt54: openai/gpt-5.4` in the cloud models map.

Use `config/bench/experimental-model-aliases.yaml` as the alias reference when creating a new bench snapshot for a model that is not part of the shipping routing.

Run with `--config config/bench/settings.bench.sonnet.yaml` or `--config config/bench/settings.bench.gpt.yaml`. See [Benchmarking](../development/benchmarking.md) for the A/B methodology and the pre-built analyses in `output/…/runs/BENCH_*.md`.

### Pipeline Settings

```yaml
pipeline:
  # Relay refactor (Stage 1e): retries zeroed. Orchestrator is forward-only.
  # The keys are retained only as a rollback valve — do not raise without
  # re-introducing the gate-driven rewrite branches in orchestrator.py.
  max_structural_retries: 0
  max_voice_retries: 0
  max_http_retries: 2              # Max retries for failed HTTP requests (with jitter)
  embeddings:
    use_mock: true                 # When true, uses mock embeddings (deterministic, no model needed)
    model: nomic-ai/nomic-embed-text-v1.5
  prompt_caching:
    enabled: true
    anthropic_ttl: 1h              # "5m" (1.25x write) or "1h" (2x write, cheaper for sequential pipelines)
  # chapter_output_dir: defaults to output/<franchise>/<book>/runs/<run_id>/chapters/
  # run_ledger_path: auto-resolved at output/<franchise>/<book>/state/run_ledger.db
```

The embeddings block is nested under `pipeline` (not top-level). The shipped `config/settings.yaml` defaults `use_mock: true`; flip to `false` on machines that have `sentence-transformers` installed for real semantic similarity.

### Per-Run Config Snapshot

Each pipeline run saves a frozen copy of the active `settings.yaml` to `output/<franchise>/<book>/runs/<run_id>/config_snapshot.yaml`. This ensures that results are reproducible even if settings change between runs.

### Local Inference Settings

```yaml
local_inference:
  gpu_layers: 99
  expert_offload: CPU
  context_size: 32768
  batch_size: 512
  flash_attention: true
```

### Worldbuilding Settings

```yaml
worldbuilding:
  # Fallback defaults for ad-hoc invocations without a concept-seed context.
  # Live runs override these paths via ProjectPaths (franchise-scoped),
  # writing to data/franchises/<franchise>/worldbuilding.db and
  # data/franchises/<franchise>/worldbuilding_vectors/ instead.
  db_path: output/_fallback/worldbuilding.db
  vectors_dir: output/_fallback/worldbuilding_vectors
  default_top_k: 5                            # Default semantic retrieval limit
  walk_parents: true                          # Walk universe inheritance chain
  include_provisional_in_context: false       # Include provisional entries (flagged)
  auto_extraction:
    enabled: true                             # Run extraction after each chapter
    auto_promote: false                       # Skip quarantine on extracted entries
  terminology:
    always_include: true                      # Bypass top-K for terminology
  reconciliation:
    run_on_startup: true                      # Run SQLite/ChromaDB reconciliation at startup
    interval_minutes: 60                      # Periodic reconciliation (0 = disabled)
```

The fallback paths live under a gitignored `output/_fallback/` tree so they never collide with a real franchise-scoped worldbuilding DB.

### Runtime Flags (Architecture Upgrade)

Slice 1–5 of the architecture upgrade land behind feature flags that default to the safest value (off or most conservative numeric). Flags resolve through `src/runtime_flags.py` with this precedence:

1. `--runtime-flag key=value` (CLI override, may be repeated)
2. `data/franchises/<franchise>/books/<book>/runtime_overrides.yaml` (per-book)
3. `data/franchises/<franchise>/runtime_overrides.yaml` (per-franchise)
4. `config/settings.yaml` `runtime:` block (global default)

```yaml
runtime:
  lean_prose_only:
    enabled: true
    line_edit:
      enabled: true
  phase0_audit:
    enabled: false
  firewall:
    enabled: false
    successor_classifier:
      enabled: false
      jaccard_threshold: 0.5
      adjacency_max_for_continue: 1
  chapter_packet:
    enabled: true
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

Current production deliberately enables `lean_prose_only` and `chapter_packet` globally. Other architecture-upgrade surfaces remain disabled unless a book or run explicitly opts in. The full spec lives at [architecture_upgrade_spec.md](../architecture/architecture_upgrade_spec.md).

The `lore_extractor` agent routing is defined in `agent_routing` (see the Agent Routing section above).

---

## failure_codes.yaml

Defines the 19 failure codes used by GateCritic, organized into 3 categories:

### Structural (11 codes)

| Code | Description |
|------|-------------|
| CONTINUITY_CONTRADICTION | Scene contradicts established story state |
| WEAK_TURNING_POINT | Scene ends in roughly the same state it began |
| MISSING_TURNING_POINT | No identifiable shift in scene dynamics |
| UNEARNED_RESOLUTION | Conflict resolved without sufficient buildup or cost |
| STRUCTURAL_PHASE_VIOLATION | Scene actions violate Brooks phase constraints |
| PROMISE_BROKEN | Setup or foreshadow contradicted without intentional subversion |
| MOTIVATION_GAP | Character action lacks traceable motivation |
| CHARACTER_ARC_STALL | POV character has not progressed Weiland arc phase within expected structural window |
| HOOK_VIOLATION | Unauthorized hook planted, or required hook advancement missed |
| SUBPLOT_DRIFT | Active subplot ignored or resolved subplot reopened without justification |
| CANON_VIOLATION | Scene contradicts established franchise lore (promoted from Polish to Structural) |

### Voice (5 codes)

| Code | Description |
|------|-------------|
| OOC_DIALOGUE | Character speaks inconsistently with voice profile |
| OOC_ACTION | Character acts inconsistently with established dimensions |
| TELLING_NOT_SHOWING | Emotional state narrated rather than demonstrated |
| TERMINOLOGY_DRIFT | Term from registry spelled differently or used inconsistently |
| VOICE_DEFINITION_VIOLATION | Prose violates voice definition rules (anti-slop, anti-patterns) |

### Polish (3 codes)

| Code | Description |
|------|-------------|
| EXPOSITION_LEAK | World-building info dumped outside natural scene flow |
| PACING_FLATLINE | Insufficient sentence/event variety |
| PROSE_CLICHE_BURST | Multiple banned phrases or AI-tells detected |

### Routing

| Category | Action |
|----------|--------|
| fail_structural | advisory ledger signal. Only `runtime.corrective_rerun.enabled=true` can trigger one narrow ProseStylist redraft, and only for configured hard trigger codes. |
| fail_voice | advisory ledger signal; no targeted-revision retry branch in the current orchestrator. |
| fail_polish | advisory ledger signal. The Scene-Gate-passed draft passes through to QualityPolish + compression guard + FinalGate; compression below 60% reverts to the Gate-passed draft. |

> **Note**: GateCritic routing labels are telemetry in the current forward-only relay. `fail_polish` no longer routes to a CraftEditor, and the 3-band revision pipeline was collapsed into a single bounded `quality_polish` pass guarded by a compression check and the Final Gate. See [pipeline-redesign.md](../architecture/pipeline-redesign.md).

---

## negative_constraints.yaml

Defines banned phrases and structural rules for quality checking.

### Banned Phrases

5 categories:
- **faux_profundity** -- Overused portentous constructions
- **sensory_cliches** -- Stock physical descriptions
- **magic_adverbs** -- Lazy modifier patterns
- **ai_tells** -- Words that signal AI-generated text (e.g., "delve", "tapestry", "nuanced", "multifaceted")

### Structural Rules

| Rule | Default | Description |
|------|---------|-------------|
| max_adverb_density | 0.02 | Max ratio of adverbs to total words |
| min_sentence_length_variance | 0.3 | Minimum coefficient of variation in sentence length |
| max_same_opener_pct | 0.15 | Max percentage of paragraphs starting with the same pattern |
| metaphor_cooldown_paragraphs | 8 | Minimum paragraphs between figurative language uses |

---

## eval_rubric.yaml

Defines the 5 dimensions used by JudgeEvaluator (LLM-as-judge):

| Dimension | 1-3 | 4-6 | 7-8 | 9-10 |
|-----------|-----|-----|-----|------|
| narrative_engagement | flat | adequate | compelling | unputdownable |
| character_authenticity | cardboard | adequate | vivid | unforgettable |
| prose_craftsmanship | clumsy | adequate | polished | masterful |
| thematic_resonance | absent | present | resonant | profound |
| structural_contribution | filler | functional | essential | irreplaceable |
