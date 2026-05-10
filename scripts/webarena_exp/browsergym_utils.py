"""BrowserGym helpers shared by local probe and prototype runners."""

from __future__ import annotations

import time
from pathlib import Path
from urllib.request import Request, urlopen

import browsergym.core  # noqa: F401 - registers browsergym/openended
import gymnasium as gym

from .io_utils import write_json
from .types import SiteProbeResult


def assert_site_reachable(url: str, timeout_seconds: float = 5.0) -> None:
    """Raise a clear error if a local benchmark URL is not reachable."""

    try:
        with urlopen(Request(url, method="GET"), timeout=timeout_seconds):
            return
    except Exception as exc:
        raise RuntimeError(f"Could not reach {url}. Start the matching local WebArena environment first.") from exc


def open_task_with_browsergym(task: dict, output_dir: Path, headed: bool = False) -> SiteProbeResult:
    """Open one rendered task in BrowserGym and write HAR plus metadata."""

    raw_task_id = task.get("task_id")
    task_id = int(raw_task_id) if raw_task_id is not None else None
    site = "-".join(task.get("sites", ["unknown"]))
    start_url = task["start_urls"][0]
    output_dir.mkdir(parents=True, exist_ok=True)
    har_path = output_dir / "network.har"
    metadata_path = output_dir / "probe_metadata.json"

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
    page.wait_for_load_state("networkidle", timeout=10000)
    result = SiteProbeResult(
        site=site,
        status="success",
        task_id=task_id,
        start_url=start_url,
        final_url=page.url,
        page_title=page.title(),
        output_dir=str(output_dir),
        task_intent=task.get("intent"),
        task_type=task.get("task_type"),
    )
    env.close()

    write_json(
        metadata_path,
        {
            **result.__dict__,
            "intent": task.get("intent"),
            "observation_keys": sorted(obs.keys()),
            "runtime_ms": int((time.perf_counter() - started) * 1000),
            "har_path": str(har_path),
            "note": "Probe only. This does not solve or evaluate the benchmark task.",
        },
    )
    return result
