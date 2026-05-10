# Repository Scan For Agent Architecture

This scan is intentionally conservative. External repositories are treated as
architecture and prompt inspiration, not as code to copy into the thesis
prototype.

| Repository | Relevant files / concepts | Architecture idea | Prompt idea | Can be reused directly? | Should influence | Notes for thesis chapter 5 |
| --- | --- | --- | --- | --- | --- | --- |
| `web-arena-x/webarena` | `agent`, `browser_env`, `evaluation_harness`, `agent/prompts` | Web task as Gym-like browser loop with observation, action, trajectory, and final evaluation | Prompt dictionaries with instruction, examples, template, and parser metadata | No | Planner, Executor, Logging | Cite as original benchmark and baseline prompt-agent framing |
| `ServiceNow/webarena-verified` | dataset, `agent-input-get`, `eval-tasks`, network trace replay | Final scoring is deterministic and separate from runtime reasoning | Avoid final LLM judge; write compatible `agent_response.json` and `network.har` | No | Evaluator boundary, Logging | Use as official benchmark evaluator and artifact contract |
| `ServiceNow/AgentLab` | `AgentArgs`, experiments, result loaders, BrowserGym support | Agents and experiment runners should be swappable and reproducible | Agent configuration and results should be inspectable | No | Runner, Logging, later AgentLab adapter | Use for future scaling beyond the local Task-44 runner |
| Local `prompts/zwischenspeicher.md` | Required modules, H/k variables, JSON contracts | Planner -> Executor -> Runtime Evaluator -> Controller -> Logger | Do not store hidden CoT; use rationale summaries and structured signals | Yes, as local requirement | All modules | This is the local implementation source of truth |
| Local architecture diagram | Orchestrator with module boundaries and trace storage | Thin module interfaces around a central runner | Explicit prompts for Planner, Executor, Evaluator | Yes, as local design | All modules | Convert diagram blocks into minimal Python interfaces |

## Implementation Decision

The first implementation keeps the task-solving behavior deterministic. This
prevents LLM variance from hiding interface bugs. The LLM Planner can be enabled
through Ollama later because the `Plan` contract is already separate from
BrowserGym execution.

## Source Links

- WebArena: https://github.com/web-arena-x/webarena
- WebArena-Verified: https://github.com/ServiceNow/webarena-verified
- AgentLab: https://github.com/ServiceNow/AgentLab/
