# Ruusan Atonement — Ch 2-28 Scene Card Audit

**Date:** 2026-04-20
**Scope:** Ch 2-28 scene cards (84 files) + chapter blueprints (27 files) + concept_seed.json
**Method:** Per-card shape classification, merge/split analysis, blueprint reconciliation, voice coverage, continuity tracing
**Output:** Diagnosis only — no edits applied

---

## 0. Scope discrepancy (read this first)

The audit brief specified Ch 2-34. The book is **28 chapters**, not 34. `concept_seed.meta.target_chapters` is 28; `chapter_blueprints/` contains `chapter_01.json` through `chapter_28.json`; `scene_cards/` runs through `chapter_28_scene_03.json`. This audit covers **Ch 2-28** (84 cards, 27 blueprints). If the brief meant "audit every chapter except Ch 1," that is the scope delivered. If the brief meant the book has expanded to 34 chapters since my last information, there is no evidence of that expansion on disk and the audit cannot cover chapters that do not exist.

---

## 1. Summary

| Metric | Count |
|---|---|
| Cards audited | 84 |
| OK (matches Ch 1 template) | 66 |
| OVER-SPECIFIED (hard) | 3 |
| OVER-SPECIFIED (soft — dialogue in anchor field) | 15 |
| UNDER-SPECIFIED | 0 |
| INCONSISTENT | 0 |
| Merge candidates | 3 (1 moderate, 2 low-confidence) |
| Split candidates | 2 (author-acknowledged dual-turn scenes) |
| Blueprint/card scene-count mismatches | 1 (Ch 16) |
| Blueprint/card word-count drifts | 14 (most ±50-100 words) |
| Voice-coverage gaps | 1 (Luke Skywalker) |
| Continuity gaps — hooks (H01-H25) | 0 |
| Continuity gaps — promises (PP01-PP26) | 6 (5 NO-PLANT, 1 UNPAID) |
| Continuity gaps — revelations (R01-R14) | 1 (R05b never lands in any card) |

Headline: **the cards are structurally sound**. Every required field is populated, every hook plants and resolves, the single POV and single-POV count line up. The main finding is a **pervasive soft pattern**: dialogue is being transcribed into `turning_point` / `closing_hook` / `opening_hook` anchor fields across ~15-20 cards. Three cards (Ch 25 s3, 27 s1, 28 s2) take this further and grow `mission` fields to paragraph-length beat-by-beat prose with embedded dialogue — those are the only genuinely over-specified ones. Under-specification is nonexistent; inconsistency is nonexistent; merge/split candidates are few and most are author-intentional.

---

## 2. Over-specified cards

### 2a. Hard over-specification (3 cards)

These cards embed transcribed dialogue inside paragraph-length `mission` fields and repeat the same dialogue across `turning_point`, `conflict`, `action_beats`, and `notes`. They diverge qualitatively from the Ch 1 template (1-2 sentence mission, no transcribed dialogue).

#### [chapter_25_scene_03](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_25_scene_03.json)

- `mission` field is ~700 words — a paragraph-level beat-by-beat script of the climax.
- Transcribed dialogue `'Ben — spiking on the east node, give me three seconds'` appears in `mission`, `turning_point`, `action_beats`, `sensory_details`, and `notes` (5 repetitions).
- `notes` field is ~500 words of authorial prescription describing the exact shape of the heartbeat-beat exchange.

**Trim recommendation** (don't rewrite — cut):
- `mission`: reduce to 2 sentences naming the three-part turn (Veraine compensates, chord survives heartbeat wobble, thesis collapses). Move the "interpreter-of-chord" framing to `notes` as guidance, not to `mission` as script.
- Remove the Desh dialogue transcription from `mission`, `turning_point`, and `action_beats`. Keep it in `notes` as a drafter anchor *once*, not as a prescription.
- `conflict` field: cut from ~180 words to one sentence.
- The `action_beats` list has 6 items — acceptable if they stay action-level, but beat 4 currently transcribes the Desh comm line.

#### [chapter_27_scene_01](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_27_scene_01.json)

- Transcribed Veraine dialogue `'The emergence you produced was interesting. I will think about it.'` inside `mission`.
- This line is not in `voice_definition.character_voices.Darth Veraine.specimens` — it is freshly prescribed by the card.

**Trim recommendation:**
- `mission`: rewrite the four embedded quotation sentences into one-sentence framing (e.g., "Veraine engages Ben academically; she will not concede"). The exact line can live in `notes` as a register anchor.

#### [chapter_28_scene_02](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_28_scene_02.json)

- `mission` is ~300 words and embeds two Luke lines: `'And you didn't call me.'` and `'We'll tell the Council. All of it.'`
- Each line is repeated in `turning_point`, `closing_hook`, `action_beats`, and `notes` (4 repetitions each).
- `notes` field is ~500 words of scene direction bordering on drafter output.

**Trim recommendation:**
- Keep *one* canonical placement of `'And you didn't call me.'` — it is load-bearing for PP26 payoff and should be preserved as an anchor. The second Luke line ("We'll tell the Council") should also be anchored *once*.
- Strip both lines from `mission`, `action_beats`, and repeated `notes` passages. The card can name the beat ("Luke's first question after the silence names the unmade Ch 13 call") without transcribing the line multiple times.
- `mission` should compress to 2-3 sentences naming the turn (Ben tells Luke everything → Luke's question names the pattern → shared decision to tell the Council).

**Pattern observation on hard over-specification:** All three cards are load-bearing payoff scenes (R13/PP16, Veraine-containment coda, R14/PP26). The cards grow thick because the author wants to guarantee the beats land. That anxiety is understandable but inverts the light-card principle: a rich `voice_definition` plus 1-2 sentence mission trusts the drafter; a 700-word mission replaces the drafter.

### 2b. Soft over-specification — dialogue in anchor fields (15 cards)

These cards otherwise match the template but transcribe 1-3 sentences of dialogue into `turning_point`, `closing_hook`, or `opening_hook`. Some of the quoted lines are canonical anchors (preserved_specimens from `voice_definition.character_voices` or authored `hooks[].description` text in concept_seed); those are **acceptable** per the brief's load-bearing-anchor exception. The others are freshly prescribed by the card and fall outside the exception.

| Card | Field | Line | Is canonical anchor? |
|---|---|---|---|
| ch05s02 | closing_hook | "The Reformations you were raised inside... were the front half of an agreement." | No |
| ch08s02 | turning_point | Kael: "You're all arguing about whose cage has nicer bars." | No |
| ch08s03 | closing_hook | Kael/Desh exchange ("You don't feel any of it" / "I feel the ship shaking...") | No |
| ch09s02 | closing_hook | Sera: "I have heard that argument before. From a man I followed into a war." | No |
| ch11s02 | turning_point | Desh: "He sounds like Jacen. The good version. Before." | No |
| ch12s02 | turning_point | Torin: "She couldn't handle it. That doesn't mean no one can." | No |
| ch15s02 | mission + turning + closing | Torin: "You're curating reality..." | **Yes** — H15 canonical text |
| ch16s02 | turning_point | Veraine: "They used us identically..." | No (Veraine pitch, 3-sentence block) |
| ch16s03 | turning_point | Ben: "I appreciate the testimony..." | No |
| ch16s04 | turning_point | Desh: "She played us..." | No |
| ch17s03 | opening_hook | Desh: "Contact. Bearing three-one-five, parallel course." | No (short tactical comm) |
| ch18s02 | turning_point | Desh: "I didn't come here to watch another good person..." | No |
| ch19s02 | mission | Sera: "What is your plan, Skywalker?" | No |
| ch19s03 | turning_point | Kael: "They built everything on one thing..." | No |
| ch20s01 | mission + closing_hook | Desh: "Her ship is on the surface. Valley coordinates..." | No (+ redundant — same line twice) |
| ch21s02 | turning_point | Torin: "I was the one they sealed. I cannot seal another." | **Yes** — Sera `arc_phase_targets` canonical |
| ch21s03 | closing_hook | Ben: "We find another way. Together." | **Yes** — Ben `arc_phase_targets` canonical |
| ch23s01 | mission + closing_hook | Kael/Ben exchange ("Not very" / "Points for honesty") | No (+ redundant — same exchange twice) |
| ch23s03 | turning_point | Kael: "If this kills me, I want it on record that I volunteered..." | No |
| ch24s03 | turning_point | Ben: "Now." | **Yes** — one-word line, brief-allowed exception |

**Net read:** 4 of the 20 transcribed lines are canonical anchors and should stay. The other 16 are freshly prescribed by the cards and should be converted to "what happens here" framing rather than "what the character says." Example:

- Current: `turning_point: "Kael: 'They built everything on one thing. Take it away and they don't know how to stand...'"`
- Lighter: `turning_point: "Kael names the modern Order's load-bearing fragility — the design problem under the Weave problem."`

The drafter + `voice_definition.character_voices.Kael Drenn` has enough to generate the actual line in the voice the book has established. The card's job is to name the beat, not to write it.

**Redundancy sub-pattern:** ch20s01 and ch23s01 transcribe the same dialogue into both `mission` and `closing_hook`. Even if the dialogue is kept, it should appear once, not twice.

---

## 3. Under-specified cards

None. All 84 cards populate `turning_point`, `characters_present`, `pov_character`, `target_word_count`, and `mission`. All have ≥3 action beats. No one-word placeholder values found.

---

## 4. Inconsistent cards

None detected. POV character is `Ben Skywalker` in every Ch 2-28 card, matching `meta.pov_structure`. POV character appears in `characters_present` in every card. `dialogue_expectation` flags are coherent with `characters_present` sizes where the flag exists.

---

## 5. Merge / split candidates

Ordered from highest to lowest confidence.

### 5a. Merge candidates

#### MC-1 — [ch23_scene_01](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_23_scene_01.json) + [ch23_scene_02](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_23_scene_02.json) (moderate confidence)

- **Criterion triggered:** same POV + overlapping characters_present (Ben/Kael in both; Desh joins as observed figure in s2) + identical setting (Veranthos camp, dawn) + emotional_trajectory continuous across boundary.
- **s1 closing_hook:** "Kael sits with it. A long time... 'Points for honesty.'"
- **s2 opening_hook:** "Kael walks away. Not leaving — thinking. Ben forces himself not to follow."
- s1 turning point is Ben's honest "Not very"; s2 turning point is Kael looking at Desh and recognizing chosen life. These could read as one scene with two beats (the honest presentation → the silent processing → the recognition).
- **Counter-argument for keeping split:** s1's turn (trust demonstrated via honesty) is Ben's beat; s2's turn (Kael recognizes freedom via Desh) is Kael's beat. Splitting them lets each turn breathe. Also: s1 has `scene_role: hook`, s2 has `scene_role: decision` — intentional escalation.
- **Rationale:** If this were a published novel, these 2500 combined words would probably read as a single scene with an internal pause. The split is justifiable but not necessary. **No action required unless the chapter is word-over.**

#### MC-2 — [ch15_scene_01](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_15_scene_01.json) + [ch15_scene_02](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_15_scene_02.json) (low confidence)

- **Criterion triggered:** both `scene_role: escalation` (unusual — adjacent scenes with the same role). Both are mid-ship Attack-phase beats with overlapping characters.
- **Counter-argument for keeping split:** they are different *types* of escalation — s1 is the coded-message + group-commitment beat, s2 is the Torin argument + Ben pattern-exposure beat. Different instruments, different turns.
- **Rationale:** The role-tag repetition reads like a drafting gap (reviewer should consider whether s1 might be `decision` or s2 `reveal`) more than a merge-necessity. **No merge; consider re-labeling roles.**

#### MC-3 — [ch25_scene_01](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_25_scene_01.json) + [ch25_scene_02](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_25_scene_02.json) (low confidence)

- **Criterion triggered:** s1 closing includes "antennas fail"; s2 opening is "array collapse threshold hit" — continuous climax beat.
- **Counter-argument for keeping split:** Ch 25 is the climax chapter with 4 scenes (the only such chapter besides Ch 5 FPP). Splitting the climax into scene-level beats is a deliberate pacing technique. The s1/s2 division carries the shift from "approach" (s1) to "everything fails" (s2) — qualitatively different emotional registers even if temporally contiguous.
- **Rationale:** **Keep split.** Climax beat-division is intentional.

### 5b. Split candidates

Two cards self-describe as containing two distinct turning points. The author's framing is explicit — these are concurrent-turn scenes, not accidental single-card overloads. Flagging for review but not recommending split.

#### SC-1 — [ch18_scene_02](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_18_scene_02.json)

- `turning_point` explicitly names two turns: Desh's line AND Sera's silent fracture. The card frames them as "Two turning points in one frame."
- Could be split (one scene for the Desh/Ben Jacen-pattern naming, one for Sera's fissure). But the craft choice — forcing the reader to hold both beats in the same breath — is structural, not accidental.
- **Rationale:** **Keep as single scene.** The concurrent-turn framing is deliberate.

#### SC-2 — [ch19_scene_03](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_19_scene_03.json)

- `turning_point` describes Kael's anchor-line and Ben's fingertip-on-Veraine's-annotation as "Two pieces of insight, two sources, one corridor of air."
- Same craft choice as SC-1.
- **Rationale:** **Keep as single scene.**

---

## 6. Blueprint issues

### 6a. Scene-count mismatch — Ch 16

- **Blueprint** `chapter_blueprints/chapter_16.json` declares `scene_count: 3`, `scene_plan` contains scenes 1, 2, 3.
- **Scene cards** on disk: `chapter_16_scene_01`, `02`, `03`, **`04`**.
- **Implication:** Ch 16 was extended from 3 to 4 scenes during revision and the blueprint was not updated. This is a direct contradiction that will break any tooling that reconciles blueprints against cards. Section 5's recommendations do not change this — merge/split analysis leaves Ch 16 at 4 cards.
- **Recommendation:** Update `chapter_blueprints/chapter_16.json` to `scene_count: 4` and add a 4th entry to `scene_plan` matching `chapter_16_scene_04.json`.

### 6b. Word-count drift (blueprint vs card target_word_count)

14 scenes have mismatched `target_word_count` between blueprint and card. Most are ±50-100 words — revisions that retuned cards but did not update blueprints. None are large enough to change chapter word targets by >5%.

| Scene | Blueprint | Card |
|---|---|---|
| ch05s01 | 1300 | 1400 |
| ch05s02 | 1250 | 1200 |
| ch05s03 | 1150 | 1200 |
| ch05s04 | 1100 | 1000 |
| ch06s01 | 1350 | 1400 |
| ch06s02 | 1100 | 1200 |
| ch06s03 | 1050 | 1100 |
| ch07s02 | 1250 | 1200 |
| ch07s03 | 1050 | 1100 |
| ch09s02 | 1250 | 1100 |
| ch11s03 | 1050 | 1100 |
| ch13s01 | 1500 | 1600 |
| ch14s03 | 1150 | 1200 |
| ch24s01 | 1250 | 1300 |

**Recommendation:** sweep blueprints to match cards (cards are more recently revised; they are the source of truth). Chapter word totals should be recomputed for chapters affected (Ch 5, 6, 7, 9, 13, 14, 24).

### 6c. POV allocation

All 27 Ch 2-28 blueprints declare `pov_allocation: ['Ben Skywalker']`. All 84 cards populate `pov_character: 'Ben Skywalker'`. Full consistency with `meta.pov_structure`.

---

## 7. Voice coverage gaps

Characters appearing in `characters_present` across Ch 2-28 cards:

```
Ben Skywalker, Darth Veraine, Desh Rolan, Kael Drenn, Luke Skywalker,
Rendell (Jedi Knight, sparring partner), Sera Varik, Torin Hal
```

Entries in `concept_seed.voice_definition.character_voices`:

```
Ben Skywalker, Sera Varik, Torin Hal, Kael Drenn, Darth Veraine, Desh Rolan
```

**One gap: Luke Skywalker.**

- Luke appears in `chapter_01_scene_02` (out of audit scope but establishes the pattern) and **`chapter_28_scene_02`** (in scope, load-bearing R14/PP26 payoff scene).
- Luke's voice is referenced once in `voice_definition.anti_slop_rules.derived_rules[3].content` as "Luke (warmth holding sadness)" but there is no dedicated `character_voices` entry with dialogue specimens, register guidance, or anti-patterns.
- The Ch 28 s2 scene leans hard on Luke's voice for a four-word line (`"And you didn't call me."`) that carries PP26 payoff. A drafter generating that line without an explicit voice entry for Luke has to infer his register from the single rule-4 hint and the Ch 1 s2 scene card context.

**Recommendation:** add a `Luke Skywalker` entry to `character_voices` — minimally: register guidance, one preserved specimen, and an anti-pattern. The Ch 28 s2 card's existing notes field already implies the register ("warm and holding sadness without performing it"); surface that into the canonical voice block.

Rendell appears only in Ch 1 (out of audit scope) and is a background character; no voice entry needed.

---

## 8. Continuity gaps

### 8a. Hooks (H01-H25) — **all OK**

Every hook plants and resolves somewhere in the 84 cards. Many have no `advance` beats but all have plant→resolve lifecycles:

```
H01-H25: all plant+resolve present
```

### 8b. Promises (PP01-PP26) — **6 issues**

| Promise | Status | Notes |
|---|---|---|
| PP03 | NO-PLANT | Paid at ch26s02 (Sera/Torin thousand-year relationship) but never explicitly planted in any card's `promises_planted` field. Ch 5 s1 would be the natural plant location. |
| PP11 | NO-PLANT | Paid at ch25s03 ("The cycle of unilateral power broken"). Plant should live in Ch 1-3 where Ben's self-reliance pattern establishes. |
| PP15 | **UNPAID** | Planted at ch05s01 but no card marks it paid. Without context I cannot tell which scene was supposed to pay it — likely Ch 27 s2 or Ch 28 s2. |
| PP18 | NO-PLANT | Paid at ch20s01 (probably Veranthos-as-place arrival payoff). Plant expected in Ch 5 or Ch 7. |
| PP20 | NO-PLANT | Paid at ch19s02 and ch22s01. Unclear what promise this is; plant expected in Ch 5-10 range. |
| PP26 | NO-PLANT | Paid at ch28s02 (Luke's "you didn't call me" — the unmade-call thread). The concept_seed describes this as a thread planted at Ch 13 and reinforced through Ch 14-15, but no card marks it as `planted`. The Ch 13 s3 / Ch 14 s1 cards should surface PP26 in their `promises_planted` lists. |

### 8c. Revelations (R01-R14) — **1 issue**

| Revelation | Status | Notes |
|---|---|---|
| R05b | **MISSING** | Per `concept_seed.revelation_schedule`, R05b ("technique's full historical lineage") is planned to land progressively across Chs 8-9 and 12. No scene card marks R05b in its `revelations` list. Either the revelation is being delivered but not tagged, or it has been absorbed into R04b/c/d. Requires author decision: tag the progressive landing in Ch 8 s1, Ch 9 s1, Ch 12 s1 cards, OR remove R05b from the revelation_schedule. |

### 8d. Downstream implications

The hook machinery is robust; the promise machinery has gaps only at the margins. None of the gaps would prevent a draft from being written — they would show up as "is PP15 actually paid?" retrospective questions during review, not as broken scenes. The R05b absence is the most likely source of a real-reader "wasn't this supposed to pay off?" reaction.

---

## 9. Recommendations (in impact order)

### 9a. Trim the three hard over-specified cards (P0)
- [chapter_25_scene_03](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_25_scene_03.json), [chapter_27_scene_01](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_27_scene_01.json), [chapter_28_scene_02](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_28_scene_02.json).
- Reduce `mission` to 2-3 sentences. Remove dialogue transcription from `mission`/`turning_point`/`action_beats`. Retain one canonical anchor per line in `notes` only.
- Expected outcome: prose generated from these cards will match the Ch 1 register surface and rely on `voice_definition` for dialogue texture rather than on card-level dictation.

### 9b. Fix Ch 16 blueprint scene_count (P0)
- Update [chapter_blueprints/chapter_16.json](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/chapter_blueprints/chapter_16.json) from `scene_count: 3` to `4`; add the 4th entry to `scene_plan`. This is the only clear structural contradiction in the audit.

### 9c. Add Luke Skywalker to `character_voices` (P1)
- In [concept_seed.json](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json), add a `Luke Skywalker` entry to `voice_definition.character_voices`. Minimum: register description, one preserved specimen, one anti-pattern. Pull from the Ch 28 s2 `notes` field which already describes the register.

### 9d. Strip dialogue transcription from soft over-specified cards (P1)
- ~15 cards in section 2b. Replace `Character: "quoted line"` constructions with "what happens here" framing when the line is not a canonical anchor. Keep the 4 canonical anchor lines (ch15s02 H15 text, ch21s02 Sera arc crystallization, ch21s03 Ben arc crystallization, ch24s03 "Now.").
- Remove duplication in ch20s01 and ch23s01 (same dialogue in two fields).

### 9e. Fill promise-lifecycle gaps (P2)
- Add `promises_planted` entries for PP03, PP11, PP18, PP20, PP26 in their natural plant locations (informed by the concept_seed rationale fields).
- Resolve PP15 — either add a `promises_paid` marker to the scene that pays it, or remove PP15 from `promise_payoff_ledger` if it has been merged into another promise.
- Tag R05b's progressive landings in Ch 8 s1 / Ch 9 s1 / Ch 12 s1 cards, or remove R05b from `revelation_schedule`.

### 9f. Reconcile word-count drift (P3 — nice-to-have)
- 14 scenes in section 6b. Update blueprint `target_word_count` to match card values. No recomputed chapter_word_target value is load-bearing; this is bookkeeping hygiene.

---

## Appendix: Methodology notes

- **What the audit verified by direct read:** Ch 1 template cards (3), concept_seed character_voices / revelation_schedule / hooks / subplots / promise_pay_map / anti_slop_rules (selective); Ch 25 s3, Ch 27 s1, Ch 28 s2, Ch 7 s1 (hard over-specification spot-check); Ch 15 s2, Ch 17 s3, Ch 23 s1, Ch 23 s2 (merge-candidate spot-check); Ch 2, Ch 5 blueprints (for blueprint-shape calibration).
- **What was classified via Explore subagent:** per-card shape classification of all 84 Ch 2-28 cards. Subagent's classification of 3 OVER-SPECIFIED cards verified against raw cards; subagent's 0-count for UNDER-SPECIFIED/INCONSISTENT verified via required-field Grep sweep (no empty/placeholder values found in `turning_point`/`characters_present`/`pov_character`/`target_word_count`/`mission`).
- **What was computed programmatically:** hook lifecycle (plant/advance/resolve) across all 87 cards (Ch 1-28), promise plant/pay lifecycle, revelation appearances, character-in-cards vs character-in-voice-definition, blueprint `scene_count` vs card count, blueprint `target_word_count` vs card `target_word_count`.
- **Non-goals honored:** no scene cards were edited; no chapter blueprints were edited; `concept_seed.json` was not modified; pipeline (`src.main`) was not run; no new cards were authored; pre-existing pytest failures were not touched.
- **Known limitations:** dialogue-in-anchor-fields classification (section 2b) used string matching against `preserved_specimens` and authored `hooks[].description` text; any canonical line with minor paraphrase may have been mis-flagged as non-canonical. Reviewer should treat the 2b table as a candidate list, not a definitive ruling.
