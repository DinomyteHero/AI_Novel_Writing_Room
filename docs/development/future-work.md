# Future Work / Known Follow-Ups

This file tracks work items that have been deliberately deferred from prior
changes. Each entry records the item, why it was deferred, and a pointer to
the original work where it was flagged.

Prefer creating small focused PRs that close individual items here rather than
letting the list grow — this is a backlog, not a permanent list.

---

## Concept workshop / schema cleanup (flagged during the post-Ruusan cleanup)

The post-Ruusan cleanup (branch `claude/nice-babbage`, merged via PR #8) committed
fully to the new workshop-native schema and architecture — deleting
`beyond_the_veil`, renaming `subplot_board`/`hook_map`/`stress_test_results`
to their canonical workshop-native names, tightening schema enums, splitting
`arc_type` into canonical enum + `arc_summary` descriptive prose, adding
`scene_type` to the scene card schema, and realigning the concept workshop
prompt's JSON template with the schema field-for-field. Five items were
explicitly flagged as out of scope for that work:

### Workshop session full-transcript capture

The workshop already writes structured session summaries via
`src/concept_workshop/workshop_summarizer.py:_save_summary` — these are
`{session_id}_summary.json` files containing confirmed decisions, open
questions, and narrative summaries.

**Deferred**: full per-turn conversation transcript capture (every assistant
and user message with timestamps) as either Markdown logs or structured JSON.
Requires a new per-turn writer hook in `workshop_runner.py` and a policy on
where transcripts live (`data/story_bibles/{project}/workshop_sessions/`
already exists as a target directory convention).

**Why deferred**: structured summaries already cover the use cases we have
(resuming sessions, tracking decisions). Full transcripts are a
nice-to-have for audit and post-hoc analysis but not required for the
pipeline to function.

### `ConceptWorkshopState.load()` malformed-JSON error handling

`src/concept_workshop/workshop_state.py:load` currently propagates
`json.JSONDecodeError` uncaught when a state file exists but contains
invalid JSON. The load method should either:

- Catch the decode error and return an empty `ConceptWorkshopState`
  (silent recovery, log a warning), OR
- Catch the error, back up the malformed file with a `.corrupt.{timestamp}`
  suffix, and return empty state (safer because the original file isn't
  lost)

**Deferred**: no repository currently has corrupt state files to recover
from. The behavior is only an issue if a workshop state file is manually
edited badly or truncated mid-write.

### Schema version marker in `workshop_state.json` files

`ConceptWorkshopState` has no `_version` or `schema_version` field. If
the dataclass shape changes again in the future, there's no way for
`load()` to detect an old-format file and migrate it.

**Deferred**: there are no legacy `workshop_state.json` files in the
repository (the `beyond_the_veil` state file was never checked in). A
version marker should be added the next time the dataclass shape is
extended, alongside a `_migrate_from_v1_to_v2` helper.

**Suggested shape**: add `workshop_state_version: int = 2` to the
dataclass (start at `2` to leave `1` available for any legacy files we
discover); `from_dict` reads the version and dispatches to a migration
helper before constructing the state.

### Renaming `tests/test_subplot_board.py` → `tests/test_subplots.py`

The SQLite table was renamed from `subplot_board` to `subplots` in the
post-Ruusan cleanup (commit `6fd5463`). The test file's **docstrings and
class names** were updated at the same time, but the **filename** was
left as `test_subplot_board.py`.

**Deferred**: the filename is functionally irrelevant — pytest discovers
the tests regardless, and all docstrings/references inside the file are
now accurate. Renaming is a clean-up that can happen whenever someone is
already touching the file for an unrelated reason. Not worth its own
commit.

**Suggested approach**: when next editing `test_subplots`-related tests,
`git mv tests/test_subplot_board.py tests/test_subplots.py` and include
in the same commit.

### `scene_type` downstream consumer (pacing enforcement)

Commit `97d3c89` added `scene_type` (`action` | `sequel`) as a first-class
field on `schemas/scene_card.json` and populated it for all 28 Ruusan
scene cards. **No agent currently reads `scene_type` from scene cards.**

**Deferred**: the field is added for queryability. A future pacing agent
(or an extension of the existing `src/quality/pacing_analyzer.py`) can
enforce action/sequel balance rules — e.g., "no more than 3 consecutive
action scenes without a sequel", "no more than 2 consecutive sequels" —
by reading the structured field instead of parsing scene card `notes`.

**Suggested approach**: extend `pacing_analyzer.py` (currently a
paragraph-level classifier) with a scene-card-level rule check that
consumes `scene_type` directly, and wire it into the pipeline quality
gate or the concept workshop's Step 8 validation rules.

---
