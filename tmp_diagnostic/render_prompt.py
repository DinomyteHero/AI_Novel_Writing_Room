"""One-shot dump of the drafter prompt for ch01_sc01 of Ruusan (dry-run, offline)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.audit_phase0 import _render_prose_stylist_prompt, _synthesize_brief

BOOK = Path("data/franchises/star-wars-legends-eu/books/the-ruusan-atonement")
CARD = BOOK / "scene_cards" / "chapter_01_scene_01.json"
SEED = BOOK / "concept_seed.json"

with CARD.open(encoding="utf-8") as fh:
    card = json.load(fh)

system, user = _render_prose_stylist_prompt(
    concept_seed_path=SEED,
    scene_card=card,
    dynamic_feedback="",
)

brief = _synthesize_brief(card)

out = Path("tmp_diagnostic")
(out / "ch01_sc01_system.txt").write_text(system, encoding="utf-8")
(out / "ch01_sc01_user.txt").write_text(user, encoding="utf-8")
(out / "ch01_sc01_brief.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"System: {len(system):,} chars")
print(f"User:   {len(user):,} chars")
print(f"Brief anti_patterns: {brief.get('anti_patterns', [])}")
print()
print("--- Locations of key strings in USER prompt ---")
for needle, label in [
    ("Diagnostic-voice trap", "scene-card notes trap"),
    ("CRITICAL TRAP TO AVOID", "voice_definition Ben trap"),
    ("diagnostic-voice discipline", "R11 rule"),
    ("Concept-vs-sensation", "R8 rule"),
    ("energy field", "franchise_terminology_notes"),
    ("Anti-Patterns", "brief anti_patterns header"),
    ("## Voice Rules", "voice rules block header"),
    ("## Scene Card", "scene card header"),
    ("## Generation Brief", "brief header"),
]:
    idx = user.find(needle)
    if idx >= 0:
        line = user[:idx].count("\n") + 1
        pct = 100.0 * idx / max(len(user), 1)
        print(f"  {label!r:45s} found at char {idx:>6} / line {line:>4} ({pct:.1f}% through)")
    else:
        print(f"  {label!r:45s} NOT FOUND")
