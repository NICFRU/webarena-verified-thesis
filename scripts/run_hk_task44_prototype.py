#!/usr/bin/env python3
"""H/k architecture prototype for selected WebArena-Verified tasks.

This runner keeps the proven scripted Task-44 behavior, but wraps it in the
Planner -> Executor -> Evaluator -> Controller structure from the thesis
architecture. The first version uses a deterministic planner so that the
process logging can be validated before introducing an LLM planner.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import gymnasium as gym
from tqdm import tqdm

from webarena_exp.browsergym_utils import assert_site_reachable
from webarena_exp.controller import decide_next_action
from webarena_exp.evaluator import evaluate_gitlab_task44_state, evaluate_shopping_task118_state
from webarena_exp.executor import ShoppingTask118Executor, Task44ScriptedExecutor, absolute_url, task44_target_url
from webarena_exp.hardcoded_tasks import HARDCODED_TASKS
from webarena_exp.io_utils import read_json, read_jsonl, write_json
from webarena_exp.logging import TraceLogger
from webarena_exp.planner import build_plan
from webarena_exp.site_definitions import SITE_INPUTS
from webarena_exp.types import PlannerRequest, RunTrace
from webarena_exp.webarena_cli import export_agent_input, run_eval, write_site_config


def load_task(tasks_file: Path, task_id: int) -> dict[str, Any]:
    data = read_json(tasks_file)
    for task in data:
        if task.get("task_id") == task_id:
            return task
    raise ValueError(f"Task {task_id} not found in {tasks_file}")


def load_gitlab_credentials(config_path: Path) -> tuple[str, str] | None:
    config = read_json(config_path)
    credentials = config.get("environments", {}).get("__GITLAB__", {}).get("credentials")
    if not credentials:
        return None
    username = credentials.get("username")
    password = credentials.get("password")
    if not username or not password:
        return None
    return username, password


def default_task_id(site_name: str) -> int:
    """Return the prototype task id for a supported site."""

    spec = HARDCODED_TASKS[site_name]
    if spec.task_id is None:
        raise ValueError(f"Site {site_name} does not define a prototype task")
    return spec.task_id


def load_or_render_task(repo_root: Path, site_name: str, task_id: int, config: Path, task_output_dir: Path, tasks_file: Path) -> dict[str, Any]:
    """Load the GitLab demo task or render a site task through the official CLI."""

    if site_name == "gitlab":
        return load_task(tasks_file, task_id)

    rendered_path = task_output_dir / "task_input.json"
    rendered = export_agent_input(repo_root, task_id, config, rendered_path)
    if not rendered:
        raise ValueError(f"No rendered task returned for {site_name} task {task_id}")
    return rendered[0]


def write_agent_response(output_dir: Path, task_type: str = "NAVIGATE") -> Path:
    response = {
        "task_type": task_type,
        "status": "SUCCESS",
        "retrieved_data": None,
        "error_details": None,
    }
    out = output_dir / "agent_response.json"
    write_json(out, response)
    return out


def plain(value: Any) -> Any:
    """Convert dataclasses to plain JSON-ready dictionaries."""

    if is_dataclass(value):
        return asdict(value)
    return value


def observation_summary(
    page,
    site_name: str,
    target_path: str | None,
    last_signal: Any = None,
    last_decision: Any = None,
) -> str:
    """Build a compact observation summary for planner calls."""

    parts = [
        f"current_url: {page.url}",
        f"page_title: {page.title()}",
    ]
    if site_name == "gitlab":
        parts.extend(
            [
                f"login_form_visible: {page.locator('#user_login').count() > 0}",
                f"target_reached: {'/dashboard/todos' in page.url}",
            ]
        )
    elif site_name == "shopping":
        target_slug = target_path.rsplit("/", maxsplit=1)[-1].replace(".html", "") if target_path else ""
        parts.extend(
            [
                f"shopping_search_visible: {'catalogsearch/result' in page.url}",
                f"target_product_reached: {target_slug in page.url or 'bruxism-night-guard' in page.url}",
            ]
        )
    if last_signal is not None:
        parts.append(f"last_evaluator_signal: {json.dumps(plain(last_signal), ensure_ascii=False)}")
    if last_decision is not None:
        parts.append(f"last_controller_decision: {json.dumps(plain(last_decision), ensure_ascii=False)}")
    return "\n".join(parts)


def task_goal_reached(page, site_name: str, target_path: str | None = None) -> bool:
    """Return whether the current prototype task has reached its target state."""

    if site_name == "gitlab":
        return "/dashboard/todos" in page.url
    if site_name == "shopping" and target_path:
        target_slug = target_path.rsplit("/", maxsplit=1)[-1].replace(".html", "")
        return target_slug in page.url or "bruxism-night-guard" in page.url
    return False


def evaluate_runtime_state(page, site_name: str, step_index: int, subgoal: Any, previous_urls: list[str], target_path: str | None):
    """Dispatch to the site-specific internal runtime evaluator."""

    if site_name == "gitlab":
        return evaluate_gitlab_task44_state(page, step_index, subgoal, previous_urls)
    if site_name == "shopping" and target_path is not None:
        return evaluate_shopping_task118_state(page, step_index, subgoal, previous_urls, target_path)
    raise ValueError(f"No runtime evaluator configured for site {site_name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--site", choices=["gitlab", "shopping"], default="gitlab")
    parser.add_argument("--tasks-file", type=Path, default=Path("output/tasks.demo.json"))
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--config", type=Path, default=Path("examples/configs/config.demo.json"))
    parser.add_argument("--h", type=int, default=0, help="Planning horizon. 0 means full LLM plan.")
    parser.add_argument("--k", type=int, default=1, help="Run evaluator after every k executor steps.")
    parser.add_argument("--planner-mode", choices=["ollama"], default="ollama")
    parser.add_argument("--model", default="gemma4:26b")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--prompt-path", type=Path, default=Path("prompts/planner_system.md"))
    parser.add_argument("--user-template-path", type=Path, default=Path("prompts/prompt_user_template.md"))
    parser.add_argument("--max-steps", type=int, default=5)
    parser.add_argument("--max-planner-calls", type=int, default=5)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args()

    if args.k < 1:
        raise ValueError("--k must be >= 1")

    repo_root = args.repo_root.resolve()
    task_id = args.task_id if args.task_id is not None else default_task_id(args.site)
    site_spec = HARDCODED_TASKS[args.site]
    site_input = SITE_INPUTS[args.site]
    tasks_file = args.tasks_file if args.tasks_file.is_absolute() else repo_root / args.tasks_file
    output_root = args.output_root or Path(f"output/hk-prototype/h{args.h}_k{args.k}")
    output_root = output_root if output_root.is_absolute() else repo_root / output_root
    task_output_dir = output_root / args.site / str(task_id) if args.output_root is None else output_root / str(task_id)
    task_output_dir.mkdir(parents=True, exist_ok=True)
    if args.site == "gitlab":
        config = args.config if args.config.is_absolute() else repo_root / args.config
    else:
        config = write_site_config(repo_root, site_input, task_output_dir / "configs")

    logger = TraceLogger(task_output_dir)
    logger.reset()

    started = time.perf_counter()
    task = load_or_render_task(repo_root, args.site, task_id, config, task_output_dir, tasks_file)
    start_url = task["start_urls"][0]
    target_path = site_spec.target_path
    if args.site == "gitlab":
        target_url = task44_target_url(start_url)
        credentials = load_gitlab_credentials(config)
        executor = Task44ScriptedExecutor(target_url=target_url, credentials=credentials)
    elif args.site == "shopping" and target_path is not None:
        target_url = absolute_url(start_url, target_path)
        executor = ShoppingTask118Executor(start_url=start_url, target_path=target_path)
    else:
        raise ValueError(f"Unsupported H/k prototype site: {args.site}")
    assert_site_reachable(start_url)

    har_path = task_output_dir / "network.har"
    eval_proc: subprocess.CompletedProcess[str] | None = None
    final_decision = "continue"
    previous_urls: list[str] = []
    step_index = 0
    planner_call_count = 0
    plan_subgoals_generated = 0
    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    all_planner_warnings: list[str] = []
    plan = None
    last_signal = None
    last_decision = None

    progress_total = args.max_steps + args.max_planner_calls + 3 + (0 if args.skip_eval else 1)
    with tqdm(total=progress_total, desc=f"H/k {args.site} task {task_id}", unit="event") as bar:
        env = gym.make(
            "browsergym/openended",
            task_kwargs={"start_url": start_url, "goal": task["intent"]},
            headless=not args.headed,
            wait_for_user_message=False,
            pw_context_kwargs={
                "record_har_path": str(har_path),
                "record_har_content": "embed",
            },
        )
        obs, info = env.reset()
        page = env.unwrapped.page
        logger.log_reset(step_index, page.url, sorted(obs.keys()))
        previous_urls.append(page.url)
        bar.update(1)

        while not task_goal_reached(page, args.site, target_path) and step_index < args.max_steps and planner_call_count < args.max_planner_calls:
            previous_plan = plain(plan) if plan is not None else None
            planner_request = PlannerRequest(
                task=task,
                site_name=args.site,
                h=args.h,
                target_hint=target_path,
                retrieved_data_hint=site_spec.retrieved_data,
                initial_observation=observation_summary(page, args.site, target_path, last_signal, last_decision),
                previous_plan=previous_plan,
                evaluator_feedback=plain(last_signal) if last_signal is not None else None,
                controller_decision=plain(last_decision) if last_decision is not None else None,
            )
            planner_artifacts = build_plan(
                planner_request,
                planner_mode=args.planner_mode,
                model_name=args.model,
                ollama_base_url=args.ollama_base_url,
                prompt_path=args.prompt_path,
                user_template_path=args.user_template_path,
            )
            planner_call_count += 1
            plan = planner_artifacts.plan
            plan_subgoals_generated += len(plan.subgoals)
            if planner_artifacts.total_tokens is not None:
                total_tokens += planner_artifacts.total_tokens
            if planner_artifacts.prompt_tokens is not None:
                prompt_tokens += planner_artifacts.prompt_tokens
            if planner_artifacts.completion_tokens is not None:
                completion_tokens += planner_artifacts.completion_tokens
            all_planner_warnings.extend(planner_artifacts.warnings or [])
            logger.write_planner_call(
                planner_call_count,
                plan,
                planner_artifacts.prompt,
                planner_artifacts.raw_response,
                planner_artifacts.warnings,
            )
            if planner_call_count == 1:
                logger.write_plan(plan)
                if planner_artifacts.prompt is not None:
                    (task_output_dir / "planner_prompt.md").write_text(planner_artifacts.prompt, encoding="utf-8")
                if planner_artifacts.raw_response is not None:
                    (task_output_dir / "planner_raw_response.txt").write_text(planner_artifacts.raw_response, encoding="utf-8")
            if planner_artifacts.warnings:
                write_json(task_output_dir / "planner_warnings.json", all_planner_warnings)
            bar.update(1)

            active_subgoals = plan.subgoals
            if not active_subgoals:
                raise RuntimeError("Planner returned no subgoals")

            for subgoal in active_subgoals:
                if step_index >= args.max_steps or task_goal_reached(page, args.site, target_path):
                    break

                subgoal_done = False
                while not subgoal_done and step_index < args.max_steps and not task_goal_reached(page, args.site, target_path):
                    executor_steps = executor.execute_subgoal(env, page, subgoal, step_index + 1)
                    for executor_step in executor_steps:
                        if executor_step.step_index > args.max_steps:
                            break

                        step_index = executor_step.step_index
                        logger.log_executor_step(executor_step)
                        previous_urls.append(page.url)
                        goal_reached = task_goal_reached(page, args.site, target_path)
                        should_validate = step_index % args.k == 0 or goal_reached

                        if should_validate:
                            last_signal = evaluate_runtime_state(page, args.site, step_index, subgoal, previous_urls, target_path)
                            logger.log_evaluator_signal(last_signal)
                            last_decision = decide_next_action(last_signal, step_index >= args.max_steps)
                            logger.log_controller_decision(last_decision)
                            final_decision = last_decision.decision
                            subgoal_done = last_signal.subgoal_done or goal_reached
                            if last_decision.decision == "abort":
                                break
                        elif args.site != "shopping":
                            subgoal_done = True

                        bar.update(1)
                        if final_decision == "abort" or goal_reached:
                            subgoal_done = True
                            break

                    if final_decision == "abort":
                        break

                if final_decision == "abort":
                    break

            if final_decision == "abort":
                break

        final_url = page.url
        final_title = page.title()
        env.close()
        bar.update(1)

        response_path = write_agent_response(task_output_dir, site_spec.task_type)
        bar.update(1)

        if not args.skip_eval:
            eval_proc = run_eval(repo_root, config, task_id, task_output_dir.parent)
            bar.update(1)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    eval_result_path = task_output_dir / "eval_result.json"
    eval_result = read_json(eval_result_path) if eval_result_path.exists() else {}
    evaluator_rows = read_jsonl(logger.evaluator_path)
    controller_rows = read_jsonl(logger.controller_path)
    run_trace = RunTrace(
        task_id=task_id,
        site=args.site,
        h=args.h,
        k=args.k,
        planner_mode=plan.planner_mode,
        model=args.model,
        prompt_version="planner_system+prompt_user_template-v1",
        total_steps=step_index,
        total_runtime_ms=elapsed_ms,
        total_tokens=total_tokens,
        num_planner_calls=planner_call_count,
        num_plan_subgoals_generated=plan_subgoals_generated,
        num_replans=sum(1 for row in controller_rows if row.get("decision") in {"local_replan", "global_replan"}),
        num_no_progress_events=sum(1 for row in evaluator_rows if row.get("no_progress") or row.get("loop_or_no_progress_flag")),
        num_invalid_actions=sum(1 for row in evaluator_rows if row.get("invalid_action") or row.get("action_validity_flag") is False),
        num_loop_events=sum(1 for row in evaluator_rows if row.get("loop_detected")),
        final_status=final_decision,
        success=eval_result.get("score") == 1.0 if eval_result else None,
        abort_reason=final_decision if final_decision == "abort" else None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    run_trace_path = logger.write_run_trace(run_trace)
    summary = {
        "task_id": task_id,
        "site": args.site,
        "h": args.h,
        "k": args.k,
        "planner_mode": plan.planner_mode,
        "model": args.model,
        "planner_warnings": all_planner_warnings,
        "num_planner_calls": planner_call_count,
        "num_plan_subgoals_generated": plan_subgoals_generated,
        "total_steps": step_index,
        "total_runtime_ms": elapsed_ms,
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "final_url": final_url,
        "final_title": final_title,
        "controller_final_decision": final_decision,
        "success": eval_result.get("score") == 1.0 if eval_result else None,
        "score": eval_result.get("score"),
        "artifacts": {
            "plan": str(task_output_dir / "plan.json"),
            "step_trace": str(logger.step_trace_path),
            "evaluator_signals": str(logger.evaluator_path),
            "controller_decisions": str(logger.controller_path),
            "run_trace": str(run_trace_path),
            "network_har": str(har_path),
            "agent_response": str(response_path),
            "eval_result": str(eval_result_path),
        },
    }
    write_json(task_output_dir / "run_summary.json", summary)

    print("\nH/k prototype summary")
    print(json.dumps({k: summary[k] for k in ["site", "task_id", "h", "k", "success", "score", "final_url"]}, indent=2))
    print(f"\nArtifacts: {task_output_dir}")

    if eval_proc is not None and eval_proc.returncode != 0:
        if eval_proc.stdout:
            print(eval_proc.stdout)
        if eval_proc.stderr:
            print(eval_proc.stderr)
        return eval_proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
