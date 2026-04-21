# Phase 0 audit — legacy-of-the-force-betrayal

- Run: `phase0_2026-04-20`
- Franchise: `star-wars-legends-eu`
- Chapter: 1
- Mode: `dry-run`
- Generated: 2026-04-21T02:59:34.740550+00:00
- Git: `301c4f1` (dirty)
- Overall pass: **YES**

## Criteria

- `voice_rules_reach_drafter` — PASS — output\star-wars-legends-eu\legacy-of-the-force-betrayal\runs\phase0_2026-04-20\phase0_debug\ch01_sc01\02_prose_stylist_prompt.txt :: prose_register=L125-L125; reference_authors=found: Aaron Allston, Timothy Zahn; anti_slop_rules=L139-L139
- `scene_contract_reaches_drafter` — PASS — output\star-wars-legends-eu\legacy-of-the-force-betrayal\runs\phase0_2026-04-20\phase0_debug\ch01_sc01\02_prose_stylist_prompt.txt :: mission=L60-L60; turning_point=L66-L66; pov_character=present; characters_present=all present; closing_hook=L67-L67
- `constraints_survive_assembly` — PASS — output\star-wars-legends-eu\legacy-of-the-force-betrayal\runs\phase0_2026-04-20\phase0_debug\ch01_sc01\02_prose_stylist_prompt.txt :: 45/45 banned phrases survived (100%); sample hits: ["faux_profundity:It wasn't just X, it was Y", 'faux_profundity:A testament to', 'faux_profundity:A tapestry of']
- `cross_scene_feedback_real` — PASS — sc01 vs sc02: markers=['## Cross-Scene Feedback', 'prior scene', 'Prior scene', 'carries pressure'], content_carry=True
- `register_policy_single_source` — PASS — output\star-wars-legends-eu\legacy-of-the-force-betrayal\runs\phase0_2026-04-20\phase0_debug\ch01_sc01\02_prose_stylist_prompt.txt:L125-L125 :: single register 'Allston's dialogue-forward register…'
- `audit_report_exists` — PASS — docs\audits\phase0_2026-04-20_legacy-of-the-force-betrayal.md

## Status

All six criteria pass. Slice 2 (chapter packet) is unblocked for this book.
