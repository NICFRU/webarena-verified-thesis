# H/k Agent Architecture README

Diese README beschreibt die aktuelle Architektur fuer den H/k Planner-Executor
Agenten auf BrowserGym und WebArena-Verified. Der Fokus liegt auf Datenfluss,
Hosting, Artefakten und darauf, welche Informationen in welchem Modus an Planner,
Executor, Runtime Evaluator und Official Evaluator gehen.

Editierbare Draw.io-Grafik: [hk_agent_architecture.drawio](hk_agent_architecture.drawio)

## Kurzueberblick

Die Architektur besteht aus einer lokalen Experiment-Pipeline:

- Entry Points starten einzelne Tasks, Sweeps oder Hard-Pipelines.
- `task_loader.py` laedt WebArena-Verified Tasks und baut BrowserGym IDs.
- `runner.py` fuehrt den H/k Loop aus.
- Der Planner erzeugt Subgoals.
- Der Executor uebersetzt ein aktives Subgoal in eine BrowserGym Action.
- BrowserGym/Playwright interagiert mit lokal gehosteten WebArena-Diensten.
- Der Runtime Evaluator bewertet nur Prozesssignale fuer Replanning.
- Der Official Evaluator bewertet erst nachgelagert mit WebArena-Verified.

Wichtig: Im `agent` Modus werden Eval-Metadaten, Gold-URLs und Oracle-Felder
nicht an Planner oder Executor gegeben. Official Success kommt nur aus
WebArena-Verified `eval-tasks`.

## Mermaid Architektur

```mermaid
flowchart LR
    User[User / Notebook / CLI] --> Entry[Entry Points<br/>run_hk_agent_task.py<br/>run_hk_agent_experiment.py<br/>run_hk_agent_hard_pipeline.py]

    subgraph Repo[Local repo: 05_Code]
        Entry --> Loader[hk_agent.task_loader<br/>Dataset, hard subset, gym_id]
        Loader --> Runner[hk_agent.runner<br/>H/k loop, budget, phases]
        Runner --> Artifacts[hk_agent.artifacts<br/>JSONL traces, summaries, HAR paths]
        Runner --> RuntimeEval[hk_agent.runtime_evaluator<br/>progress, no-progress, invalid actions]
        RuntimeEval --> Controller[webarena_exp.controller<br/>continue / replan / abort]
        Controller --> Runner
    end

    subgraph Prompts[Prompt files]
        PlannerPrompt[prompts/planner_system.md<br/>prompts/prompt_user_template.md]
        ExecutorPrompt[prompts/executor_system.md]
    end

    subgraph Ollama[Local Ollama: http://localhost:11434]
        PlannerModel[Planner model<br/>gemma4:26b]
        ExecutorModel[Executor model<br/>gemma4:e4b]
    end

    Runner -->|sanitized task + observation + previous plan + feedback| PlannerPrompt
    PlannerPrompt -->|system + user chat messages| PlannerModel
    PlannerModel -->|Plan JSON with subgoals| Runner

    Runner -->|active subgoal + observation + candidates + recent steps| ExecutorPrompt
    ExecutorPrompt -->|system + user chat messages| ExecutorModel
    ExecutorModel -->|Action JSON| Runner

    subgraph Browser[BrowserGym + Playwright]
        Gym[BrowserGym env<br/>browsergym/webarena_verified.*]
        Page[Playwright page<br/>actions + observations]
    end

    Runner -->|gym.make + env.step(action)| Gym
    Gym --> Page
    Page -->|URL, title, text, AX tree, errors| Runner

    subgraph Services[Local WebArena services]
        GitLab[GitLab<br/>WA_GITLAB<br/>http://localhost:8023]
        Shopping[Shopping<br/>WA_SHOPPING<br/>http://localhost:7770]
        Admin[Shopping Admin<br/>WA_SHOPPING_ADMIN<br/>http://localhost:7780/admin]
        Reddit[Reddit/Postmill<br/>WA_REDDIT<br/>http://localhost:9999]
        Home[Homepage<br/>WA_HOMEPAGE<br/>http://localhost:4399]
        Wiki[Wikipedia<br/>WA_WIKIPEDIA<br/>http://localhost:8888]
        Map[Map<br/>WA_MAP]
    end

    Page --> Services
    Services --> Page

    Runner -->|network.har + agent_response.json + config| Official[WebArena-Verified official evaluator<br/>uv run webarena-verified eval-tasks]
    Official -->|eval_result.json| Artifacts
    Artifacts --> Summary[summary.json / summary.csv<br/>official + runtime + cost metrics]
```

## Hosting und Endpunkte

| Komponente | Ort | Zweck |
| --- | --- | --- |
| Repository Code | Lokales Projekt `05_Code` | Runner, Prompts, Artefakte, Notebooks |
| Ollama | `http://localhost:11434` | Planner- und Executor-LLM |
| GitLab | `http://localhost:8023` | WebArena GitLab Tasks |
| Shopping | `http://localhost:7770` | Storefront Tasks |
| Shopping Admin | `http://localhost:7780/admin` | Magento Admin Tasks |
| Reddit/Postmill | `http://localhost:9999` | Forum Tasks |
| Homepage | `http://localhost:4399` | WebArena Homepage |
| Wikipedia | `http://localhost:8888` | Lokale Wikipedia Tasks |
| Map | `WA_MAP` | Spaeter separat absichern |
| WebArena-Verified repo | `external/webarena-verified` | Dataset, Hard-Subset, offizieller Evaluator |

Default-Werte werden in `scripts/hk_agent/task_loader.py` ueber
`DEFAULT_BROWSERGYM_ENV` gesetzt. CLI-Flags wie `--wa-gitlab` koennen sie
ueberschreiben.

## Datenfluss im Agent-Modus

1. CLI oder Notebook startet ein Experiment.
2. `task_loader.py` laedt Dataset und Hard-Subset:
   - `assets/dataset/webarena-verified.json`
   - `assets/dataset/subsets/webarena-verified-hard.json`
3. Fuer BrowserGym wird eine ID gebaut:
   - `browsergym/webarena_verified.{intent_template_id}.{task_id}.{revision}`
4. `sanitize_task_for_agent(...)` entfernt im `agent` Modus unter anderem:
   - `eval`
   - `reference_answer`
   - `reference_url`
   - `gold`
   - `oracle`
   - `expected`
5. `runner.py` startet BrowserGym und Playwright.
6. Der Planner bekommt:
   - sanitisierten Task
   - Site-Name
   - H-Wert
   - aktuelle Observation Summary
   - vorherigen Plan, falls vorhanden
   - Runtime-Evaluator Feedback, falls vorhanden
   - Controller-Entscheidung, falls Replanning
7. Der Planner liefert Plan-JSON mit Subgoals.
8. Der Executor bekommt:
   - sanitisierten Task
   - aktives Subgoal
   - aktuelle URL, Titel, sichtbaren Text
   - AX-/DOM-Auszug
   - interaktive BrowserGym-Kandidaten
   - allgemeine Site-Konventionen
   - recent steps
9. Der Executor liefert genau eine BrowserGym Action als JSON.
10. BrowserGym/Playwright fuehrt die Action auf den lokalen Diensten aus.
11. Nach jeweils `k` Aktionen laeuft der Runtime Evaluator.
12. Der Controller entscheidet:
    - `continue`
    - `local_replan`
    - `global_replan`
    - `abort`
13. Nach dem Run werden `agent_response.json` und `network.har` geschrieben.
14. WebArena-Verified `eval-tasks` laeuft nachgelagert und schreibt
    `eval_result.json`.

## H und k

| Symbol | Bedeutung |
| --- | --- |
| `H=0` | Planner darf den vollstaendigen High-Level-Plan ausgeben |
| `H>0` | Planner gibt nur die naechsten `H` Subgoals aus |
| `k=0` | Keine periodische Runtime-Validierung; Baseline ohne Evaluator-Feedback |
| `k>0` | Runtime Evaluator laeuft nach jeweils `k` ausgefuehrten Browser-Aktionen |

`H` beeinflusst den Planungshorizont. `k` beeinflusst, wie oft der aktuelle
Fortschritt geprueft und Replanning angestossen wird.

## Modelle und Prompt-Rollen

Aktuelle Standardaufteilung:

| Rolle | Modell | Grund |
| --- | --- | --- |
| Planner | `gemma4:26b` | Staerker fuer Long-Horizon Planung und Subgoal-Struktur |
| Executor | `gemma4:e4b` | Schneller fuer konkrete Einzelschritte und Action Grounding |

Die Promptdateien werden als Chat-Rollen gesendet:

- `prompts/planner_system.md` -> `system`
- `prompts/prompt_user_template.md` + Task-Kontext -> `user`
- `prompts/executor_system.md` -> `system`
- Executor-Kontext -> `user`

Die Implementierung schreibt keine rohen Gemma-4-Turn-Tokens in die Prompts,
weil Ollama die Chat-Templates aus den Rollen ableitet. Antworten werden vor dem
JSON-Parsing um Gemma-4-Control-Tokens bereinigt.

## Run-Modi

| Modus | Bedeutung |
| --- | --- |
| `agent` | Fairer Modus. Planner/Executor sehen keine Eval-/Oracle-Felder |
| `oracle_debug` | Debug-Modus. Kann Eval-/Target-Hints nutzen |
| `analysis` | Keine Agent-Ausfuehrung, nur vorhandene Artefakte/Official Eval |

## Artefakte pro Run

Jeder Task/H/k Run schreibt in:

```text
runs/hk-agent/<experiment>/<site>/<task_id>/h<H>_k<k>/<task_id>/
```

Wichtige Dateien:

| Datei | Inhalt |
| --- | --- |
| `run_summary.json` | Zentrale Run-Zusammenfassung |
| `plan.json` | Letzter Plan |
| `step_trace.jsonl` | Browser-Schritte und Status |
| `planner_calls.jsonl` | Planner Calls, Tokens, Raw Preview |
| `executor_calls.jsonl` | Executor Calls, Tokens, Actions |
| `runtime_evaluator_signals.jsonl` | Runtime-Fortschrittssignale |
| `controller_decisions.jsonl` | Continue/Replan/Abort Entscheidungen |
| `agent_response.json` | WebArena-Verified Agent Response |
| `network.har` | Browser-Netzwerk-Trace |
| `eval_result.json` | Offizielle WebArena-Verified Bewertung |

Pro Experiment entstehen zusaetzlich:

| Datei | Inhalt |
| --- | --- |
| `experiment_config.json` | Reproduzierbare Experimentkonfiguration |
| `selected_tasks.json` | Ausgewaehlte Tasks |
| `summary.json` | Alle Runs als JSON |
| `summary.csv` | Alle Runs als Tabelle |

## Metriken

Official Metrics:

- `official_score`
- `official_success`
- `official_eval_status`

Runtime/Process Metrics:

- `runtime_progress_score`
- `runtime_replans`
- `runtime_no_progress_events`
- `runtime_invalid_actions`
- `runtime_loop_events`

Cost/Process Metrics:

- `planner_tokens`
- `executor_tokens`
- `total_tokens`
- `total_runtime_ms`
- `planner_calls`
- `executor_calls`
- `num_plan_subgoals_generated`

## Typische Befehle

Mini-Smoke:

```bash
uv run python scripts/run_hk_agent_experiment.py \
  --experiment-name hk-agent-browsergym-example-smoke-v2-mini \
  --task-ids 44 157 105 27 118 \
  --allow-non-hard-task-ids \
  --hs 2 \
  --ks 2 \
  --run-mode agent \
  --planner-model gemma4:26b \
  --executor-model gemma4:e4b \
  --max-planner-calls 3 \
  --max-steps 8 \
  --llm-timeout-seconds 600
```

Random stratifizierter Smoke:

```bash
uv run python scripts/run_hk_agent_experiment.py \
  --experiment-name hk-agent-random-gemma4-mini \
  --sample-sites gitlab reddit shopping shopping_admin \
  --sample-buckets short medium long \
  --sample-seed 42 \
  --exclude-task-ids 44 157 105 27 118 \
  --hs 2 \
  --ks 2 \
  --run-mode agent \
  --planner-model gemma4:26b \
  --executor-model gemma4:e4b \
  --max-planner-calls 3 \
  --max-steps 8 \
  --llm-timeout-seconds 600
```

Hard-Pipeline:

```bash
uv run python scripts/run_hk_agent_hard_pipeline.py \
  --profile supported-single-site \
  --hs 0 2 5 \
  --ks 2 5 \
  --planner-model gemma4:26b \
  --executor-model gemma4:e4b
```

## Wissenschaftliche Trennung

Die Architektur trennt bewusst:

- Runtime Evaluator: Prozesssignal fuer Replanning waehrend des Runs.
- Official Evaluator: Benchmark-Erfolg nach dem Run.

Deshalb darf `runtime_progress_score` nie als finaler Benchmark-Erfolg
interpretiert werden. Fuer die Thesis ist `official_success` die zentrale
Effektivitaetsmetrik, Runtime-Metriken erklaeren nur den Prozess.
