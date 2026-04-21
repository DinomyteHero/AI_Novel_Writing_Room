# Phase 0 audit — the-ruusan-atonement

- Run: `phase0_2026-04-20`
- Franchise: `star-wars-legends-eu`
- Chapter: 1
- Mode: `dry-run`
- Generated: 2026-04-21T02:59:34.157499+00:00
- Git: `301c4f1` (dirty)
- Overall pass: **YES**

## Criteria

- `voice_rules_reach_drafter` — PASS — output\star-wars-legends-eu\the-ruusan-atonement\runs\phase0_2026-04-20\phase0_debug\ch01_sc01\02_prose_stylist_prompt.txt :: prose_register=L110-L110; reference_authors=found: Timothy Zahn, James Luceno, Aaron Allston, Matthew Stover, Lois McMaster Bujold
- `scene_contract_reaches_drafter` — PASS — output\star-wars-legends-eu\the-ruusan-atonement\runs\phase0_2026-04-20\phase0_debug\ch01_sc01\02_prose_stylist_prompt.txt :: mission=L55-L55; turning_point=L59-L59; pov_character=present; characters_present=all present; closing_hook=L61-L61
- `constraints_survive_assembly` — PASS — output\star-wars-legends-eu\the-ruusan-atonement\runs\phase0_2026-04-20\phase0_debug\ch01_sc01\02_prose_stylist_prompt.txt :: 45/45 banned phrases survived (100%); sample hits: ["faux_profundity:It wasn't just X, it was Y", 'faux_profundity:A testament to', 'faux_profundity:A tapestry of']
- `cross_scene_feedback_real` — PASS — sc01 vs sc02: markers=['## Cross-Scene Feedback', 'prior scene', 'Prior scene', 'carries pressure'], content_carry=True
- `register_policy_single_source` — PASS — output\star-wars-legends-eu\the-ruusan-atonement\runs\phase0_2026-04-20\phase0_debug\ch01_sc01\02_prose_stylist_prompt.txt:L110-L110 :: single register 'Adult Legends fiction…'
- `audit_report_exists` — PASS — docs\audits\phase0_2026-04-20_the-ruusan-atonement.md

## Status

All six criteria pass. Slice 2 (chapter packet) is unblocked for this book.
