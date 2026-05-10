"""Hardcoded smoke tasks for each enabled local WebArena-Verified service.

These tasks are intentionally deterministic. They are not meant to replace a
real agent; they provide stable per-site execution examples while the planner,
evaluator, controller, and logging layers are still being built.
"""

from __future__ import annotations

from .types import HardcodedTaskSpec


HARDCODED_TASKS: dict[str, HardcodedTaskSpec] = {
    "gitlab": HardcodedTaskSpec(
        site="gitlab",
        task_id=44,
        task_type="NAVIGATE",
        intent="Open my todos page",
        target_path="/dashboard/todos",
        success_url_contains="/dashboard/todos",
        requires_login=True,
        run_official_eval=True,
    ),
    "shopping": HardcodedTaskSpec(
        site="shopping",
        task_id=118,
        task_type="NAVIGATE",
        intent="Open a shopping product page that matches the bruxism-related task.",
        target_path="/dentemp-ora-guard-custom-fit-dental-guard-bruxism-night-guard-for-teeth-grinding-two-pack-mouth-guard-for-clenching-teeth-at-night-mouth-guard-for-sleeping-relieve-soreness-in-jaw-muscles.html",
        success_url_contains="bruxism-night-guard",
        requires_login=False,
        run_official_eval=True,
    ),
    "shopping_admin": HardcodedTaskSpec(
        site="shopping_admin",
        task_id=157,
        task_type="NAVIGATE",
        intent="Open the shopping admin customer overview.",
        target_path="/customer/index/",
        success_url_contains="/admin/customer/index",
        requires_login=True,
        run_official_eval=True,
    ),
    "reddit": HardcodedTaskSpec(
        site="reddit",
        task_id=27,
        task_type="RETRIEVE",
        intent="Open the Reddit clone for the personal-finance retrieval task.",
        target_path="/",
        success_url_contains="localhost:9999",
        requires_login=False,
        run_official_eval=True,
        retrieved_data=[
            {
                "username": "Hammer94",
                "post_title": "56 year old mom has no retirement. Where do I even start on her behalf?",
                "count": 0,
            }
        ],
    ),
    "wikipedia": HardcodedTaskSpec(
        site="wikipedia",
        task_id=None,
        task_type="SERVICE_PROBE",
        intent="Open the local Wikipedia landing page.",
        target_path=None,
        success_url_contains="/wikipedia_en_all_maxi_2022-05/",
        requires_login=False,
        run_official_eval=False,
    ),
}


def hardcoded_task_names() -> list[str]:
    """Return site names with hardcoded task definitions."""

    return list(HARDCODED_TASKS)
