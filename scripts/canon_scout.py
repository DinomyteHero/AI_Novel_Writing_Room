"""Static Canon Scout enrichment for scene cards.

Default mode is a no-API dry run: reports missing/stale guidance sidecars,
token estimates, and projected OpenRouter cost. Use --execute to spend API
calls and write data/franchises/<franchise>/books/<book>/canon_guidance/*.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.canon_scout import CanonScout, build_canon_scout_context
from src.model_router import ModelRouter
from src.pipeline.canon_guidance import CanonGuidanceStore, estimate_tokens
from src.project_paths import ProjectPaths


OPENROUTER_PRICING_PER_MILLION = {
    "x-ai/grok-4.1-fast": {"input": 0.20, "output": 0.50},
    "openai/gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    "deepseek/deepseek-v4-flash": {"input": 0.14, "output": 0.28},
}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--franchise", required=True, help="Franchise slug")
    parser.add_argument("--book", required=True, help="Book slug")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--chapter", type=int, help="Only scout one chapter")
    parser.add_argument("--scene", type=int, help="Only scout one scene number")
    parser.add_argument("--force", action="store_true", help="Regenerate fresh sidecars too")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Spend API calls and write canon_guidance sidecars",
    )
    parser.add_argument(
        "--rekey-only",
        action="store_true",
        help=(
            "Do not regenerate content; recompute input_hash on each stale "
            "sidecar against current inputs and write it back. Use after "
            "reviewing input drift (e.g. seed cleanup, additive scene-card "
            "enrichment) and confirming the existing canon analysis still "
            "applies. Skips missing/invalid sidecars."
        ),
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=0.50,
        help="Abort --execute when estimated cost exceeds this cap",
    )
    parser.add_argument(
        "--estimated-output-tokens",
        type=int,
        default=1200,
        help="Dry-run output token estimate per scene",
    )
    parser.add_argument(
        "--no-prompt-snapshots",
        action="store_true",
        help="Do not write canon_guidance/_prompt_snapshots/*.md during --execute",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary")
    return parser.parse_args(argv)


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _load_scene_cards(paths: ProjectPaths, *, chapter: int | None, scene: int | None) -> list[dict]:
    cards: list[dict] = []
    for path in sorted(paths.scene_cards_dir.glob("*.json")):
        card = _load_json(path)
        if chapter is not None and card.get("chapter_number") != chapter:
            continue
        if scene is not None and card.get("scene_number") != scene:
            continue
        cards.append(card)
    return cards


def _load_blueprints(paths: ProjectPaths) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not paths.chapter_blueprints_dir.exists():
        return out
    for path in sorted(paths.chapter_blueprints_dir.glob("chapter_*.json")):
        try:
            chapter_number = int(path.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        out[chapter_number] = _load_json(path)
    return out


def _resolve_canon_scout_model(config_path: Path) -> str:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    routing = config.get("agent_routing", {}).get("canon_scout", {})
    model_key = routing.get("model", "grok41fast")
    cloud_models = config.get("models", {}).get("cloud", {}).get("models", {})
    return cloud_models.get(model_key, model_key)


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = OPENROUTER_PRICING_PER_MILLION.get(model)
    if pricing is None:
        return 0.0
    return (
        (input_tokens * pricing["input"]) + (output_tokens * pricing["output"])
    ) / 1_000_000


def _build_plan(args: argparse.Namespace) -> dict[str, Any]:
    paths = ProjectPaths(
        args.book,
        base_dir=args.base_dir,
        franchise_slug=args.franchise,
    )
    concept_seed = _load_json(paths.concept_seed_path)
    blueprints = _load_blueprints(paths)
    store = CanonGuidanceStore(
        paths.canon_guidance_dir,
        canon_contract_path=paths.canon_contract_path,
    )
    model = _resolve_canon_scout_model(Path(args.config))
    cards = _load_scene_cards(paths, chapter=args.chapter, scene=args.scene)

    targets = []
    total_input_tokens = 0
    for card in cards:
        blueprint = blueprints.get(int(card.get("chapter_number") or 0), {})
        freshness = store.freshness(
            concept_seed=concept_seed,
            chapter_blueprint=blueprint,
            scene_card=card,
        )
        should_run = args.force or not freshness.is_fresh
        prompt = build_canon_scout_context(
            concept_seed=concept_seed,
            chapter_blueprint=blueprint,
            scene_card=card,
            canon_contract_text=store.contract_text(),
        )
        input_tokens = estimate_tokens(prompt)
        if should_run:
            total_input_tokens += input_tokens
        targets.append({
            "scene_id": freshness.scene_id,
            "status": freshness.status,
            "path": str(freshness.path),
            "should_run": should_run,
            "input_tokens": input_tokens,
            "expected_hash": freshness.expected_hash,
            "actual_hash": freshness.actual_hash,
        })

    calls = [target for target in targets if target["should_run"]]
    total_output_tokens = len(calls) * int(args.estimated_output_tokens)
    return {
        "paths": paths,
        "concept_seed": concept_seed,
        "blueprints": blueprints,
        "store": store,
        "model": model,
        "targets": targets,
        "call_count": len(calls),
        "input_tokens": total_input_tokens,
        "estimated_output_tokens": total_output_tokens,
        "estimated_cost_usd": _cost_usd(model, total_input_tokens, total_output_tokens),
    }


def _print_plan(plan: dict[str, Any], *, as_json: bool) -> None:
    public = {
        "model": plan["model"],
        "call_count": plan["call_count"],
        "input_tokens": plan["input_tokens"],
        "estimated_output_tokens": plan["estimated_output_tokens"],
        "estimated_cost_usd": round(plan["estimated_cost_usd"], 6),
        "targets": plan["targets"],
    }
    if as_json:
        print(json.dumps(public, indent=2))
        return
    print(f"Canon Scout model: {public['model']}")
    print(f"Scenes needing calls: {public['call_count']}")
    print(f"Estimated input tokens: {public['input_tokens']}")
    print(f"Estimated output tokens: {public['estimated_output_tokens']}")
    print(f"Estimated cost: ${public['estimated_cost_usd']:.4f}")
    for target in public["targets"]:
        marker = "RUN" if target["should_run"] else "fresh"
        print(f"- {target['scene_id']}: {target['status']} -> {marker}")


def _rekey(plan: dict[str, Any], args: argparse.Namespace) -> None:
    paths: ProjectPaths = plan["paths"]
    store: CanonGuidanceStore = plan["store"]
    cards_by_scene = {
        f"ch{int(c['chapter_number']):02d}_sc{int(c.get('scene_number', 1)):02d}": c
        for c in _load_scene_cards(paths, chapter=args.chapter, scene=args.scene)
    }
    rekeyed = 0
    skipped: list[tuple[str, str]] = []
    for target in plan["targets"]:
        scene_id = target["scene_id"]
        status = target["status"]
        if status in {"missing", "invalid"}:
            skipped.append((scene_id, status))
            continue
        if status == "fresh":
            continue
        card = cards_by_scene[scene_id]
        blueprint = plan["blueprints"].get(int(card.get("chapter_number") or 0), {})
        try:
            changed, old, new = store.rekey(
                concept_seed=plan["concept_seed"],
                chapter_blueprint=blueprint,
                scene_card=card,
            )
        except (FileNotFoundError, ValueError) as exc:
            skipped.append((scene_id, f"error: {exc}"))
            continue
        if changed:
            rekeyed += 1
            print(f"Re-keyed {scene_id}: {old[:8]} -> {new[:8]}")
    if skipped:
        print(f"Skipped {len(skipped)} sidecar(s) that cannot be re-keyed:")
        for scene_id, reason in skipped:
            print(f"  - {scene_id}: {reason}")
    print(f"Re-keyed {rekeyed} sidecar(s).")


async def _execute(plan: dict[str, Any], args: argparse.Namespace) -> None:
    if plan["estimated_cost_usd"] > args.max_cost_usd:
        raise SystemExit(
            f"Estimated cost ${plan['estimated_cost_usd']:.4f} exceeds "
            f"--max-cost-usd ${args.max_cost_usd:.4f}"
        )

    router = ModelRouter(args.config)
    scout = CanonScout(router)
    paths: ProjectPaths = plan["paths"]
    cards_by_scene = {
        f"ch{int(c['chapter_number']):02d}_sc{int(c.get('scene_number', 1)):02d}": c
        for c in _load_scene_cards(paths, chapter=args.chapter, scene=args.scene)
    }
    store: CanonGuidanceStore = plan["store"]

    failures: list[tuple[str, str]] = []
    # Bounded concurrency: sidecars are independent per-scene files, and the
    # dominant cost is provider latency on ~30k-token prompts. The per-scene
    # wait_for cap turns a wedged retry stack (300s httpx timeout x 3 HTTP
    # attempts x structured-output retry) into a recorded failure instead of
    # a quarter-hour stall; a re-run retries just the missing scenes.
    semaphore = asyncio.Semaphore(4)

    async def _scout_one(target: dict) -> None:
        card = cards_by_scene[target["scene_id"]]
        blueprint = plan["blueprints"].get(int(card.get("chapter_number") or 0), {})
        prompt_text = build_canon_scout_context(
            concept_seed=plan["concept_seed"],
            chapter_blueprint=blueprint,
            scene_card=card,
            canon_contract_text=store.contract_text(),
        )
        if not args.no_prompt_snapshots:
            snapshot_dir = paths.canon_guidance_dir / "_prompt_snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / f"{target['scene_id']}.md").write_text(
                prompt_text,
                encoding="utf-8",
            )
        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    scout.run({
                        "concept_seed": plan["concept_seed"],
                        "chapter_blueprint": blueprint,
                        "scene_card": card,
                        "canon_contract_text": store.contract_text(),
                    }),
                    timeout=300.0,
                )
            payload = store.prepare_payload(
                model_output=result,
                model=plan["model"],
                concept_seed=plan["concept_seed"],
                chapter_blueprint=blueprint,
                scene_card=card,
            )
            path = store.write(payload)
        except Exception as exc:  # noqa: BLE001
            failures.append(
                (target["scene_id"], f"{type(exc).__name__}: {exc}")
            )
            print(f"FAILED {target['scene_id']}: {type(exc).__name__}: {exc}")
            return
        print(f"Wrote {path}")

    try:
        await asyncio.gather(*(
            _scout_one(target)
            for target in plan["targets"]
            if target["should_run"]
        ))
    finally:
        await router.close()
    if failures:
        print(f"\n{len(failures)} scene(s) failed; re-run to retry just those:")
        for scene_id, err in failures:
            print(f"  - {scene_id}: {err}")
    return len(failures)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.rekey_only and args.force:
        raise SystemExit("--rekey-only and --force are mutually exclusive")
    plan = _build_plan(args)
    _print_plan(plan, as_json=args.json)
    if not args.execute:
        return 0
    if args.rekey_only:
        _rekey(plan, args)
        return 0
    failures = asyncio.run(_execute(plan, args))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
