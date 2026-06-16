"""Task loading and BrowserGym ID helpers for WebArena-Verified Hard."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hk_agent.capabilities import capability_tier, infer_official_task_type, infer_task_capability, is_main_analysis_capability
from webarena_exp.io_utils import read_json, write_json


HARD_SUBSET_NAME = "webarena-verified-hard"
SUPPORTED_SINGLE_SITES = {"gitlab", "shopping", "shopping_admin", "reddit"}
DEFAULT_BROWSERGYM_ENV = {
    "WA_GITLAB": "http://localhost:8023",
    "WA_GITLAB_USERNAME": "byteblaze",
    "WA_GITLAB_PASSWORD": "hello1234",
    "WA_SHOPPING": "http://localhost:7770",
    "WA_SHOPPING_ADMIN": "http://localhost:7780/admin",
    "WA_SHOPPING_ADMIN_USERNAME": "admin",
    "WA_SHOPPING_ADMIN_PASSWORD": "admin1234",
    "WA_REDDIT": "http://localhost:9999",
    "WA_WIKIPEDIA": "http://localhost:8888",
    "WA_MAP": "todo",
    "WA_HOMEPAGE": "http://localhost:4399",
}
HIDDEN_AGENT_KEYS = {
    "eval",
    "reference_answer",
    "reference_url",
    "gold",
    "oracle",
    "expected",
}


@dataclass(frozen=True)
class HkTask:
    """One WebArena-Verified task with its BrowserGym registration id."""

    task_id: int
    intent_template_id: int
    revision: int
    sites: tuple[str, ...]
    intent: str
    gym_id: str
    raw_task: dict[str, Any]

    @property
    def is_single_site(self) -> bool:
        return len(self.sites) == 1

    @property
    def primary_site(self) -> str:
        return self.sites[0] if self.sites else "unknown"


def dataset_path(repo_root: Path) -> Path:
    """Return the official WebArena-Verified dataset path."""

    return repo_root / "assets" / "dataset" / "webarena-verified.json"


def hard_subset_path(repo_root: Path) -> Path:
    """Return the local hard-subset metadata path."""

    return repo_root / "assets" / "dataset" / "subsets" / f"{HARD_SUBSET_NAME}.json"


def load_dataset(repo_root: Path) -> dict[int, dict[str, Any]]:
    """Load all WebArena-Verified tasks keyed by task id."""

    return {int(task["task_id"]): task for task in read_json(dataset_path(repo_root))}


def load_hard_subset_ids(repo_root: Path) -> list[int]:
    """Load the 258 WebArena-Verified Hard task ids."""

    data = read_json(hard_subset_path(repo_root))
    if isinstance(data, dict) and "task_ids" in data:
        return [int(task_id) for task_id in data["task_ids"]]
    if isinstance(data, list):
        return [int(task["task_id"]) for task in data]
    raise ValueError(f"Unsupported hard subset shape: {hard_subset_path(repo_root)}")


def build_gym_id(task: dict[str, Any]) -> str:
    """Build the BrowserGym WebArena-Verified task id."""

    return "browsergym/webarena_verified.{intent_template_id}.{task_id}.{revision}".format(
        intent_template_id=int(task["intent_template_id"]),
        task_id=int(task["task_id"]),
        revision=int(task["revision"]),
    )


def intent_bucket(intent: str) -> str:
    """Return a coarse task-length bucket for experiment stratification."""

    length = len(intent)
    if length < 60:
        return "short"
    if length < 140:
        return "medium"
    return "long"


def to_hk_task(task: dict[str, Any]) -> HkTask:
    """Convert a raw dataset row into an HkTask."""

    return HkTask(
        task_id=int(task["task_id"]),
        intent_template_id=int(task["intent_template_id"]),
        revision=int(task["revision"]),
        sites=tuple(str(site) for site in task.get("sites", [])),
        intent=str(task.get("intent", "")),
        gym_id=build_gym_id(task),
        raw_task=task,
    )


def sample_tasks_by_site_and_bucket(
    repo_root: Path,
    *,
    sites: list[str] | None = None,
    buckets: list[str] | None = None,
    task_types: list[str] | None = None,
    per_group: int = 1,
    seed: int | None = None,
    hard_only: bool = True,
    single_site_only: bool = True,
    supported_sites_only: bool = True,
    exclude_task_ids: set[int] | None = None,
) -> list[HkTask]:
    """Sample tasks stratified by site, length bucket, and optionally task type."""

    sites = sites or sorted(SUPPORTED_SINGLE_SITES)
    buckets = buckets or ["short", "medium", "long"]
    task_types = [task_type.upper() for task_type in task_types] if task_types else None
    exclude_task_ids = exclude_task_ids or set()
    dataset = load_dataset(repo_root)
    hard_ids = set(load_hard_subset_ids(repo_root))
    rng = random.Random(seed)
    candidates = [to_hk_task(task) for task in dataset.values()]
    if hard_only:
        candidates = [task for task in candidates if task.task_id in hard_ids]
    if single_site_only:
        candidates = [task for task in candidates if task.is_single_site]
    if supported_sites_only:
        candidates = [task for task in candidates if task.primary_site in SUPPORTED_SINGLE_SITES]
    candidates = [task for task in candidates if task.task_id not in exclude_task_ids]

    selected: list[HkTask] = []
    selected_ids: set[int] = set()
    for site in sites:
        for bucket in buckets:
            group = [
                task
                for task in candidates
                if task.primary_site == site
                and intent_bucket(task.intent) == bucket
                and (task_types is None or infer_official_task_type(task.raw_task) in task_types)
            ]
            rng.shuffle(group)
            for task in group:
                if task.task_id in selected_ids:
                    continue
                selected.append(task)
                selected_ids.add(task.task_id)
                if sum(1 for selected_task in selected if selected_task.primary_site == site and intent_bucket(selected_task.intent) == bucket) >= per_group:
                    break
    return selected


def filter_tasks_by_capability(
    tasks: list[HkTask],
    *,
    capabilities: list[str] | None = None,
    tiers: list[str] | None = None,
    main_analysis_only: bool = False,
) -> list[HkTask]:
    """Filter tasks by inferred capability/tier without using hidden eval answers."""

    capability_set = {value.lower() for value in capabilities or []}
    tier_set = {value.lower() for value in tiers or []}
    filtered: list[HkTask] = []
    for task in tasks:
        capability = infer_task_capability(task.raw_task, task.primary_site)
        tier = capability_tier(capability)
        if capability_set and capability.lower() not in capability_set:
            continue
        if tier_set and tier.lower() not in tier_set:
            continue
        if main_analysis_only and not is_main_analysis_capability(capability):
            continue
        filtered.append(task)
    return filtered


def load_hard_tasks(repo_root: Path) -> list[HkTask]:
    """Load all hard-subset tasks in dataset order."""

    dataset = load_dataset(repo_root)
    hard_ids = set(load_hard_subset_ids(repo_root))
    tasks = [to_hk_task(task) for task_id, task in dataset.items() if task_id in hard_ids]
    if len(tasks) != 258:
        raise ValueError(f"Expected 258 hard-subset tasks, found {len(tasks)}")
    return tasks


def select_tasks(
    repo_root: Path,
    task_ids: list[int] | None,
    single_site_only: bool = True,
    supported_sites_only: bool = True,
    allow_non_hard_task_ids: bool = False,
    limit: int | None = None,
) -> list[HkTask]:
    """Select hard-subset tasks for an experiment."""

    dataset = load_dataset(repo_root)
    tasks = load_hard_tasks(repo_root)
    hard_ids = {task.task_id for task in tasks}
    if task_ids:
        missing = [task_id for task_id in task_ids if task_id not in hard_ids and not allow_non_hard_task_ids]
        if missing:
            raise ValueError(f"Task ids are not in WebArena-Verified Hard: {missing}")
        by_id = {task.task_id: task for task in tasks}
        tasks = [
            by_id[task_id] if task_id in by_id else to_hk_task(dataset[task_id])
            for task_id in task_ids
        ]
    if single_site_only:
        # Only keep tasks that involve exactly one site, since multi-site tasks are more complex and less common.
        tasks = [task for task in tasks if task.is_single_site]
    if supported_sites_only:
        # Only keep tasks whose primary site is in the supported set, since some sites are more difficult to work with and less relevant for our experiments.
        tasks = [task for task in tasks if task.primary_site in SUPPORTED_SINGLE_SITES]
    if limit is not None:
        # Only keep the first n tasks, which is useful for quick iteration during development. 
        tasks = tasks[:limit]
    return tasks


def sanitize_task_for_agent(task: dict[str, Any], run_mode: str) -> dict[str, Any]:
    """Return task context for planner/executor according to the run mode."""

    if run_mode == "oracle_debug":
        return task
    # For the planner and executor, we remove the hidden keys that contain oracle information about the task, since they would make the task trivial and unrealistic. The agent should only see the intent, sites, and any other non-hidden metadata.
    sanitized = {key: value for key, value in task.items() if key not in HIDDEN_AGENT_KEYS}
    return sanitized


def ensure_browsergym_env(env_updates: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment with the WA_* variables BrowserGym requires."""

    env = os.environ.copy()
    if env_updates:
        env.update({key: value for key, value in env_updates.items() if value is not None})
    # Set defaults for WA_* variables if not already set. This allows running the agent without manually setting these variables, while still allowing overrides through env_updates or existing environment variables.
    defaults = DEFAULT_BROWSERGYM_ENV
    for key, value in defaults.items():
        env.setdefault(key, value)
        os.environ.setdefault(key, value)
    for key, value in env.items():
        if key.startswith("WA_"):
            os.environ[key] = value
    return env


def write_experiment_tasks(path: Path, tasks: list[HkTask]) -> None:
    """Write selected task metadata for reproducibility."""

    write_json(
        path,
        [
            {
                "task_id": task.task_id,
                "intent_template_id": task.intent_template_id,
                "revision": task.revision,
                "sites": list(task.sites),
                "intent": task.intent,
                "task_type": infer_official_task_type(task.raw_task),
                "task_capability": infer_task_capability(task.raw_task, task.primary_site),
                "capability_tier": capability_tier(infer_task_capability(task.raw_task, task.primary_site)),
                "gym_id": task.gym_id,
            }
            for task in tasks
        ],
    )
