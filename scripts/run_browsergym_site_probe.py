#!/usr/bin/env python3
"""Probe a WebArena-Verified site with BrowserGym without claiming task success.

This script is for the step after the GitLab task-44 success path. It opens a
real WebArena-Verified site through BrowserGym, records a HAR, and writes probe
metadata. It intentionally does not write agent_response.json or evaluate the
task, because loading a page is not the same as solving the benchmark task.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

import browsergym.core  # noqa: F401 - registers browsergym/openended
import gymnasium as gym
from tqdm import tqdm


def load_task(tasks_file: Path, task_id: int | None) -> dict:
    data = json.loads(tasks_file.read_text(encoding="utf-8"))
    if not data:
        raise ValueError(f"No tasks in {tasks_file}")
    if task_id is None:
        return data[0]
    for task in data:
        if task.get("task_id") == task_id:
            return task
    raise ValueError(f"Task {task_id} not found in {tasks_file}")


def assert_site_reachable(url: str, timeout_seconds: float = 5.0) -> None:
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout_seconds):
            return
    except Exception as exc:
        raise RuntimeError(f"Could not reach {url}. Start the matching WebArena environment first.") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks-file", type=Path, required=True)
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--output-root", type=Path, default=Path("runs/site-probe"))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    task = load_task(args.tasks_file, args.task_id)
    task_id = task["task_id"]
    site = "-".join(task.get("sites", ["unknown"]))
    start_url = task["start_urls"][0]
    output_dir = args.output_root / site / str(task_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    har_path = output_dir / "network.har"
    metadata_path = output_dir / "probe_metadata.json"

    started = time.perf_counter()
    with tqdm(total=4, desc=f"Probe task {task_id}", unit="step") as bar:
        assert_site_reachable(start_url)
        bar.update(1)

        env = gym.make(
            "browsergym/openended",
            task_kwargs={"start_url": start_url, "goal": task.get("intent")},
            headless=not args.headed,
            wait_for_user_message=False,
            pw_context_kwargs={
                "record_har_path": str(har_path),
                "record_har_content": "embed",
            },
        )
        obs, info = env.reset()
        bar.update(1)

        page = env.unwrapped.page
        page.wait_for_load_state("networkidle", timeout=10000)
        current_url = page.url
        title = page.title()
        env.close()
        bar.update(1)

        metadata = {
            "task_id": task_id,
            "sites": task.get("sites"),
            "intent": task.get("intent"),
            "start_url": start_url,
            "current_url_after_reset": current_url,
            "page_title_after_reset": title,
            "observation_keys": sorted(obs.keys()),
            "runtime_ms": int((time.perf_counter() - started) * 1000),
            "har_path": str(har_path),
            "note": "Probe only. This does not solve or evaluate the benchmark task.",
        }
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        bar.update(1)

    print("\nProbe artifacts")
    print(f"- metadata: {metadata_path}")
    print(f"- network.har: {har_path} ({har_path.stat().st_size} bytes)")
    print("\nCurrent URL:", current_url)
    print("Page title:", title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

