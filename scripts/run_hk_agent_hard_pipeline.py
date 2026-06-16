#!/usr/bin/env python3
"""Convenience pipeline for sequential WebArena-Verified Hard H/k runs."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from hk_agent.warnings import suppress_third_party_warnings


suppress_third_party_warnings()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["supported-single-site", "all-hard"], default="supported-single-site")
    parser.add_argument("--experiment-name")
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--output-root", type=Path, default=Path("runs/hk-agent"))
    parser.add_argument("--hs", type=int, nargs="+", default=[0, 2, 5])
    parser.add_argument("--ks", type=int, nargs="+", default=[2, 5])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--capabilities", nargs="+")
    parser.add_argument("--capability-tiers", nargs="+")
    parser.add_argument("--main-analysis-capabilities-only", action="store_true")
    parser.add_argument("--planner-model", default="gemma4:26b")
    parser.add_argument("--executor-model", default="gemma4:e4b")
    parser.add_argument("--max-planner-calls", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--llm-timeout-seconds", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rerun-existing", action="store_true")
    parser.add_argument("--skip-official-eval", action="store_true")
    args = parser.parse_args()

    experiment_name = args.experiment_name
    if not experiment_name:
        hk_slug = "h" + "-".join(str(h) for h in args.hs) + "_k" + "-".join(str(k) for k in args.ks)
        experiment_name = f"hk-agent-{args.profile}-{hk_slug}"

    command = [
        sys.executable,
        "scripts/run_hk_agent_experiment.py",
        "--repo-root",
        str(args.repo_root),
        "--output-root",
        str(args.output_root),
        "--experiment-name",
        experiment_name,
        "--hs",
        *[str(h) for h in args.hs],
        "--ks",
        *[str(k) for k in args.ks],
        "--run-mode",
        "agent",
        "--planner-model",
        args.planner_model,
        "--executor-model",
        args.executor_model,
        "--max-planner-calls",
        str(args.max_planner_calls),
        "--max-steps",
        str(args.max_steps),
        "--llm-timeout-seconds",
        str(args.llm_timeout_seconds),
    ]
    if args.profile == "all-hard":
        command.extend(["--include-multisite", "--include-unsupported-sites"])
    if args.capabilities:
        command.extend(["--capabilities", *args.capabilities])
    if args.capability_tiers:
        command.extend(["--capability-tiers", *args.capability_tiers])
    if args.main_analysis_capabilities_only:
        command.append("--main-analysis-capabilities-only")
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
    if args.dry_run:
        command.append("--dry-run")
    if not args.rerun_existing:
        command.append("--skip-existing")
    if args.skip_official_eval:
        command.append("--skip-official-eval")

    print("$ " + " ".join(command), flush=True)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
