"""Local site definitions for the current experimental scope.

Map is intentionally excluded because its downloaded archives and Docker
volumes are too large for the local machine used in this thesis prototype.
"""

from __future__ import annotations

import os

from .types import Credentials, SiteInput


def env_value(name: str, default: str) -> str:
    """Return a non-empty environment override or the default value."""

    return os.environ.get(name) or default


SITE_INPUTS: dict[str, SiteInput] = {
    "shopping": SiteInput(
        name="shopping",
        env_key="__SHOPPING__",
        base_url="http://localhost:7770",
        credentials=Credentials(username="emma.lopez@gmail.com", password="Password.123"),
    ),
    "shopping_admin": SiteInput(
        name="shopping_admin",
        env_key="__SHOPPING_ADMIN__",
        base_url="http://localhost:7780/admin",
        credentials=Credentials(username="admin", password="admin1234"),
    ),
    "reddit": SiteInput(
        name="reddit",
        env_key="__REDDIT__",
        base_url="http://localhost:9999",
        credentials=Credentials(username="MarvelsGrantMan136", password="test1234"),
        task_type="RETRIEVE",
        fallback_task_types=("NAVIGATE", "RETRIEVE", "MUTATE"),
    ),
    "gitlab": SiteInput(
        name="gitlab",
        env_key="__GITLAB__",
        base_url=env_value("WA_GITLAB", "http://localhost:8012"),
        credentials=Credentials(
            username=env_value("WA_GITLAB_USERNAME", "root"),
            password=env_value("WA_GITLAB_PASSWORD", "demopass"),
        ),
    ),
    "wikipedia": SiteInput(
        name="wikipedia",
        env_key="__WIKIPEDIA__",
        base_url="http://localhost:8888",
        credentials=None,
        fallback_task_types=("NAVIGATE", "RETRIEVE", "MUTATE"),
    ),
    "map": SiteInput(
        name="map",
        env_key="__MAP__",
        base_url="http://localhost:3000",
        credentials=None,
        enabled=False,
        exclusion_reason="Excluded from the local experiment because the Map data and Docker volumes exceed the available storage budget.",
    ),
}


def enabled_sites() -> list[SiteInput]:
    """Return all sites that belong to the current local experimental scope."""

    return [site for site in SITE_INPUTS.values() if site.enabled]


def site_names(include_disabled: bool = False) -> list[str]:
    """Return known site names, optionally including excluded sites."""

    sites = SITE_INPUTS.values() if include_disabled else enabled_sites()
    return [site.name for site in sites]
