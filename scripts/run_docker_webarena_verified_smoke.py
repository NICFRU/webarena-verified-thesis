#!/usr/bin/env python3
"""Run a minimal WebArena-Verified Docker smoke workflow.

This script deliberately uses the official WebArena-Verified Docker image for
benchmark-data operations. It does not start WebArena site services and it does
not run an agent.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


DEFAULT_IMAGE = "ghcr.io/servicenow/webarena-verified:latest"


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    print("\n$", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip())
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


def docker_base(image: str, project_root: Path) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{project_root}:/workspace",
        image,
    ]


def count_json_entries(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return len(value)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--subset-name", default="webarena-verified-hard")
    parser.add_argument("--task-id", default="108")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root mounted into the container as /workspace.",
    )
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    runs_dir = project_root / "runs" / "webarena_verified"
    runs_dir.mkdir(parents=True, exist_ok=True)

    config_path = project_root / "configs" / "webarena_verified_config.example.json"
    if not config_path.exists():
        raise SystemExit(f"Missing config: {config_path}")

    hard_subset = runs_dir / "webarena_verified_hard.json"
    agent_input = runs_dir / f"agent_input_task_{args.task_id}.json"
    eval_dir = runs_dir / "example_eval"

    print("WebArena-Verified Docker Smoke")
    print("=" * 72)
    print(f"Project root: {project_root}")
    print(f"Docker image: {args.image}")

    run(["docker", "run", "--rm", args.image, "--help"], project_root)
    run(["docker", "run", "--rm", args.image, "subsets-ls"], project_root)

    base = docker_base(args.image, project_root)
    run(
        base
        + [
            "subset-export",
            "--name",
            args.subset_name,
            "--output",
            "/workspace/runs/webarena_verified/webarena_verified_hard.json",
        ],
        project_root,
    )
    run(
        base
        + [
            "agent-input-get",
            "--task-ids",
            args.task_id,
            "--config",
            "/workspace/configs/webarena_verified_config.example.json",
            "--output",
            f"/workspace/runs/webarena_verified/agent_input_task_{args.task_id}.json",
        ],
        project_root,
    )
    run(
        base
        + [
            "eval-tasks",
            "--task-ids",
            args.task_id,
            "--output-dir",
            "/workspace/runs/webarena_verified/example_eval",
            "--config",
            "/workspace/configs/webarena_verified_config.example.json",
            "--dry-run",
        ],
        project_root,
    )

    print("\nOutputs")
    print("-" * 72)
    for path in [hard_subset, agent_input, eval_dir]:
        if path.exists():
            if path.is_file():
                entries = count_json_entries(path)
                suffix = f", entries={entries}" if entries is not None else ""
                print(f"OK {path.relative_to(project_root)} ({path.stat().st_size} bytes{suffix})")
            else:
                print(f"OK {path.relative_to(project_root)}/")
        else:
            print(f"fehlt {path.relative_to(project_root)}")

    print("\nEinordnung")
    print("-" * 72)
    print("Docker prueft hier Dataset, Subset-Export, Agent-Input und Eval-Dry-Run.")
    print("Fuer echte Browser-Runs brauchst du danach WebArena-Instanzen plus Agent/BrowserGym.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

