#!/usr/bin/env python3
"""Start missing local WebArena-Verified services for the current experiment.

The script checks Docker container state and starts only services that are not
currently running. Map is intentionally excluded through the shared site
definitions because it exceeds the local storage budget.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from webarena_exp.site_definitions import SITE_INPUTS, enabled_sites, site_names
from webarena_exp.service_control import docker_available, service_start_spec, service_status
from webarena_exp.types import SiteInput


def run_command(command: list[str], cwd: Path, dry_run: bool) -> subprocess.CompletedProcess[str] | None:
    """Run a command unless dry-run mode is enabled."""

    print("$", " ".join(command))
    if dry_run:
        return None
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def select_sites(names: list[str] | None, include_wikipedia: bool) -> list[SiteInput]:
    """Select enabled sites, optionally omitting Wikipedia."""

    selected = []
    source = [SITE_INPUTS[name] for name in names] if names else enabled_sites()
    for site in source:
        if not site.enabled:
            raise ValueError(f"Site {site.name!r} is excluded: {site.exclusion_reason}")
        if site.name == "wikipedia" and not include_wikipedia:
            continue
        selected.append(site)
    return selected


def validate_site_names(names: list[str] | None) -> None:
    """Fail early for unknown site names."""

    if not names:
        return
    known = set(site_names(include_disabled=True))
    unknown = [name for name in names if name not in known]
    if unknown:
        raise ValueError(f"Unknown site(s): {', '.join(unknown)}. Known sites: {', '.join(sorted(known))}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--sites", nargs="*", help="Optional subset, e.g. --sites gitlab shopping reddit")
    parser.add_argument("--include-wikipedia", action="store_true", help="Also start Wikipedia if selected or implied")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    validate_site_names(args.sites)
    repo_root = args.repo_root.resolve()
    sites = select_sites(args.sites, include_wikipedia=args.include_wikipedia)

    docker_ok, docker_error = docker_available()
    if not docker_ok:
        print("Docker is not reachable. Start Docker Desktop first.")
        if docker_error:
            print(docker_error)
        return 1

    if not sites:
        print("No services selected. Use --include-wikipedia if only Wikipedia was omitted.")
        return 0

    failures = []
    for site in sites:
        spec = service_start_spec(repo_root, site)
        status = service_status(repo_root, site)
        if status.running:
            print(f"[OK] {site.name}: {spec.container_name} is already running ({status.docker_status})")
            continue

        print(f"[START] {site.name}: {spec.container_name} is not running ({status.docker_status})")
        proc = run_command(spec.command, spec.cwd, args.dry_run)
        if proc is None:
            continue
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr)
        if proc.returncode != 0:
            failures.append(site.name)

    if failures:
        print("Failed to start:", ", ".join(failures))
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
