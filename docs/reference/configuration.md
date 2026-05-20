# Configuration

All configuration files are in the `config/` directory.

> **Production note.** `config/settings.yaml` defaults to lean manuscript production. The live scene path is `PlotArchitect → ProseStylist → [LineWriter] → save`, with `prose_stylist` on DeepSeek V4 Pro, `line_writer` on GPT-5.4 Mini, and `manuscript_reviewer` on GPT-5.4 for post-production review. There is no save-time gate, quality-polish, or quarantine layer.

## settings.yaml

The main configuration file. Controls deployment mode, model routing, pipeline behavior, and runtime flags.

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
      gpt54_mini:     openai/gpt-5.4-mini      # lean line edit
    default_params:
      # Per-alias defaults (temperature, max_tokens) applied when an agent
      # routing entry does not override them.
      gemini:         { temperature: 0.6, max_tokens: 8192 }
      deepseekpro:    { temperature: 0.3, max_tokens: 8192 }
      gpt54_mini:     { temperature: 0.5, max_tokens: 8192 }
      # ...
```

The shipped config keeps only aliases referenced by `agent_routing`. Bench-only aliases such as `qwen`, `minimax`, `kimi`, `glm`, and `gemini_flash` live in `config/bench/experimental-model-aliases.yaml` or in frozen bench snapshots.

### Timeout Settings

Both local and cloud model sections accept a `timeout_seconds` field controlling the HTTP client timeout for API calls (default `300`). Increase it if large requests time out (e.g., scene-card generation for novels with 25+ chapters).

### Agent Routing

`agent_routing` maps each agent role to a backend, model tier, and optional parameter overrides. The shipped routing reflects the lean pipeline — the live scene path is `plot_architect → prose_stylist → line_writer`; everything else is a planning, post-save, or post-production role.

```yaml
agent_routing:
  # LIVE SCENE PIPELINE
  prose_stylist:   { backend: cloud, model: deepseekpro, params: { temperature: 0.70, max_tokens: 8192 } }
  line_writer:     { backend: cloud, model: gpt54_mini,  params: { temperature: 0.35, max_tokens: 8192 } }
  rhythm_editor:   { backend: cloud, model: deepseekpro, params: { temperature: 0.2,  max_tokens: 2400 } }

  # PLANNING / COMPILE-TIME UTILITIES
  plot_architect:                { backend: cloud, model: deepseek, params: { temperature: 0.4, max_tokens: 4096 } }
  outline_planner:               { backend: cloud, model: gemini,   params: { temperature: 0.5, max_tokens: 32768 } }
  seed_builder:                  { backend: cloud, model: gemini,   params: { temperature: 0.3, max_tokens: 16384 } }
  chapter_blueprint_synthesizer: { backend: cloud, model: gemini,   params: { temperature: 0.4, max_tokens: 8192 } }
  canon_scout:                   { backend: cloud, model: grok41fast, params: { temperature: 0.1, max_tokens: 1800 } }
  editorial_consultant:          { backend: cloud, model: claude,   params: { temperature: 0.4, max_tokens: 16384 } }

  # POST-SAVE MEMORY / POST-PRODUCTION
  summarizer:          { backend: cloud, model: deepseek, params: { temperature: 0.2 } }
  lore_extractor:      { backend: cloud, model: deepseek, params: { temperature: 0.2, max_tokens: 8192 } }
  manuscript_reviewer: { backend: cloud, model: gpt54,    params: { temperature: 0.3, max_tokens: 16000 } }
  literary_polish:     { backend: cloud, model: gpt54,    params: { temperature: 0.45, max_tokens: 12000 } }
```

**Deployment mode override**: When `deployment_mode` is `cloud`, the `backend` field on every routing entry is overridden — all agents use cloud models. When `local`, all use local. `hybrid` is the only mode that honours the per-agent `backend` field.

The `rhythm_editor` agent only runs when `runtime.rhythm_editor.enabled` is true; its routing entry must exist for the agent to load. The gate / polish / canon-expert / presence-checker routing entries that earlier configs carried were removed in the 2026-05-19 lean teardown — those agents no longer exist.

### Prompt Caching

```yaml
pipeline:
  prompt_caching:
    enabled: true
    anthropic_ttl: 1h  # "5m" (1.25x write cost) or "1h" (2x write, cheaper for sequential pipelines)
```

The 1h TTL is the right choice for chapter-level batches — the input cost amortizes across many scene-level calls within a run.

### Pipeline Settings

```yaml
pipeline:
  max_http_retries: 2              # Max retries for failed HTTP requests (with jitter)
  embeddings:
    use_mock: true                 # When true, uses mock embeddings (deterministic, no model needed)
    model: nomic-ai/nomic-embed-text-v1.5
  prompt_caching:
    enabled: true
    anthropic_ttl: 1h
  # chapter_output_dir: defaults to output/<franchise>/<book>/runs/<run_id>/chapters/
```

The embeddings block is nested under `pipeline`. The shipped config defaults `use_mock: true`; flip to `false` on machines that have `sentence-transformers` installed for real semantic similarity. `max_http_retries` controls HTTP-level retries on a failed API call — it is not a pipeline retry loop; the lean pipeline never re-drafts a scene.

### Per-Run Config Snapshot

Each pipeline run saves a frozen copy of the active `settings.yaml` to `output/<franchise>/<book>/runs/<run_id>/config_snapshot.yaml`, so results stay reproducible even if settings change between runs.

### Worldbuilding Settings

```yaml
worldbuilding:
  # Storage paths resolve via ProjectPaths from the loaded concept seed:
  #   data/franchises/<franchise>/worldbuilding.db
  #   data/franchises/<franchise>/worldbuilding_vectors/
  default_top_k: 5                            # Default semantic retrieval limit
  walk_parents: true                          # Walk universe inheritance chain
  include_provisional_in_context: false       # Include provisional entries (flagged)
  auto_extraction:
    enabled: true                             # Run extraction after each scene save
    auto_promote: false                       # Skip the provisional hold on extracted entries
  terminology:
    always_include: true                      # Bypass top-K for terminology
```

`auto_extraction.enabled` only takes effect when a `lore_service` is wired (i.e. a franchise slug is resolvable from the concept seed). Set it to `false` to disable post-save lore extraction without removing the rest of the worldbuilding stack.

### Runtime Flags

The chapter packet and the standby slices land behind runtime flags. Flags resolve through `src/runtime_flags.py` with this precedence:

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
  chapter_packet:
    enabled: true
    fallback_on_error: true
  revision_debt:
    enabled: false
  promise_ledger:
    enabled: false
  final_copy:
    enabled: false
    literary_polish_model: gpt54
    literary_polish_temperature: 0.45
  rhythm_validator:
    enabled: false
    thresholds: {}
  rhythm_editor:
    enabled: false
    trigger_codes: [rhythm.em_dash_overuse, rhythm.staccato_cluster, rhythm.opener_monotone, rhythm.abstract_tic]
    max_trigger_codes: 5
    max_edits: 8
    max_total_changed_chars: 1500
    max_changed_ratio: 0.15
  continuity_validator:
    enabled: false
```

The shipping defaults are lean. `lean_prose_only`, `lean_prose_only.line_edit`, and `chapter_packet` are effectively on; everything else (`revision_debt`, `promise_ledger`, `rhythm_validator`, `rhythm_editor`, `continuity_validator`, `final_copy`) is standby tooling, default-off until a per-book review approves it. Adding a new runtime flag without a safe default (off, or the most conservative numeric) is a review-blocker. Per-book guard tests in `tests/test_runtime_flags.py` block accidental flips on the shipping books.

### Bench Configs

Frozen routing snapshots live under `config/bench/` for benchmarking — e.g. `config/bench/settings.bench.sonnet.yaml` and `config/bench/settings.bench.gpt.yaml`. Use `config/bench/experimental-model-aliases.yaml` as the alias reference when creating a new bench snapshot for a model that is not part of the shipping routing. Run with `--config config/bench/<snapshot>.yaml`. See [Benchmarking](../development/benchmarking.md).

---

## negative_constraints.yaml

Defines banned phrases and structural rules for prose quality. The `ContextAssembler` bakes the banned-phrase list into the drafter's prompt, so anti-slop guidance reaches the drafter at draft time.

### Banned Phrases

Categories:
- **faux_profundity** — overused portentous constructions
- **sensory_cliches** — stock physical descriptions
- **magic_adverbs** — lazy modifier patterns
- **ai_tells** — words that signal AI-generated text (e.g., "delve", "tapestry", "nuanced")

### Structural Rules

| Rule | Default | Description |
|------|---------|-------------|
| max_adverb_density | 0.02 | Max ratio of adverbs to total words |
| min_sentence_length_variance | 0.3 | Minimum coefficient of variation in sentence length |
| max_same_opener_pct | 0.15 | Max percentage of paragraphs starting with the same pattern |
| metaphor_cooldown_paragraphs | 8 | Minimum paragraphs between figurative-language uses |
