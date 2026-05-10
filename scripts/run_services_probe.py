#!/usr/bin/env python3
"""Probe all enabled local WebArena-Verified services except Map.

The script generates one local config per enabled site, exports a candidate
task, opens it through BrowserGym, and writes a compact summary. It does not
claim benchmark success; it only checks whether the local service, URL
rendering, BrowserGym reset, HAR recording, and output structure work.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from tqdm import tqdm

from webarena_exp.browsergym_utils import open_task_with_browsergym
from webarena_exp.io_utils import append_jsonl, write_json
from webarena_exp.service_control import docker_available, service_status
from webarena_exp.site_definitions import SITE_INPUTS, enabled_sites, site_names
from webarena_exp.types import SiteInput, SiteProbeResult
from webarena_exp.webarena_cli import export_agent_input, export_candidate_tasks, write_site_config


def select_sites(names: list[str] | None) -> list[SiteInput]:
    """Select enabled sites by name, rejecting disabled or unknown sites."""

    if not names:
        return enabled_sites()

    selected = []
    for name in names:
        if name not in SITE_INPUTS:
            raise ValueError(f"Unknown site: {name}. Known sites: {', '.join(site_names(include_disabled=True))}")
        site = SITE_INPUTS[name]
        if not site.enabled:
            raise ValueError(f"Site {name!r} is excluded: {site.exclusion_reason}")
        selected.append(site)
    return selected


def first_candidate_task(repo_root: Path, site: SiteInput, output_root: Path, log_path: Path) -> tuple[dict | None, str | None]:
    """Return the first candidate task and the task type that produced it."""

    task_types = (site.task_type, *site.fallback_task_types)
    seen = set()
    for task_type in task_types:
        if task_type in seen:
            continue
        seen.add(task_type)
        candidates_path = output_root / "candidate-tasks" / f"{site.name}_{task_type.lower()}_tasks.json"
        try:
            candidates = export_candidate_tasks(repo_root, site, task_type, candidates_path)
        except Exception as exc:
            append_jsonl(
                log_path,
                {
                    "event": "candidate_task_export_failed",
                    "site": site.name,
                    "task_type": task_type,
                    "error": str(exc),
                },
            )
            continue
        if candidates:
            return candidates[0], task_type
    return None, None


def probe_site(repo_root: Path, site: SiteInput, output_root: Path, headed: bool, log_path: Path) -> SiteProbeResult:
    """Generate one rendered task input and open it with BrowserGym."""

    site_output = output_root / site.name
    append_jsonl(log_path, {"event": "site_probe_started", "site": site.name, "task_type": site.task_type})
    config_path = write_site_config(repo_root, site, output_dir=output_root / "configs")
    append_jsonl(log_path, {"event": "site_config_written", "site": site.name, "config_path": str(config_path)})
    candidate, selected_task_type = first_candidate_task(repo_root, site, output_root, log_path)
    if candidate is None:
        direct_task = {
            "sites": [site.name],
            "task_id": None,
            "start_urls": [site.base_url],
            "intent": f"Open the local {site.name} service start page.",
            "task_type": "SERVICE_PROBE",
        }
        tqdm.write(f"[DIRECT] {site.name}: no matching benchmark task found; opening {site.base_url}")
        append_jsonl(
            log_path,
            {
                "event": "direct_service_probe_selected",
                "site": site.name,
                "start_url": site.base_url,
                "reason": "No matching benchmark task found through dataset-get",
            },
        )
        result = open_task_with_browsergym(direct_task, site_output / "direct", headed=headed)
        append_jsonl(log_path, {"event": "site_probe_finished", **result.__dict__})
        return result

    task_id = int(candidate["task_id"])
    task_type = selected_task_type or site.task_type
    tqdm.write(f"[TASK] {site.name}: task_id={task_id} type={task_type} intent={candidate.get('intent')}")
    append_jsonl(
        log_path,
        {
            "event": "candidate_task_selected",
            "site": site.name,
            "task_id": task_id,
            "task_type": task_type,
            "intent": candidate.get("intent"),
        },
    )
    task_path = site_output / f"task_{task_id}.json"
    rendered_tasks = export_agent_input(repo_root, task_id, config_path, task_path)
    rendered_task = rendered_tasks[0]
    tqdm.write(f"[OPEN] {site.name}: start_url={rendered_task['start_urls'][0]}")
    append_jsonl(
        log_path,
        {
            "event": "agent_input_rendered",
            "site": site.name,
            "task_id": task_id,
            "task_path": str(task_path),
            "start_urls": rendered_task.get("start_urls"),
        },
    )
    result = open_task_with_browsergym(rendered_task, site_output / str(task_id), headed=headed)
    if result.task_type is None:
        result = replace(result, task_type=task_type)
    append_jsonl(log_path, {"event": "site_probe_finished", **result.__dict__})
    return result


def check_services(repo_root: Path, sites: list[SiteInput], output_root: Path) -> list[str]:
    """Print and persist Docker service status before BrowserGym probing."""

    status_rows = []
    missing = []
    docker_ok, docker_error = docker_available()
    if not docker_ok:
        raise RuntimeError(f"Docker is not reachable. Start Docker Desktop first. {docker_error or ''}".strip())

    print("\nService status")
    for site in sites:
        status = service_status(repo_root, site)
        marker = "OK" if status.running else "MISSING"
        print(f"- {marker}: {site.name} container={status.container_name} status={status.docker_status}")
        if not status.running:
            print(f"  start with: {' '.join(status.start_command)}")
            missing.append(site.name)
        status_rows.append(status.__dict__)

    write_json(output_root / "service_status.json", status_rows)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--output-root", type=Path, default=Path("output/service-probe"))
    parser.add_argument("--sites", nargs="*", help="Optional subset, e.g. --sites shopping reddit")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--ignore-service-status", action="store_true", help="Try probes even if Docker status says a service is not running")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    output_root = args.output_root if args.output_root.is_absolute() else repo_root / args.output_root
    sites = select_sites(args.sites)
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / "probe_log.jsonl"
    log_path.unlink(missing_ok=True)

    missing_services = check_services(repo_root, sites, output_root)
    if missing_services and not args.ignore_service_status:
        summary = {
            "status": "blocked",
            "reason": "services_not_running",
            "missing_services": missing_services,
            "included_sites": [site.name for site in sites],
            "hint": "Run python scripts/start_enabled_services.py before probing.",
        }
        write_json(output_root / "summary.json", summary)
        print("\nProbe skipped because services are missing:", ", ".join(missing_services))
        print("Start them with:")
        print("python scripts/start_enabled_services.py --sites", " ".join(missing_services))
        return 1

    results: list[SiteProbeResult] = []
    with tqdm(total=len(sites), desc="Service probes", unit="site") as bar:
        for site in sites:
            try:
                result = probe_site(repo_root, site, output_root, args.headed, log_path)
            except Exception as exc:
                result = SiteProbeResult(
                    site=site.name,
                    status="failed",
                    task_id=None,
                    start_url=site.base_url,
                    final_url=None,
                    page_title=None,
                    output_dir=str(output_root / site.name),
                    error=str(exc),
                )
                append_jsonl(log_path, {"event": "site_probe_failed", **result.__dict__})
            results.append(result)
            bar.update(1)

    summary = {
        "included_sites": [site.name for site in sites],
        "excluded_sites": {
            name: site.exclusion_reason
            for name, site in SITE_INPUTS.items()
            if not site.enabled
        },
        "results": [result.__dict__ for result in results],
        "log_path": str(log_path),
    }
    summary_path = output_root / "summary.json"
    write_json(summary_path, summary)

    print(f"\nSummary: {summary_path}")
    for result in results:
        marker = "OK" if result.status == "success" else result.status.upper()
        print(f"- {marker}: {result.site} task={result.task_id} final_url={result.final_url} error={result.error}")
    return 0 if all(result.status in {"success", "skipped"} for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
