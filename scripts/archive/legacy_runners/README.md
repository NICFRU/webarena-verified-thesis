# Legacy Runners

These scripts are kept for reference because they document the incremental
setup path used before the consolidated experiment runners existed.

Current entry points:

- `scripts/run_services_probe.py`: checks all enabled local services except Map.
- `scripts/run_hk_task44_prototype.py`: runs the GitLab Task-44 H/k prototype.
- `scripts/webarena_exp/`: shared dataclasses, site inputs, CLI wrappers, and
  BrowserGym helpers.

Archived scripts should not be used as the primary experiment interface unless
an older notebook explicitly needs them for historical reproduction.
