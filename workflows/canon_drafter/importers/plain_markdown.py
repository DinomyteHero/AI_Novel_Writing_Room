"""Build a canon-drafter artifact from a hand-written markdown file."""

from __future__ import annotations

from pathlib import Path

from workflows._shared.markdown_parser import (
    join_prose,
    parse_bullets,
    parse_kv_block,
    parse_sections,
    read_text,
)


def import_from_markdown(path: str | Path) -> dict:
    """Return a canon-drafter artifact dict from a markdown file."""
    text = read_text(path)
    sections = parse_sections(text)

    constraints_kv = parse_kv_block(sections.get("canon_constraints", []))
    canon_preserved = parse_bullets(sections.get("canon_preserved", []))
    canon_overridden = parse_bullets(sections.get("canon_overridden", []))
    style_constraints = parse_bullets(sections.get("style_constraints", []))

    canon_constraints: dict = {
        "continuity": constraints_kv.get("continuity", "<EDIT_ME>"),
        "canon_preserved": canon_preserved,
        "style_constraints": style_constraints,
    }
    if "divergence_point" in constraints_kv:
        canon_constraints["divergence_point"] = constraints_kv["divergence_point"]
    if canon_overridden:
        canon_constraints["canon_overridden"] = canon_overridden

    artifact: dict = {
        "surface": "canon-drafter",
        "schema_version": "1.0",
        "canon_constraints": canon_constraints,
    }

    profile_kv = parse_kv_block(sections.get("canon_profile", []))
    cross_violations = parse_bullets(sections.get("cross_continuity_violations", []))
    meta_rules = parse_bullets(sections.get("meta_reference_rules", []))
    if profile_kv or cross_violations or meta_rules:
        canon_profile: dict = {}
        for key in (
            "franchise", "continuity", "continuity_description",
            "era_description", "narrative_register",
            "franchise_terminology_notes",
        ):
            if key in profile_kv:
                canon_profile[key] = profile_kv[key]
        if cross_violations:
            canon_profile["cross_continuity_violations"] = cross_violations
        if meta_rules:
            canon_profile["meta_reference_rules"] = meta_rules
        artifact["canon_profile"] = canon_profile

    force_kv = parse_kv_block(sections.get("force_mechanics", []))
    force_implications = parse_bullets(sections.get("force_implications", []))
    if force_kv or force_implications:
        force: dict = {}
        for key in ("primary_rule", "canon_grounding"):
            if key in force_kv:
                force[key] = force_kv[key]
        if force_implications:
            force["implications"] = force_implications
        artifact["force_mechanics"] = force

    # Terminology entries — one per `### Term: <term>` subsection.
    sub3 = parse_sections(text, level=3)
    terms = []
    for title, lines in sub3.items():
        if not title.startswith("term_"):
            continue
        term_name = title[len("term_"):].replace("_", " ")
        kv = parse_kv_block(lines)
        if "definition" not in kv or "category" not in kv:
            continue
        entry: dict = {
            "term": kv.get("term", term_name),
            "definition": kv["definition"],
            "category": kv["category"],
        }
        aliases = parse_bullets(lines)
        if aliases:
            entry["aliases"] = aliases
        if "first_appearance" in kv:
            try:
                entry["first_appearance"] = int(kv["first_appearance"])
            except ValueError:
                entry["first_appearance"] = kv["first_appearance"]
        if "usage_notes" in kv:
            entry["usage_notes"] = kv["usage_notes"]
        terms.append(entry)
    if terms:
        artifact["terminology_registry"] = terms

    return artifact
