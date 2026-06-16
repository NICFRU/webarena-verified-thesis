#!/usr/bin/env python3
"""Create explanatory failure/near-miss reports for H/k agent experiments."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from hk_agent.diagnostics import call_ollama_diagnostic_judge, diagnose_run_dir, summarize_diagnostics
from hk_agent.warnings import suppress_third_party_warnings
from webarena_exp.io_utils import read_json, write_json


suppress_third_party_warnings()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "task_id",
        "site",
        "task_type",
        "task_capability",
        "capability_tier",
        "h",
        "k",
        "official_success",
        "official_score",
        "diagnostic_completion",
        "failure_category",
        "failure_notes",
        "final_response_status",
        "final_action_kind",
        "is_mutate_task",
        "mutation_eval_focus",
        "mutation_tier_requires_state_change",
        "mutation_action_count",
        "mutation_actions_before_finish",
        "finish_after_mutation_action",
        "final_success_without_mutation_action",
        "recent_error_before_finish",
        "num_executor_json_calls",
        "num_step_errors",
        "last_step_error",
        "judge_completion",
        "judge_failure_category",
        "judge_failure_reason",
        "judge_recommended_fix",
        "output_dir",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("experiment_root", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--judge-mode", choices=["none", "ollama"], default="none")
    parser.add_argument("--judge-model", default="gemma4:26b")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--judge-timeout-seconds", type=int, default=120)
    args = parser.parse_args()

    experiment_root = args.experiment_root.resolve()
    summary_path = experiment_root / "summary.json"
    summary = read_json(summary_path)
    rows: list[dict[str, Any]] = []
    for row in summary.get("rows", []):
        run_dir = Path(str(row.get("output_dir", "")))
        if not run_dir.exists() or not (run_dir / "run_summary.json").exists():
            diagnostic = {
                "diagnostic_completion": 0.0,
                "failure_category": row.get("failure_category") or "missing_run_artifacts",
                "failure_notes": row.get("error") or "Run artifacts are missing.",
            }
        else:
            diagnostic = diagnose_run_dir(run_dir)
            if args.judge_mode == "ollama" and diagnostic.get("official_success") is not True:
                try:
                    run_summary = read_json(run_dir / "run_summary.json")
                    diagnostic.update(
                        call_ollama_diagnostic_judge(
                            summary=run_summary,
                            output_dir=run_dir,
                            model_name=args.judge_model,
                            base_url=args.ollama_base_url,
                            timeout_seconds=args.judge_timeout_seconds,
                        )
                    )
                except Exception as exc:
                    diagnostic.update(
                        {
                            "judge_failure_category": "judge_error",
                            "judge_failure_reason": str(exc),
                        }
                    )
        rows.append({**row, **diagnostic, "output_dir": str(run_dir)})

    report = {
        "experiment_root": str(experiment_root),
        "num_rows": len(rows),
        "judge_mode": args.judge_mode,
        "judge_model": args.judge_model if args.judge_mode == "ollama" else None,
        "diagnostics": summarize_diagnostics(rows),
        "rows": rows,
    }
    output_json = args.output_json or experiment_root / "failure_analysis.json"
    output_csv = args.output_csv or experiment_root / "failure_analysis.csv"
    write_json(output_json, report)
    write_csv(output_csv, rows)
    print(f"Failure analysis JSON: {output_json}")
    print(f"Failure analysis CSV: {output_csv}")
    print("Diagnostics:", report["diagnostics"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
