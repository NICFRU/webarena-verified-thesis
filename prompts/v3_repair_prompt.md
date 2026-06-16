# v3 Repair Prompt

This prompt defines the repair brief produced after a k-step runtime evaluator
signal. The repair brief is not an executable BrowserGym action and not a final
answer. It is a structured diagnostic object that helps the planner and executor
repair the current workflow state.

Return or store a compact JSON-like object with these fields:

```json
{
  "repair_prompt_version": "v3_repair_prompt",
  "failure_class": "<short error class>",
  "current_state": "<what the browser currently shows>",
  "wrong_actions": ["<recent action to avoid>"],
  "avoid": ["<wrong target or workflow>"],
  "needed_next_target": "<UI object or state needed next>",
  "repair_strategy": "<concrete recovery strategy>",
  "planner_instruction": "<subgoal-level instruction, no BrowserGym action>",
  "executor_instruction": "<action-level instruction with current-candidate constraints>"
}
```

Rules:

- Do not use evaluator gold answers or task-id-specific shortcuts.
- Use only current browser state, recent actions, runtime evaluator feedback,
  recovery hints, and visible task intent.
- The planner instruction must stay at subgoal level.
- The executor instruction may mention action constraints, but it must not
  invent bids. It must require exact current `action_candidates`.
- For GitLab MUTATE, distinguish source pages, fork forms, invite modals,
  group member tables, simple file editors, Web IDE, and missing editor/modal
  candidates.
