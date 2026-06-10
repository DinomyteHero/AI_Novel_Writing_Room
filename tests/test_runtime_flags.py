"""Tests for the runtime-flag resolver."""

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
        "runtime.lean_prose_only.enabled=true",
        "runtime.rhythm_editor.max_changed_ratio=0.4",
        "runtime.rhythm_editor.trigger_codes=[em_dash_overuse]",
    ])
    assert parsed == {
        "runtime": {
            "lean_prose_only": {
                "enabled": True,
            },
            "rhythm_editor": {
                "max_changed_ratio": 0.4,
                "trigger_codes": ["em_dash_overuse"],
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
        "runtime": {"lean_prose_only": {"enabled": False}},
    })
    merged = load_runtime_flags(
        settings_path=settings_path, base_dir=tmp_path,
    )
    assert merged == {"runtime": {"lean_prose_only": {"enabled": False}}}


def test_load_runtime_flags_applies_franchise_then_book_overrides(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, {
        "runtime": {
            "lean_prose_only": {"enabled": False},
            "chapter_packet": {"enabled": False, "fallback_on_error": True},
        },
    })

    franchise_dir = tmp_path / "data" / "franchises" / "test-franchise"
    franchise_dir.mkdir(parents=True)
    _write_yaml(franchise_dir / "runtime_overrides.yaml", {
        "runtime": {"lean_prose_only": {"enabled": True}},
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
    assert merged["runtime"]["lean_prose_only"]["enabled"] is True
    assert merged["runtime"]["chapter_packet"]["enabled"] is True
    # Base value preserved
    assert merged["runtime"]["chapter_packet"]["fallback_on_error"] is True


def test_cli_override_beats_everything(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, {
        "runtime": {"lean_prose_only": {"enabled": False}},
    })
    merged = load_runtime_flags(
        settings_path=settings_path,
        base_dir=tmp_path,
        cli_overrides=["runtime.lean_prose_only.enabled=true"],
    )
    assert merged["runtime"]["lean_prose_only"]["enabled"] is True


def test_resolve_flag_returns_default_for_missing_key(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, {"runtime": {}})
    value = resolve_flag(
        "runtime.lean_prose_only.enabled",
        settings_path=settings_path,
        base_dir=tmp_path,
        default=False,
    )
    assert value is False


def test_resolve_flag_returns_value(tmp_path: Path):
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, {
        "runtime": {"lean_prose_only": {"enabled": True}},
    })
    value = resolve_flag(
        "runtime.lean_prose_only.enabled",
        settings_path=settings_path,
        base_dir=tmp_path,
    )
    assert value is True


def test_shipping_defaults_all_safe():
    """Every flag in the shipped config/settings.yaml must default to the
    safe value (False or empty list). The exception is ``chapter_packet.enabled``
    — D4a rolled it on as the drafter's single inspectable runtime contract
    after Phase 0 audit and packet parity both passed on shipping books."""
    merged = load_runtime_flags(settings_path=Path("config/settings.yaml"))
    runtime = merged["runtime"]
    assert runtime["chapter_packet"]["enabled"] is True
    assert runtime["chapter_packet"]["fallback_on_error"] is True
    assert runtime["revision_debt"]["enabled"] is False
    assert runtime["promise_ledger"]["enabled"] is False
    assert runtime["rhythm_validator"]["enabled"] is False
    assert runtime["rhythm_editor"]["enabled"] is False
    assert runtime["continuity_validator"]["enabled"] is False


# --- Slice 2 shipping-book protection ----------------------------------------


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_run_chapter_packet_by_default(book_slug: str):
    """Post-D4a rollout: the chapter packet is the drafter's single
    inspectable runtime contract. Phase 0 audit + packet parity both pass
    for Ruusan and Betrayal at HEAD, so the packet ships on by default
    (config/settings.yaml). This guard catches accidental per-book
    runtime_overrides that would disable the packet path.
    """
    import json
    seed_path = Path(
        f"data/franchises/star-wars-legends-eu/books/{book_slug}/concept_seed.json"
    )
    if not seed_path.exists():
        pytest.skip(f"seed not present: {seed_path}")
    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    merged = load_runtime_flags(concept_seed=seed)
    cp = merged["runtime"]["chapter_packet"]
    assert cp["enabled"] is True, (
        f"{book_slug} must run with runtime.chapter_packet.enabled=true "
        "(post-D4a shipping default). If this guard trips, a per-book "
        "runtime_overrides.yaml has disabled the packet — revert it."
    )
    # fallback_on_error is a degradation policy, not a safety flag. Keep
    # the safe default (true) so a compile regression reverts to flat
    # context instead of aborting the run.
    assert cp["fallback_on_error"] is True


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_revision_debt_off(book_slug: str):
    """Spec §6.8: revision_debt is safe-off until the book-scoped SQLite
    migration has run and a parity test confirms no behavioral change."""
    import json
    seed_path = Path(
        f"data/franchises/star-wars-legends-eu/books/{book_slug}/concept_seed.json"
    )
    if not seed_path.exists():
        pytest.skip(f"seed not present: {seed_path}")
    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    merged = load_runtime_flags(concept_seed=seed)
    assert merged["runtime"]["revision_debt"]["enabled"] is False, (
        f"{book_slug} must keep runtime.revision_debt.enabled=false until a "
        "parity test and the SQLite migration approve the flip"
    )


# --- Slice 3 shipping-book protection ----------------------------------------


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_promise_ledger_off(book_slug: str):
    """Spec §7.5: promise_ledger populates the active_promises overlay slot
    and can induce forced-payoff drift in drafter prose. Keep the flag off for
    Ruusan and Betrayal until the per-book parity test approves the flip and
    the seeded ledger has been human-spot-checked.
    """
    import json
    seed_path = Path(
        f"data/franchises/star-wars-legends-eu/books/{book_slug}/concept_seed.json"
    )
    if not seed_path.exists():
        pytest.skip(f"seed not present: {seed_path}")
    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    merged = load_runtime_flags(concept_seed=seed)
    assert merged["runtime"]["promise_ledger"]["enabled"] is False, (
        f"{book_slug} must keep runtime.promise_ledger.enabled=false until the "
        "per-book parity test (spec §11.6.3) approves the flip"
    )


# --- Rhythm + continuity validator shipping-book protection ----------------


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_rhythm_validator_off(book_slug: str):
    """RhythmValidator is telemetry-only but adds new revision_debt rows.
    Keep off on shipping books until a per-book review confirms the per-scene
    issue volume is signal rather than noise.
    """
    import json
    seed_path = Path(
        f"data/franchises/star-wars-legends-eu/books/{book_slug}/concept_seed.json"
    )
    if not seed_path.exists():
        pytest.skip(f"seed not present: {seed_path}")
    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    merged = load_runtime_flags(concept_seed=seed)
    assert merged["runtime"]["rhythm_validator"]["enabled"] is False, (
        f"{book_slug} must keep runtime.rhythm_validator.enabled=false until "
        "the per-book review approves the rhythm-telemetry surface"
    )


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_continuity_validator_off(book_slug: str):
    """Cross-chapter continuity validator runs at bundle-compile time and
    reads optional scene-card fields (end_state, start_state, objects_at_*).
    The shipping books don't have those fields populated yet, so enabling the
    flag would be a no-op at best and a confusing report at worst. Keep off
    until the per-book scene cards have been migrated.
    """
    import json
    seed_path = Path(
        f"data/franchises/star-wars-legends-eu/books/{book_slug}/concept_seed.json"
    )
    if not seed_path.exists():
        pytest.skip(f"seed not present: {seed_path}")
    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    merged = load_runtime_flags(concept_seed=seed)
    assert merged["runtime"]["continuity_validator"]["enabled"] is False, (
        f"{book_slug} must keep runtime.continuity_validator.enabled=false "
        "until end_state / start_state fields are populated on its scene cards"
    )


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_rhythm_editor_off(book_slug: str):
    """RhythmEditor mutates saved prose via bounded literal substitutions.
    Keep off on shipping books until a per-book parity test confirms the edits
    land within voice.
    """
    import json
    seed_path = Path(
        f"data/franchises/star-wars-legends-eu/books/{book_slug}/concept_seed.json"
    )
    if not seed_path.exists():
        pytest.skip(f"seed not present: {seed_path}")
    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    merged = load_runtime_flags(concept_seed=seed)
    rhythm_editor = merged["runtime"]["rhythm_editor"]
    assert rhythm_editor["enabled"] is False, (
        f"{book_slug} must keep runtime.rhythm_editor.enabled=false until a "
        "per-book parity test confirms the literal-edit pass preserves voice"
    )
    # Belt-and-braces: ensure the safety caps stay tight if someone flips the
    # flag without re-tuning the bounds.
    assert rhythm_editor["max_edits"] <= 10
    assert rhythm_editor["max_total_changed_chars"] <= 2500
    assert rhythm_editor["max_changed_ratio"] <= 0.20


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_declared_state_off(book_slug: str):
    """Declared-state apply writes characters.status from scene-card
    end_state declarations at save time. The shipping books' scene cards
    don't carry start_state / end_state fields, so enabling the flag would
    be a no-op at best; keep off until their cards are migrated and a
    per-book parity test confirms the writes.
    """
    import json
    seed_path = Path(
        f"data/franchises/star-wars-legends-eu/books/{book_slug}/concept_seed.json"
    )
    if not seed_path.exists():
        pytest.skip(f"seed not present: {seed_path}")
    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    merged = load_runtime_flags(concept_seed=seed)
    assert merged["runtime"]["declared_state"]["enabled"] is False, (
        f"{book_slug} must keep runtime.declared_state.enabled=false until "
        "its scene cards carry declarations and a per-book parity test passes"
    )
