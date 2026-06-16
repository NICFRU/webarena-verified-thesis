#!/usr/bin/env python3
"""Run BrowserGym/WebArena-Verified Hard H/k sweeps."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if sys.version_info < (3, 12):
    raise RuntimeError(
        "This experiment requires Python >= 3.12 because "
        "browsergym-webarena-verified depends on it. Active interpreter: "
        f"{sys.executable} ({sys.version.split()[0]}). Recreate .venv with "
        "`uv venv --python 3.12 .venv` before running experiments."
    )

from tqdm import tqdm

from hk_agent.diagnostics import diagnose_run_summary, summarize_diagnostics
from hk_agent.runner import llm_backend_metadata, run_hk_task
from hk_agent.prompt_builder import resolve_agent_architecture
from hk_agent.task_loader import (
    capability_tier,
    filter_tasks_by_capability,
    infer_official_task_type,
    infer_task_capability,
    sample_tasks_by_site_and_bucket,
    select_tasks,
    write_experiment_tasks,
)
from hk_agent.warnings import suppress_third_party_warnings
from webarena_exp.io_utils import read_json, write_json


suppress_third_party_warnings()


RESTARTABLE_FAILURE_CATEGORIES = {
    "runtime_exception",
    "repeated_llm_timeout",
    "step_budget_exhausted",
    "planner_call_budget_exhausted",
    "bad_route_or_not_found",
    "llm_json_or_action_parse_failure",
    "loop_or_no_progress",
}

RESETTABLE_SITES = {"gitlab", "shopping", "shopping_admin", "reddit"}
GITLAB_POST_READY_SETTLE_SECONDS = 60
SITE_HOST_PORTS = {
    "shopping": [7770, 7771],
    "shopping_admin": [7780, 7781],
    "reddit": [9999, 9998],
    "gitlab": [8023, 8024],
}
SITE_READY_URLS = {
    "shopping": "http://localhost:7770/",
    "shopping_admin": "http://localhost:7780/admin",
    "reddit": "http://localhost:9999/",
    "gitlab": "http://localhost:8023/users/sign_in",
}
DOCKER_SITE_SPECS = {
    "shopping": {
        "container": "webarena-verified-shopping",
        "image": "am1n3e/webarena-verified-shopping",
        "ports": [("7770", "80"), ("7771", "8877")],
    },
    "shopping_admin": {
        "container": "webarena-verified-shopping_admin",
        "image": "am1n3e/webarena-verified-shopping_admin",
        "ports": [("7780", "80"), ("7781", "8877")],
    },
    "reddit": {
        "container": "webarena-verified-reddit",
        "image": "am1n3e/webarena-verified-reddit",
        "ports": [("9999", "80"), ("9998", "8877")],
    },
    "gitlab": {
        "container": "webarena-verified-gitlab",
        "image": "am1n3e/webarena-verified-gitlab",
        "ports": [("8023", "8023"), ("8024", "8877")],
    },
}


def assert_runtime_environment() -> None:
    """Fail before touching summaries when the active Python env is unusable."""

    if sys.version_info < (3, 12):
        raise RuntimeError(
            "This experiment requires Python >= 3.12 because "
            "browsergym-webarena-verified depends on it. Active interpreter: "
            f"{sys.executable} ({sys.version.split()[0]}). Recreate .venv with "
            "`uv venv --python 3.12 .venv` before running experiments."
        )
    missing: list[str] = []
    for module_name in ["gymnasium", "browsergym", "webarena_verified"]:
        try:
            __import__(module_name)
        except ModuleNotFoundError:
            missing.append(module_name)
    if missing:
        raise RuntimeError(
            "The active Python environment is missing required modules: "
            f"{', '.join(missing)}. Install with `uv pip install -r requirements.txt` "
            "and `uv pip install -e external/webarena-verified` before running experiments."
        )


def slug(value: str) -> str:
    return value.replace(":", "-").replace("/", "-").replace(" ", "-")


def resolve_planner_call_budget(max_planner_calls: str | int, max_steps: int, h: int, margin: int = 2) -> int | None:
    """Return the per-run planner-call budget for a horizon setting."""

    value = str(max_planner_calls).strip().lower()
    if value in {"auto", "dynamic", "-1"}:
        if max_steps <= 0:
            return None
        if h <= 0:
            return max(10, (max_steps + 4) // 5 + margin)
        return max(1, (max_steps + h - 1) // h + margin)
    parsed = int(value)
    return parsed if parsed > 0 else None


def resolve_step_budget_for_task(
    *,
    task_capability_tier: str,
    max_steps: int,
    max_steps_policy: str,
    navigation_steps: int,
    retrieval_steps: int,
    policy_steps: int,
    mutation_steps: int,
) -> int | None:
    """Return the per-task step budget for fixed or tiered resource policies."""

    if max_steps <= 0:
        return None
    if max_steps_policy != "tiered":
        return max_steps
    if task_capability_tier == "navigation":
        return navigation_steps
    if task_capability_tier in {"visible_retrieve", "structured_retrieve"}:
        return retrieval_steps
    if task_capability_tier == "policy":
        return policy_steps
    if task_capability_tier == "mutation":
        return mutation_steps
    return max_steps


def wait_for_site_ready(site: str, timeout_seconds: int) -> tuple[bool, str | None]:
    """Poll a reset WebArena site until it is usable by the browser task."""

    ready_url = SITE_READY_URLS.get(site)
    if not ready_url:
        return True, None

    deadline = time.monotonic() + max(1, timeout_seconds)
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            headers = {"User-Agent": "hk-agent-readiness/1.0"}
            if site == "shopping_admin":
                headers["X-M2-Admin-Auto-Login"] = "admin:admin1234"
            req = Request(ready_url, headers=headers)
            with urlopen(req, timeout=10) as response:
                status = getattr(response, "status", 200)
                body = response.read(200_000).decode("utf-8", errors="ignore").lower()
            if 200 <= status < 400:
                if site == "gitlab":
                    if "username or email" in body or "sign in" in body or "new user" in body:
                        return True, None
                    last_error = "gitlab_http_ok_but_login_not_ready"
                elif site == "shopping_admin":
                    admin_login_ready = (
                        'id="username"' in body
                        or "name=\"login[username]\"" in body
                        or "name='login[username]'" in body
                        or "username" in body and "password" in body and "sign in" in body
                    )
                    admin_session_ready = (
                        "dashboard" in body
                        or "admin dashboard" in body
                        or "data-ui-id=\"page-title-wrapper\"" in body
                        or "admin__menu" in body
                        or "menu-magento-backend" in body
                        or "magento" in body and "/admin/" in body
                    )
                    if admin_login_ready or admin_session_ready:
                        return True, None
                    last_error = "shopping_admin_http_ok_but_login_not_ready"
                else:
                    return True, None
        except HTTPError as exc:
            last_error = f"http_{exc.code}"
            if site != "gitlab" and exc.code < 500:
                return True, None
        except (OSError, TimeoutError, URLError) as exc:
            last_error = str(exc)
        time.sleep(5)

    return False, last_error or f"{site}_not_ready"


def reset_webarena_site_before_run(repo_root: Path, site: str, timeout_seconds: int) -> dict[str, Any]:
    """Restart one WebArena-Verified site container before a stateful run."""

    info: dict[str, Any] = {
        "site_reset_before_run": True,
        "site_reset_site": site,
        "site_reset_elapsed_ms": None,
        "site_reset_returncode": None,
        "site_reset_error": None,
    }
    if site not in RESETTABLE_SITES:
        info["site_reset_returncode"] = 0
        info["site_reset_error"] = f"site_not_resettable:{site}"
        return info

    spec = DOCKER_SITE_SPECS.get(site)
    if not spec:
        info["site_reset_returncode"] = 0
        info["site_reset_error"] = f"site_not_docker_resettable:{site}"
        return info

    container_name = str(spec["container"])
    image = str(spec["image"])
    port_args: list[str] = []
    for host_port, container_port in spec["ports"]:
        port_args.extend(["-p", f"{host_port}:{container_port}"])
    command = ["docker", "run", "-d", "--name", container_name, *port_args, image]
    started = time.perf_counter()
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        conflicts = clear_site_port_conflicts(site)
        proc = subprocess.run(
            command,
            cwd=repo_root,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        info["site_reset_returncode"] = proc.returncode
        if proc.returncode != 0:
            output_tail = "\n".join((proc.stderr or proc.stdout or "").splitlines()[-12:])
            info["site_reset_error"] = output_tail or f"docker reset failed with returncode {proc.returncode}"
        if info["site_reset_returncode"] == 0:
            ready, ready_error = wait_for_site_ready(site, timeout_seconds)
            if ready:
                if site == "gitlab":
                    time.sleep(GITLAB_POST_READY_SETTLE_SECONDS)
                if conflicts:
                    info["site_reset_error"] = f"docker_recreated; cleared_port_conflicts:{conflicts}; ready_check=ok"
                else:
                    info["site_reset_error"] = "docker_recreated; ready_check=ok"
            else:
                info["site_reset_returncode"] = -2
                info["site_reset_error"] = f"site reset completed but {site} was not ready: {ready_error}"
    except subprocess.TimeoutExpired as exc:
        info["site_reset_returncode"] = -1
        info["site_reset_error"] = f"site reset timed out after {exc.timeout} seconds"
    finally:
        info["site_reset_elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return info


def docker_containers_on_ports(ports: list[int]) -> list[dict[str, str]]:
    """Return Docker containers publishing any of the given host ports."""

    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Ports}}"],
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    matches: list[dict[str, str]] = []
    port_markers = [f":{port}->" for port in ports]
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        container_id, name, published = parts
        if any(marker in published for marker in port_markers):
            matches.append({"id": container_id, "name": name, "ports": published})
    return matches


def clear_site_port_conflicts(site: str) -> list[dict[str, str]]:
    """Stop and remove Docker containers currently occupying this site's host ports."""

    conflicts = docker_containers_on_ports(SITE_HOST_PORTS.get(site, []))
    for conflict in conflicts:
        container_id = conflict["id"]
        subprocess.run(["docker", "stop", container_id], text=True, capture_output=True, check=False, timeout=60)
        subprocess.run(["docker", "rm", "-f", container_id], text=True, capture_output=True, check=False, timeout=30)
    return conflicts


def apply_success_policy(summary: dict[str, Any], success_policy: str) -> dict[str, Any]:
    """Attach the report-level evaluation metric and promote accepted corrections.

    For ``contamination_adjusted`` runs, transparent evaluator-normalization
    fixes are treated as official successes for the experiment summary. The raw
    WebArena result is preserved in ``official_success_raw``/``official_score_raw``.
    """

    if "official_success_raw" not in summary:
        summary["official_success_raw"] = summary.get("official_success")
    if "official_score_raw" not in summary:
        summary["official_score_raw"] = summary.get("official_score")

    official_success = summary.get("official_success_raw") is True
    official_score = summary.get("official_score_raw")
    if success_policy == "contamination_adjusted":
        evaluation_success = bool(summary.get("contamination_adjusted_success")) or official_success
        evaluation_score = 1.0 if evaluation_success else official_score
    else:
        evaluation_success = official_success
        evaluation_score = official_score
    summary["official_success"] = evaluation_success
    summary["official_score"] = evaluation_score
    summary["evaluation_success_policy"] = success_policy
    summary["evaluation_success"] = evaluation_success
    summary["evaluation_score"] = evaluation_score
    return summary


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "task_id",
        "intent_template_id",
        "revision",
        "gym_id",
        "site",
        "sites",
        "task_type",
        "task_capability",
        "capability_tier",
        "h",
        "k",
        "run_mode",
        "planner_model",
        "executor_model",
        "agent_architecture",
        "max_consecutive_llm_timeouts",
        "llm_backend",
        "ollama_base_url",
        "vertex_proxy_enabled",
        "vertex_project_id",
        "vertex_location",
        "vertex_maas_model",
        "num_attempts",
        "max_attempts",
        "had_restart",
        "restart_count",
        "restart_reason",
        "first_attempt_status",
        "first_attempt_failure_category",
        "official_score_raw",
        "official_success_raw",
        "official_score",
        "official_success",
        "official_eval_status",
        "failure_category",
        "evaluation_success_policy",
        "evaluation_score",
        "evaluation_success",
        "contamination_adjusted_success",
        "official_eval_contamination_suffix_detected",
        "official_eval_adjustable_suffix_failures",
        "official_eval_nonadjustable_failures",
        "contamination_adjusted_reason",
        "runtime_progress_score",
        "runtime_replans",
        "runtime_no_progress_events",
        "runtime_invalid_actions",
        "runtime_loop_events",
        "total_steps",
        "max_steps_policy",
        "max_steps",
        "max_steps_disabled",
        "step_budget_reached",
        "total_runtime_ms",
        "total_tokens",
        "planner_tokens",
        "executor_tokens",
        "prompt_tokens",
        "completion_tokens",
        "planner_prompt_tokens",
        "planner_completion_tokens",
        "executor_prompt_tokens",
        "executor_completion_tokens",
        "num_plan_subgoals_generated",
        "planner_calls",
        "max_planner_calls",
        "max_planner_calls_disabled",
        "planner_call_budget_reached",
        "executor_calls",
        "diagnostic_completion",
        "near_miss_score",
        "failure_class",
        "final_attempt_index",
        "final_attempt_status",
        "final_attempt_official_score",
        "final_success_after_restart",
        "total_steps_all_attempts",
        "total_tokens_all_attempts",
        "planner_tokens_all_attempts",
        "executor_tokens_all_attempts",
        "prompt_tokens_all_attempts",
        "completion_tokens_all_attempts",
        "total_runtime_ms_all_attempts",
        "attempt_output_dirs",
        "status",
        "official_eval_incomplete_multi_invite_detected",
        "official_eval_incomplete_multi_invite_reason",
        "state_reached",
        "submit_reached",
        "mutation_attempted",
        "loop_after_reaching_form",
        "failure_notes",
        "final_response_status",
        "final_action_kind",
        "route_satisfied_auto_final",
        "is_mutate_task",
        "mutation_eval_focus",
        "mutation_tier_requires_state_change",
        "mutation_action_count",
        "mutation_actions_before_finish",
        "finish_after_mutation_action",
        "final_success_without_mutation_action",
        "recent_error_before_finish",
        "site_reset_before_run",
        "site_reset_site",
        "site_reset_elapsed_ms",
        "site_reset_returncode",
        "site_reset_error",
        "num_executor_json_calls",
        "num_step_errors",
        "last_step_error",
        "output_dir",
        "error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def row_from_summary(summary: dict[str, Any], output_dir: Path, status: str = "completed") -> dict[str, Any]:
    return {
        "task_id": summary.get("task_id"),
        "intent_template_id": summary.get("intent_template_id"),
        "revision": summary.get("revision"),
        "gym_id": summary.get("gym_id"),
        "site": summary.get("site"),
        "sites": ",".join(summary.get("sites", [])),
        "task_type": summary.get("task_type"),
        "task_capability": summary.get("task_capability"),
        "capability_tier": summary.get("capability_tier"),
        "h": summary.get("h"),
        "k": summary.get("k"),
        "run_mode": summary.get("run_mode"),
        "planner_model": summary.get("planner_model"),
        "executor_model": summary.get("executor_model"),
        "agent_architecture": summary.get("agent_architecture"),
        "max_consecutive_llm_timeouts": summary.get("max_consecutive_llm_timeouts"),
        "llm_backend": summary.get("llm_backend"),
        "ollama_base_url": summary.get("ollama_base_url"),
        "vertex_proxy_enabled": summary.get("vertex_proxy_enabled"),
        "vertex_project_id": summary.get("vertex_project_id"),
        "vertex_location": summary.get("vertex_location"),
        "vertex_maas_model": summary.get("vertex_maas_model"),
        "num_attempts": summary.get("num_attempts"),
        "max_attempts": summary.get("max_attempts"),
        "had_restart": summary.get("had_restart"),
        "restart_count": summary.get("restart_count"),
        "restart_reason": summary.get("restart_reason"),
        "first_attempt_status": summary.get("first_attempt_status"),
        "first_attempt_failure_category": summary.get("first_attempt_failure_category"),
        "final_attempt_index": summary.get("final_attempt_index"),
        "final_attempt_status": summary.get("final_attempt_status"),
        "final_attempt_official_score": summary.get("final_attempt_official_score"),
        "final_success_after_restart": summary.get("final_success_after_restart"),
        "total_steps_all_attempts": summary.get("total_steps_all_attempts"),
        "total_tokens_all_attempts": summary.get("total_tokens_all_attempts"),
        "planner_tokens_all_attempts": summary.get("planner_tokens_all_attempts"),
        "executor_tokens_all_attempts": summary.get("executor_tokens_all_attempts"),
        "prompt_tokens_all_attempts": summary.get("prompt_tokens_all_attempts"),
        "completion_tokens_all_attempts": summary.get("completion_tokens_all_attempts"),
        "total_runtime_ms_all_attempts": summary.get("total_runtime_ms_all_attempts"),
        "attempt_output_dirs": json.dumps(summary.get("attempt_output_dirs", []), ensure_ascii=False),
        "status": status,
        "official_score_raw": summary.get("official_score_raw"),
        "official_success_raw": summary.get("official_success_raw"),
        "official_score": summary.get("official_score"),
        "official_success": summary.get("official_success"),
        "official_eval_status": summary.get("official_eval_status"),
        "evaluation_success_policy": summary.get("evaluation_success_policy"),
        "evaluation_score": summary.get("evaluation_score"),
        "evaluation_success": summary.get("evaluation_success"),
        "contamination_adjusted_success": summary.get("contamination_adjusted_success"),
        "official_eval_contamination_suffix_detected": summary.get("official_eval_contamination_suffix_detected"),
        "official_eval_adjustable_suffix_failures": summary.get("official_eval_adjustable_suffix_failures"),
        "official_eval_nonadjustable_failures": summary.get("official_eval_nonadjustable_failures"),
        "contamination_adjusted_reason": summary.get("contamination_adjusted_reason"),
        "runtime_progress_score": summary.get("runtime_progress_score"),
        "runtime_replans": summary.get("runtime_replans"),
        "runtime_no_progress_events": summary.get("runtime_no_progress_events"),
        "runtime_invalid_actions": summary.get("runtime_invalid_actions"),
        "runtime_loop_events": summary.get("runtime_loop_events"),
        "total_steps": summary.get("total_steps"),
        "max_steps_policy": summary.get("max_steps_policy"),
        "max_steps": summary.get("max_steps"),
        "max_steps_disabled": summary.get("max_steps_disabled"),
        "step_budget_reached": summary.get("step_budget_reached"),
        "total_runtime_ms": summary.get("total_runtime_ms"),
        "total_tokens": summary.get("total_tokens"),
        "planner_tokens": summary.get("planner_tokens"),
        "executor_tokens": summary.get("executor_tokens"),
        "prompt_tokens": summary.get("prompt_tokens"),
        "completion_tokens": summary.get("completion_tokens"),
        "planner_prompt_tokens": summary.get("planner_prompt_tokens"),
        "planner_completion_tokens": summary.get("planner_completion_tokens"),
        "executor_prompt_tokens": summary.get("executor_prompt_tokens"),
        "executor_completion_tokens": summary.get("executor_completion_tokens"),
        "num_plan_subgoals_generated": summary.get("num_plan_subgoals_generated"),
        "planner_calls": summary.get("planner_calls"),
        "max_planner_calls": summary.get("max_planner_calls"),
        "max_planner_calls_disabled": summary.get("max_planner_calls_disabled"),
        "planner_call_budget_reached": summary.get("planner_call_budget_reached"),
        "executor_calls": summary.get("executor_calls"),
        "diagnostic_completion": summary.get("diagnostic_completion"),
        "failure_category": summary.get("failure_category"),
        "near_miss_score": summary.get("near_miss_score"),
        "failure_class": summary.get("failure_class"),
        "official_eval_incomplete_multi_invite_detected": summary.get("official_eval_incomplete_multi_invite_detected"),
        "official_eval_incomplete_multi_invite_reason": summary.get("official_eval_incomplete_multi_invite_reason"),
        "state_reached": summary.get("state_reached"),
        "submit_reached": summary.get("submit_reached"),
        "mutation_attempted": summary.get("mutation_attempted"),
        "loop_after_reaching_form": summary.get("loop_after_reaching_form"),
        "failure_notes": summary.get("failure_notes"),
        "final_response_status": summary.get("final_response_status"),
        "final_action_kind": summary.get("final_action_kind"),
        "route_satisfied_auto_final": summary.get("route_satisfied_auto_final"),
        "is_mutate_task": summary.get("is_mutate_task"),
        "mutation_eval_focus": summary.get("mutation_eval_focus"),
        "mutation_tier_requires_state_change": summary.get("mutation_tier_requires_state_change"),
        "mutation_action_count": summary.get("mutation_action_count"),
        "mutation_actions_before_finish": summary.get("mutation_actions_before_finish"),
        "finish_after_mutation_action": summary.get("finish_after_mutation_action"),
        "final_success_without_mutation_action": summary.get("final_success_without_mutation_action"),
        "recent_error_before_finish": summary.get("recent_error_before_finish"),
        "site_reset_before_run": summary.get("site_reset_before_run"),
        "site_reset_site": summary.get("site_reset_site"),
        "site_reset_elapsed_ms": summary.get("site_reset_elapsed_ms"),
        "site_reset_returncode": summary.get("site_reset_returncode"),
        "site_reset_error": summary.get("site_reset_error"),
        "num_executor_json_calls": summary.get("num_executor_json_calls"),
        "num_step_errors": summary.get("num_step_errors"),
        "last_step_error": summary.get("last_step_error"),
        "output_dir": str(output_dir),
    }


def refresh_existing_row_diagnostics(row: dict[str, Any], *, success_policy: str) -> dict[str, Any]:
    """Refresh diagnostic-only columns for a completed row without rerunning the task."""

    output_dir_value = row.get("output_dir")
    if not output_dir_value:
        return row
    output_dir = Path(str(output_dir_value))
    summary_path = output_dir / "run_summary.json"
    if not summary_path.exists():
        return row
    try:
        summary = read_json(summary_path)
        diagnostic = diagnose_run_summary(summary, output_dir)
        summary.update(diagnostic)
        apply_success_policy(summary, success_policy)
        write_json(output_dir / "diagnostic.json", diagnostic)
        write_json(summary_path, summary)
        refreshed = row_from_summary(summary, output_dir, status=str(row.get("status") or "completed"))
        return {**row, **refreshed}
    except Exception:
        return row


def _sum_int(rows: list[dict[str, Any]], key: str) -> int:
    return sum(int(row.get(key) or 0) for row in rows)


def should_restart_attempt(summary: dict[str, Any], attempt_index: int, max_attempts: int, k: int) -> bool:
    """Return whether the restart variant should launch another full attempt."""

    if k <= 0:
        return False
    if attempt_index >= max_attempts:
        return False
    if summary.get("official_success") is True:
        return False
    category = str(summary.get("failure_category") or "")
    return category in RESTARTABLE_FAILURE_CATEGORIES


def aggregate_attempt_summaries(
    *,
    attempts: list[dict[str, Any]],
    output_dir: Path,
    max_attempts: int,
    restart_reason: str | None = None,
) -> dict[str, Any]:
    """Aggregate multiple attempt summaries into one experiment row summary."""

    if not attempts:
        raise ValueError("Cannot aggregate empty attempt list")
    successful = [attempt for attempt in attempts if attempt.get("official_success") is True]
    final = successful[0] if successful else attempts[-1]
    first = attempts[0]
    attempt_output_dirs = [str(attempt.get("output_dir") or attempt.get("artifacts", {}).get("run_summary", "")) for attempt in attempts]
    attempt_output_dirs = [str(Path(path).parent if path.endswith("run_summary.json") else path) for path in attempt_output_dirs if path]
    aggregate = dict(final)
    aggregate.update(
        {
            "output_dir": str(output_dir),
            "artifacts": {
                **dict(final.get("artifacts", {})),
                "attempt_output_dirs": attempt_output_dirs,
                "attempt_summaries": str(output_dir / "attempts_summary.json"),
                "run_summary": str(output_dir / "run_summary.json"),
            },
            "attempts": attempts,
            "num_attempts": len(attempts),
            "max_attempts": max_attempts,
            "had_restart": len(attempts) > 1,
            "restart_count": max(0, len(attempts) - 1),
            "restart_reason": restart_reason,
            "first_attempt_status": "success" if first.get("official_success") is True else "failure",
            "first_attempt_failure_category": first.get("failure_category"),
            "final_attempt_index": attempts.index(final) + 1,
            "final_attempt_status": "success" if final.get("official_success") is True else "failure",
            "final_attempt_official_score": final.get("official_score"),
            "final_success_after_restart": len(attempts) > 1 and final.get("official_success") is True,
            "total_steps_all_attempts": _sum_int(attempts, "total_steps"),
            "total_tokens_all_attempts": _sum_int(attempts, "total_tokens"),
            "planner_tokens_all_attempts": _sum_int(attempts, "planner_tokens"),
            "executor_tokens_all_attempts": _sum_int(attempts, "executor_tokens"),
            "prompt_tokens_all_attempts": _sum_int(attempts, "prompt_tokens"),
            "completion_tokens_all_attempts": _sum_int(attempts, "completion_tokens"),
            "total_runtime_ms_all_attempts": _sum_int(attempts, "total_runtime_ms"),
            "attempt_output_dirs": attempt_output_dirs,
            "total_steps": _sum_int(attempts, "total_steps"),
            "total_tokens": _sum_int(attempts, "total_tokens"),
            "planner_tokens": _sum_int(attempts, "planner_tokens"),
            "executor_tokens": _sum_int(attempts, "executor_tokens"),
            "prompt_tokens": _sum_int(attempts, "prompt_tokens"),
            "completion_tokens": _sum_int(attempts, "completion_tokens"),
            "planner_prompt_tokens": _sum_int(attempts, "planner_prompt_tokens"),
            "planner_completion_tokens": _sum_int(attempts, "planner_completion_tokens"),
            "executor_prompt_tokens": _sum_int(attempts, "executor_prompt_tokens"),
            "executor_completion_tokens": _sum_int(attempts, "executor_completion_tokens"),
            "total_runtime_ms": _sum_int(attempts, "total_runtime_ms"),
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "attempts_summary.json", attempts)
    write_json(output_dir / "run_summary.json", aggregate)
    return aggregate


def run_hk_task_with_optional_restart(
    *,
    task,
    repo_root: Path,
    output_dir: Path,
    h: int,
    k: int,
    run_mode: str,
    planner_model: str,
    executor_model: str,
    agent_architecture: str,
    planner_mode: str,
    max_steps: int,
    max_planner_calls: int,
    headed: bool,
    skip_official_eval: bool,
    ollama_base_url: str,
    llm_timeout_seconds: int,
    max_consecutive_llm_timeouts: int,
    env_updates: dict[str, str | None],
) -> dict[str, Any]:
    """Run one H/k task, optionally restarting once after a hard failure."""

    max_attempts = 2 if agent_architecture == "v2_restart1" else 1
    attempts: list[dict[str, Any]] = []
    restart_reason = None
    for attempt_index in range(1, max_attempts + 1):
        attempt_output_dir = output_dir / f"attempt_{attempt_index}" / str(task.task_id)
        summary = run_hk_task(
            task=task,
            repo_root=repo_root,
            output_dir=attempt_output_dir if max_attempts > 1 else output_dir,
            h=h,
            k=k,
            run_mode=run_mode,
            planner_model=planner_model,
            executor_model=executor_model,
            agent_architecture=agent_architecture,
            planner_mode=planner_mode,
            max_steps=max_steps,
            max_planner_calls=max_planner_calls,
            headed=headed,
            skip_official_eval=skip_official_eval,
            ollama_base_url=ollama_base_url,
            llm_timeout_seconds=llm_timeout_seconds,
            max_consecutive_llm_timeouts=max_consecutive_llm_timeouts,
            env_updates={key: value for key, value in env_updates.items() if value is not None},
        )
        summary["attempt_index"] = attempt_index
        summary["max_attempts"] = max_attempts
        summary["output_dir"] = str(attempt_output_dir if max_attempts > 1 else output_dir)
        attempts.append(summary)
        if not should_restart_attempt(summary, attempt_index, max_attempts, k):
            break
        restart_reason = str(summary.get("failure_category") or "hard_abort")
    if max_attempts == 1:
        summary = attempts[-1]
        summary.update(
            {
                "num_attempts": 1,
                "max_attempts": 1,
                "had_restart": False,
                "restart_count": 0,
                "restart_reason": None,
                "first_attempt_status": "success" if summary.get("official_success") is True else "failure",
                "first_attempt_failure_category": summary.get("failure_category"),
                "final_attempt_index": 1,
                "final_attempt_status": "success" if summary.get("official_success") is True else "failure",
                "final_attempt_official_score": summary.get("official_score"),
                "final_success_after_restart": False,
                "total_steps_all_attempts": summary.get("total_steps"),
                "total_tokens_all_attempts": summary.get("total_tokens"),
                "planner_tokens_all_attempts": summary.get("planner_tokens"),
                "executor_tokens_all_attempts": summary.get("executor_tokens"),
                "prompt_tokens_all_attempts": summary.get("prompt_tokens"),
                "completion_tokens_all_attempts": summary.get("completion_tokens"),
                "total_runtime_ms_all_attempts": summary.get("total_runtime_ms"),
                "attempt_output_dirs": [str(output_dir)],
            }
        )
        write_json(output_dir / "run_summary.json", summary)
        return summary
    return aggregate_attempt_summaries(
        attempts=attempts,
        output_dir=output_dir,
        max_attempts=max_attempts,
        restart_reason=restart_reason,
    )


def row_key(row: dict[str, Any]) -> tuple[int, int, int]:
    return (int(row["task_id"]), int(row["h"]), int(row["k"]))


def load_existing_rows(
    experiment_root: Path,
    *,
    refresh_diagnostics: bool = False,
    success_policy: str = "webarena",
) -> dict[tuple[int, int, int], dict[str, Any]]:
    """Load rows from a previous summary so long experiments can resume."""

    summary_path = experiment_root / "summary.json"
    csv_path = experiment_root / "summary.csv"
    rows: list[dict[str, Any]] = []
    try:
        if summary_path.exists():
            loaded = read_json(summary_path).get("rows", [])
            if isinstance(loaded, list):
                rows = loaded
    except Exception:
        rows = []
    if not rows and csv_path.exists():
        try:
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        except Exception:
            rows = []
    existing: dict[tuple[int, int, int], dict[str, Any]] = {}
    for row in rows:
        try:
            if refresh_diagnostics:
                row = refresh_existing_row_diagnostics(row, success_policy=success_policy)
            existing[row_key(row)] = row
        except Exception:
            continue
    return existing


def should_rerun_existing_row(row: dict[str, Any], failure_categories: set[str], error_substrings: list[str]) -> bool:
    """Return whether an existing summary row should be recomputed."""

    if failure_categories and str(row.get("failure_category") or "") in failure_categories:
        return True
    error = str(row.get("error") or "")
    return any(fragment and fragment in error for fragment in error_substrings)


def write_experiment_outputs(experiment_root: Path, config: dict[str, Any], rows: list[dict[str, Any]], started: float) -> dict[str, Any]:
    """Write summary files, including partial output during long runs."""

    summary = {
        "experiment_config": config,
        "total_runtime_ms": int((time.perf_counter() - started) * 1000),
        "num_rows": len(rows),
        "num_completed": sum(1 for row in rows if row.get("status") == "completed"),
        "num_failed": sum(1 for row in rows if row.get("status") == "failed"),
        "num_dry_run": sum(1 for row in rows if row.get("status") == "dry_run"),
        "num_skipped_existing": sum(1 for row in rows if row.get("status") == "skipped_existing"),
        "diagnostics": summarize_diagnostics(rows),
        "rows": rows,
    }
    write_json(experiment_root / "summary.json", summary)
    write_csv(experiment_root / "summary.csv", rows)
    return summary


def backup_existing_summary(experiment_root: Path) -> None:
    """Keep a timestamped copy before a resume run rewrites summary files."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name in ["summary.csv", "summary.json"]:
        path = experiment_root / name
        if path.exists():
            backup = experiment_root / f"{path.stem}_backup_before_resume_{timestamp}{path.suffix}"
            shutil.copy2(path, backup)


def main() -> int:
    assert_runtime_environment()

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--output-root", type=Path, default=Path("runs/hk-agent"))
    parser.add_argument("--experiment-name")
    parser.add_argument("--task-ids", type=int, nargs="+")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sample-sites", nargs="+")
    parser.add_argument("--sample-buckets", nargs="+", default=["short", "medium", "long"])
    parser.add_argument("--sample-task-types", nargs="+")
    parser.add_argument("--sample-per-group", type=int, default=1)
    parser.add_argument("--sample-seed", type=int)
    parser.add_argument("--exclude-task-ids", type=int, nargs="+", default=[])
    parser.add_argument("--capabilities", nargs="+")
    parser.add_argument("--capability-tiers", nargs="+")
    parser.add_argument("--main-analysis-capabilities-only", action="store_true")
    parser.add_argument("--include-multisite", action="store_true")
    parser.add_argument("--include-unsupported-sites", action="store_true")
    parser.add_argument("--allow-non-hard-task-ids", action="store_true")
    parser.add_argument("--hs", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--ks", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--run-mode", choices=["agent", "oracle_debug", "analysis"], default="agent")
    parser.add_argument("--planner-mode", choices=["ollama", "scripted"], default="ollama")
    parser.add_argument("--planner-model", default="gemma4:26b")
    parser.add_argument("--executor-model", default="gemma4:e4b")
    parser.add_argument(
        "--agent-architecture",
        choices=["v1", "v2", "v2_guarded", "v2_restart1", "v2_planact", "v3", "v3_repair_brief", "v3_repair_llm"],
        help="Agent architecture variant. Defaults to v3_repair_llm when experiment name contains 'v3_repair_llm', v3_repair_brief when it contains 'v3_repair', v3 when it contains 'v3', v2_planact when it contains 'planact', v2 when it contains 'v2', v2_guarded when it contains 'guarded', or v2_restart1 when it contains 'restart1'.",
    )
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--llm-timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--max-consecutive-llm-timeouts",
        type=int,
        default=0,
        help=(
            "For v2_planact, abort a run after this many consecutive planner/executor "
            "LLM timeouts. Use 0 to disable this guard and preserve full H/k execution."
        ),
    )
    parser.add_argument("--max-steps", type=int, default=30, help="Maximum BrowserGym actions per run. Use 0 to disable this safety budget.")
    parser.add_argument("--max-steps-policy", choices=["fixed", "tiered"], default="fixed", help="Use a fixed max-steps budget or a capability-tier budget per task.")
    parser.add_argument("--max-steps-navigation", type=int, default=10)
    parser.add_argument("--max-steps-retrieval", type=int, default=20)
    parser.add_argument("--max-steps-policy-task", type=int, default=15)
    parser.add_argument("--max-steps-mutation", type=int, default=30)
    parser.add_argument(
        "--max-planner-calls",
        default="0",
        help="Maximum planner calls per run. Use 0 to disable this safety budget, or 'auto' for ceil(max_steps / h) + margin per run.",
    )
    parser.add_argument("--planner-call-margin", type=int, default=2, help="Extra planner calls used by --max-planner-calls auto for runtime-triggered replans.")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--skip-official-eval", action="store_true")
    parser.add_argument(
        "--success-policy",
        choices=["webarena", "contamination_adjusted"],
        default="webarena",
        help=(
            "Report-level success metric. 'webarena' uses raw official_success. "
            "'contamination_adjusted' treats evaluator failures caused only by duplicate-name suffixes as evaluation_success."
        ),
    )
    parser.add_argument(
        "--reset-site-before-run",
        action="store_true",
        help="Restart the task's WebArena-Verified site container before every run. Slow, but gives clean state.",
    )
    parser.add_argument(
        "--reset-site-before-mutate",
        action="store_true",
        help="Restart the task's site container before each official MUTATE run. Useful for uncontaminated mutation sweeps.",
    )
    parser.add_argument("--site-reset-timeout-seconds", type=int, default=180)
    parser.add_argument("--wa-gitlab")
    parser.add_argument("--wa-gitlab-username")
    parser.add_argument("--wa-gitlab-password")
    parser.add_argument("--wa-shopping")
    parser.add_argument("--wa-shopping-admin")
    parser.add_argument("--wa-reddit")
    parser.add_argument("--wa-homepage")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--resume-summary",
        action="store_true",
        help="Preserve rows already present in summary.json/csv while appending missing runs. Implies --skip-existing.",
    )
    parser.add_argument(
        "--refresh-existing-diagnostics",
        action="store_true",
        help="With --resume-summary/--skip-existing, refresh diagnostic-only columns from existing run artifacts without rerunning tasks.",
    )
    parser.add_argument(
        "--refresh-existing-only",
        action="store_true",
        help="Refresh and rewrite existing summary rows only. Missing task/H/K combinations are not started.",
    )
    parser.add_argument("--rerun-failure-categories", nargs="+", default=[], help="With --resume-summary, recompute existing rows whose failure_category matches.")
    parser.add_argument("--rerun-error-contains", nargs="+", default=[], help="With --resume-summary, recompute existing rows whose error text contains one of these substrings.")
    parser.add_argument(
        "--replace-requested-runs",
        action="store_true",
        help=(
            "With resume mode, remove and rerun only the requested task_id/H/K "
            "combinations from the existing summary. All other summary rows are preserved."
        ),
    )
    args = parser.parse_args()
    if args.replace_requested_runs:
        args.resume_summary = True
        args.skip_existing = True
    if args.refresh_existing_only:
        args.resume_summary = True
        args.skip_existing = True
        args.refresh_existing_diagnostics = True
    if args.resume_summary:
        args.skip_existing = True

    repo_root = args.repo_root.resolve()
    if args.sample_sites:
        tasks = sample_tasks_by_site_and_bucket(
            repo_root,
            sites=args.sample_sites,
            buckets=args.sample_buckets,
            task_types=args.sample_task_types,
            per_group=args.sample_per_group,
            seed=args.sample_seed,
            hard_only=not args.allow_non_hard_task_ids,
            single_site_only=not args.include_multisite,
            supported_sites_only=not args.include_unsupported_sites,
            exclude_task_ids=set(args.exclude_task_ids),
        )
        if args.limit is not None:
            tasks = tasks[: args.limit]
    else:
        tasks = select_tasks(
            repo_root,
            args.task_ids,
            single_site_only=not args.include_multisite,
            supported_sites_only=not args.include_unsupported_sites,
            allow_non_hard_task_ids=args.allow_non_hard_task_ids,
            limit=args.limit,
        )
    tasks = filter_tasks_by_capability(
        tasks,
        capabilities=args.capabilities,
        tiers=args.capability_tiers,
        main_analysis_only=args.main_analysis_capabilities_only,
    )
    experiment_name = args.experiment_name or f"hard-{slug(args.planner_model)}-{slug(args.executor_model)}-{args.run_mode}"
    agent_architecture = resolve_agent_architecture(args.agent_architecture, experiment_name)
    experiment_root = args.output_root.resolve() / experiment_name
    experiment_root.mkdir(parents=True, exist_ok=True)
    config = {
        "experiment_name": experiment_name,
        "task_ids": [task.task_id for task in tasks],
        "sample_sites": args.sample_sites,
        "sample_buckets": args.sample_buckets,
        "sample_task_types": args.sample_task_types,
        "sample_per_group": args.sample_per_group,
        "sample_seed": args.sample_seed,
        "exclude_task_ids": args.exclude_task_ids,
        "capabilities": args.capabilities,
        "capability_tiers": args.capability_tiers,
        "main_analysis_capabilities_only": args.main_analysis_capabilities_only,
        "hs": args.hs,
        "ks": args.ks,
        "run_mode": args.run_mode,
        "planner_mode": args.planner_mode,
        "planner_model": args.planner_model,
        "executor_model": args.executor_model,
        "agent_architecture": agent_architecture,
        **llm_backend_metadata(args.ollama_base_url),
        "max_attempts": 2 if agent_architecture == "v2_restart1" else 1,
        "llm_timeout_seconds": args.llm_timeout_seconds,
        "max_consecutive_llm_timeouts": args.max_consecutive_llm_timeouts,
        "max_steps": args.max_steps,
        "max_steps_policy": args.max_steps_policy,
        "max_steps_by_capability_tier": {
            "navigation": args.max_steps_navigation,
            "visible_retrieve": args.max_steps_retrieval,
            "structured_retrieve": args.max_steps_retrieval,
            "policy": args.max_steps_policy_task,
            "mutation": args.max_steps_mutation,
        },
        "max_planner_calls": args.max_planner_calls,
        "planner_call_margin": args.planner_call_margin,
        "single_site_only": not args.include_multisite,
        "supported_sites_only": not args.include_unsupported_sites,
        "allow_non_hard_task_ids": args.allow_non_hard_task_ids,
        "skip_official_eval": args.skip_official_eval,
        "success_policy": args.success_policy,
        "reset_site_before_run": args.reset_site_before_run,
        "reset_site_before_mutate": args.reset_site_before_mutate,
        "site_reset_timeout_seconds": args.site_reset_timeout_seconds,
        "skip_existing": args.skip_existing,
        "resume_summary": args.resume_summary,
        "refresh_existing_diagnostics": args.refresh_existing_diagnostics,
        "refresh_existing_only": args.refresh_existing_only,
        "rerun_failure_categories": args.rerun_failure_categories,
        "rerun_error_contains": args.rerun_error_contains,
        "replace_requested_runs": args.replace_requested_runs,
        "env_overrides": {
            "WA_GITLAB": args.wa_gitlab,
            "WA_GITLAB_USERNAME": args.wa_gitlab_username,
            "WA_GITLAB_PASSWORD": "***" if args.wa_gitlab_password else None,
            "WA_SHOPPING": args.wa_shopping,
            "WA_SHOPPING_ADMIN": args.wa_shopping_admin,
            "WA_REDDIT": args.wa_reddit,
            "WA_HOMEPAGE": args.wa_homepage,
        },
    }
    env_updates = {
        "WA_GITLAB": args.wa_gitlab,
        "WA_GITLAB_USERNAME": args.wa_gitlab_username,
        "WA_GITLAB_PASSWORD": args.wa_gitlab_password,
        "WA_SHOPPING": args.wa_shopping,
        "WA_SHOPPING_ADMIN": args.wa_shopping_admin,
        "WA_REDDIT": args.wa_reddit,
        "WA_HOMEPAGE": args.wa_homepage,
    }
    write_json(experiment_root / "experiment_config.json", config)
    write_experiment_tasks(experiment_root / "selected_tasks.json", tasks)
    print("Selected task ids:", " ".join(str(task.task_id) for task in tasks), flush=True)
    print(
        "Selected capabilities:",
        json.dumps(
            [
                {
                    "task_id": task.task_id,
                    "site": task.primary_site,
                    "task_type": infer_official_task_type(task.raw_task),
                    "task_capability": infer_task_capability(task.raw_task, task.primary_site),
                    "capability_tier": capability_tier(infer_task_capability(task.raw_task, task.primary_site)),
                }
                for task in tasks
            ],
            ensure_ascii=False,
        ),
        flush=True,
    )

    existing_rows = (
        load_existing_rows(
            experiment_root,
            refresh_diagnostics=args.refresh_existing_diagnostics,
            success_policy=args.success_policy,
        )
        if args.skip_existing
        else {}
    )
    rerun_failure_categories = set(args.rerun_failure_categories or [])
    rerun_error_substrings = list(args.rerun_error_contains or [])
    configs = [(h, k) for h in args.hs for k in args.ks]
    replace_requested_keys = (
        {(task.task_id, h, k) for task in tasks for h, k in configs}
        if args.replace_requested_runs
        else set()
    )
    rerun_keys = {
        key
        for key, row in existing_rows.items()
        if key in replace_requested_keys or should_rerun_existing_row(row, rerun_failure_categories, rerun_error_substrings)
    }
    if args.resume_summary and existing_rows:
        backup_existing_summary(experiment_root)
    rows: list[dict[str, Any]] = (
        [row for key, row in existing_rows.items() if key not in rerun_keys]
        if args.resume_summary
        else []
    )
    started = time.perf_counter()
    with tqdm(total=len(tasks) * len(configs), desc="hk-agent", unit="run") as bar:
        for task in tasks:
            for h, k in configs:
                run_dir = experiment_root / task.primary_site / str(task.task_id) / f"h{h}_k{k}" / str(task.task_id)
                key = (task.task_id, h, k)
                task_capability = infer_task_capability(task.raw_task, task.primary_site)
                task_tier = capability_tier(task_capability)
                step_budget = resolve_step_budget_for_task(
                    task_capability_tier=task_tier,
                    max_steps=args.max_steps,
                    max_steps_policy=args.max_steps_policy,
                    navigation_steps=args.max_steps_navigation,
                    retrieval_steps=args.max_steps_retrieval,
                    policy_steps=args.max_steps_policy_task,
                    mutation_steps=args.max_steps_mutation,
                )
                planner_call_budget = resolve_planner_call_budget(
                    args.max_planner_calls,
                    step_budget or 0,
                    h,
                    margin=args.planner_call_margin,
                )
                if args.skip_existing and key in existing_rows and key not in rerun_keys:
                    if not args.resume_summary:
                        row = dict(existing_rows[key])
                        row["status"] = "skipped_existing"
                        rows.append(row)
                    write_experiment_outputs(experiment_root, config, rows, started)
                    bar.update(1)
                    continue
                if args.skip_existing and key not in rerun_keys and (run_dir / "run_summary.json").exists():
                    try:
                        summary = read_json(run_dir / "run_summary.json")
                        apply_success_policy(summary, args.success_policy)
                        rows.append(row_from_summary(summary, run_dir, status="skipped_existing"))
                        write_experiment_outputs(experiment_root, config, rows, started)
                        bar.update(1)
                        continue
                    except Exception:
                        pass
                if args.refresh_existing_only:
                    write_experiment_outputs(experiment_root, config, rows, started)
                    bar.update(1)
                    continue
                if args.dry_run:
                    rows.append(
                        {
                            "task_id": task.task_id,
                            "intent_template_id": task.intent_template_id,
                            "revision": task.revision,
                            "gym_id": task.gym_id,
                            "site": task.primary_site,
                            "sites": ",".join(task.sites),
                            "task_type": infer_official_task_type(task.raw_task),
                            "task_capability": task_capability,
                            "capability_tier": task_tier,
                            "h": h,
                            "k": k,
                            "max_steps_policy": args.max_steps_policy,
                            "max_steps": step_budget,
                            "max_steps_disabled": step_budget is None,
                            "max_planner_calls": planner_call_budget,
                            "max_planner_calls_disabled": planner_call_budget is None,
                            "run_mode": args.run_mode,
                            "planner_model": args.planner_model,
                            "executor_model": args.executor_model,
                            "agent_architecture": agent_architecture,
                            **llm_backend_metadata(args.ollama_base_url),
                            "is_mutate_task": infer_official_task_type(task.raw_task) == "MUTATE",
                            "evaluation_success_policy": args.success_policy,
                            "evaluation_success": None,
                            "evaluation_score": None,
                            "mutation_eval_focus": (
                                "state_change_required"
                                if task_tier == "mutation"
                                else "policy_or_permission_check"
                                if infer_official_task_type(task.raw_task) == "MUTATE"
                                else "not_mutate"
                            ),
                            "mutation_tier_requires_state_change": task_tier == "mutation",
                            "site_reset_before_run": False,
                            "site_reset_site": None,
                            "site_reset_elapsed_ms": None,
                            "site_reset_returncode": None,
                            "site_reset_error": None,
                            "num_attempts": 0,
                            "max_attempts": 2 if agent_architecture == "v2_restart1" else 1,
                            "had_restart": False,
                            "restart_count": 0,
                            "attempt_output_dirs": json.dumps([], ensure_ascii=False),
                            "status": "dry_run",
                            "output_dir": str(run_dir),
                        }
                    )
                    write_experiment_outputs(experiment_root, config, rows, started)
                    bar.update(1)
                    continue
                reset_info: dict[str, Any] = {
                    "site_reset_before_run": False,
                    "site_reset_site": None,
                    "site_reset_elapsed_ms": None,
                    "site_reset_returncode": None,
                    "site_reset_error": None,
                }
                try:
                    should_reset_site = args.reset_site_before_run or (
                        args.reset_site_before_mutate and infer_official_task_type(task.raw_task) == "MUTATE"
                    )
                    if should_reset_site:
                        reset_info = reset_webarena_site_before_run(
                            repo_root=repo_root,
                            site=task.primary_site,
                            timeout_seconds=args.site_reset_timeout_seconds,
                        )
                        if reset_info.get("site_reset_returncode") not in (0, None):
                            raise RuntimeError(f"site reset failed for {task.primary_site}: {reset_info.get('site_reset_error')}")
                    summary = run_hk_task_with_optional_restart(
                        task=task,
                        repo_root=repo_root,
                        output_dir=run_dir,
                        h=h,
                        k=k,
                        run_mode=args.run_mode,
                        planner_model=args.planner_model,
                        executor_model=args.executor_model,
                        agent_architecture=agent_architecture,
                        planner_mode=args.planner_mode,
                        max_steps=step_budget or 0,
                        max_planner_calls=planner_call_budget,
                        headed=args.headed,
                        skip_official_eval=args.skip_official_eval,
                        ollama_base_url=args.ollama_base_url,
                        llm_timeout_seconds=args.llm_timeout_seconds,
                        max_consecutive_llm_timeouts=args.max_consecutive_llm_timeouts,
                        env_updates=env_updates,
                    )
                    summary["max_steps_policy"] = args.max_steps_policy
                    summary.update(reset_info)
                    apply_success_policy(summary, args.success_policy)
                    write_json(run_dir / "run_summary.json", summary)
                    rows.append(row_from_summary(summary, run_dir))
                except Exception as exc:
                    rows.append(
                        {
                            "task_id": task.task_id,
                            "intent_template_id": task.intent_template_id,
                            "revision": task.revision,
                            "gym_id": task.gym_id,
                            "site": task.primary_site,
                            "sites": ",".join(task.sites),
                            "task_type": infer_official_task_type(task.raw_task),
                            "task_capability": task_capability,
                            "capability_tier": task_tier,
                            "h": h,
                            "k": k,
                            "max_steps_policy": args.max_steps_policy,
                            "max_steps": step_budget,
                            "max_steps_disabled": step_budget is None,
                            "max_planner_calls": planner_call_budget,
                            "max_planner_calls_disabled": planner_call_budget is None,
                            "run_mode": args.run_mode,
                            "planner_model": args.planner_model,
                            "executor_model": args.executor_model,
                            "agent_architecture": agent_architecture,
                            "max_consecutive_llm_timeouts": args.max_consecutive_llm_timeouts,
                            "evaluation_success_policy": args.success_policy,
                            "evaluation_success": False,
                            "evaluation_score": 0.0,
                            "num_attempts": 0,
                            "max_attempts": 2 if agent_architecture == "v2_restart1" else 1,
                            "had_restart": False,
                            "restart_count": 0,
                            "attempt_output_dirs": json.dumps([], ensure_ascii=False),
                            **reset_info,
                            "status": "failed",
                            "output_dir": str(run_dir),
                            "error": str(exc),
                            "failure_category": "runtime_exception",
                            "near_miss_score": 0.0,
                            "failure_class": "runtime_exception",
                            "official_eval_incomplete_multi_invite_detected": False,
                            "official_eval_incomplete_multi_invite_reason": None,
                            "state_reached": False,
                            "submit_reached": False,
                            "mutation_attempted": False,
                            "loop_after_reaching_form": False,
                            "failure_notes": str(exc),
                            "diagnostic_completion": 0.0,
                        }
                    )
                    tqdm.write(f"[FAIL] task={task.task_id} h={h} k={k}: {exc}")
                write_experiment_outputs(experiment_root, config, rows, started)
                bar.update(1)

    summary = write_experiment_outputs(experiment_root, config, rows, started)
    print(f"Experiment output: {experiment_root}")
    print(f"Summary JSON: {experiment_root / 'summary.json'}")
    print(f"Summary CSV: {experiment_root / 'summary.csv'}")
    return 0 if summary["num_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
