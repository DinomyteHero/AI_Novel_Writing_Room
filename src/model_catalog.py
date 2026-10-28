"""OpenRouter's public model catalog, cached for a day beside the settings.

The hand-picked models under ``models.cloud.models`` in config/settings.yaml
come first. The catalog adds each OpenRouter model's price, and the newest
model of each recent family from the main makers, so new models appear
without a code change. Older catalog models stay, hidden, so a chat or role
that chose one keeps working. Nothing switches to a discovered model by
itself: they are only offered.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

CATALOG_URL = "https://openrouter.ai/api/v1/models"
MAX_AGE_SECONDS = 24 * 60 * 60
MAKERS = ("anthropic", "google", "openai", "deepseek", "x-ai", "moonshotai", "z-ai", "qwen", "mistralai")
# A family is offered while its newest model is within six months of the
# newest model in the catalog.
RECENT_SECONDS = 183 * 24 * 60 * 60
# Models made for something other than conversation and prose.
_NOT_FOR_PROSE = re.compile(
    r"\b(code|coder|codex|codestral|devstral|vision|vl|image|audio|voxtral|guard|safeguard|search|research)\b"
)
# Words that mark a release rather than a different model.
_RELEASE_WORDS = {"v", "preview", "exp", "latest"}


def cache_path(config_path: str | Path) -> Path:
    return Path(config_path).with_name("openrouter_models.json")


def fetch() -> list[dict]:
    response = httpx.get(CATALOG_URL, timeout=20)
    response.raise_for_status()
    return response.json()["data"]


def _per_million(value) -> float | None:
    try:
        price = float(value) * 1_000_000
    except (TypeError, ValueError):
        return None
    return round(price, 4) if price >= 0 else None


def slim(models: list[dict]) -> list[dict]:
    """What the app keeps of each catalog entry."""
    out = []
    for m in models:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        arch = m.get("architecture") or {}
        pricing = m.get("pricing") or {}
        price_in, price_out = _per_million(pricing.get("prompt")), _per_million(pricing.get("completion"))
        out.append({
            "id": m["id"],
            "name": m.get("name") or m["id"],
            "created": int(m.get("created") or 0),
            "context": int(m.get("context_length") or 0),
            "price": {"in": price_in, "out": price_out} if price_in is not None and price_out is not None else None,
            "text": "text" in (arch.get("input_modalities") or ["text"])
                    and (arch.get("output_modalities") or ["text"]) == ["text"],
            "tools": "tools" in (m.get("supported_parameters") or []),
            # The catalog lists efforts strongest first; the app shows them weakest first.
            "efforts": list(reversed((m.get("reasoning") or {}).get("supported_efforts") or [])),
            "expires": m.get("expiration_date"),
        })
    return out


def family(model_id: str) -> str:
    """A model's name without its version: anthropic/claude-opus-5.5 and
    anthropic/claude-opus-5 are both anthropic/claude-opus."""
    maker, _, name = model_id.partition("/")
    words = [re.sub(r"[\d.]+", "", word) for word in name.split("-")]
    return maker + "/" + "-".join(w for w in words if w and w not in _RELEASE_WORDS)


def discovered(records: list[dict]) -> dict[str, dict]:
    """Entries for ``models.cloud.models``, keyed by OpenRouter id: the newest
    of each recent family offered, the rest hidden."""
    usable = [
        r for r in records
        if r["id"].split("/")[0] in MAKERS and ":" not in r["id"] and r["text"] and r["tools"]
        and not _NOT_FOR_PROSE.search(r["id"].split("/", 1)[-1])
    ]
    if not usable:
        return {}
    recent = max(r["created"] for r in usable) - RECENT_SECONDS
    newest = {}
    for r in sorted(usable, key=lambda r: r["created"]):
        newest[family(r["id"])] = r["id"]
    offered = set(newest.values())
    out = {}
    for r in sorted(usable, key=lambda r: (r["id"].split("/")[0], -r["created"])):
        entry = {"id": r["id"], "label": r["name"].split(": ", 1)[-1], "discovered": True}
        if r["context"]:
            entry["context"] = r["context"]
        if r["price"]:
            entry["price"] = r["price"]
        if r["efforts"]:
            entry["efforts"] = r["efforts"]
        if r["id"] not in offered or r["created"] < recent or r["expires"]:
            entry["hidden"] = True
        out[r["id"]] = entry
    return out


def load(config_path: str | Path) -> list[dict]:
    try:
        return json.loads(cache_path(config_path).read_text(encoding="utf-8"))["models"]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def apply(config: dict, records: list[dict]) -> dict:
    """Add the catalog to an OpenRouter backend named ``cloud``: prices (and
    context sizes not given) for the configured models, then the discovered ones."""
    cloud = (config.get("models") or {}).get("cloud")
    if not records or not isinstance(cloud, dict) or "openrouter.ai" not in str(cloud.get("base_url", "")):
        return config
    models = cloud.setdefault("models", {})
    by_id = {r["id"]: r for r in records}
    configured = set()
    for entry in models.values():
        model_id = entry.get("id") if isinstance(entry, dict) else entry
        configured.add(model_id)
        found = by_id.get(model_id)
        if found and isinstance(entry, dict):
            if found["price"]:
                entry.setdefault("price", found["price"])
            if found["context"]:
                entry.setdefault("context", found["context"])
    for model_id, entry in discovered(records).items():
        if model_id not in configured and model_id not in models:
            models[model_id] = entry
    return config


def stale(config_path: str | Path, now: float | None = None) -> bool:
    try:
        fetched = float(json.loads(cache_path(config_path).read_text(encoding="utf-8"))["fetched"])
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return (time.time() if now is None else now) - fetched >= MAX_AGE_SECONDS


def refresh(config_path: str | Path, fetch: Callable[[], list[dict]] = fetch, now: float | None = None) -> bool:
    """Fetch the catalog and cache it. On any failure the cache stays as it
    was, and so do the model lists."""
    try:
        records = slim(fetch())
    except Exception as exc:  # offline, rate-limited or a changed format: keep what we have
        logger.info("Couldn't refresh the OpenRouter model list: %s", exc)
        return False
    if not records:
        return False
    path = cache_path(config_path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched": time.time() if now is None else now, "models": records}), encoding="utf-8")
    os.replace(tmp, path)
    return True
