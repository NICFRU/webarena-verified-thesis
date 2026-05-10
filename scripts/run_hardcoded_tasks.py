#!/usr/bin/env python3
"""Run deterministic hardcoded smoke tasks for enabled WebArena sites.

This runner is the bridge between service probes and full agent execution. It
performs one deterministic action sequence per site, writes HAR and metadata,
and runs the official WebArena-Verified evaluator where the task is known to be
fully solved by the hardcoded sequence.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import browsergym.core  # noqa: F401 - registers browsergym/openended
import gymnasium as gym
from tqdm import tqdm

from webarena_exp.browsergym_utils import assert_site_reachable
from webarena_exp.hardcoded_tasks import HARDCODED_TASKS, hardcoded_task_names
from webarena_exp.io_utils import append_jsonl, read_json, write_json
from webarena_exp.service_control import docker_available, service_status
from webarena_exp.site_definitions import SITE_INPUTS, site_names
from webarena_exp.types import HardcodedTaskResult, HardcodedTaskSpec, SiteInput
from webarena_exp.webarena_cli import export_agent_input, run_eval, write_site_config


def select_sites(names: list[str] | None) -> list[SiteInput]:
    """Select enabled sites that have hardcoded task definitions."""

    selected_names = names or hardcoded_task_names()
    selected = []
    known = set(site_names(include_disabled=True))
    for name in selected_names:
        if name not in known:
            raise ValueError(f"Unknown site: {name}. Known sites: {', '.join(sorted(known))}")
        site = SITE_INPUTS[name]
        if not site.enabled:
            raise ValueError(f"Site {name!r} is excluded: {site.exclusion_reason}")
        if name not in HARDCODED_TASKS:
            raise ValueError(f"No hardcoded task is defined for site {name!r}")
        selected.append(site)
    return selected


def build_task_input(repo_root: Path, site: SiteInput, spec: HardcodedTaskSpec, output_dir: Path) -> dict:
    """Render official agent input when task_id exists, otherwise build a direct probe task."""

    if spec.task_id is None:
        return {
            "sites": [site.name],
            "task_id": None,
            "start_urls": [site.base_url],
            "intent": spec.intent,
            "task_type": spec.task_type,
        }

    config_path = write_site_config(repo_root, site, output_dir=output_dir / "configs")
    task_path = output_dir / site.name / f"task_{spec.task_id}.json"
    rendered = export_agent_input(repo_root, spec.task_id, config_path, task_path)
    task = rendered[0]
    task["task_type"] = spec.task_type
    return task


def target_url(start_url: str, spec: HardcodedTaskSpec) -> str | None:
    """Build an absolute target URL for the hardcoded task."""

    if spec.target_path is None:
        return None
    return urljoin(start_url.rstrip("/") + "/", spec.target_path.lstrip("/"))


def login_gitlab(page, site: SiteInput) -> bool:
    """Log into GitLab if the sign-in form is visible."""

    if site.credentials is None or page.locator("#user_login").count() == 0:
        return False
    page.locator("#user_login").fill(site.credentials.username)
    page.locator("#user_password").fill(site.credentials.password)
    page.locator("input[type='submit'], button[type='submit']").first.click(timeout=5000)
    page.wait_for_load_state("networkidle")
    return True


def login_shopping_admin(page, site: SiteInput) -> bool:
    """Log into Magento admin if the admin login form is visible."""

    if site.credentials is None:
        return False
    username = page.locator("#username")
    password = page.locator("#login")
    if username.count() == 0 or password.count() == 0:
        return False
    username.fill(site.credentials.username)
    password.fill(site.credentials.password)
    for selector in ["button.action-login", "button[type='submit']", ".actions .action-primary"]:
        locator = page.locator(selector).first
        if locator.count() > 0:
            locator.click(timeout=5000)
            page.wait_for_load_state("networkidle")
            return True
    password.press("Enter")
    page.wait_for_load_state("networkidle")
    return True


def login_if_needed(page, site: SiteInput) -> bool:
    """Dispatch site-specific login logic."""

    if site.name == "gitlab":
        return login_gitlab(page, site)
    if site.name == "shopping_admin":
        return login_shopping_admin(page, site)
    return False


def write_agent_response(output_dir: Path, spec: HardcodedTaskSpec, success: bool, error: str | None = None) -> Path:
    """Write the WebArena-Verified agent_response.json contract."""

    response = {
        "task_type": spec.task_type if spec.task_type != "SERVICE_PROBE" else "NAVIGATE",
        "status": "SUCCESS" if success else "FAILURE",
        "retrieved_data": spec.retrieved_data,
        "error_details": error,
    }
    path = output_dir / "agent_response.json"
    write_json(path, response)
    return path


def run_one_task(
    repo_root: Path,
    site: SiteInput,
    spec: HardcodedTaskSpec,
    output_root: Path,
    headed: bool,
    force_official_eval: bool,
) -> HardcodedTaskResult:
    """Execute one hardcoded task and write all artifacts."""

    task = build_task_input(repo_root, site, spec, output_root)
    raw_task_id = task.get("task_id")
    task_label = str(raw_task_id) if raw_task_id is not None else "direct"
    output_dir = output_root / site.name / task_label
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "hardcoded_trace.jsonl"
    trace_path.unlink(missing_ok=True)

    start_url = task["start_urls"][0]
    destination = target_url(start_url, spec)
    har_path = output_dir / "network.har"
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    assert_site_reachable(start_url)

    env = gym.make(
        "browsergym/openended",
        task_kwargs={"start_url": start_url, "goal": task.get("intent")},
        headless=not headed,
        wait_for_user_message=False,
        pw_context_kwargs={
            "record_har_path": str(har_path),
            "record_har_content": "embed",
        },
    )
    obs, info = env.reset()
    page = env.unwrapped.page
    append_jsonl(trace_path, {"event": "reset", "url": page.url, "observation_keys": sorted(obs.keys())})

    did_login = login_if_needed(page, site) if spec.requires_login else False
    append_jsonl(trace_path, {"event": "login", "site": site.name, "attempted": spec.requires_login, "performed": did_login, "url": page.url})

    if destination is not None:
        action = f'goto("{destination}")'
        obs, reward, terminated, truncated, info = env.step(action)
        page.wait_for_load_state("networkidle", timeout=10000)
        append_jsonl(trace_path, {"event": "navigate", "action": action, "url": page.url})

    final_url = page.url
    page_title = page.title()
    env.close()
    browser_runtime_ms = int((time.perf_counter() - started) * 1000)

    success = spec.success_url_contains in final_url if spec.success_url_contains else True
    agent_response_path = write_agent_response(output_dir, spec, success)
    eval_score = None
    eval_runtime_ms = None
    eval_result_path = output_dir / "eval_result.json"
    should_eval = (spec.run_official_eval or force_official_eval) and spec.task_id is not None
    if should_eval:
        config_path = write_site_config(repo_root, site, output_dir=output_root / "configs")
        eval_started = time.perf_counter()
        eval_proc = run_eval(repo_root, config_path, spec.task_id, output_root / site.name)
        eval_runtime_ms = int((time.perf_counter() - eval_started) * 1000)
        append_jsonl(
            trace_path,
            {
                "event": "official_eval",
                "returncode": eval_proc.returncode,
                "runtime_ms": eval_runtime_ms,
                "stdout": eval_proc.stdout,
                "stderr": eval_proc.stderr,
            },
        )
        generated_eval_path = output_root / site.name / str(spec.task_id) / "eval_result.json"
        if generated_eval_path.exists():
            eval_result = read_json(generated_eval_path)
            eval_score = eval_result.get("score")
            eval_result_path = generated_eval_path
    total_runtime_ms = int((time.perf_counter() - started) * 1000)
    finished_at = datetime.now(timezone.utc)

    result = HardcodedTaskResult(
        site=site.name,
        status="success" if success else "failed",
        task_id=raw_task_id,
        task_type=spec.task_type,
        intent=task.get("intent", spec.intent),
        start_url=start_url,
        target_url=destination,
        final_url=final_url,
        page_title=page_title,
        success=success,
        output_dir=str(output_dir),
        official_score=eval_score,
        total_runtime_ms=total_runtime_ms,
        browser_runtime_ms=browser_runtime_ms,
        official_eval_runtime_ms=eval_runtime_ms,
        total_tokens=None,
    )
    write_json(
        output_dir / "hardcoded_metadata.json",
        {
            **result.__dict__,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "runtime_ms": total_runtime_ms,
            "browser_runtime_ms": browser_runtime_ms,
            "official_eval_runtime_ms": eval_runtime_ms,
            "total_tokens": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "network_har": str(har_path),
            "agent_response": str(agent_response_path),
            "eval_result": str(eval_result_path) if eval_result_path.exists() else None,
            "trace": str(trace_path),
        },
    )
    return result


def check_services(repo_root: Path, sites: list[SiteInput], output_root: Path) -> list[str]:
    """Check Docker status before running hardcoded tasks."""

    docker_ok, docker_error = docker_available()
    if not docker_ok:
        raise RuntimeError(f"Docker is not reachable. Start Docker Desktop first. {docker_error or ''}".strip())

    missing = []
    rows = []
    print("\nService status")
    for site in sites:
        status = service_status(repo_root, site)
        marker = "OK" if status.running else "MISSING"
        print(f"- {marker}: {site.name} container={status.container_name} status={status.docker_status}")
        rows.append(status.__dict__)
        if not status.running:
            missing.append(site.name)
    write_json(output_root / "service_status.json", rows)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--output-root", type=Path, default=Path("output/hardcoded-tasks"))
    parser.add_argument("--sites", nargs="*", help="Optional subset, e.g. --sites gitlab shopping")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--ignore-service-status", action="store_true")
    parser.add_argument(
        "--official-eval-all",
        action="store_true",
        help="Run official WebArena-Verified evaluation for every hardcoded task with a real task id.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    output_root = args.output_root if args.output_root.is_absolute() else repo_root / args.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    sites = select_sites(args.sites)

    missing = check_services(repo_root, sites, output_root)
    if missing and not args.ignore_service_status:
        write_json(
            output_root / "summary.json",
            {
                "status": "blocked",
                "missing_services": missing,
                "hint": "Run python scripts/start_enabled_services.py before hardcoded tasks.",
            },
        )
        print("Hardcoded tasks skipped because services are missing:", ", ".join(missing))
        return 1

    results: list[HardcodedTaskResult] = []
    log_path = output_root / "hardcoded_log.jsonl"
    log_path.unlink(missing_ok=True)
    with tqdm(total=len(sites), desc="Hardcoded tasks", unit="site") as bar:
        for site in sites:
            spec = HARDCODED_TASKS[site.name]
            tqdm.write(f"[RUN] {site.name}: task={spec.task_id or 'direct'} type={spec.task_type}")
            try:
                result = run_one_task(repo_root, site, spec, output_root, args.headed, args.official_eval_all)
            except Exception as exc:
                result = HardcodedTaskResult(
                    site=site.name,
                    status="failed",
                    task_id=spec.task_id,
                    task_type=spec.task_type,
                    intent=spec.intent,
                    start_url=site.base_url,
                    target_url=None,
                    final_url=None,
                    page_title=None,
                    success=False,
                    output_dir=str(output_root / site.name / str(spec.task_id or "direct")),
                    error=str(exc),
                )
            append_jsonl(log_path, result)
            results.append(result)
            bar.update(1)

    summary = {
        "results": [result.__dict__ for result in results],
        "log_path": str(log_path),
        "excluded_sites": {
            name: site.exclusion_reason
            for name, site in SITE_INPUTS.items()
            if not site.enabled
        },
    }
    write_json(output_root / "summary.json", summary)

    print(f"\nSummary: {output_root / 'summary.json'}")
    for result in results:
        score = f" official_score={result.official_score}" if result.official_score is not None else ""
        runtime = f" total_runtime_ms={result.total_runtime_ms}" if result.total_runtime_ms is not None else ""
        print(f"- {result.status.upper()}: {result.site} task={result.task_id} final_url={result.final_url}{score}{runtime} error={result.error}")
    return 0 if all(result.success for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
