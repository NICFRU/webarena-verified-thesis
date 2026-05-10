# Planner Design

The planner is the strategic layer of the local WebArena-Verified thesis
prototype. It creates high-level subgoals from a task instruction and rendered
task input. It does not execute browser actions.

## External References

- WebArena: original self-hosted web benchmark and conceptual task setting.
  Repository: https://github.com/web-arena-x/webarena
- WebArena-Verified: verified task dataset, deterministic evaluators, network
  trace evaluation, and final official scores.
  Repository: https://github.com/ServiceNow/webarena-verified
- AgentLab: later experiment runner and scalable BrowserGym-based agent
  framework.
  Repository: https://github.com/ServiceNow/AgentLab/
- Gemma 4: candidate local model family for LLM planning through Ollama.
  Documentation: https://ai.google.dev/gemma/docs/core

## Local Files

- `scripts/webarena_exp/planner.py`
  - defines `PlannerRequest`, `PlannerArtifacts`, and the Ollama planner
    interface.
- `prompts/planner_system.md`
  - contains the planner prompt and JSON response contract.
- `prompts/prompt_user_template.md`
  - contains the task-specific user prompt template. The planner fills it with
    task metadata, site scope, constraints, previous plan, evaluator feedback,
    and controller decision fields.
- `scripts/preview_planner.py`
  - renders local task inputs and writes planner outputs without running the
    browser environment.

## Planner Contract

The local runner stores every plan as `plan.json` with this structure:

```json
{
  "planner_mode": "ollama",
  "h": 0,
  "task_id": 44,
  "task_intent": "Open my todos page",
  "subgoals": [
    {
      "id": "sg1",
      "objective": "Open the task start page",
      "expected_outcome": "The target website is reachable"
    }
  ]
}
```

`h=0` means full available plan. `h>0` keeps only the first `h` subgoals.

## Ollama Mode

The active planner mode uses Ollama and the same planner contract across
preview and H/k execution:

```bash
uv run python scripts/preview_planner.py --planner-mode ollama --model gemma4:26b
uv run python scripts/preview_planner.py --planner-mode ollama --model gemma4:31b
```

The recommended first local model is `gemma4:26b`, with `gemma4:31b` reserved
as a stronger but heavier comparison model.

No static fallback is used in the active Task-44 prototype. If the LLM plan is
bad, the run should expose that through planner warnings, runtime evaluator
signals, controller decisions, and final WebArena-Verified evaluation.

Planner token fields are populated from Ollama metadata when available:

- `prompt_eval_count` -> `prompt_tokens`
- `eval_count` -> `completion_tokens`
- sum of both -> `total_tokens`

## GitLab Prompt Context

GitLab planner prompts always receive site-specific context:

- the run can start on a login page or an already authenticated dashboard
- authentication must be represented as a possible subgoal before task-specific
  navigation
- Task 44 uses `/dashboard/todos` as the target path hint

This context is injected automatically by `scripts/webarena_exp/planner.py` so
the model does not silently assume that the user is already logged in.

The preview runner also validates Task-44 plans. If an Ollama plan omits both
authentication and the todos target, the warning is written into
`output/planner-preview/summary.json`.

## Continuation Planning

The active Task-44 H/k runner treats `H` as the horizon of one planner call, not
as the maximum length of the whole run. If a plan segment is completed and the
global task goal is not reached, the planner is called again with:

- current URL
- page title
- login-form visibility
- target-reached flag
- previous plan
- last evaluator signal
- last controller decision

This makes `H=1` meaningful: the model can plan authentication first and then,
after observing the authenticated dashboard state, plan the todos navigation in
a second planner call.
