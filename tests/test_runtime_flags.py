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
    # Forward Relay v4: smart single corrective rerun defaults off.
    assert runtime["corrective_rerun"]["enabled"] is False
    assert "MISSING_TURNING_POINT" in runtime["corrective_rerun"]["trigger_codes"]
    assert "CLOSING_HOOK_VIOLATION" in runtime["corrective_rerun"]["trigger_codes"]


# --- test-bench + shipping-book protection -------------------------------


def test_testbench_classifier_smoke_book_enables_firewall():
    """The test-bench scratch book opts in to the Slice 1 firewall + classifier.

    This is the canonical flag-flip receipt per spec §4.4: non-Ruusan/non-
    Betrayal book goes first, the successor_classifier 30-label gate has
    passed, so classifier.enabled is trusted for this scratch project.
    """
    import json
    seed_path = Path(
        "data/franchises/test-bench/books/classifier-smoke-test/concept_seed.json"
    )
    if not seed_path.exists():
        pytest.skip(f"test-bench seed not present: {seed_path}")
    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    merged = load_runtime_flags(concept_seed=seed)
    fw = merged["runtime"]["firewall"]
    assert fw["enabled"] is True, (
        "test-bench runtime_overrides.yaml must enable the firewall"
    )
    assert fw["successor_classifier"]["enabled"] is True, (
        "test-bench runtime_overrides.yaml must enable the classifier"
    )


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_firewall_off(book_slug: str):
    """Ruusan + Betrayal must keep global defaults (firewall off) until their
    per-book parity tests land. This test guards against an accidental
    runtime_overrides.yaml in either book dir.
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
    fw = merged["runtime"]["firewall"]
    assert fw["enabled"] is False, (
        f"{book_slug} must keep runtime.firewall.enabled=false until its "
        "per-book parity test approves the flip (spec §4.4)"
    )
    assert fw["successor_classifier"]["enabled"] is False, (
        f"{book_slug} must keep runtime.firewall.successor_classifier.enabled=false "
        "until its parity test approves the flip"
    )


# --- Slice 2 shipping-book protection ----------------------------------------


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_chapter_packet_off(book_slug: str):
    """Spec §6.8 + §11.6.3: Ruusan and Betrayal must keep
    runtime.chapter_packet.enabled=false until their per-book parity tests
    approve the flip. An accidental override dropped under either book dir
    trips this guard so the prose-path flag cannot silently flip.
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
    assert cp["enabled"] is False, (
        f"{book_slug} must keep runtime.chapter_packet.enabled=false until "
        "the per-book parity test approves the flip (spec §6.8, §11.6.3)"
    )
    # fallback_on_error is not a safety flag but a degradation policy; assert
    # the safe default (true) stays intact so an accidental override that
    # enables packet mode still falls back to flat on error.
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


# --- Slice 4 shipping-book protection ----------------------------------------


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_sociogram_off(book_slug: str):
    """Spec §9.6: sociogram is the highest-inference-risk slot in the
    stateful-memory family. Keep the flag off on Ruusan/Betrayal until a
    non-shipping book has it flipped on and produces relationally-grounded
    prose without drift (spec §9.6 go/no-go).
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
    assert merged["runtime"]["sociogram"]["enabled"] is False
    # suggest_mode (assisted-suggestion) must also stay off \u2014 it routes to
    # revision debt but still makes an LLM call per scene.
    assert merged["runtime"]["sociogram"]["suggest_mode"] is False


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_continuity_log_off(book_slug: str):
    """Spec §8.6: the continuity extractor is the risky slice. Even with
    threshold filtering, precision < 0.90 on the labeled eval set risks
    hallucinated facts reaching the drafter. Keep the flag off on shipping
    books until the per-book eval gate passes (>= 0.95 for Ruusan).
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
    assert merged["runtime"]["continuity_log"]["enabled"] is False, (
        f"{book_slug} must keep runtime.continuity_log.enabled=false until "
        "the extractor eval gate passes (spec §8.4.3)"
    )
    # min_confidence safe default stays intact even when an override creeps in.
    assert merged["runtime"]["continuity_log"]["min_confidence"] == 0.85


# --- Forward Relay v4 shipping-book protection --------------------------------


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_corrective_rerun_off(book_slug: str):
    """Forward Relay v4: the smart corrective rerun is a new retry-branch path
    under the forward-only relay. Ruusan and Betrayal keep the flag off until
    their per-book parity tests approve the flip; same discipline as every
    other architecture-upgrade flag.
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
    assert merged["runtime"]["corrective_rerun"]["enabled"] is False, (
        f"{book_slug} must keep runtime.corrective_rerun.enabled=false until "
        "the per-book parity test approves the flip"
    )


@pytest.mark.parametrize("book_slug", [
    "the-ruusan-atonement",
    "legacy-of-the-force-betrayal",
])
def test_shipping_books_keep_canon_apply_local_fixes_off(book_slug: str):
    """Slice 11.1 (Forward Relay v4): narrow canon repair mutates saved prose
    via literal substitution. Keep off on Ruusan/Betrayal until a non-shipping
    book has flipped it on and proven the whitelist is safe in practice.
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
    assert merged["runtime"]["canon_expert"]["apply_local_fixes"] is False, (
        f"{book_slug} must keep runtime.canon_expert.apply_local_fixes=false "
        "until a parity test confirms no prose drift from whitelisted fixes"
    )
    # Belt-and-braces: whitelist must stay empty so an accidental flag flip
    # still has no whitelisted category to act on.
    assert merged["runtime"]["canon_expert"]["local_fixes_whitelist"] == []
