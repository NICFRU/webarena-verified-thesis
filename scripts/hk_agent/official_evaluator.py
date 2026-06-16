"""Official WebArena-Verified evaluator wrapper for H/k runs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from webarena_exp.io_utils import read_json, write_json
from .task_loader import DEFAULT_BROWSERGYM_ENV


def build_official_config(env: dict[str, str], output_path: Path) -> Path:
    """Write a WebArena-Verified config matching the active BrowserGym URLs."""

    def url(key: str, default: str) -> str:
        return env.get(key) or os.environ.get(key) or default

    config: dict[str, Any] = {
        "environments": {
            "__SHOPPING__": {"urls": [url("WA_SHOPPING", DEFAULT_BROWSERGYM_ENV["WA_SHOPPING"])]},
            "__SHOPPING_ADMIN__": {
                "urls": [url("WA_SHOPPING_ADMIN", DEFAULT_BROWSERGYM_ENV["WA_SHOPPING_ADMIN"])],
                "use_header_login": True,
                "credentials": {
                    "username": env.get("WA_SHOPPING_ADMIN_USERNAME")
                    or DEFAULT_BROWSERGYM_ENV["WA_SHOPPING_ADMIN_USERNAME"],
                    "password": env.get("WA_SHOPPING_ADMIN_PASSWORD")
                    or DEFAULT_BROWSERGYM_ENV["WA_SHOPPING_ADMIN_PASSWORD"],
                },
            },
            "__REDDIT__": {"urls": [url("WA_REDDIT", DEFAULT_BROWSERGYM_ENV["WA_REDDIT"])]},
            "__GITLAB__": {
                "urls": [url("WA_GITLAB", DEFAULT_BROWSERGYM_ENV["WA_GITLAB"])],
                "credentials": {
                    "username": env.get("WA_GITLAB_USERNAME") or DEFAULT_BROWSERGYM_ENV["WA_GITLAB_USERNAME"],
                    "password": env.get("WA_GITLAB_PASSWORD") or DEFAULT_BROWSERGYM_ENV["WA_GITLAB_PASSWORD"],
                },
            },
            "__WIKIPEDIA__": {"urls": [url("WA_WIKIPEDIA", DEFAULT_BROWSERGYM_ENV["WA_WIKIPEDIA"])]},
            "__MAP__": {"urls": [url("WA_MAP", DEFAULT_BROWSERGYM_ENV["WA_MAP"])]},
            "__HOMEPAGE__": {"urls": [url("WA_HOMEPAGE", DEFAULT_BROWSERGYM_ENV["WA_HOMEPAGE"])]},
        }
    }
    write_json(output_path, config)
    return output_path


def run_official_eval(
    *,
    repo_root: Path,
    config_path: Path,
    task_id: int,
    output_root: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run WebArena-Verified `eval-tasks` for one task."""

    eval_env = os.environ.copy()
    if env:
        eval_env.update(env)
    warning_filter = r"ignore:PEP 484 type hint typing\.Mapping.*deprecated by PEP 585:Warning:beartype\..*"
    existing_filters = eval_env.get("PYTHONWARNINGS")
    eval_env["PYTHONWARNINGS"] = f"{existing_filters},{warning_filter}" if existing_filters else warning_filter
    return subprocess.run(
        [
            "uv",
            "run",
            "webarena-verified",
            "eval-tasks",
            "--config",
            str(config_path),
            "--task-ids",
            str(task_id),
            "--output-dir",
            str(output_root),
        ],
        cwd=repo_root,
        env=eval_env,
        text=True,
        capture_output=True,
        check=False,
    )


def read_official_result(task_output_dir: Path) -> tuple[float | None, bool | None, str | None]:
    """Read score, success and status from an official eval result if present."""

    result_path = task_output_dir / "eval_result.json"
    if not result_path.exists():
        return None, None, None
    result = read_json(result_path)
    score = result.get("score")
    status = str(result.get("status")) if result.get("status") is not None else None
    return score, score == 1.0 if score is not None else None, status
