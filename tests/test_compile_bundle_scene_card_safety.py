"""Regression: a scene-card write that produces nothing must not wipe the
existing scene_cards/ tree (the live pipeline input).

The previous _write_scene_cards unlinked every card up front, then translated;
if every card failed translation (or the input list was empty) it left the
canonical tree empty.
"""

from scripts.compile_bundle import CompileReport, _write_scene_cards


def test_no_translatable_cards_preserves_existing_tree(tmp_path):
    out = tmp_path / "scene_cards"
    out.mkdir()
    keep = out / "chapter_01_scene_01.json"
    keep.write_text('{"keep": true}\n', encoding="utf-8")

    report = CompileReport(franchise="f", book="b")
    written = _write_scene_cards(
        [], output_dir=out, structural_overrides=None, schema=None, report=report
    )

    assert written == 0
    assert keep.exists(), "existing scene cards must survive a no-op compile"
    assert keep.read_text(encoding="utf-8") == '{"keep": true}\n'
