# Configuration

All configuration files are in the `config/` directory.

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
      gemini_flash:   google/gemini-3-flash-preview
      deepseek:       deepseek/deepseek-v3.2
      claude:         anthropic/claude-sonnet-4.6
      haiku:          anthropic/claude-haiku-4.5
      glm:            z-ai/glm-5.1
      qwen:           qwen/qwen3.6-plus
      kimi:           moonshotai/kimi-k2
      grok420:        x-ai/grok-4.20
      grok41fast:     x-ai/grok-4.1-fast
      mistral_small4: mistralai/mistral-small-2603
      minimax:        minimax/minimax-m2.7
    default_params:
      # Per-alias defaults (temperature, max_tokens) applied when an agent
      # routing entry does not override them.
      gemini:         { temperature: 0.6, max_tokens: 8192 }
      gemini_flash:   { temperature: 0.5, max_tokens: 8192 }
      deepseek:       { temperature: 0.3, max_tokens: 4096 }
      claude:         { temperature: 0.4, max_tokens: 8192 }
      haiku:          { temperature: 0.4, max_tokens: 4096 }
      # ...
```

Add more aliases as needed. The bench configs (`settings.bench.sonnet.yaml`, `settings.bench.gpt.yaml`) also register `gpt54: openai/gpt-5.4` when benchmarking OpenAI prose models.

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
  # PROSE — premium voice under current live config
  prose_stylist:   { backend: cloud, model: claude,   params: { temperature: 0.80, max_tokens: 8192 } }

  # GATES / EVAL — cheap, precise
  gate_critic:         { backend: cloud, model: haiku,   params: { temperature: 0.3 } }
  chapter_gate_critic: { backend: cloud, model: haiku,   params: { temperature: 0.3 } }
  final_gate:          { backend: cloud, model: haiku,   params: { temperature: 0.2 } }
  judge_evaluator:     { backend: cloud, model: grok420, params: { temperature: 0.2 } }
  manuscript_reviewer: { backend: cloud, model: kimi,    params: { temperature: 0.3 } }

  # PLANNING — Gemini Pro for outline/seed/brief generation
  concept_workshop: { backend: cloud, model: gemini, params: { temperature: 0.7, max_tokens: 8192 } }
  outline_planner:  { backend: cloud, model: gemini, params: { temperature: 0.5, max_tokens: 32768 } }
  seed_builder:     { backend: cloud, model: gemini, params: { temperature: 0.3, max_tokens: 16384 } }
  plot_architect:   { backend: cloud, model: gemini, params: { temperature: 0.4 } }
  chapter_blueprint_synthesizer: { backend: cloud, model: gemini, params: { temperature: 0.4, max_tokens: 8192 } }

  # POLISH — single bounded expression-level pass
  quality_polish: { backend: cloud, model: claude, params: { temperature: 0.5, max_tokens: 8192 } }

  # STRUCTURAL REVISION / UTILITY
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

Two frozen routing snapshots live alongside `settings.yaml` for benchmarking:

- `config/settings.bench.sonnet.yaml` — `prose_stylist` on Sonnet 4.6 @ t=0.70, `plot_architect` on Grok 4.20, `quality_polish` on Haiku 4.5.
- `config/settings.bench.gpt.yaml` — same pipeline but `prose_stylist` on GPT 5.4 @ t=0.70, and registers `gpt54: openai/gpt-5.4` in the cloud models map.

Run with `--config config/settings.bench.sonnet.yaml` or `--config config/settings.bench.gpt.yaml`. See [Benchmarking](../development/benchmarking.md) for the A/B methodology and the pre-built analyses in `output/…/runs/BENCH_*.md`.

### Pipeline Settings

```yaml
pipeline:
  max_structural_retries: 3
  max_voice_retries: 2
  max_http_retries: 3              # Max retries for failed HTTP requests (with jitter)
  # chapter_output_dir: defaults to output/<franchise>/<book>/runs/<run_id>/chapters/
  # run_ledger_path: auto-resolved at output/<franchise>/<book>/state/run_ledger.db
```

### Embeddings Settings

```yaml
embeddings:
  use_mock: false                  # When true, uses mock embeddings (deterministic, no model needed)
                                   # Useful for testing or environments without an embedding model
```

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
  db_path: data/worldbuilding.db              # SQLite database for universes/lore
  vectors_dir: data/worldbuilding_vectors     # ChromaDB persistent directory
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

The `lore_extractor` agent routing is also defined in `agent_routing`:

```yaml
agent_routing:
  lore_extractor: { backend: local, model: utility, params: { temperature: 0.2 } }
```

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
| fail_structural | full_rewrite (back to ProseStylist with failure context; up to `max_structural_retries`) |
| fail_voice | targeted_revision (ProseStylist with specific notes; up to `max_voice_retries`) |
| fail_polish | no rewrite — the Scene-Gate-passed draft passes through to QualityPolish + compression guard + FinalGate, which either accept the polish or revert to the Gate-passed draft |

> **Note**: `fail_polish` no longer routes to a CraftEditor. The 3-band revision pipeline was collapsed into a single bounded `quality_polish` pass guarded by a compression check and the Final Gate. See [pipeline-redesign.md](../architecture/pipeline-redesign.md).

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
