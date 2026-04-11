#!/usr/bin/env python3
"""Validate The Ruusan Atonement story bible.

Tasks:
  1. Schema validation of concept seed and scene cards
  2. Story logic audit (hooks, subplots, revelations, arcs, word count, scene balance)
  3. Pipeline readiness check
"""

import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONCEPT_SEED_PATH = PROJECT_ROOT / "data" / "projects" / "the-ruusan-atonement" / "concept_seed.json"
SCENE_CARDS_DIR = PROJECT_ROOT / "data" / "projects" / "the-ruusan-atonement" / "scene_cards"

# ---------------------------------------------------------------------------
# Enum definitions (from schemas)
# ---------------------------------------------------------------------------
CANON_STATUS_ENUM = {"canon_compliant", "AU", "original"}
TONE_ENUM = {"dark_gritty", "adventurous_hopeful", "political_intrigue", "character_study", "heroic_with_weight"}
PROJECT_SCOPE_ENUM = {"standalone", "planned_series", "continuation"}
ARC_TYPE_ENUM = {"positive_change", "flat", "negative", "disillusionment"}
STRUCTURAL_PHASE_ENUM = {"setup", "first_plot_point", "response", "first_pinch", "midpoint", "attack", "second_pinch", "second_plot_point", "resolution", "climax"}
SCENE_TYPE_ENUM = {"action", "sequel"}
CONFLICT_TYPE_ENUM = {"internal", "interpersonal", "external", "environmental"}
HOOK_TYPE_ENUM = {"hard", "soft", "series"}
HOOK_ACTION_ENUM = {"plant", "advance", "resolve", "subvert"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
issues = []

def report(category: str, severity: str, file: str, description: str):
    issues.append({"category": category, "severity": severity, "file": file, "description": description})

def check_non_empty_string(obj, field, file, context=""):
    val = obj.get(field)
    if val is None:
        report("schema", "critical", file, f"{context}Missing required field '{field}'")
        return False
    if isinstance(val, str) and len(val.strip()) == 0:
        report("schema", "critical", file, f"{context}Field '{field}' is empty string")
        return False
    return True

def check_enum(obj, field, allowed, file, context=""):
    val = obj.get(field)
    if val is not None and val not in allowed:
        report("schema", "critical", file, f"{context}Field '{field}' has value '{val}' not in {sorted(allowed)}")
        return False
    return True

def check_min_length(obj, field, min_len, file, context=""):
    val = obj.get(field)
    if val is not None and isinstance(val, str) and len(val) < min_len:
        report("schema", "warning", file, f"{context}Field '{field}' length {len(val)} < minLength {min_len}")
        return False
    return True

def parse_chapter_ref(ref) -> int | None:
    if ref is None:
        return None
    if isinstance(ref, int):
        return ref
    if isinstance(ref, str):
        m = re.search(r"(\d+)", ref)
        if m:
            return int(m.group(1))
    return None

# ---------------------------------------------------------------------------
# TASK 1: Schema Validation
# ---------------------------------------------------------------------------
def validate_concept_seed(seed: dict, filepath: str):
    print("=" * 60)
    print("TASK 1: Schema Validation — Concept Seed")
    print("=" * 60)

    # Top-level required fields
    for field in ["meta", "premise", "conflict", "theme", "ensemble_cast", "canon_constraints"]:
        if field not in seed:
            report("schema", "critical", filepath, f"Missing top-level required field '{field}'")

    # --- Meta ---
    meta = seed.get("meta", {})
    for field in ["project_title", "franchise", "canon_status", "era", "tone", "target_word_count"]:
        check_non_empty_string(meta, field, filepath, "meta.")
    check_enum(meta, "canon_status", CANON_STATUS_ENUM, filepath, "meta.")
    check_enum(meta, "tone", TONE_ENUM, filepath, "meta.")
    check_enum(meta, "project_scope", PROJECT_SCOPE_ENUM, filepath, "meta.")
    twc = meta.get("target_word_count")
    if twc is not None:
        if not isinstance(twc, int):
            report("schema", "critical", filepath, f"meta.target_word_count must be integer, got {type(twc).__name__}")
        elif twc < 40000 or twc > 120000:
            report("schema", "warning", filepath, f"meta.target_word_count={twc} outside range [40000, 120000]")

    # --- Premise ---
    premise = seed.get("premise", {})
    for field in ["what_if", "central_dramatic_question", "logline"]:
        check_non_empty_string(premise, field, filepath, "premise.")
    check_min_length(premise, "what_if", 50, filepath, "premise.")
    logline = premise.get("logline", "")
    if isinstance(logline, str) and len(logline) > 500:
        report("schema", "warning", filepath, f"premise.logline length {len(logline)} > maxLength 500")

    # --- Conflict ---
    conflict = seed.get("conflict", {})
    for field in ["primary_antagonistic_force", "lock_in_mechanism"]:
        check_non_empty_string(conflict, field, filepath, "conflict.")
    paf = conflict.get("primary_antagonistic_force", {})
    if isinstance(paf, dict):
        for field in ["type", "motivation", "escalation"]:
            check_non_empty_string(paf, field, filepath, "conflict.primary_antagonistic_force.")
        check_min_length(paf, "motivation", 50, filepath, "conflict.primary_antagonistic_force.")
        check_min_length(paf, "escalation", 100, filepath, "conflict.primary_antagonistic_force.")
    check_min_length(conflict, "lock_in_mechanism", 30, filepath, "conflict.")

    # --- Theme ---
    theme = seed.get("theme", {})
    for field in ["thematic_premise", "thematic_argument", "how_each_arc_tests_theme"]:
        check_non_empty_string(theme, field, filepath, "theme.")
    check_min_length(theme, "thematic_argument", 100, filepath, "theme.")

    # --- Ensemble Cast ---
    cast = seed.get("ensemble_cast", [])
    if not isinstance(cast, list) or len(cast) < 2:
        report("schema", "critical", filepath, f"ensemble_cast must have >=2 members, got {len(cast) if isinstance(cast, list) else 'non-list'}")
    elif len(cast) > 6:
        report("schema", "warning", filepath, f"ensemble_cast has {len(cast)} members (max recommended: 6)")

    for i, member in enumerate(cast):
        ctx = f"ensemble_cast[{i}] ({member.get('name', '?')})."
        for field in ["name", "role", "three_dimensions"]:
            check_non_empty_string(member, field, filepath, ctx)
        td = member.get("three_dimensions", {})
        if isinstance(td, dict):
            for field in ["surface", "backstory_inner_demons", "action_under_pressure"]:
                check_non_empty_string(td, field, filepath, ctx + "three_dimensions.")
                check_min_length(td, field, 50, filepath, ctx + "three_dimensions.")

        weiland = member.get("weiland_arc")
        if weiland and isinstance(weiland, dict):
            check_enum(weiland, "arc_type", ARC_TYPE_ENUM, filepath, ctx + "weiland_arc.")
            for field in ["lie_believed", "ghost", "want", "need", "arc_type"]:
                check_non_empty_string(weiland, field, filepath, ctx + "weiland_arc.")
            check_min_length(weiland, "lie_believed", 30, filepath, ctx + "weiland_arc.")
            check_min_length(weiland, "ghost", 30, filepath, ctx + "weiland_arc.")
            check_min_length(weiland, "want", 20, filepath, ctx + "weiland_arc.")
            check_min_length(weiland, "need", 20, filepath, ctx + "weiland_arc.")

    # --- Canon Constraints ---
    cc = seed.get("canon_constraints", {})
    for field in ["continuity", "canon_preserved", "style_constraints"]:
        if field not in cc:
            report("schema", "critical", filepath, f"canon_constraints.{field} missing")

    # --- Hooks ---
    for i, hook in enumerate(seed.get("hooks", [])):
        ctx = f"hooks[{i}] ({hook.get('hook_id', '?')})."
        check_non_empty_string(hook, "hook_id", filepath, ctx)
        check_enum(hook, "hook_type", HOOK_TYPE_ENUM, filepath, ctx)

    # --- Subplots ---
    for i, sp in enumerate(seed.get("subplots", [])):
        ctx = f"subplots[{i}] ({sp.get('subplot_id', '?')})."
        check_non_empty_string(sp, "subplot_id", filepath, ctx)

    # --- Revelation schedule ---
    for i, rev in enumerate(seed.get("revelation_schedule", [])):
        ctx = f"revelation_schedule[{i}] ({rev.get('revelation_id', '?')})."
        check_non_empty_string(rev, "revelation_id", filepath, ctx)

    schema_count = len([i for i in issues if i["category"] == "schema"])
    print(f"  Concept seed checks complete. Issues found: {schema_count}")


def validate_scene_cards(cards: list[tuple[str, dict]]):
    print("\n" + "=" * 60)
    print("TASK 1: Schema Validation — Scene Cards")
    print("=" * 60)

    initial_count = len(issues)
    for filepath, card in cards:
        fname = os.path.basename(filepath)
        # Required fields
        for field in ["chapter_number", "scene_number", "structural_phase", "pov_character", "mission", "conflict", "turning_point"]:
            check_non_empty_string(card, field, fname, "")

        # Type checks
        for int_field in ["chapter_number", "scene_number"]:
            val = card.get(int_field)
            if val is not None and not isinstance(val, int):
                report("schema", "critical", fname, f"'{int_field}' must be integer, got {type(val).__name__}")

        # Enum checks
        check_enum(card, "structural_phase", STRUCTURAL_PHASE_ENUM, fname)
        check_enum(card, "scene_type", SCENE_TYPE_ENUM, fname)
        check_enum(card, "conflict_type", CONFLICT_TYPE_ENUM, fname)

        # minLength checks (minLength: 1)
        for field in ["pov_character", "mission", "conflict", "turning_point"]:
            val = card.get(field)
            if isinstance(val, str) and len(val) < 1:
                report("schema", "critical", fname, f"Field '{field}' empty (minLength: 1)")

        # Hook action enums
        for j, ha in enumerate(card.get("hook_actions", [])):
            check_enum(ha, "action", HOOK_ACTION_ENUM, fname, f"hook_actions[{j}].")

    new_count = len(issues) - initial_count
    print(f"  Scene card checks complete ({len(cards)} cards). Issues found: {new_count}")


# ---------------------------------------------------------------------------
# TASK 2: Story Logic Audit
# ---------------------------------------------------------------------------
def story_logic_audit(seed: dict, cards: list[tuple[str, dict]]):
    print("\n" + "=" * 60)
    print("TASK 2: Story Logic Audit")
    print("=" * 60)

    meta = seed.get("meta", {})
    target_chapters = meta.get("target_chapters", 28)
    target_wc = meta.get("target_word_count", 100000)

    # Build lookup structures
    hooks_by_id = {}
    for h in seed.get("hooks", []):
        hooks_by_id[h["hook_id"]] = h

    subplots_by_id = {}
    for sp in seed.get("subplots", []):
        subplots_by_id[sp["subplot_id"]] = sp

    revelations_by_id = {}
    for r in seed.get("revelation_schedule", []):
        revelations_by_id[r["revelation_id"]] = r

    cast_by_name = {}
    for c in seed.get("ensemble_cast", []):
        cast_by_name[c["name"]] = c

    # Scene card data indexed by chapter
    card_by_chapter = {}
    for filepath, card in cards:
        ch = card.get("chapter_number")
        card_by_chapter[ch] = (filepath, card)

    # -----------------------------------------------------------------------
    # Hook Integrity
    # -----------------------------------------------------------------------
    print("\n  --- Hook Integrity ---")

    # Collect all hook actions from scene cards
    scene_hook_actions = {}  # hook_id -> list of (chapter, action)
    for filepath, card in cards:
        ch = card.get("chapter_number")
        for ha in card.get("hook_actions", []):
            hid = ha.get("hook_id")
            action = ha.get("action")
            if hid:
                scene_hook_actions.setdefault(hid, []).append((ch, action))

    # Hard hooks must be resolved in at least one scene card
    hard_hooks = [h for h in seed.get("hooks", []) if h.get("hook_type") == "hard"]
    for h in hard_hooks:
        hid = h["hook_id"]
        actions = scene_hook_actions.get(hid, [])
        resolved = [a for a in actions if a[1] == "resolve"]
        if not resolved:
            report("hook_integrity", "critical", "concept_seed.json",
                   f"Hard hook '{hid}' has no 'resolve' action in any scene card")

    # Every hook referenced in scene cards must exist in concept seed
    all_seed_hook_ids = set(hooks_by_id.keys())
    for filepath, card in cards:
        fname = os.path.basename(filepath)
        for ha in card.get("hook_actions", []):
            hid = ha.get("hook_id")
            if hid and hid not in all_seed_hook_ids:
                report("hook_integrity", "critical", fname,
                       f"Hook '{hid}' referenced in scene card but not in concept seed hooks[]")

    # Hard hook budget: count <= target_chapters / 3
    budget = target_chapters // 3
    if len(hard_hooks) > budget:
        report("hook_integrity", "warning", "concept_seed.json",
               f"Hard hook count ({len(hard_hooks)}) exceeds budget ({budget} = {target_chapters}/3)")
    else:
        print(f"    Hard hook budget: {len(hard_hooks)} / {budget} — OK")

    # No hook planted after it is resolved
    for hid, actions in scene_hook_actions.items():
        resolve_chapters = [ch for ch, act in actions if act == "resolve"]
        plant_chapters = [ch for ch, act in actions if act == "plant"]
        if resolve_chapters and plant_chapters:
            earliest_resolve = min(resolve_chapters)
            late_plants = [ch for ch in plant_chapters if ch > earliest_resolve]
            if late_plants:
                report("hook_integrity", "critical", "scene_cards",
                       f"Hook '{hid}' planted in chapter(s) {late_plants} after resolution in chapter {earliest_resolve}")

    # -----------------------------------------------------------------------
    # Subplot Integrity
    # -----------------------------------------------------------------------
    print("\n  --- Subplot Integrity ---")

    # Exactly one A-line subplot
    a_lines = [sp for sp in seed.get("subplots", []) if sp.get("line_type") == "A"]
    if len(a_lines) != 1:
        report("subplot_integrity", "critical", "concept_seed.json",
               f"Expected exactly 1 A-line subplot, found {len(a_lines)}")
    else:
        print(f"    A-line subplot: '{a_lines[0].get('name')}' — OK")

    # Subplot chapters_active vs scene card references
    scene_subplot_refs = {}  # subplot_id -> set of chapters
    for filepath, card in cards:
        ch = card.get("chapter_number")
        for sp_id in card.get("active_subplots", []):
            scene_subplot_refs.setdefault(sp_id, set()).add(ch)
        for sp_id in card.get("plot_threads_advanced", []):
            scene_subplot_refs.setdefault(sp_id, set()).add(ch)

    for sp in seed.get("subplots", []):
        sp_id = sp["subplot_id"]
        declared = set(sp.get("chapters_active", []))
        actual = scene_subplot_refs.get(sp_id, set())

        # Check for chapters in scene cards but not declared
        undeclared = actual - declared
        if undeclared:
            report("subplot_integrity", "warning", "concept_seed.json",
                   f"Subplot '{sp_id}' referenced in scene cards for chapters {sorted(undeclared)} but not in chapters_active")

        # Check for declared chapters without scene card references
        unreferenced = declared - actual
        if unreferenced:
            report("subplot_integrity", "info", "concept_seed.json",
                   f"Subplot '{sp_id}' declares chapters_active {sorted(unreferenced)} but no scene card references them")

    # Minimum 3-chapter activity (except A-line)
    for sp in seed.get("subplots", []):
        if sp.get("line_type") == "A":
            continue
        chapters = sp.get("chapters_active", [])
        if len(chapters) < 3:
            report("subplot_integrity", "warning", "concept_seed.json",
                   f"Subplot '{sp['subplot_id']}' active for only {len(chapters)} chapters (minimum 3 recommended)")

    # -----------------------------------------------------------------------
    # Revelation Integrity
    # -----------------------------------------------------------------------
    print("\n  --- Revelation Integrity ---")

    # Collect revelations from scene cards
    scene_revelations = {}  # rev_id -> list of chapters
    for filepath, card in cards:
        ch = card.get("chapter_number")
        for rev_id in card.get("revelations", []):
            scene_revelations.setdefault(rev_id, []).append(ch)

    # Every revelation in schedule must appear in exactly one scene card
    for rev in seed.get("revelation_schedule", []):
        rev_id = rev["revelation_id"]
        occurrences = scene_revelations.get(rev_id, [])
        if len(occurrences) == 0:
            report("revelation_integrity", "warning", "concept_seed.json",
                   f"Revelation '{rev_id}' in schedule but not in any scene card's revelations[]")
        elif len(occurrences) > 1:
            report("revelation_integrity", "info", "concept_seed.json",
                   f"Revelation '{rev_id}' appears in {len(occurrences)} scene cards (chapters {occurrences}) — expected 1")

    # Every revelation in scene cards must exist in schedule
    all_rev_ids = set(revelations_by_id.keys())
    for filepath, card in cards:
        fname = os.path.basename(filepath)
        for rev_id in card.get("revelations", []):
            if rev_id not in all_rev_ids:
                report("revelation_integrity", "critical", fname,
                       f"Revelation '{rev_id}' in scene card but not in revelation_schedule")

    # -----------------------------------------------------------------------
    # Character Arc Integrity
    # -----------------------------------------------------------------------
    print("\n  --- Character Arc Integrity ---")

    for member in seed.get("ensemble_cast", []):
        name = member.get("name", "?")
        weiland = member.get("weiland_arc")
        if not weiland:
            continue
        arc_type = weiland.get("arc_type")
        if arc_type is None:
            continue

        # Minimum field lengths
        lie = weiland.get("lie_believed", "")
        ghost = weiland.get("ghost", "")
        want = weiland.get("want", "")
        need = weiland.get("need", "")

        if len(lie) < 30:
            report("character_arc", "warning", "concept_seed.json",
                   f"{name}: lie_believed length {len(lie)} < 30 chars")
        if len(ghost) < 30:
            report("character_arc", "warning", "concept_seed.json",
                   f"{name}: ghost length {len(ghost)} < 30 chars")
        if len(want) < 20:
            report("character_arc", "warning", "concept_seed.json",
                   f"{name}: want length {len(want)} < 20 chars")
        if len(need) < 20:
            report("character_arc", "warning", "concept_seed.json",
                   f"{name}: need length {len(need)} < 20 chars")

    # POV characters need arc_phase_map with lie_established and arc_resolved
    pov_characters = set()
    for filepath, card in cards:
        pov = card.get("pov_character")
        if pov:
            pov_characters.add(pov)

    for pov_name in pov_characters:
        member = cast_by_name.get(pov_name)
        if not member:
            report("character_arc", "warning", "concept_seed.json",
                   f"POV character '{pov_name}' not found in ensemble_cast")
            continue
        weiland = member.get("weiland_arc", {})
        apm = weiland.get("arc_phase_map", {})
        if not apm:
            report("character_arc", "warning", "concept_seed.json",
                   f"POV character '{pov_name}' has no arc_phase_map")
            continue
        if "lie_established" not in apm:
            report("character_arc", "warning", "concept_seed.json",
                   f"POV character '{pov_name}' arc_phase_map missing 'lie_established'")
        if "arc_resolved" not in apm:
            # Check for variant names
            has_resolved = any(k for k in apm if "resolved" in k.lower())
            if not has_resolved:
                report("character_arc", "warning", "concept_seed.json",
                       f"POV character '{pov_name}' arc_phase_map missing 'arc_resolved' (or variant)")

    # -----------------------------------------------------------------------
    # Word Count
    # -----------------------------------------------------------------------
    print("\n  --- Word Count ---")

    total_scene_wc = 0
    for filepath, card in cards:
        wc = card.get("target_word_count", 0)
        total_scene_wc += wc

    deviation = abs(total_scene_wc - target_wc) / target_wc * 100
    if deviation > 15:
        report("word_count", "warning", "scene_cards",
               f"Total scene word count ({total_scene_wc:,}) deviates {deviation:.1f}% from target ({target_wc:,}); max allowed: 15%")
    else:
        print(f"    Total: {total_scene_wc:,} vs target {target_wc:,} ({deviation:.1f}% deviation) — OK")

    # -----------------------------------------------------------------------
    # Scene Type Balance
    # -----------------------------------------------------------------------
    print("\n  --- Scene Type Balance ---")

    sorted_cards = sorted(cards, key=lambda x: (x[1].get("chapter_number", 0), x[1].get("scene_number", 0)))
    scene_types = [(c[1].get("chapter_number"), c[1].get("scene_type")) for c in sorted_cards]

    # Check consecutive action scenes (max 4)
    consecutive_action = 0
    max_action_run = 0
    action_run_start = None
    for ch, st in scene_types:
        if st == "action":
            if consecutive_action == 0:
                action_run_start = ch
            consecutive_action += 1
            if consecutive_action > max_action_run:
                max_action_run = consecutive_action
        else:
            if consecutive_action > 4:
                report("scene_balance", "warning", "scene_cards",
                       f"{consecutive_action} consecutive action scenes starting at chapter {action_run_start}")
            consecutive_action = 0
    if consecutive_action > 4:
        report("scene_balance", "warning", "scene_cards",
               f"{consecutive_action} consecutive action scenes starting at chapter {action_run_start}")

    # Check consecutive sequel scenes (max 2)
    consecutive_sequel = 0
    sequel_run_start = None
    max_sequel_run = 0
    for ch, st in scene_types:
        if st == "sequel":
            if consecutive_sequel == 0:
                sequel_run_start = ch
            consecutive_sequel += 1
            if consecutive_sequel > max_sequel_run:
                max_sequel_run = consecutive_sequel
        else:
            if consecutive_sequel > 2:
                report("scene_balance", "warning", "scene_cards",
                       f"{consecutive_sequel} consecutive sequel scenes starting at chapter {sequel_run_start}")
            consecutive_sequel = 0
    if consecutive_sequel > 2:
        report("scene_balance", "warning", "scene_cards",
               f"{consecutive_sequel} consecutive sequel scenes starting at chapter {sequel_run_start}")

    print(f"    Max consecutive action: {max_action_run} (limit: 4)")
    print(f"    Max consecutive sequel: {max_sequel_run} (limit: 2)")


# ---------------------------------------------------------------------------
# TASK 3: Pipeline Readiness
# ---------------------------------------------------------------------------
def pipeline_readiness(seed: dict, cards: list[tuple[str, dict]]):
    print("\n" + "=" * 60)
    print("TASK 3: Pipeline Readiness Check")
    print("=" * 60)

    # Test StoryState initialization
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    pipeline_ok = True

    try:
        from memory.story_state import StoryState
        state = StoryState(":memory:")
        state.init_from_concept_seed(seed)
        chars = state.get_all_characters()
        print(f"    Characters loaded: {len(chars)}")
        # Try get_all_plot_threads — may not exist
        if hasattr(state, "get_all_plot_threads"):
            threads = state.get_all_plot_threads()
            print(f"    Plot threads: {len(threads)}")
        elif hasattr(state, "get_active_threads"):
            threads = state.get_active_threads()
            print(f"    Active threads: {len(threads)} (get_all_plot_threads not found, using get_active_threads)")
        else:
            print("    Plot threads: N/A (no accessor method found)")
        print("    Story state initialization: OK")
    except Exception as e:
        report("pipeline", "critical", "story_state.py", f"StoryState.init_from_concept_seed failed: {e}")
        pipeline_ok = False

    # Test scene card loading
    try:
        ok_count = 0
        for filepath, card in cards:
            fname = os.path.basename(filepath)
            mission = card.get("mission")
            tp = card.get("turning_point")
            if not mission:
                report("pipeline", "critical", fname, "Empty mission field — pipeline will reject")
                pipeline_ok = False
            if not tp:
                report("pipeline", "critical", fname, "Empty turning_point field — pipeline will reject")
                pipeline_ok = False
            ok_count += 1
        print(f"    Scene cards loadable: {ok_count}/{len(cards)}")
        if ok_count == len(cards):
            print("    All scene cards loadable: OK")
    except Exception as e:
        report("pipeline", "critical", "scene_cards", f"Scene card loading failed: {e}")
        pipeline_ok = False

    return pipeline_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Load data
    print("Loading story bible data...")
    with open(CONCEPT_SEED_PATH, "r", encoding="utf-8") as f:
        seed = json.load(f)

    card_files = sorted(SCENE_CARDS_DIR.glob("chapter_*_scene_*.json"))
    cards = []
    for fp in card_files:
        with open(fp, "r", encoding="utf-8") as f:
            cards.append((str(fp), json.load(f)))
    print(f"  Loaded concept seed + {len(cards)} scene cards\n")

    # Task 1
    validate_concept_seed(seed, "concept_seed.json")
    validate_scene_cards(cards)

    # Task 2
    story_logic_audit(seed, cards)

    # Task 3
    pipeline_ok = pipeline_readiness(seed, cards)

    # ---------------------------------------------------------------------------
    # TASK 4: Report
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("VALIDATION REPORT")
    print("=" * 60)

    if not issues:
        print("\nStory bible is pipeline-ready. No issues found.")
        return 0

    # Group by category
    categories = {}
    for issue in issues:
        cat = issue["category"]
        categories.setdefault(cat, []).append(issue)

    # Schema violations
    schema_issues = categories.get("schema", [])
    if schema_issues:
        print(f"\n1. SCHEMA VIOLATIONS ({len(schema_issues)})")
        print("-" * 40)
        for i in schema_issues:
            sev = i["severity"].upper()
            print(f"  [{sev}] {i['file']}: {i['description']}")

    # Story logic
    logic_cats = ["hook_integrity", "subplot_integrity", "revelation_integrity", "character_arc", "word_count", "scene_balance"]
    logic_issues = []
    for cat in logic_cats:
        logic_issues.extend(categories.get(cat, []))
    if logic_issues:
        print(f"\n2. STORY LOGIC ISSUES ({len(logic_issues)})")
        print("-" * 40)
        for i in logic_issues:
            sev = i["severity"].upper()
            print(f"  [{sev}] {i['category']}: {i['description']}")

    # Pipeline
    pipeline_issues = categories.get("pipeline", [])
    print(f"\n3. PIPELINE READINESS")
    print("-" * 40)
    if pipeline_issues:
        for i in pipeline_issues:
            sev = i["severity"].upper()
            print(f"  [{sev}] {i['file']}: {i['description']}")
        print(f"  Result: FAIL")
    else:
        print(f"  Result: PASS")

    # Summary
    critical = len([i for i in issues if i["severity"] == "critical"])
    warnings = len([i for i in issues if i["severity"] == "warning"])
    info = len([i for i in issues if i["severity"] == "info"])
    print(f"\nTOTAL: {len(issues)} issues — {critical} critical, {warnings} warnings, {info} info")

    if critical > 0:
        print("\nStory bible has critical issues that must be resolved before pipeline entry.")
        return 1
    elif warnings > 0:
        print("\nStory bible has warnings but no critical blockers. Review recommended before pipeline entry.")
        return 0
    else:
        print("\nStory bible is pipeline-ready with minor informational notes.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
