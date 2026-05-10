"""Code-level source notes for the local experiment implementation.

The project uses the official WebArena-Verified repository for task data,
environment management, URL rendering, and final evaluation. Browser execution
is performed through BrowserGym's `browsergym/openended` environment.
"""

CODE_SOURCES = [
    {
        "name": "ServiceNow WebArena-Verified",
        "purpose": "Official benchmark CLI, task dataset, local environment management, and final evaluation.",
        "local_path": "external/webarena-verified",
        "used_by": [
            "scripts/webarena_exp/webarena_cli.py",
            "scripts/run_hk_task44_prototype.py",
            "scripts/run_services_probe.py",
        ],
    },
    {
        "name": "BrowserGym",
        "purpose": "Browser environment API used to open rendered WebArena-Verified task URLs and record HAR traces.",
        "used_by": [
            "scripts/webarena_exp/browsergym_utils.py",
            "scripts/run_hk_task44_prototype.py",
            "scripts/run_services_probe.py",
        ],
    },
    {
        "name": "Local thesis prototype code",
        "purpose": "Planner, executor, internal evaluator, controller, and H/k logging logic.",
        "used_by": [
            "scripts/run_hk_task44_prototype.py",
            "notebooks/06_hk_task44_prototype.ipynb",
        ],
    },
]
