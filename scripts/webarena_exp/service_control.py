"""Docker service inspection helpers for local WebArena-Verified services."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .types import SiteInput


@dataclass(frozen=True)
class ServiceStartSpec:
    """Docker container and start command for one local service."""

    site: str
    container_name: str
    command: list[str]
    cwd: Path


@dataclass(frozen=True)
class ServiceStatus:
    """Current Docker status for one local service."""

    site: str
    container_name: str
    running: bool
    docker_status: str | None
    start_command: list[str]


def docker_available() -> tuple[bool, str | None]:
    """Return whether Docker is reachable and an optional error message."""

    proc = subprocess.run(["docker", "info"], text=True, capture_output=True, check=False)
    if proc.returncode == 0:
        return True, None
    return False, (proc.stderr or proc.stdout).strip()


def service_start_spec(repo_root: Path, site: SiteInput) -> ServiceStartSpec:
    """Build the service-specific start command."""

    if site.name == "gitlab":
        return ServiceStartSpec(
            site=site.name,
            container_name="wa-demo-gitlab",
            command=["uv", "run", "invoke", "-r", "examples", "gitlab-start"],
            cwd=repo_root,
        )

    command = ["uv", "run", "webarena-verified", "env", "start", "--site", site.name]
    if site.name == "wikipedia":
        data_dir = repo_root / "data" / "wikipedia"
        command.extend(["--data-dir", str(data_dir)])

    return ServiceStartSpec(
        site=site.name,
        container_name=f"webarena_verified_{site.name}",
        command=command,
        cwd=repo_root,
    )


def inspect_container(container_name: str) -> tuple[bool, str | None]:
    """Inspect one Docker container and return running flag plus status text."""

    proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}|{{.State.Status}}", container_name],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return False, "not_found"
    running, status = proc.stdout.strip().split("|", 1)
    return running.lower() == "true", status


def service_status(repo_root: Path, site: SiteInput) -> ServiceStatus:
    """Return Docker status and start command for one site."""

    spec = service_start_spec(repo_root, site)
    running, docker_status = inspect_container(spec.container_name)
    return ServiceStatus(
        site=site.name,
        container_name=spec.container_name,
        running=running,
        docker_status=docker_status,
        start_command=spec.command,
    )

