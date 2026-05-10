You are working in my thesis repository for a WebArena-Verified / BrowserGym web-agent experiment.

Goal:
Build and document a modular web-agent architecture with:
1. Planner
2. Executor
3. Runtime Evaluator / Verifier
4. Rule-based Controller
5. Logging / Trace Storage
6. Prompt templates and JSON contracts

Important design constraint:
WebArena-Verified remains the official final benchmark evaluator. My own Evaluator is only a runtime module for intermediate progress, subgoal completion, no-progress, loop, invalid-action and replanning signals. Do not replace WebArena-Verified eval-tasks.

My research variables:
- H = planning horizon
- k = validation interval
The system must support controlled experiments over different H and k values.

Local project context:
- WebArena-Verified is under external/webarena-verified
- Own code should live in scripts/webarena_exp/
- Prompts should live in prompts/
- Runs/artifacts should go into runs/
- Expected official task output per task must include:
  - agent_response.json
  - network.har
  - eval_result.json after eval-tasks

Primary official references to inspect:
https://servicenow.github.io/webarena-verified/latest/getting_started/usage/
https://servicenow.github.io/webarena-verified/latest/getting_started/data_format/
https://servicenow.github.io/webarena-verified/latest/evaluation/network_event_based_evaluation/
https://github.com/ServiceNow/AgentLab
https://github.com/ServiceNow/BrowserGym
https://github.com/web-arena-x/webarena

Research/code references to inspect for architecture and prompts:
https://github.com/liyichen-cly/PoG/blob/main/PoG/prompt_list.py
https://github.com/DataArcTech/ToG
https://github.com/kenhktsui/self-correction-bench
https://github.com/MadeAgents/browser-agent
https://github.com/ai-kmu/GUIDE-CoT
https://github.com/YoungDubbyDu/Awesome-LLM-Agent-Optimization-Papers
https://github.com/cdhx/QueryAgent
https://github.com/ace-agent/ace
https://github.com/long-horizon-execution/measuring-execution
https://github.com/karthikv792/cot-planning
https://github.com/kstechly/cot-scheduling
https://github.com/ZhiningLiu1998/SelfElicit
https://github.com/Gitlawb/openclaude
https://github.com/HKUDS/RAG-Anything
https://github.com/MemPalace/mempalace
https://github.com/acl2025-submission/acl2025
https://github.com/RichardHGL/CHI2025_Plan-then-Execute_LLMAgent
https://github.com/karthikv792/LLMs-Planning
https://github.com/UMass-Embodied-AGI/CoELA
https://jykoh.com/search-agents
https://github.com/colonylabs/ScribeAgent
https://github.com/kyle8581/WMA-Agents
https://github.com/KCL-Planning/VAL
https://github.com/wll199566/Awesome-LLM-Planning-Capability
https://github.com/UCSB-NLP-Chang/WebDART
https://github.com/nsidn98/LLaMAR
https://www.agentdataprotocol.com/
https://github.com/sej2020/manipulating-web-agents
https://github.com/maitrix-org/llm-reasoners
https://github.com/Ber666/Chain-of-ThoughtsPapers
https://github.com/matthewrenze/jhu-concise-cot
https://github.com/masamasa59/ai-agent-papers

What to search for in these repositories:
- prompt templates
- planner / plan / subgoal / decomposition logic
- executor / operator / action generation logic
- evaluator / verifier / critic / judge / reflection logic
- controller / replanning / self-correction logic
- memory / summarization / trajectory compression
- logging, traces, metrics, result schemas
- JSON output contracts
- BrowserGym / Playwright / WebArena integration patterns

Deliverables:
1. Create a Markdown report at docs/repo_scan_for_agent_architecture.md with a table:
   - repository
   - relevant files
   - architecture idea
   - prompt idea
   - can be reused directly? yes/no
   - should influence Planner / Executor / Evaluator / Controller / Logging
   - notes for thesis chapter 5
2. Create or update prompt files:
   - prompts/planner_system.md
   - prompts/executor_system.md
   - prompts/evaluator_system.md
3. Create or update data contracts in scripts/webarena_exp/types.py for:
   - PlannerRequest
   - Subgoal
   - Plan
   - ExecutorStep
   - EvaluatorSignal
   - ControllerDecision
   - RunTrace
4. Implement a minimal static baseline first:
   - static planner
   - scripted executor for GitLab Task 44 if available
   - heuristic evaluator
   - rule-based controller
   - JSON logging
5. Add optional Ollama planner mode:
   - call local Ollama chat endpoint
   - enforce JSON-only output
   - validate against the Plan schema
   - fallback to static planner on invalid JSON
6. Do not implement a full autonomous web agent yet.
7. Do not store full hidden chain-of-thought. Use concise rationale_summary, reason_code, expected_outcome and structured signals instead.

Architecture I want:
Task input -> Planner -> Plan/Subgoals -> Executor -> BrowserGym/WebArena -> Observation -> Runtime Evaluator every k steps -> Controller -> Continue / Local Replan / Global Replan / Abort -> Logger -> WebArena-Verified final eval.

Controller decisions:
- continue
- local_replan
- global_replan
- abort

Evaluator signals:
- progress_score
- subgoal_done
- constraint_violation
- invalid_action
- loop_detected
- no_progress
- risk_score
- recoverability_score
- recommended_intervention
- rationale_summary

Logging metrics:
- task_id
- site
- h
- k
- planner_mode
- model
- prompt_version
- total_steps
- total_runtime_ms
- total_tokens
- num_replans
- num_no_progress_events
- num_invalid_actions
- num_loop_events
- final_status
- success
- abort_reason

Implementation order:
1. Inspect existing local files and current scripts.
2. Inspect the external references listed above.
3. Produce the report.
4. Implement only minimal interfaces and stubs if missing.
5. Keep WebArena-Verified output compatibility.
6. Add tests or smoke scripts where feasible.