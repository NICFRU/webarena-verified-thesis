#!/usr/bin/env python3
"""Main H/k experiment runner for the thesis evaluation.

The runner stores experiment outputs outside of ``external/`` under
``runs/hk-test``. It can run selected task ids or a WebArena-Verified subset
file. Current execution support is intentionally explicit: single-site local
tasks are run, while multi-site and Map tasks are recorded as skipped until the
corresponding environment/executor support is implemented.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tqdm import tqdm

from webarena_exp.io_utils import read_json, write_json
from webarena_exp.site_definitions import SITE_INPUTS


SUPPORTED_SINGLE_SITES = ("gitlab", "shopping", "shopping_admin", "reddit", "wikipedia")


def slug(value: str) -> str:
    """Return a filesystem-safe slug."""

    return value.replace(":", "-").replace("/", "-").replace(" ", "-")


def load_dataset(repo_root: Path) -> dict[int, dict[str, Any]]:
    """Load WebArena-Verified dataset metadata by task id."""

    dataset_path = repo_root / "assets" / "dataset" / "webarena-verified.json"
    return {int(task["task_id"]): task for task in read_json(dataset_path)}


def load_subset_ids(repo_root: Path, subset_file: Path | None, subset_name: str | None) -> list[int]:
    """Load task ids from a subset file or built-in subset name."""

    if subset_file is None:
        if subset_name != "webarena-verified-hard":
            raise ValueError("Only --subset-name webarena-verified-hard is currently mapped locally.")
        subset_file = repo_root / "assets" / "dataset" / "subsets" / "webarena-verified-hard.json"
    elif not subset_file.is_absolute():
        cwd_candidate = Path.cwd() / subset_file
        repo_candidate = repo_root / subset_file
        subset_file = cwd_candidate if cwd_candidate.exists() else repo_candidate

    data = read_json(subset_file)
    if isinstance(data, dict) and "task_ids" in data:
        return [int(task_id) for task_id in data["task_ids"]]
    if isinstance(data, list):
        return [int(task["task_id"]) for task in data]
    raise ValueError(f"Unsupported subset file shape: {subset_file}")


def classify_task(task: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return runnable site or skip reason for the current local implementation."""

    sites = task.get("sites", [])
    if "map" in sites:
        return None, "map_not_available"
    local_sites = [site for site in sites if site in SUPPORTED_SINGLE_SITES and SITE_INPUTS[site].enabled]
    if len(sites) != 1:
        return None, "multi_site_not_supported_yet"
    if len(local_sites) != 1:
        return None, f"unsupported_site:{sites}"
    return local_sites[0], None


def task_selection(args: argparse.Namespace, repo_root: Path, dataset: dict[int, dict[str, Any]]) -> list[int]:
    """Resolve selected task ids."""

    if args.task_ids:
        task_ids = [int(task_id) for task_id in args.task_ids]
    else:
        task_ids = load_subset_ids(repo_root, args.subset_file, args.subset_name)
    if args.limit is not None:
        task_ids = task_ids[: args.limit]
    missing = [task_id for task_id in task_ids if task_id not in dataset]
    if missing:
        raise ValueError(f"Task ids not found in WebArena-Verified dataset: {missing[:10]}")
    return task_ids


def build_command(
    repo_root: Path,
    task_output_root: Path,
    site: str,
    task_id: int,
    h: int,
    k: int,
    planner_mode: str,
    executor_mode: str,
    model: str,
    executor_model: str | None,
    headed: bool,
    skip_eval: bool,
    target_hint_mode: str,
    max_steps: int,
    max_planner_calls: int,
) -> list[str]:
    """Build the single-task runner command."""

    command = [
        sys.executable,
        "scripts/run_hk_task.py",
        "--repo-root",
        str(repo_root),
        "--site",
        site,
        "--task-id",
        str(task_id),
        "--output-root",
        str(task_output_root),
        "--h",
        str(h),
        "--k",
        str(k),
        "--planner-mode",
        planner_mode,
        "--executor-mode",
        executor_mode,
        "--model",
        model,
        "--target-hint-mode",
        target_hint_mode,
        "--max-steps",
        str(max_steps),
        "--max-planner-calls",
        str(max_planner_calls),
    ]
    if executor_model:
        command.extend(["--executor-model", executor_model])
    if headed:
        command.append("--headed")
    if skip_eval:
        command.append("--skip-eval")
    return command


def load_run_row(
    task_dir: Path,
    task: dict[str, Any],
    site: str,
    h: int,
    k: int,
    planner_mode: str,
    executor_mode: str,
    model: str,
    proc: subprocess.CompletedProcess[str],
) -> dict[str, Any]:
    """Load one run's summary row."""

    summary_path = task_dir / "run_summary.json"
    trace_path = task_dir / "run_trace.json"
    summary = read_json(summary_path) if summary_path.exists() else {}
    trace = read_json(trace_path) if trace_path.exists() else {}
    return {
        "task_id": task["task_id"],
        "intent_template_id": task.get("intent_template_id"),
        "site": site,
        "sites": ",".join(task.get("sites", [])),
        "h": h,
        "k": k,
        "planner_mode": summary.get("planner_mode", planner_mode),
        "executor_mode": summary.get("executor_mode", executor_mode),
        "model": model,
        "status": "completed" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "score": summary.get("score"),
        "success": summary.get("success"),
        "total_steps": summary.get("total_steps"),
        "total_runtime_ms": summary.get("total_runtime_ms"),
        "total_tokens": summary.get("total_tokens"),
        "executor_tokens": summary.get("executor_tokens"),
        "prompt_tokens": summary.get("prompt_tokens"),
        "completion_tokens": summary.get("completion_tokens"),
        "num_planner_calls": summary.get("num_planner_calls") or trace.get("num_planner_calls"),
        "num_executor_calls": summary.get("num_executor_calls"),
        "num_plan_subgoals_generated": summary.get("num_plan_subgoals_generated") or trace.get("num_plan_subgoals_generated"),
        "num_replans": trace.get("num_replans"),
        "num_no_progress_events": trace.get("num_no_progress_events"),
        "num_invalid_actions": trace.get("num_invalid_actions"),
        "num_loop_events": trace.get("num_loop_events"),
        "final_url": summary.get("final_url"),
        "output_dir": str(task_dir),
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows as CSV with stable columns."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "task_id",
        "intent_template_id",
        "site",
        "sites",
        "h",
        "k",
        "planner_mode",
        "executor_mode",
        "model",
        "status",
        "skip_reason",
        "returncode",
        "score",
        "success",
        "total_steps",
        "total_runtime_ms",
        "total_tokens",
        "executor_tokens",
        "prompt_tokens",
        "completion_tokens",
        "num_planner_calls",
        "num_executor_calls",
        "num_plan_subgoals_generated",
        "num_replans",
        "num_no_progress_events",
        "num_invalid_actions",
        "num_loop_events",
        "final_url",
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
    parser.add_argument("--output-root", type=Path, default=Path("runs/hk-test"))
    parser.add_argument("--experiment-name", default=None)
    parser.add_argument("--task-ids", type=int, nargs="+")
    parser.add_argument("--subset-name", default="webarena-verified-hard")
    parser.add_argument("--subset-file", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--hs", type=int, nargs="+", default=[0])
    parser.add_argument("--ks", type=int, nargs="+", default=[1])
    parser.add_argument("--planner-mode", choices=["ollama", "scripted"], default="ollama")
    parser.add_argument("--executor-mode", choices=["heuristic", "llm"], default="heuristic")
    parser.add_argument("--model", default="gemma4:26b")
    parser.add_argument("--executor-model", default=None)
    parser.add_argument("--target-hint-mode", choices=["eval", "none"], default="eval")
    parser.add_argument("--max-steps", type=int, default=5)
    parser.add_argument("--max-planner-calls", type=int, default=5)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    dataset = load_dataset(repo_root)
    task_ids = task_selection(args, repo_root, dataset)
    experiment_name = args.experiment_name or f"{args.subset_name or 'selected'}-{slug(args.model)}-{args.planner_mode}"
    output_root = args.output_root.resolve() / experiment_name
    output_root.mkdir(parents=True, exist_ok=True)

    experiment_config = {
        "experiment_name": experiment_name,
        "subset_name": args.subset_name,
        "subset_file": str(args.subset_file) if args.subset_file else None,
        "task_ids": task_ids,
        "hs": args.hs,
        "ks": args.ks,
        "planner_mode": args.planner_mode,
        "executor_mode": args.executor_mode,
        "model": args.model,
        "executor_model": args.executor_model,
        "target_hint_mode": args.target_hint_mode,
        "max_steps": args.max_steps,
        "max_planner_calls": args.max_planner_calls,
        "headed": args.headed,
        "skip_eval": args.skip_eval,
        "execution_note": "Current runnable scope executes single-site non-map tasks. Multi-site and map tasks are recorded as skipped.",
        "guidance_note": (
            "The current local executor/planner path is oracle-assisted for smoke/control runs: "
            "it may use evaluator-derived target hints. Use official score for final evaluation, "
            "but do not treat oracle-assisted success as a fair autonomous-agent result."
        ),
    }
    write_json(output_root / "experiment_config.json", experiment_config)
    selected_tasks = [dataset[task_id] for task_id in task_ids]
    write_json(output_root / "selected_tasks.json", selected_tasks)

    rows: list[dict[str, Any]] = []
    configs = [(h, k) for h in args.hs for k in args.ks]
    total = len(task_ids) * len(configs)
    started = time.perf_counter()
    with tqdm(total=total, desc="main execution", unit="run") as bar:
        for task_id in task_ids:
            task = dataset[task_id]
            site, skip_reason = classify_task(task)
            for h, k in configs:
                if skip_reason is not None or site is None:
                    rows.append(
                        {
                            "task_id": task_id,
                            "intent_template_id": task.get("intent_template_id"),
                            "site": site,
                            "sites": ",".join(task.get("sites", [])),
                            "h": h,
                            "k": k,
                            "planner_mode": args.planner_mode,
                            "executor_mode": args.executor_mode,
                            "model": args.model,
                            "status": "skipped",
                            "skip_reason": skip_reason,
                        }
                    )
                    bar.update(1)
                    continue

                task_output_root = output_root / site / str(task_id) / f"h{h}_k{k}"
                command = build_command(
                    repo_root,
                    task_output_root,
                    site,
                    task_id,
                    h,
                    k,
                    args.planner_mode,
                    args.executor_mode,
                    args.model,
                    args.executor_model,
                    args.headed,
                    args.skip_eval,
                    args.target_hint_mode,
                    args.max_steps,
                    args.max_planner_calls,
                )
                tqdm.write("$ " + " ".join(command))
                if args.dry_run:
                    rows.append(
                        {
                            "task_id": task_id,
                            "intent_template_id": task.get("intent_template_id"),
                            "site": site,
                            "sites": ",".join(task.get("sites", [])),
                            "h": h,
                            "k": k,
                            "planner_mode": args.planner_mode,
                            "executor_mode": args.executor_mode,
                            "model": args.model,
                            "status": "dry_run",
                            "output_dir": str(task_output_root / str(task_id)),
                        }
                    )
                    bar.update(1)
                    continue

                proc = subprocess.run(command, cwd=Path.cwd(), env=os.environ.copy(), text=True, capture_output=True, check=False)
                task_dir = task_output_root / str(task_id)
                rows.append(load_run_row(task_dir, task, site, h, k, args.planner_mode, args.executor_mode, args.model, proc))
                status = "OK" if proc.returncode == 0 else "FAIL"
                tqdm.write(f"[{status}] task={task_id} site={site} h={h} k={k}")
                bar.update(1)

    summary = {
        "experiment_config": experiment_config,
        "total_runtime_ms": int((time.perf_counter() - started) * 1000),
        "num_rows": len(rows),
        "num_completed": sum(1 for row in rows if row.get("status") == "completed"),
        "num_failed": sum(1 for row in rows if row.get("status") == "failed"),
        "num_skipped": sum(1 for row in rows if row.get("status") == "skipped"),
        "rows": rows,
    }
    write_json(output_root / "summary.json", summary)
    write_csv(output_root / "summary.csv", rows)
    print(f"\nExperiment output: {output_root}")
    print(f"Summary JSON: {output_root / 'summary.json'}")
    print(f"Summary CSV: {output_root / 'summary.csv'}")
    return 0 if summary["num_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
