#!/usr/bin/env python3
"""Run a small H/k sweep for local WebArena-Verified prototypes."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

from tqdm import tqdm

from webarena_exp.hardcoded_tasks import HARDCODED_TASKS
from webarena_exp.io_utils import read_json, write_json


def model_slug(model: str) -> str:
    """Convert an Ollama model name into a filesystem-friendly slug."""

    return model.replace(":", "-").replace("/", "-")


def run_one(
    repo_root: Path,
    output_root: Path,
    site: str,
    task_id: int | None,
    h: int,
    k: int,
    model: str,
    headed: bool,
    skip_eval: bool,
) -> dict:
    """Run one H/k configuration and return a summary row."""

    run_root = output_root / model_slug(model) / f"h{h}_k{k}"
    command = [
        sys.executable,
        "scripts/run_hk_task44_prototype.py",
        "--repo-root",
        str(repo_root),
        "--site",
        site,
        "--output-root",
        str(run_root),
        "--planner-mode",
        "ollama",
        "--model",
        model,
        "--h",
        str(h),
        "--k",
        str(k),
    ]
    if task_id is not None:
        command.extend(["--task-id", str(task_id)])
    if headed:
        command.append("--headed")
    if skip_eval:
        command.append("--skip-eval")

    proc = subprocess.run(command, text=True, capture_output=True, check=False)
    task_dir = run_root / (str(task_id) if task_id is not None else "direct")
    summary_path = task_dir / "run_summary.json"
    trace_path = task_dir / "run_trace.json"
    summary = read_json(summary_path) if summary_path.exists() else {}
    trace = read_json(trace_path) if trace_path.exists() else {}
    return {
        "site": site,
        "task_id": task_id,
        "h": h,
        "k": k,
        "planner_mode": summary.get("planner_mode"),
        "model": model,
        "returncode": proc.returncode,
        "score": summary.get("score"),
        "success": summary.get("success"),
        "total_steps": summary.get("total_steps"),
        "total_runtime_ms": summary.get("total_runtime_ms"),
        "total_tokens": summary.get("total_tokens"),
        "prompt_tokens": summary.get("prompt_tokens"),
        "completion_tokens": summary.get("completion_tokens"),
        "num_planner_calls": summary.get("num_planner_calls") or trace.get("num_planner_calls"),
        "num_plan_subgoals_generated": summary.get("num_plan_subgoals_generated") or trace.get("num_plan_subgoals_generated"),
        "num_replans": trace.get("num_replans"),
        "num_no_progress_events": trace.get("num_no_progress_events"),
        "num_invalid_actions": trace.get("num_invalid_actions"),
        "num_loop_events": trace.get("num_loop_events"),
        "final_url": summary.get("final_url"),
        "planner_warnings": summary.get("planner_warnings", []),
        "output_dir": str(task_dir),
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write sweep rows as CSV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "task_id",
        "site",
        "h",
        "k",
        "planner_mode",
        "model",
        "returncode",
        "score",
        "success",
        "total_steps",
        "total_runtime_ms",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "num_planner_calls",
        "num_plan_subgoals_generated",
        "num_replans",
        "num_no_progress_events",
        "num_invalid_actions",
        "num_loop_events",
        "final_url",
        "planner_warnings",
        "output_dir",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--output-root", type=Path, default=Path("output/hk-sweep"))
    parser.add_argument("--site", choices=["gitlab", "shopping", "shopping_admin", "reddit", "wikipedia"], default="gitlab")
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--hs", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--ks", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--model", default="gemma4:26b")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    task_id = args.task_id if args.task_id is not None else HARDCODED_TASKS[args.site].task_id
    output_root = args.output_root if args.output_root.is_absolute() else repo_root / args.output_root
    output_root.mkdir(parents=True, exist_ok=True)

    configs = [(h, k) for h in args.hs for k in args.ks]
    rows = []
    with tqdm(total=len(configs), desc="H/k sweep", unit="run") as bar:
        for h, k in configs:
            tqdm.write(f"[RUN] site={args.site} task={task_id} h={h} k={k} model={args.model}")
            row = run_one(repo_root, output_root, args.site, task_id, h, k, args.model, args.headed, args.skip_eval)
            rows.append(row)
            status = "OK" if row["returncode"] == 0 else "FAIL"
            tqdm.write(f"[{status}] h={h} k={k} score={row.get('score')} success={row.get('success')}")
            bar.update(1)

    summary = {
        "site": args.site,
        "task_id": task_id,
        "model": args.model,
        "hs": args.hs,
        "ks": args.ks,
        "rows": rows,
    }
    summary_path = output_root / "summary.json"
    csv_path = output_root / "summary.csv"
    write_json(summary_path, summary)
    write_csv(csv_path, rows)
    print(f"\nSummary JSON: {summary_path}")
    print(f"Summary CSV: {csv_path}")
    return 0 if all(row["returncode"] == 0 for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
