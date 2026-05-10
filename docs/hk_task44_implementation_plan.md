# H/k Task-44 Implementation Plan

This plan consolidates the current thesis baseline from:

- `prompts/zwischenspeicher.md`
- `docs/aufbau_planner.md`
- the local architecture diagram shared in the IDE context
- current scripts under `scripts/webarena_exp/`

The existing Markdown files remain the source material. This document is only a
clean implementation plan for the minimal Task-44 prototype.

## Scope

Implement only the interfaces needed for the GitLab Task-44 H/k prototype:

1. Planner
2. Executor
3. Runtime Evaluator
4. Rule-based Controller
5. Logging / Trace Storage

Do not implement a full autonomous web agent yet. WebArena-Verified remains the
official final evaluator through `eval-tasks`.

## External References Used As Inspiration

| Repository / doc | Relevant files or concepts | Architecture idea | Prompt idea | Direct reuse? | Influences | Notes for chapter 5 |
| --- | --- | --- | --- | --- | --- | --- |
| WebArena | `agent`, `browser_env`, `evaluation_harness`, prompt dictionaries | Gym-like browser interaction and prompt-based agents | Prompt dictionaries with instruction, examples, template, metadata | No | Executor, prompts | Use as original benchmark background and action/observation framing |
| WebArena-Verified | dataset, `agent-input-get`, `eval-tasks`, network trace evaluators | Deterministic final scoring from `agent_response.json` and `network.har` | Do not use LLM-as-final-judge | No | Evaluator boundary, logging | Own Evaluator is runtime-only; official score remains external |
| AgentLab / BrowserGym | `AgentArgs`, experiments, result loading | Scalable experiment runner and result inspection | Agent components should be swappable | No | Runner, logging, later integration | Current prototype should keep contracts compatible with later AgentLab wrapping |
| Local diagram | Planner, Executor, Evaluator, Controller, Logging layer | Orchestrated modular runtime | JSON contracts between modules | Yes, as design | All modules | Use to explain module separation and H/k interventions |

## Minimal Interfaces

### Planner

- Input: rendered WebArena task, site name, `H`, optional target hints.
- Output: `Plan` with ordered `Subgoal` objects.
- Current implementation: Ollama planner mode. Static fallback is intentionally
  not part of the active prototype.

### Executor

- Input: active `Subgoal`, BrowserGym env/page, credentials.
- Output: `ExecutorStep`.
- Current implementation: deterministic GitLab Task-44 executor.

### Runtime Evaluator

- Input: page state, active subgoal, previous URLs, step index.
- Output: `EvaluatorSignal`.
- Current implementation: heuristic Task-44 evaluator.

### Controller

- Input: `EvaluatorSignal`, step-budget flag.
- Output: `ControllerDecision`.
- Current implementation: rule-based mapping to `continue`, `local_replan`,
  `global_replan`, or `abort`; only `continue`, `local_replan`, and `abort`
  are active in Task 44.

### Logging

- Output files:
  - `plan.json`
  - `step_trace.jsonl`
  - `evaluator_signals.jsonl`
  - `controller_decisions.jsonl`
  - `run_trace.json`
  - `run_summary.json`
  - WebArena-compatible `agent_response.json`
  - WebArena-compatible `network.har`
  - WebArena-produced `eval_result.json`

## Next Implementation Steps

1. Run Task 44 with the Ollama planner and the semantic scripted executor.
2. Run `H` and `k` variants against the same task.
3. Replanning calls with current observation, previous plan, evaluator feedback,
   and controller decision are now part of the Task-44 prototype loop.
4. Add a notebook view for `run_trace.json`, evaluator signals, and controller
   decisions.
5. Only after this, add an LLM executor or broader task set.

## Current Sweep Command

```bash
uv run python scripts/run_hk_sweep.py --task-id 44 --hs 0 1 2 --ks 1 2 --model gemma4:26b
```

The sweep writes:

```text
external/webarena-verified/output/hk-sweep/summary.json
external/webarena-verified/output/hk-sweep/summary.csv
```

For `H=1`, the runner now performs continuation planning: after the first
one-subgoal plan segment is executed, the planner is called again with the
current observation until the task goal is reached or the step/planner-call
budget is exhausted.
