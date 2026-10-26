from pathlib import Path


def test_cli_wires_chapter_packet_compiler_into_orchestrator():
    src = Path("src/main.py").read_text(encoding="utf-8")

    assert "chapter_packet_compiler = build_chapter_packet_compiler(" in src
    assert "chapter_packet_compiler=chapter_packet_compiler" in src
