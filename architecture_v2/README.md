# H/k Agent Architecture v2

This variant keeps the existing H/k runner and official WebArena-Verified
evaluation interface, but changes executor prompting.

Core idea:
- Keep v1 intact for comparison.
- Use the official WebArena-Verified task contract as executor prompt basis.
- Add site-specialized executor context per platform.
- Keep official artifacts unchanged: `network.har`, `agent_response.json`,
  `eval_result.json`.

Implementation:
- Prompt composition: `scripts/hk_agent/prompt_builder.py`
- Shared executor rules: `prompts/v2/executor_base.md`
- Site executor rules: `prompts/v2/sites/*.md`
- CLI switch: `--agent-architecture v2`
- Optional guarded variant: `--agent-architecture v2_guarded`
- Optional restart variant: `--agent-architecture v2_restart1`
- Convenience behavior: experiment names containing `v2` automatically select
  architecture v2 when no explicit architecture is provided. Names containing
  `guarded` select `v2_guarded`; names containing `restart1` select
  `v2_restart1`.

Smoke command:

```bash
uv run python scripts/run_hk_agent_experiment.py \
  --experiment-name hk-agent-browsergym-example-smoke-v2 \
  --task-ids 44 157 105 27 118 \
  --allow-non-hard-task-ids \
  --hs 0 2 5 \
  --ks 0 2 5 \
  --run-mode agent \
  --planner-model gemma4:26b \
  --executor-model gemma4:e4b \
  --max-planner-calls 3 \
  --max-steps 8 \
  --llm-timeout-seconds 600
```

For explicit selection, add:

```bash
--agent-architecture v2
```

Use `v2_guarded` only for the separate engineering/ablation variant with
deterministic action guards such as common shopping product-page route priors.
The default `v2` path keeps the official prompt contract and action validation
but does not auto-solve shopping product navigation.

Use `v2_restart1` for the separate Success@2 variant. It keeps the same prompt
and executor behavior as `v2`, but after selected hard-failure categories it may
start one fresh second attempt. Restarts are only enabled when `k > 0`, because
`k=0` is the no-periodic-runtime-evaluation baseline and should not receive
recovery behavior. The aggregate row keeps attempt costs:

- `num_attempts`
- `had_restart`
- `restart_count`
- `restart_reason`
- `final_attempt_index`
- `final_success_after_restart`
- `total_steps_all_attempts`
- `total_tokens_all_attempts`
- `total_runtime_ms_all_attempts`
- `attempt_output_dirs`
