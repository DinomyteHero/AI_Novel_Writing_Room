"""Runtime flag resolution for the architecture upgrade.

Provides two entry points used by the orchestrator, CLI, and tests:

- ``load_runtime_flags(...)`` builds the merged flag dictionary (settings →
  franchise override → book override → CLI override), returning a dict rooted
  at ``{"runtime": {...}}`` so call-sites can chain ``.get()`` naturally.
- ``resolve_flag("runtime.foo.bar", ...)`` returns a single value by dotted key.

Precedence (first match wins, highest priority last in merge order):

    config/settings.yaml  <  franchise runtime_overrides.yaml  <
    book runtime_overrides.yaml  <  CLI ``--runtime-flag`` overrides

See ``docs/architecture/architecture_upgrade_spec.md`` §4.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml

_DEFAULT_SETTINGS_PATH = Path("config/settings.yaml")


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Runtime flag file {path} must be a mapping at root, got {type(data).__name__}")
    return data


def _deep_merge(base: dict, overlay: Mapping) -> dict:
    """Recursive merge. Overlay wins at every scalar leaf.

    Lists are replaced wholesale (not concatenated) so whitelists in
    overrides fully supersede the defaults.
    """
    out = deepcopy(base)
    for key, value in overlay.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, Mapping)
        ):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _coerce_cli_value(raw: str) -> Any:
    """Coerce a CLI override string like ``true`` or ``0.5`` to a typed value.

    Uses YAML's scalar parser so ``true``/``false``/``null``/ints/floats/lists
    come out typed, while ambiguous strings stay as strings.
    """
    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw
    return value


def parse_cli_overrides(raw_items: list[str] | None) -> dict:
    """Parse ``--runtime-flag key=value`` items into a nested dict.

    Example::

        parse_cli_overrides(["runtime.firewall.enabled=true",
                             "runtime.firewall.successor_classifier.jaccard_threshold=0.4"])

    returns::

        {"runtime": {"firewall": {"enabled": True,
                                  "successor_classifier": {"jaccard_threshold": 0.4}}}}
    """
    out: dict = {}
    if not raw_items:
        return out
    for item in raw_items:
        if not item or "=" not in item:
            raise ValueError(f"--runtime-flag expects key=value form, got {item!r}")
        key, _, raw_value = item.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f"--runtime-flag has empty key in {item!r}")
        value = _coerce_cli_value(raw_value.strip())
        _set_dotted(out, key, value)
    return out


def _set_dotted(target: dict, dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    cursor = target
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


def _get_dotted(source: Mapping, dotted_key: str, default: Any = None) -> Any:
    cursor: Any = source
    for part in dotted_key.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def _franchise_override_path(base_dir: Path, franchise_slug: str | None) -> Path | None:
    if not franchise_slug:
        return None
    return base_dir / "data" / "franchises" / franchise_slug / "runtime_overrides.yaml"


def _book_override_path(
    base_dir: Path, franchise_slug: str | None, book_slug: str | None,
) -> Path | None:
    if not (franchise_slug and book_slug):
        return None
    return (
        base_dir / "data" / "franchises" / franchise_slug
        / "books" / book_slug / "runtime_overrides.yaml"
    )


def _derive_slugs_from_seed(concept_seed: Mapping) -> tuple[str | None, str | None]:
    """Extract (franchise_slug, book_slug) using ProjectPaths' slugifier so
    override-file paths match what ProjectPaths resolves to.
    """
    from src.project_paths import ProjectPaths  # local import to avoid cycles

    paths = ProjectPaths.from_concept_seed(dict(concept_seed))
    return paths.franchise_slug, paths.project_slug


def load_runtime_flags(
    *,
    concept_seed: Mapping | None = None,
    cli_overrides: list[str] | Mapping | None = None,
    settings: Mapping | None = None,
    settings_path: str | Path = _DEFAULT_SETTINGS_PATH,
    base_dir: str | Path = ".",
) -> dict:
    """Build the merged runtime-flag dictionary.

    Returned dict is rooted at ``{"runtime": {...}}`` so callers can use the
    dotted ``.get()`` chain shown in the spec.
    """
    base_path = Path(base_dir)

    if settings is None:
        settings_file = Path(settings_path)
        if not settings_file.is_absolute():
            settings_file = base_path / settings_file
        loaded_settings = _load_yaml(settings_file)
    else:
        loaded_settings = dict(settings)

    merged: dict = {"runtime": deepcopy(loaded_settings.get("runtime", {}))}

    franchise_slug = None
    book_slug = None
    if concept_seed is not None:
        try:
            franchise_slug, book_slug = _derive_slugs_from_seed(concept_seed)
        except Exception:  # noqa: BLE001 -- missing meta is not fatal
            franchise_slug, book_slug = None, None

    franchise_path = _franchise_override_path(base_path, franchise_slug)
    if franchise_path is not None and franchise_path.exists():
        franchise_overrides = _load_yaml(franchise_path)
        if "runtime" in franchise_overrides:
            merged = _deep_merge(merged, {"runtime": franchise_overrides["runtime"]})

    book_path = _book_override_path(base_path, franchise_slug, book_slug)
    if book_path is not None and book_path.exists():
        book_overrides = _load_yaml(book_path)
        if "runtime" in book_overrides:
            merged = _deep_merge(merged, {"runtime": book_overrides["runtime"]})

    if cli_overrides:
        if isinstance(cli_overrides, list):
            cli_dict = parse_cli_overrides(cli_overrides)
        elif isinstance(cli_overrides, Mapping):
            cli_dict = dict(cli_overrides)
        else:
            raise TypeError(
                f"cli_overrides must be list[str] or Mapping, got {type(cli_overrides).__name__}"
            )
        if cli_dict:
            merged = _deep_merge(merged, cli_dict)

    return merged


def resolve_flag(
    key: str,
    *,
    concept_seed: Mapping | None = None,
    cli_overrides: list[str] | Mapping | None = None,
    settings: Mapping | None = None,
    settings_path: str | Path = _DEFAULT_SETTINGS_PATH,
    base_dir: str | Path = ".",
    default: Any = None,
) -> Any:
    """Resolve a single dotted flag key (e.g. ``runtime.firewall.enabled``)."""
    merged = load_runtime_flags(
        concept_seed=concept_seed,
        cli_overrides=cli_overrides,
        settings=settings,
        settings_path=settings_path,
        base_dir=base_dir,
    )
    return _get_dotted(merged, key, default)
