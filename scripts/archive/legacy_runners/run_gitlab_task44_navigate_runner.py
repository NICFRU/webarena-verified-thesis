#!/usr/bin/env python3
"""Minimal non-LLM runner for WebArena-Verified GitLab task 44.

The runner intentionally solves only the demo task "Open my todos page".
It exists to prove the artifact contract:

- agent_response.json
- network.har

Then the official WebArena-Verified evaluator can score the run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from playwright.async_api import async_playwright
from tqdm import tqdm


def load_task(tasks_file: Path, task_id: int) -> dict:
    data = json.loads(tasks_file.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array in {tasks_file}")
    for task in data:
        if task.get("task_id") == task_id:
            return task
    raise ValueError(f"Task {task_id} not found in {tasks_file}")


def write_agent_response(output_dir: Path) -> Path:
    payload = {
        "task_type": "NAVIGATE",
        "status": "SUCCESS",
        "retrieved_data": None,
        "error_details": None,
    }
    out = output_dir / "agent_response.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def todos_url(start_url: str) -> str:
    parsed = urlparse(start_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid start_url: {start_url}")
    return f"{parsed.scheme}://{parsed.netloc}/dashboard/todos"


def load_gitlab_credentials(config_path: Path) -> tuple[str, str] | None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    gitlab = config.get("environments", {}).get("__GITLAB__", {})
    credentials = gitlab.get("credentials")
    if not credentials:
        return None
    username = credentials.get("username")
    password = credentials.get("password")
    if not username or not password:
        return None
    return username, password


def assert_site_reachable(url: str, timeout_seconds: float = 5.0) -> None:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds):
            return
    except Exception as exc:
        raise RuntimeError(
            f"Could not reach {url}. Start Demo-GitLab first:\n"
            "  cd external/webarena-verified\n"
            "  uv run invoke -r examples gitlab-start"
        ) from exc


async def login_if_needed(page, credentials: tuple[str, str] | None) -> None:
    if credentials is None:
        return

    login_input = page.locator("#user_login")
    password_input = page.locator("#user_password")
    if await login_input.count() == 0 or await password_input.count() == 0:
        return

    username, password = credentials
    await login_input.fill(username)
    await password_input.fill(password)

    submit_candidates = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Sign in')",
        "button:has-text('Log in')",
    ]
    for selector in submit_candidates:
        locator = page.locator(selector).first
        if await locator.count() > 0:
            try:
                await locator.click(timeout=5000)
                break
            except Exception:
                continue
    else:
        await password_input.press("Enter")

    await page.wait_for_load_state("networkidle")


async def run_browser(
    task: dict,
    output_dir: Path,
    *,
    config: Path,
    headed: bool,
    slow_mo_ms: int,
) -> Path:
    har_path = output_dir / "network.har"
    start_url = task["start_urls"][0]
    target_url = todos_url(start_url)
    credentials = load_gitlab_credentials(config)
    assert_site_reachable(start_url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=not headed,
            slow_mo=slow_mo_ms,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        context = await browser.new_context(
            record_har_path=str(har_path),
            record_har_content="embed",
        )
        page = await context.new_page()
        await page.goto(start_url, wait_until="domcontentloaded")
        await login_if_needed(page, credentials)
        await page.goto(target_url, wait_until="networkidle")
        await context.close()
        await browser.close()

    return har_path


def run_eval(repo_root: Path, config: Path, task_id: int, output_root: Path) -> subprocess.CompletedProcess[str]:
    cmd = [
        "uv",
        "run",
        "webarena-verified",
        "eval-tasks",
        "--config",
        str(config),
        "--task-ids",
        str(task_id),
        "--output-dir",
        str(output_root),
    ]
    return subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True, check=False)


async def main_async() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--tasks-file", type=Path, default=Path("output/tasks.demo.json"))
    parser.add_argument("--task-id", type=int, default=44)
    parser.add_argument("--output-root", type=Path, default=Path("output/auto-run"))
    parser.add_argument("--config", type=Path, default=Path("examples/configs/config.demo.json"))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--slow-mo-ms", type=int, default=0)
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    tasks_file = args.tasks_file if args.tasks_file.is_absolute() else repo_root / args.tasks_file
    config = args.config if args.config.is_absolute() else repo_root / args.config
    output_root = args.output_root if args.output_root.is_absolute() else repo_root / args.output_root
    task_output_dir = output_root / str(args.task_id)
    task_output_dir.mkdir(parents=True, exist_ok=True)

    steps = [
        "load task",
        "open browser and record HAR",
        "write agent_response.json",
        "evaluate",
    ]
    if args.skip_eval:
        steps = steps[:-1]

    started = time.perf_counter()
    with tqdm(total=len(steps), desc=f"Task {args.task_id}", unit="step") as bar:
        task = load_task(tasks_file, args.task_id)
        bar.update(1)

        har_path = await run_browser(
            task,
            task_output_dir,
            config=config,
            headed=args.headed,
            slow_mo_ms=args.slow_mo_ms,
        )
        bar.update(1)

        response_path = write_agent_response(task_output_dir)
        bar.update(1)

        eval_proc: subprocess.CompletedProcess[str] | None = None
        if not args.skip_eval:
            eval_proc = run_eval(repo_root, config, args.task_id, output_root)
            bar.update(1)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    print("\nArtifacts")
    print(f"- task_output_dir: {task_output_dir}")
    print(f"- network.har: {har_path} ({har_path.stat().st_size} bytes)")
    print(f"- agent_response.json: {response_path} ({response_path.stat().st_size} bytes)")

    eval_result_path = task_output_dir / "eval_result.json"
    if eval_proc is not None:
        if eval_proc.stdout:
            print("\nEvaluation stdout")
            print(eval_proc.stdout)
        if eval_proc.stderr:
            print("\nEvaluation stderr")
            print(eval_proc.stderr, file=sys.stderr)
        if eval_proc.returncode != 0:
            return eval_proc.returncode
        if eval_result_path.exists():
            result = json.loads(eval_result_path.read_text(encoding="utf-8"))
            print("\nEvaluation result")
            print(json.dumps({k: result.get(k) for k in ["task_id", "status", "score"]}, indent=2))

    print(f"\nRuntime: {elapsed_ms} ms")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
