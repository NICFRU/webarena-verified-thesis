# Code Sources and Local Responsibilities

This document records which external code sources the local experiment scripts
use and which parts are local thesis prototype code.

## External Sources

### ServiceNow WebArena-Verified

- Local path: `external/webarena-verified`
- Used for:
  - official task dataset
  - URL rendering through `agent-input-get`
  - candidate task export through `dataset-get`
  - Docker environment management through `env`
  - final benchmark evaluation through `eval-tasks`
- Local wrapper:
  - `scripts/webarena_exp/webarena_cli.py`

### BrowserGym

- Used for:
  - `browsergym/openended` browser environment
  - browser reset and page access
  - HAR recording through Playwright context options
- Local wrapper:
  - `scripts/webarena_exp/browsergym_utils.py`

### WebArena

- Repository: `https://github.com/web-arena-x/webarena`
- Used for:
  - conceptual benchmark background
  - original WebArena task and environment framing
  - architecture discussion in the thesis.

### AgentLab

- Repository: `https://github.com/ServiceNow/AgentLab/`
- Used for:
  - planned later experiment-runner integration
  - BrowserGym-based agent architecture reference
  - scalable experiment and result-management direction.

### Gemma / Ollama

- Gemma documentation: `https://ai.google.dev/gemma/docs/core`
- Ollama model endpoint: local `http://localhost:11434/api/chat`
- Used for:
  - optional local LLM planner mode.

## Local Prototype Code

### Shared Data Contracts

- File: `scripts/webarena_exp/types.py`
- Purpose:
  - defines the JSON artifact format for site inputs, plans, subgoals,
    evaluator signals, controller decisions, and service probe results.

### Site Scope

- File: `scripts/webarena_exp/site_definitions.py`
- Included sites:
  - `gitlab`
  - `shopping`
  - `shopping_admin`
  - `reddit`
  - `wikipedia`
- Excluded sites:
  - `map`, because its data archives and Docker volumes exceed the available
    local storage budget.

### Experiment Entry Points

- `scripts/preview_planner.py`
  - renders task inputs and writes `plan.json` files before browser execution.
  - uses the Ollama planner path for local LLM planning previews.
- `scripts/run_services_probe.py`
  - checks whether all enabled local services can be rendered into task inputs
    and opened through BrowserGym.
- `scripts/run_hk_task44_prototype.py`
  - runs the H/k architecture prototype with planner, executor, evaluator,
    controller, and artifact logging.
  - currently supports GitLab Task 44 and Shopping Task 118.
- `scripts/run_hardcoded_tasks.py`
  - runs deterministic per-site smoke tasks before a full agent policy exists.
  - all hardcoded tasks with real task IDs run through the official evaluator.
  - Shopping Task 118, Shopping Admin Task 157, Reddit Task 27, and GitLab Task
    44 currently solve their official evaluator checks with `score=1.0`.

### Archived Historical Scripts

- Path: `scripts/archive/legacy_runners/`
- Purpose:
  - keeps older setup and smoke-test scripts for historical reproducibility.
  - they are not the primary experiment interface anymore.
