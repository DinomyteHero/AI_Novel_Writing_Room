# Ruusan Chapter 1 Prose Model Benchmark

Date: 2026-04-23
Base commit: e67d5fff816d8c2df382a7ff074090dde59a30c1
Pipeline: phase 5, quality_polish variant
Scope: Chapter 1, scenes 1-3 of `star-wars-legends-eu/the-ruusan-atonement`

This pass compares production-shaped Chapter 1 runs where only the `prose_stylist`
model was changed. The rest of the agent roster stayed aligned with the current
production config, including GPT 5.4-mini as `quality_polish`.

## Runs

| Candidate | Config | Run directory |
| --- | --- | --- |
| Claude Sonnet 4.6 baseline | `config/bench/settings.bench.ruusan-sonnet.yaml` | `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-sonnet-20260423/` |
| MiniMax M2.7 | `config/bench/settings.bench.ruusan-minimax.yaml` | `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-minimax-20260423/` |
| Qwen 3.6 Plus | `config/bench/settings.bench.ruusan-qwen.yaml` | `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-qwen-20260423/` |

## Automated Outcome

| Candidate | Scene 1 | Scene 2 | Scene 3 | Total words | Save status |
| --- | ---: | ---: | ---: | ---: | --- |
| MiniMax M2.7 | 1,225 | 1,391 | 1,244 | 3,860 | 0 clean, 3 advisory |
| Qwen 3.6 Plus | 870 | 816 | 736 | 2,422 | 2 clean, 1 advisory |
| Sonnet 4.6 baseline | 1,225 | 1,107 | 1,032 | 3,364 | 2 clean, 1 advisory |

Observed gate summaries:

- MiniMax: all three scenes saved with advisory. Scene 2 hit voice/terminology/telling issues; Scene 3 hit opening hook, voice definition, and telling issues. Character and continuity checks passed.
- Qwen: two scenes saved clean and one with advisory. Scene 2 hit terminology drift and telling issues. Character and continuity checks passed.
- Sonnet: two scenes saved clean and one with advisory. Scene 2 hit structural concerns including hook, out-of-character action, weak turning point, and telling. Character and continuity checks passed.

## Prose Assessment

Sonnet 4.6 remains the strongest pure prose baseline. It has the best line-level
control, the most confident interiority, and the cleanest commercial rhythm. It
also stays closest to the tone expected from a polished Legends-style scene:
restrained sensory detail, clear dramatic beats, and less visible prompt
compliance. The downside is cost. Its Chapter 1 output was also shorter than the
MiniMax run, though still usable.

MiniMax M2.7 is the best non-Claude candidate for continuing the drafter
benchmark. It hit the expected scene length most consistently and produced full
scenes rather than compressed summaries. Its best passages are close enough to
commercial genre prose to be worth further testing. The weakness is cleanliness:
it attracted more gate advisories, repeated ideas more visibly, and sometimes
leaned into explanatory narration. It likely needs strong gate/polish support,
but the raw material is viable.

Qwen 3.6 Plus was the cleanest by automated save status, but it substantially
underwrote the chapter. The prose is efficient and often sharp, yet the scenes
read more like strong compressed drafts than finished book scenes. It is worth
keeping in the bench because it may respond well to stricter target-length
instructions, but it should not be treated as the leading Sonnet replacement yet.

## Recommendation

Continue the prose benchmark with three lanes:

1. Sonnet 4.6 as the quality control baseline.
2. MiniMax M2.7 as the primary low-cost drafter candidate.
3. Qwen 3.6 Plus as the lean-control candidate, with a second pass focused on
   target-length obedience.

For "clean commercial writing" specifically, the current rank is:

1. Sonnet 4.6
2. MiniMax M2.7
3. Qwen 3.6 Plus

For "cost-conscious replacement potential," the current rank is:

1. MiniMax M2.7
2. Qwen 3.6 Plus
3. Sonnet 4.6 baseline

## Prose Files

MiniMax:

- `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-minimax-20260423/chapters/chapter_01_scene_01.md`
- `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-minimax-20260423/chapters/chapter_01_scene_02.md`
- `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-minimax-20260423/chapters/chapter_01_scene_03.md`

Qwen:

- `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-qwen-20260423/chapters/chapter_01_scene_01.md`
- `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-qwen-20260423/chapters/chapter_01_scene_02.md`
- `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-qwen-20260423/chapters/chapter_01_scene_03.md`

Sonnet:

- `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-sonnet-20260423/chapters/chapter_01_scene_01.md`
- `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-sonnet-20260423/chapters/chapter_01_scene_02.md`
- `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-ch1-sonnet-20260423/chapters/chapter_01_scene_03.md`

## Next Benchmark

After locking the drafter shortlist, run a separate Haiku 4.5 replacement bench
against the roles where Haiku still appears: chapter gate critic, continuity
extractor, final gate, micro repair, plot architect, and presence checker. That
bench should measure structured-output reliability, latency, cost, and false
positive/false negative behavior rather than prose beauty.
