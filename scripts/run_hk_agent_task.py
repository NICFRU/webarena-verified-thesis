#!/usr/bin/env python3
"""Run one BrowserGym/WebArena-Verified Hard H/k task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hk_agent.runner import run_hk_task
from hk_agent.task_loader import select_tasks
from hk_agent.warnings import suppress_third_party_warnings


suppress_third_party_warnings()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--output-root", type=Path, default=Path("runs/hk-agent"))
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--allow-non-hard-task-id", action="store_true")
    parser.add_argument("--h", type=int, default=0)
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--run-mode", choices=["agent", "oracle_debug", "analysis"], default="agent")
    parser.add_argument("--planner-mode", choices=["ollama", "scripted"], default="ollama")
    parser.add_argument("--planner-model", default="gemma4:26b")
    parser.add_argument("--executor-model", default="gemma4:e4b")
    parser.add_argument("--agent-architecture", choices=["v1", "v2", "v2_guarded", "v2_restart1", "v2_planact", "v3", "v3_repair_brief", "v3_repair_llm"], default="v1")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--llm-timeout-seconds", type=int, default=300)
    parser.add_argument("--max-consecutive-llm-timeouts", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=30, help="Maximum BrowserGym actions per run. Use 0 to disable this safety budget.")
    parser.add_argument("--max-planner-calls", type=int, default=0, help="Maximum planner calls per run. Use 0 to disable this safety budget.")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--skip-official-eval", action="store_true")
    parser.add_argument("--wa-gitlab")
    parser.add_argument("--wa-gitlab-username")
    parser.add_argument("--wa-gitlab-password")
    parser.add_argument("--wa-shopping")
    parser.add_argument("--wa-shopping-admin")
    parser.add_argument("--wa-reddit")
    parser.add_argument("--wa-homepage")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    tasks = select_tasks(
        repo_root,
        [args.task_id],
        single_site_only=False,
        supported_sites_only=False,
        allow_non_hard_task_ids=args.allow_non_hard_task_id,
    )
    task = tasks[0]
    output_root = args.output_root.resolve()
    run_dir = output_root / task.primary_site / str(task.task_id) / f"h{args.h}_k{args.k}" / str(task.task_id)
    summary = run_hk_task(
        task=task,
        repo_root=repo_root,
        output_dir=run_dir,
        h=args.h,
        k=args.k,
        run_mode=args.run_mode,
        planner_model=args.planner_model,
        executor_model=args.executor_model,
        agent_architecture=args.agent_architecture,
        planner_mode=args.planner_mode,
        max_steps=args.max_steps,
        max_planner_calls=args.max_planner_calls,
        headed=args.headed,
        skip_official_eval=args.skip_official_eval,
        ollama_base_url=args.ollama_base_url,
        llm_timeout_seconds=args.llm_timeout_seconds,
        max_consecutive_llm_timeouts=args.max_consecutive_llm_timeouts,
        env_updates={
            "WA_GITLAB": args.wa_gitlab,
            "WA_GITLAB_USERNAME": args.wa_gitlab_username,
            "WA_GITLAB_PASSWORD": args.wa_gitlab_password,
            "WA_SHOPPING": args.wa_shopping,
            "WA_SHOPPING_ADMIN": args.wa_shopping_admin,
            "WA_REDDIT": args.wa_reddit,
            "WA_HOMEPAGE": args.wa_homepage,
        },
    )
    print(json.dumps({key: summary.get(key) for key in [
        "task_id",
        "gym_id",
        "h",
        "k",
        "run_mode",
        "total_steps",
        "max_steps",
        "max_steps_disabled",
        "step_budget_reached",
        "official_score",
        "official_success",
        "runtime_replans",
        "planner_calls",
        "max_planner_calls",
        "max_planner_calls_disabled",
        "planner_call_budget_reached",
        "total_tokens",
    ]}, indent=2))
    print(f"Artifacts: {run_dir}")
    return 0 if summary.get("official_eval_returncode") in (None, 0) else int(summary["official_eval_returncode"])


if __name__ == "__main__":
    raise SystemExit(main())
