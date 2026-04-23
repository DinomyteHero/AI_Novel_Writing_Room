from pathlib import Path


def test_cli_wires_chapter_packet_compiler_into_orchestrator():
    src = Path("src/main.py").read_text(encoding="utf-8")

    assert "chapter_packet_compiler = build_chapter_packet_compiler(" in src
    assert "chapter_packet_compiler=chapter_packet_compiler" in src


def test_ui_wires_runtime_flags_and_chapter_packet_compiler():
    src = Path("src/ui/routes/pipeline.py").read_text(encoding="utf-8")

    assert "chapter_packet_compiler = ChapterPacketCompiler(" in src
    assert "runtime_flags = load_runtime_flags(" in src
    assert "runtime_flags=runtime_flags" in src
    assert "chapter_packet_compiler=chapter_packet_compiler" in src
