"""Wrappers around the official WebArena-Verified CLI.

These helpers keep subprocess usage in one place. The official CLI remains the
source of task data, URL rendering, and final benchmark evaluation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .io_utils import read_json, write_json
from .types import SiteInput


def process_output(proc: subprocess.CompletedProcess[str]) -> str:
    """Return combined stdout/stderr, keeping WebArena errors visible."""

    parts = [part.strip() for part in [proc.stdout, proc.stderr] if part and part.strip()]
    return "\n".join(parts)


def site_config(site: SiteInput) -> dict:
    """Build a WebArena-Verified config for one local site."""

    entry: dict = {"urls": [site.base_url]}
    if site.credentials is not None:
        entry["credentials"] = {
            "username": site.credentials.username,
            "password": site.credentials.password,
        }
    return {"environments": {site.env_key: entry}}


def write_site_config(repo_root: Path, site: SiteInput, output_dir: Path | None = None) -> Path:
    """Write a one-site WebArena-Verified config and return its path."""

    output_dir = output_dir or repo_root / "output" / "local-configs"
    path = output_dir / f"config.{site.name}.local.json"
    write_json(path, site_config(site))
    return path


def run_webarena_cli(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run `uv run webarena-verified ...` in the official repository."""

    return subprocess.run(
        ["uv", "run", "webarena-verified", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def cli_path(repo_root: Path, path: Path) -> str:
    """Return a stable path string for a WebArena-Verified CLI argument."""

    if not path.is_absolute():
        return str(path)
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def export_candidate_tasks(
    repo_root: Path,
    site: SiteInput,
    task_type: str,
    output_path: Path,
) -> list[dict]:
    """Export candidate tasks for one site and task type."""

    proc = run_webarena_cli(
        repo_root,
        [
            "dataset-get",
            "--sites",
            site.name,
            "--task-type",
            task_type,
            "--output",
            cli_path(repo_root, output_path),
        ],
    )
    if proc.returncode != 0:
        raise RuntimeError(process_output(proc))
    return read_json(output_path)


def export_agent_input(
    repo_root: Path,
    task_id: int,
    config_path: Path,
    output_path: Path,
) -> list[dict]:
    """Render one task into concrete agent input using a local config."""

    proc = run_webarena_cli(
        repo_root,
        [
            "agent-input-get",
            "--task-ids",
            str(task_id),
            "--config",
            cli_path(repo_root, config_path),
            "--output",
            cli_path(repo_root, output_path),
        ],
    )
    if proc.returncode != 0:
        raise RuntimeError(process_output(proc))
    return read_json(output_path)


def run_eval(repo_root: Path, config: Path, task_id: int, output_root: Path) -> subprocess.CompletedProcess[str]:
    """Run the official WebArena-Verified evaluator for one task."""

    return run_webarena_cli(
        repo_root,
        [
            "eval-tasks",
            "--config",
            str(config),
            "--task-ids",
            str(task_id),
            "--output-dir",
            str(output_root),
        ],
    )
