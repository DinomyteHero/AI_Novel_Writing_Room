"""Tests for the runtime-flag resolver (Slice 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.runtime_flags import (
    _deep_merge,
    load_runtime_flags,
    parse_cli_overrides,
    resolve_flag,
)


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_parse_cli_overrides_coerces_types():
    parsed = parse_cli_overrides([
        "runtime.firewall.enabled=true",
        "runtime.firewall.successor_classifier.jaccard_threshold=0.4",
        "runtime.canon_expert.local_fixes_whitelist=[terminology_registry_swap]",
    ])
    assert parsed == {
        "runtime": {
            "firewall": {
                "enabled": True,
                "successor_classifier": {"jaccard_threshold": 0.4},
            },
            "canon_expert": {
                "local_fixes_whitelist": ["terminology_registry_swap"],
            },
        },
    }


def test_parse_cli_overrides_rejects_bad_input():
    with pytest.raises(ValueError):
        parse_cli_overrides(["badformat"])


def test_deep_merge_overlay_wins_scalar():
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    overlay = {"b": {"c": 20}}
    assert _deep_merge(base, overlay) == {"a": 1, "b": {"c": 20, "d": 3}}


def test_deep_merge_list_is_replaced_not_concatenated():
    base = {"whitelist": ["a", "b"]}
    overlay = {"whitelist": ["c"]}
    assert _deep_merge(base, overlay) == {"whitelist": ["c"]}


def test_load_runtime_flags_from_settings_only(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, {
        "runtime": {"firewall": {"enabled": False}},
    })
    merged = load_runtime_flags(
        settings_path=settings_path, base_dir=tmp_path,
    )
    assert merged == {"runtime": {"firewall": {"enabled": False}}}


def test_load_runtime_flags_applies_franchise_then_book_overrides(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, {
        "runtime": {
            "firewall": {"enabled": False},
            "chapter_packet": {"enabled": False, "fallback_on_error": True},
        },
    })

    franchise_dir = tmp_path / "data" / "franchises" / "test-franchise"
    franchise_dir.mkdir(parents=True)
    _write_yaml(franchise_dir / "runtime_overrides.yaml", {
        "runtime": {"firewall": {"enabled": True}},
    })

    book_dir = franchise_dir / "books" / "test-book"
    book_dir.mkdir(parents=True)
    _write_yaml(book_dir / "runtime_overrides.yaml", {
        "runtime": {"chapter_packet": {"enabled": True}},
    })

    concept_seed = {
        "meta": {
            "project_title": "Test Book",
            "franchise": "test-franchise",
        },
    }
    # Override the project_title slugifier → "test-book" to match our path.
    # (The slugifier lowercases and kebabifies by default.)
    merged = load_runtime_flags(
        concept_seed=concept_seed,
        settings_path=settings_path,
        base_dir=tmp_path,
    )
    assert merged["runtime"]["firewall"]["enabled"] is True
    assert merged["runtime"]["chapter_packet"]["enabled"] is True
    # Base value preserved
    assert merged["runtime"]["chapter_packet"]["fallback_on_error"] is True


def test_cli_override_beats_everything(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, {
        "runtime": {"firewall": {"enabled": False}},
    })
    merged = load_runtime_flags(
        settings_path=settings_path,
        base_dir=tmp_path,
        cli_overrides=["runtime.firewall.enabled=true"],
    )
    assert merged["runtime"]["firewall"]["enabled"] is True


def test_resolve_flag_returns_default_for_missing_key(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, {"runtime": {}})
    value = resolve_flag(
        "runtime.firewall.enabled",
        settings_path=settings_path,
        base_dir=tmp_path,
        default=False,
    )
    assert value is False


def test_resolve_flag_returns_value(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, {
        "runtime": {"firewall": {"enabled": True}},
    })
    value = resolve_flag(
        "runtime.firewall.enabled",
        settings_path=settings_path,
        base_dir=tmp_path,
    )
    assert value is True


def test_shipping_defaults_all_safe():
    """Every flag in the shipped config/settings.yaml must default to the
    safe value (False or empty list), per spec §4.2 invariant."""
    merged = load_runtime_flags(settings_path=Path("config/settings.yaml"))
    runtime = merged["runtime"]
    assert runtime["firewall"]["enabled"] is False
    assert runtime["firewall"]["successor_classifier"]["enabled"] is False
    assert runtime["chapter_packet"]["enabled"] is False
    assert runtime["revision_debt"]["enabled"] is False
    assert runtime["canon_expert"]["early_position"] is False
    assert runtime["canon_expert"]["apply_local_fixes"] is False
    assert runtime["canon_expert"]["local_fixes_whitelist"] == []
    assert runtime["promise_ledger"]["enabled"] is False
    assert runtime["continuity_log"]["enabled"] is False
    assert runtime["sociogram"]["enabled"] is False
