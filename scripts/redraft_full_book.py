"""Batch redraft all 38 scenes of The Unfinished Shadow through the upgraded pipeline.

Pipeline per scene (mirrors the bench harness ch01-full-pipeline-v3 setup):

  PlotArchitect  ->  ProseStylist  ->  LineWriter  ->  RhythmValidator  ->  RhythmEditor

Init costs (ModelRouter, agent setup) happen once; the per-scene loop reuses
every agent. Per-chapter outputs land under
``output/<franchise>/<book>/runs/full-redraft-v3/chapter_NN/`` with the same
file naming the bench script uses (drafter, __LINE_EDIT_*, __RHYTHM_EDIT).
Per-scene metrics and audit logs land in ``batch_summary.json``.

After the loop, stitches the per-chapter rhythm-edited prose into a single
``manuscript.md`` + ``chapter_index.md`` + ``validation_report.json`` under
``export/full-redraft-v3-<date>/``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.agents.line_writer import LineWriter  # noqa: E402
from src.agents.plot_architect import PlotArchitect  # noqa: E402
from src.agents.prose_stylist import ProseStylist  # noqa: E402
from src.agents.rhythm_editor import RhythmEditor, apply_rhythm_edits  # noqa: E402
from src.memory.context_assembler import ContextAssembler  # noqa: E402
from src.model_router import ModelRouter  # noqa: E402
from src.project_paths import ProjectPaths  # noqa: E402
from src.quality.rhythm_validator import validate_rhythm  # noqa: E402


def _estimate_cost(model_full: str, in_tokens: int, out_tokens: int) -> float:
    """Rough cost estimate (USD)."""
    rates = {
        "deepseek/deepseek-v4-flash": (0.27e-6, 1.10e-6),
        "deepseek/deepseek-v4-pro":   (0.55e-6, 2.19e-6),
        "openai/gpt-5.4-mini":        (0.15e-6, 0.60e-6),
    }
    rate_in, rate_out = rates.get(model_full, (1e-6, 4e-6))
    return in_tokens * rate_in + out_tokens * rate_out


def _count_tokens_rough(text: str) -> int:
    return max(1, len(text) // 4)


def _resolve_dialogue_requirement(scene_card: dict) -> bool:
    return not (
        scene_card.get("dialogue_density_target") == "low"
        or scene_card.get("dialogue_expectation") == "interior"
    )


async def _redraft_one_scene(
    *,
    scene_card_path: Path,
    concept_seed_path: Path,
    assembler: ContextAssembler,
    plot_architect: PlotArchitect,
    prose_stylist: ProseStylist,
    line_writer: LineWriter,
    rhythm_editor: RhythmEditor,
    out_dir: Path,
    rhythm_edit_max_edits: int,
    rhythm_edit_max_total_changed_chars: int,
    rhythm_edit_max_changed_ratio: float,
) -> dict:
    scene_card = json.loads(scene_card_path.read_text(encoding="utf-8"))
    ch = scene_card["chapter_number"]
    sc = scene_card.get("scene_number", 1)
    out_dir.mkdir(parents=True, exist_ok=True)

    entry: dict = {
        "chapter": ch,
        "scene": sc,
        "scene_card_path": str(scene_card_path),
        "stages": {},
    }
    total_cost = 0.0

    # --- Stage 1: PlotArchitect ---
    stage_start = time.time()
    brief_result = await plot_architect.run({
        "scene_card": scene_card,
        "previous_chapter": assembler.get_previous_chapter(ch),
        "characters_present": scene_card.get("characters_present", []),
        "pov_approach": assembler.get_pov_approach(),
        "franchise_profile_text": assembler.get_franchise_profile_text(),
    })
    brief = brief_result if isinstance(brief_result, dict) else {"raw": brief_result}
    brief_json = json.dumps(brief, indent=2, ensure_ascii=False) if isinstance(brief, dict) else str(brief)
    brief_in = _count_tokens_rough(json.dumps(scene_card))
    brief_out = _count_tokens_rough(brief_json)
    brief_cost = _estimate_cost("deepseek/deepseek-v4-flash", brief_in, brief_out)
    total_cost += brief_cost
    (out_dir / "generation_brief.json").write_text(brief_json, encoding="utf-8")
    entry["stages"]["plot_architect"] = {
        "duration_s": round(time.time() - stage_start, 1),
        "est_in_tokens": brief_in,
        "est_out_tokens": brief_out,
        "est_cost_usd": round(brief_cost, 4),
    }

    # --- Stage 2: ProseStylist ---
    stage_start = time.time()
    prose_input = {
        "scene_card": scene_card,
        "generation_brief": brief,
        "context_blob": assembler.assemble(scene_card),
        "characters_present": scene_card.get("characters_present", []),
        "pov_approach": assembler.get_pov_approach(),
        "franchise_profile_text": assembler.get_franchise_profile_text(),
    }
    prose_result = await prose_stylist.run(prose_input)
    prose = prose_result["prose"]
    ps_in = _count_tokens_rough(json.dumps(prose_input))
    ps_out = _count_tokens_rough(prose)
    ps_cost = _estimate_cost("deepseek/deepseek-v4-pro", ps_in, ps_out)
    total_cost += ps_cost
    prose_path = out_dir / "deepseek-v4-pro-t070.md"
    prose_path.write_text(prose, encoding="utf-8")
    entry["stages"]["prose_stylist"] = {
        "duration_s": round(time.time() - stage_start, 1),
        "word_count": len(prose.split()),
        "est_in_tokens": ps_in,
        "est_out_tokens": ps_out,
        "est_cost_usd": round(ps_cost, 4),
        "output_file": str(prose_path),
    }

    downstream_prose = prose

    # --- Stage 3: LineWriter ---
    stage_start = time.time()
    try:
        line_edit_result = await line_writer.run({
            "source_prose": downstream_prose,
            "scene_card": scene_card,
            "generation_brief": brief,
            "characters_present": scene_card.get("characters_present", []),
            "pov_approach": assembler.get_pov_approach(),
            "franchise_profile_text": assembler.get_franchise_profile_text(),
        })
        line_edited = line_edit_result["prose"]
    except Exception as e:  # noqa: BLE001 - log and keep going
        line_edited = downstream_prose
        entry["stages"]["line_writer"] = {"error": f"{e.__class__.__name__}: {e}"}
    else:
        le_in = _count_tokens_rough(downstream_prose)
        le_out = _count_tokens_rough(line_edited)
        le_cost = _estimate_cost("openai/gpt-5.4-mini", le_in, le_out)
        total_cost += le_cost
        le_path = out_dir / "deepseek-v4-pro-t070__LINE_EDIT_gpt54_mini.md"
        le_path.write_text(line_edited, encoding="utf-8")
        entry["stages"]["line_writer"] = {
            "duration_s": round(time.time() - stage_start, 1),
            "word_count": len(line_edited.split()),
            "est_in_tokens": le_in,
            "est_out_tokens": le_out,
            "est_cost_usd": round(le_cost, 4),
            "output_file": str(le_path),
        }
        downstream_prose = line_edited

    # --- Stage 4: RhythmValidator (deterministic) ---
    require_dialogue = _resolve_dialogue_requirement(scene_card)
    pre_edit_rhythm = validate_rhythm(
        downstream_prose,
        scope="scene",
        scope_id=f"ch{ch:02d}_sc{sc:02d}",
        require_dialogue=require_dialogue,
    )
    actionable = [
        i for i in pre_edit_rhythm.issues
        if i.code in {
            "rhythm.em_dash_overuse",
            "rhythm.staccato_cluster",
            "rhythm.opener_monotone",
            "rhythm.abstract_tic",
        }
    ]
    entry["stages"]["rhythm_validator_pre"] = {
        "metrics": pre_edit_rhythm.to_dict()["metrics"],
        "issues": [{"code": i.code, "severity": i.severity} for i in pre_edit_rhythm.issues],
    }

    # --- Stage 5: RhythmEditor ---
    if not actionable:
        entry["stages"]["rhythm_editor"] = {"skipped": "no actionable issues"}
        rhythm_edit_path = out_dir / "deepseek-v4-pro-t070__RHYTHM_EDIT.md"
        rhythm_edit_path.write_text(downstream_prose, encoding="utf-8")
    elif len(pre_edit_rhythm.issues) > 5:
        entry["stages"]["rhythm_editor"] = {"skipped": "confusion threshold (>5 issues)"}
        rhythm_edit_path = out_dir / "deepseek-v4-pro-t070__RHYTHM_EDIT.md"
        rhythm_edit_path.write_text(downstream_prose, encoding="utf-8")
    else:
        stage_start = time.time()
        try:
            editor_result = await rhythm_editor.run({
                "prose": downstream_prose,
                "scene_card": scene_card,
                "rhythm_issues": [
                    {
                        "code": i.code,
                        "severity": i.severity,
                        "message": i.message,
                        "metric_value": i.metric_value,
                        "threshold": i.threshold,
                    }
                    for i in actionable
                ],
            })
        except Exception as e:  # noqa: BLE001
            editor_result = {"summary": "", "edits": []}
            entry["stages"]["rhythm_editor"] = {"error": f"{e.__class__.__name__}: {e}"}
        edits_proposed = editor_result.get("edits", [])
        re_in = _count_tokens_rough(downstream_prose) + _count_tokens_rough(json.dumps(scene_card))
        re_out = _count_tokens_rough(json.dumps(editor_result))
        re_cost = _estimate_cost("deepseek/deepseek-v4-pro", re_in, re_out)
        total_cost += re_cost

        patched, audit = apply_rhythm_edits(
            downstream_prose,
            edits_proposed,
            max_edits=rhythm_edit_max_edits,
            max_total_changed_chars=rhythm_edit_max_total_changed_chars,
            max_changed_ratio=rhythm_edit_max_changed_ratio,
        )
        applied = sum(1 for a in audit if a["action"] == "applied")
        rejected = sum(1 for a in audit if a["action"] == "rejected")
        post_edit_rhythm = validate_rhythm(
            patched,
            scope="scene",
            scope_id=f"ch{ch:02d}_sc{sc:02d}__rhythm_edit",
            require_dialogue=require_dialogue,
        )
        rhythm_edit_path = out_dir / "deepseek-v4-pro-t070__RHYTHM_EDIT.md"
        rhythm_edit_path.write_text(patched, encoding="utf-8")
        entry["stages"]["rhythm_editor"] = {
            "duration_s": round(time.time() - stage_start, 1),
            "summary": editor_result.get("summary", ""),
            "proposed": len(edits_proposed),
            "applied": applied,
            "rejected": rejected,
            "est_in_tokens": re_in,
            "est_out_tokens": re_out,
            "est_cost_usd": round(re_cost, 4),
            "pre_edit_metrics": pre_edit_rhythm.to_dict()["metrics"],
            "post_edit_metrics": post_edit_rhythm.to_dict()["metrics"],
            "pre_edit_issues": [{"code": i.code, "severity": i.severity} for i in pre_edit_rhythm.issues],
            "post_edit_issues": [{"code": i.code, "severity": i.severity} for i in post_edit_rhythm.issues],
            "audit": audit,
            "output_file": str(rhythm_edit_path),
        }
        downstream_prose = patched

    entry["final_word_count"] = len(downstream_prose.split())
    entry["total_cost_usd"] = round(total_cost, 4)
    return entry


async def run_batch(
    *,
    concept_seed_path: str,
    scene_cards_dir: str,
    run_name: str,
    config_path: str = "config/settings.yaml",
    rhythm_edit_max_edits: int = 8,
    rhythm_edit_max_total_changed_chars: int = 1500,
    rhythm_edit_max_changed_ratio: float = 0.15,
    start_from: int = 1,
    stop_after: int | None = None,
) -> None:
    print(f"[init] router from {config_path}")
    router = ModelRouter(config_path)
    ok, msg = await router.health_check()
    if not ok:
        print(f"[FATAL] router health check failed: {msg}")
        await router.close()
        return
    print(f"[ok] {msg}")

    paths = ProjectPaths.from_concept_seed_path(concept_seed_path, run_id=run_name)
    run_dir = paths.run_dir
    if run_dir is None:
        print("[FATAL] run_dir is None")
        await router.close()
        return
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run] {run_dir}")

    assembler = ContextAssembler(concept_seed_path=concept_seed_path)
    plot_architect = PlotArchitect(router)
    prose_stylist = ProseStylist(router)
    line_writer = LineWriter(router)
    rhythm_editor = RhythmEditor(router)

    scene_card_paths = sorted(Path(scene_cards_dir).glob("chapter_*_scene_*.json"))
    scene_card_paths = [p for p in scene_card_paths if start_from <= int(p.stem.split("_")[1]) <= (stop_after or 9999)]
    print(f"[scenes] {len(scene_card_paths)} cards to redraft")

    batch_summary: dict = {
        "run_name": run_name,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scene_count": len(scene_card_paths),
        "scenes": [],
        "total_cost_usd": 0.0,
        "wall_time_s": 0.0,
    }
    batch_start = time.time()
    total_cost = 0.0

    for i, card_path in enumerate(scene_card_paths, start=1):
        ch_num = int(card_path.stem.split("_")[1])
        sc_num = int(card_path.stem.split("_")[3])
        chapter_dir = run_dir / f"chapter_{ch_num:02d}"
        scene_start = time.time()
        print(f"\n[{i}/{len(scene_card_paths)}] redrafting Ch{ch_num:02d}_Sc{sc_num:02d} ...")
        try:
            entry = await _redraft_one_scene(
                scene_card_path=card_path,
                concept_seed_path=Path(concept_seed_path),
                assembler=assembler,
                plot_architect=plot_architect,
                prose_stylist=prose_stylist,
                line_writer=line_writer,
                rhythm_editor=rhythm_editor,
                out_dir=chapter_dir,
                rhythm_edit_max_edits=rhythm_edit_max_edits,
                rhythm_edit_max_total_changed_chars=rhythm_edit_max_total_changed_chars,
                rhythm_edit_max_changed_ratio=rhythm_edit_max_changed_ratio,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR] {e.__class__.__name__}: {e}")
            entry = {"chapter": ch_num, "scene": sc_num, "error": f"{e.__class__.__name__}: {e}"}

        entry["wall_time_s"] = round(time.time() - scene_start, 1)
        total_cost += entry.get("total_cost_usd", 0.0)
        batch_summary["scenes"].append(entry)
        batch_summary["total_cost_usd"] = round(total_cost, 4)
        batch_summary["wall_time_s"] = round(time.time() - batch_start, 1)

        (run_dir / "batch_summary.json").write_text(
            json.dumps(batch_summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        pre = entry.get("stages", {}).get("rhythm_validator_pre", {}).get("metrics", {})
        post_block = entry.get("stages", {}).get("rhythm_editor", {})
        post = post_block.get("post_edit_metrics", pre)
        print(
            f"  done in {entry['wall_time_s']}s  cost=${entry.get('total_cost_usd', 0):.4f}  "
            f"em/1k {pre.get('em_dashes_per_1k_words', 0):.1f}->{post.get('em_dashes_per_1k_words', 0):.1f}  "
            f"runs {pre.get('short_sentence_runs', 0)}->{post.get('short_sentence_runs', 0)}  "
            f"running total=${total_cost:.2f}"
        )

    print("\n" + "=" * 70)
    print("BATCH COMPLETE")
    print(f"  scenes: {len(scene_card_paths)}")
    print(f"  total cost: ${total_cost:.4f}")
    print(f"  wall time: {batch_summary['wall_time_s']}s ({batch_summary['wall_time_s']/60:.1f} min)")
    print(f"  output: {run_dir}")
    print("=" * 70)

    await router.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Batch redraft all scenes through the upgraded pipeline")
    p.add_argument(
        "--concept-seed",
        default="data/franchises/star-wars-legends-eu/books/the-unfinished-shadow/concept_seed.json",
    )
    p.add_argument(
        "--scene-cards-dir",
        default="data/franchises/star-wars-legends-eu/books/the-unfinished-shadow/scene_cards",
    )
    p.add_argument("--run-name", default="full-redraft-v3")
    p.add_argument("--config", default="config/settings.yaml")
    p.add_argument("--rhythm-edit-max-edits", type=int, default=8)
    p.add_argument("--rhythm-edit-max-total-changed-chars", type=int, default=1500)
    p.add_argument("--rhythm-edit-max-changed-ratio", type=float, default=0.15)
    p.add_argument("--start-from", type=int, default=1, help="Start at chapter N (default 1)")
    p.add_argument("--stop-after", type=int, default=None, help="Stop after chapter N (default: run all)")
    args = p.parse_args()
    asyncio.run(run_batch(
        concept_seed_path=args.concept_seed,
        scene_cards_dir=args.scene_cards_dir,
        run_name=args.run_name,
        config_path=args.config,
        rhythm_edit_max_edits=args.rhythm_edit_max_edits,
        rhythm_edit_max_total_changed_chars=args.rhythm_edit_max_total_changed_chars,
        rhythm_edit_max_changed_ratio=args.rhythm_edit_max_changed_ratio,
        start_from=args.start_from,
        stop_after=args.stop_after,
    ))


if __name__ == "__main__":
    main()
