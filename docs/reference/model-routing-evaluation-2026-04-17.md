# Model Routing Evaluation - 2026-04-17

## Scope

This review is based on:

1. The current router and model config in `config/settings.yaml` and `src/model_router.py`.
2. The current prompt and context assembly path in `src/orchestrator.py`, `src/memory/context_assembler.py`, and the agent prompt files.
3. Existing chapter 1 run logs and outputs in `output/runs-logs/` and `output/star-wars-legends-eu/the-ruusan-atonement/runs/`.
4. Current OpenRouter model pricing and prompt-caching documentation as of April 17, 2026.

I did **not** find an in-repo Chrome extension to inspect. This evaluation therefore uses the actual OpenRouter integration in the repo plus live OpenRouter model data.

## Executive Answer

You should **not** switch the main prose drafter to a much cheaper model yet.

The fastest path to reducing spend is:

1. Keep `prose_stylist` on `anthropic/claude-sonnet-4.6` for now.
2. Stop running `quality_polish` on every scene by default.
3. Keep `gate_critic`, `chapter_gate_critic`, and `final_gate` on `anthropic/claude-haiku-4.5`.
4. Keep `summarizer` and `character_specialist` on `deepseek/deepseek-v3.2`.
5. Use a **different family** for higher-level feedback: `x-ai/grok-4.20` or `moonshotai/kimi-k2`.
6. If you want to test cheaper prose models, test `qwen/qwen3.6-plus` and `minimax/minimax-m2.7` first. Do **not** jump straight to `gemini-3-flash-preview` or `glm-5.1` for prose based on the runs already in this repo.

## Step 1: What the Current System Is Doing

Current phase-5 routing in `config/settings.yaml`:

| Role | Current model | Notes |
|---|---|---|
| `prose_stylist` | `anthropic/claude-sonnet-4.6` | Primary scene draft |
| `quality_polish` | `anthropic/claude-sonnet-4.6` | Full second pass over scene prose |
| `gate_critic` | `anthropic/claude-haiku-4.5` | Cheap structured gate |
| `chapter_gate_critic` | `anthropic/claude-haiku-4.5` | Chapter-level composition gate |
| `final_gate` | `anthropic/claude-haiku-4.5` | Post-polish contract check |
| `plot_architect` | `google/gemini-3.1-pro-preview` | Planning brief |
| `judge_evaluator` | `x-ai/grok-4.20` | Optional LLM judge |
| `manuscript_reviewer` | `moonshotai/kimi-k2` | Full-manuscript feedback |
| `summarizer` | `deepseek/deepseek-v3.2` | Cheap utility role |
| `character_specialist` | `deepseek/deepseek-v3.2` | Cheap utility role |

## Step 2: Why Chapter 1 Feels Expensive

The main cost driver is not the cheap utility models. It is repeated full-context passes over the same scene.

From `output/runs-logs/polish-ch01.log`, chapter 1 used:

- `plot_architect`: 3 calls
- `prose_stylist`: 6 calls
- `gate_critic`: 6 calls
- `quality_polish`: 3 calls
- `final_gate`: 3 calls
- `summarizer`: 3 calls
- `character_specialist`: 3 calls
- `chapter_gate_critic`: 1 call

Total: **28 LLM calls** for one 3-scene chapter.

The raw-draft smoke runs were much lower:

- `smoke-ch01-v3`: 11 LLM calls
- `smoke-ch01`: 13 LLM calls
- `smoke-ch01-v2`: 17 LLM calls

So the full chapter-1 phase-5 path is roughly **2x to 2.5x** the LLM call count of the raw-draft path before any optional judge or manuscript review.

## Step 3: Why Sonnet Dominates Cost

`prose_stylist` and `quality_polish` are both full-scene passes on `claude-sonnet-4.6`.

That means Sonnet is paying for:

1. The initial draft.
2. Every rewrite retry triggered by the gate.
3. A second full polish pass after the gate.

In the `polish-ch01` run, Sonnet was called **9 times** in one chapter:

- 6 prose calls
- 3 polish calls

Even though Haiku had more total calls than Sonnet in that run, Haiku is much cheaper and its outputs are short structured JSON. Sonnet is the expensive role because it is both high-priced and fed the largest prompts.

## Step 4: Prompt Size Is Also a Problem

The context assembly budgets in `src/memory/context_assembler.py` add up to **18,000 tokens** before you even count:

- the system prompt
- the generated brief
- the current prose being evaluated or polished
- failure notes on retries

The configured tier budgets include:

- recent prose: 8000
- bible summary: 2000
- chapter summaries: 1200
- canon RAG: 1000
- character voices: 1000
- worldbuilding lore and dialogue tiers
- scene card and constraint layers

This means the system is not only using expensive models; it is repeatedly sending large prompt bodies to them.

## Step 5: Interpreting The Earlier Cheap-Prose Runs Carefully

The earlier cheap-prose experiments in this repo were run under the **older architecture**, where the scene passed through the removed multi-band revision pipeline (`craft_editor`, `scene_emotion_reviewer`, `line_copy_editor`, and related post-draft stages).

That means those runs are **confounded** if the question is:

"Would a cheaper prose drafter work well in the current redesigned pipeline?"

Useful historical context:

| Run | Prose model | Architecture context | Chapter 1 output words |
|---|---|---|---:|
| `run8-gemini-flash-prose-fixes` | `gemini_flash` | old revision stack | 1693 |
| `run10-glm-prose` | `glm` | old revision stack | 2323 |
| `run19-baseline-raw-draft` | `claude` | newer raw-draft baseline | 3515 |
| `smoke-ch01-v3` | `claude` | newer raw-draft baseline | 3641 |

So the right conclusion is **not**:

"Cheap prose already failed, therefore cheaper drafting is a bad idea."

The defensible conclusion is:

"Cheap prose has not yet been cleanly re-tested under the post-redesign architecture."

That changes the recommendation materially. Older `gemini_flash` and `glm` results should be treated as **suggestive but not decisive**.

## Step 6: The Best Immediate Saving Is to Change Polish, Not Prose

The strongest cost/quality opportunity is `quality_polish`.

Reasons:

1. It is a full second pass on the most expensive family.
2. It runs even when quality metrics already passed.
3. It is followed by another gate call.
4. Historical baseline comparison does **not** show clear heuristic improvement from always-on polish.

Repo-local metrics comparison:

| Run | Avg heuristic score across chapter 1 scenes |
|---|---:|
| `phase1_baseline_raw_draft` | 0.819 |
| `phase1_baseline_with_polish` | 0.798 |
| `phase1_polish_v2_post_1_5` | 0.784 |
| `polish-ch01` | 0.816 |

This is not a human taste verdict, but it is enough to say the current always-on polish pass is **not obviously earning its cost**.

## Step 7: Current OpenRouter Price Snapshot

OpenRouter prices checked on April 17, 2026:

| Model | Input / 1M | Output / 1M | Source |
|---|---:|---:|---|
| Claude Sonnet 4.6 | $3.00 | $15.00 | [OpenRouter](https://openrouter.ai/anthropic/claude-sonnet-4.6/pricing) |
| Claude Haiku 4.5 | $1.00 | $5.00 | [OpenRouter](https://openrouter.ai/anthropic/claude-haiku-4.5/pricing) |
| Gemini 3.1 Pro Preview | $2.00 | $12.00 | [OpenRouter](https://openrouter.ai/google/gemini-3.1-pro-preview/pricing) |
| Gemini 3 Flash Preview | $0.50 | $3.00 | [OpenRouter](https://openrouter.ai/google/gemini-3-flash-preview/pricing) |
| Grok 4.20 | $2.00 | $6.00 | [OpenRouter](https://openrouter.ai/x-ai/grok-4.20/pricing) |
| Grok 4.1 Fast | $0.20 | $0.50 | [OpenRouter](https://openrouter.ai/x-ai/grok-4.1-fast/pricing) |
| Kimi K2 | $0.57 | $2.30 | [OpenRouter](https://openrouter.ai/moonshotai/kimi-k2/pricing) |
| Qwen 3.6 Plus | $0.325 | $1.95 | [OpenRouter](https://openrouter.ai/qwen/qwen3.6-plus/pricing) |
| Mistral Small 4 | $0.15 | $0.60 | [OpenRouter](https://openrouter.ai/mistralai/mistral-small-2603/pricing) |
| MiniMax M2.7 | $0.30 | $1.20 | [OpenRouter](https://openrouter.ai/minimax/minimax-m2.7/pricing) |
| GLM 5.1 | $0.95 | $3.15 | [OpenRouter](https://openrouter.ai/z-ai/glm-5.1/pricing) |
| DeepSeek V3.2 | $0.26 | $0.38 | [OpenRouter](https://openrouter.ai/deepseek/deepseek-v3.2/pricing) |

## Step 8: Which Models Actually Make Sense By Role

### Prose drafter

Best current recommendation: **do not replace Sonnet globally until you have a clean post-redesign A/B**.

Why:

- It is already producing complete scenes in the redesigned pipeline.
- The prose role is the one most exposed to scene-card obedience and retry penalties.
- The negative evidence against cheaper prose is currently confounded by the old revision architecture.

Best next prose A/B candidates in the **current** architecture:

1. `qwen/qwen3.6-plus`
2. `minimax/minimax-m2.7`
3. `anthropic/claude-haiku-4.5`

Why these three:

- They are much cheaper than Sonnet.
- They are stronger first candidates than immediately rerunning the older `gemini_flash` and `glm` experiments.
- They offer different family behavior, not just cheaper versions of the same failure mode.

What this means operationally:

1. Keep Sonnet as the default prose model right now.
2. Run a **clean raw-draft A/B on the redesigned pipeline** with identical scene cards and identical gate settings.
3. Compare:
   - gate pass rate
   - retry count
   - final word count
   - human preference on scene quality
   - total input/output token cost per accepted scene

Until that test exists, any strong claim for or against cheaper prose is premature.

### Planning

Best current recommendation: **keep Gemini 3.1 Pro Preview on `plot_architect`** until prose spend is under control.

Why:

- Planning is not the dominant cost driver.
- Better briefs reduce expensive Sonnet rewrite loops.
- Saving on the planner while increasing rewrite rate is a false economy.

### Gate and final checks

Best current recommendation: **keep Haiku 4.5**.

Why:

- Cheap enough.
- Strong structured-output fit.
- Already doing the right kind of bounded critic work.

### High-level feedback

Best current recommendation: use a **different family** from the prose drafter.

Good choices:

- `x-ai/grok-4.20` for chapter or judge-style feedback
- `moonshotai/kimi-k2` for broader manuscript/editorial review

This is where cross-family critique makes sense. It is a good heuristic because it reduces shared blind spots between drafter and critic. It is not a magic rule, but it is directionally right for this system.

### Utility and analysis roles

Best current recommendation: **leave them alone**.

- `deepseek-v3.2` for summarizer and character specialist is already extremely cheap.
- `mistral-small-2603` for voice checker is already cheap.
- `grok-4.1-fast` for orchestration is already cheap.

These are not where your credits are disappearing.

## Step 9: Prompt Caching Edge Cases

OpenRouter caching docs matter here.

Important facts from the docs:

1. Anthropic top-level `cache_control` works, but only when routed directly to Anthropic.
2. Claude Sonnet 4.6 caches only when the prompt is at least 2048 tokens.
3. Claude Haiku 4.5 caches only when the prompt is at least 4096 tokens.
4. Anthropic 1-hour TTL cache writes cost **2x** input price; 5-minute writes cost **1.25x** input price.
5. OpenRouter returns cache usage in `usage.prompt_tokens_details.cached_tokens` and `cache_write_tokens`.

Why this matters here:

- Your router currently enables Anthropic top-level caching for every Claude call.
- It uses `anthropic_ttl: 1h`.
- The system does **not** log cache usage from the API response.

So you currently cannot tell whether caching is saving money or making it worse.

My recommendation:

1. Change Anthropic cache TTL from `1h` to `5m`.
2. Log `usage.prompt_tokens`, `completion_tokens`, `cached_tokens`, and `cache_write_tokens`.
3. Re-check after 3 to 5 real chapter runs.

Why I prefer `5m` here:

- Your rewrite loops happen quickly.
- Your scene generation sessions are bursty, not hour-long repeated conversations against identical prompts.
- A 1-hour write premium is more justified for long-lived repeated reuse than for one chapter drafted in one sitting.

Source: [OpenRouter prompt caching docs](https://openrouter.ai/docs/guides/best-practices/prompt-caching).

## Step 10: Recommended Routing Strategy

### Best practical default

Use this if you want the safest cost reduction:

- Keep `prose_stylist` on `claude-sonnet-4.6`
- Keep `plot_architect` on `gemini-3.1-pro-preview`
- Keep `gate_critic`, `chapter_gate_critic`, `final_gate` on `claude-haiku-4.5`
- Keep `summarizer`, `character_specialist`, `lore_extractor` on `deepseek-v3.2`
- Keep `judge_evaluator` on `grok-4.20`
- Keep `manuscript_reviewer` on `kimi-k2`
- Make `quality_polish` conditional instead of always-on

### If you want an aggressive savings profile

Test in this order:

1. Make `quality_polish` conditional.
2. If polish still needs to run often, test `quality_polish -> claude-haiku-4.5`.
3. If prose cost is still too high, A/B `prose_stylist -> qwen/qwen3.6-plus` on the redesigned pipeline.
4. Then A/B `prose_stylist -> minimax/minimax-m2.7` on the redesigned pipeline.

I would still **not** jump directly to:

- `gemini-3-flash-preview` for prose
- `glm-5.1` for prose

There is historical reason to be cautious with those models here, but the stronger reason is that better candidates should be tested first under the redesigned pipeline.

## Step 11: Best Workflow for Cross-Family Critique

This is the model-family split I recommend:

1. Drafter: `Claude Sonnet 4.6`
2. Cheap contract critics: `Claude Haiku 4.5`
3. Editorial or judge pass: `Grok 4.20` or `Kimi K2`

Why this split works:

- Sonnet handles scene obedience and prose quality.
- Haiku handles cheap structured compliance checks.
- Grok or Kimi gives you a genuinely different critic perspective.

That is better than using Sonnet to draft and Sonnet again to tell itself what it thinks of its own scene.

## Step 12: Final Recommendation

If the goal is to cut spend **without** risking a quality collapse:

1. Keep Sonnet as the default drafter for now.
2. Stop always-on polish.
3. Keep Haiku as the gate model.
4. Use Grok 4.20 or Kimi K2 for higher-level feedback.
5. Change Anthropic cache TTL to `5m`.
6. Add token and cache logging before making any bigger routing decision.

If the goal is to push harder on savings after that:

1. Run a clean post-redesign prose A/B.
2. Start with Qwen 3.6 Plus for prose.
3. Then test MiniMax M2.7 for prose.
3. Keep a human-reviewed comparison set for chapter 1 scene 1 through scene 3.

## Short Version

The biggest mistake would be replacing Sonnet prose first.

The best first move is to reduce the number of Sonnet full-scene passes.

That means:

- conditional polish
- better cache observability
- cross-family feedback at chapter/manuscript level
- only then prose-model A/B testing
