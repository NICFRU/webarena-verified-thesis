uv run python scripts/run_hk_agent_experiment.py
  --experiment-name hk-agent-browsergym-example-smoke-v2
  --task-ids 44 157 105 27 118
  --allow-non-hard-task-ids
  --hs 0 2 5
  --ks 0 2 5
  --run-mode agent
  --planner-model gemma4:26b
  --executor-model gemma4:e4b
  --max-planner-calls 3
  --max-steps 8
  --llm-timeout-seconds 600

uv run python scripts/run_hk_agent_experiment.py --experiment-name hk-agent-browsergym-random-gemma4-smoke --task-ids 522 800 444 407 644 28 387 795 507 505 15 108 --hs 0 2 5 --ks 0 2 5 --run-mode agent --planner-model gemma4:26b --executor-model gemma4:e4b --max-planner-calls 3 --max-steps 8 --llm-timeout-seconds 600
