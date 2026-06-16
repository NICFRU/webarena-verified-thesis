# WebArena-Verified Minimaldurchstich

Dieses Projekt ist ein kleiner, nachvollziehbarer Minimaldurchstich fuer eine Masterarbeit zu LLM-basierten Webagenten. Der finale Zielbenchmark ist WebArena-Verified; BrowserGym dient als Environment-Schicht und AgentLab als spaeterer Experiment Runner.

Aktuell enthalten sind Service-Probes, hardcoded offizielle Beispielaufgaben,
ein lokaler Ollama-Planner, erste Planner/Executor/Evaluator/Controller/Logging-
Schnittstellen und ein kleiner H/k-Orchestrator fuer GitLab Task 44 sowie
Shopping Task 118. Map ist lokal ausgeschlossen, weil die Daten/Volumes zu
gross fuer den aktuellen Speicherrahmen sind.

## Setup Kurzfassung

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

Falls `python3.12` lokal fehlt, zuerst die Projektdateien und Dokumentation verwenden und die venv spaeter nachziehen.

Auf diesem Rechner wurde Python 3.12 mit Homebrew installiert:

```bash
brew install python@3.12
```

## Docker fuer WebArena-Verified

WebArena-Verified-Dataset-, Subset- und Evaluations-CLI-Schritte koennen direkt ueber Docker laufen:

```bash
docker run --rm ghcr.io/servicenow/webarena-verified:latest --help
docker run --rm ghcr.io/servicenow/webarena-verified:latest subsets-ls
docker run --rm -v "$PWD:/workspace" ghcr.io/servicenow/webarena-verified:latest subset-export --name webarena-verified-hard --output /workspace/runs/webarena_verified/webarena_verified_hard.json
```

Lokal Python/AgentLab bleibt fuer BrowserGym, AgentLab-Experimente, den Fallback-Smoke-Test und spaeter die eigene `H`/`k`-Agentenlogik noetig.

Der offizielle Demo-GitLab-Workflow mit `uv` liegt als zweites Notebook vor:

```bash
code notebooks/02_official_demo_gitlab_uv.ipynb
```

Das offizielle Repo liegt unter `external/webarena-verified`. Dort funktionieren die Doku-nahen Befehle:

```bash
cd external/webarena-verified
uv run invoke -r examples gitlab-start
uv run invoke -r examples gitlab-stop
```

Im aktuell geklonten Repo heisst der Invoke-Task `gitlab-start`; falls eine Doku-Version `demo-gitlab-start` zeigt, ist das hier der entsprechende Task.

Die historischen Setup- und Smoke-Test-Skripte liegen im Archiv:

```bash
scripts/archive/legacy_runners/
```

## Aktuelle Einstiegspunkte

Alle Befehle unten vom Projektroot aus ausfuehren:

```bash
cd /Users/niclascramer/Privat/Uni/Uni-Reutlingen/Masterarbeit/05_Code
```

Fehlende lokale Services starten, Map ausgeschlossen:

```bash
uv run python scripts/start_enabled_services.py
```

Nur eine Auswahl starten:

```bash
uv run python scripts/start_enabled_services.py --sites gitlab shopping shopping_admin reddit
```

Wikipedia wird standardmaessig ausgelassen und kann bewusst dazugenommen werden:

```bash
uv run python scripts/start_enabled_services.py --include-wikipedia
```

Alle eingeschlossenen lokalen Services ausser Map pruefen:

```bash
uv run python scripts/run_services_probe.py
```

Explizit alle aktuell genutzten Services pruefen:

```bash
uv run python scripts/run_services_probe.py --sites shopping shopping_admin reddit gitlab wikipedia
```

Der Probe-Runner prueft vorab den Docker-Status und schreibt:

```text
external/webarena-verified/output/service-probe/service_status.json
external/webarena-verified/output/service-probe/probe_log.jsonl
external/webarena-verified/output/service-probe/summary.json
```

Hardcoded Beispielaufgaben pro Site ausfuehren und offiziell evaluieren:

```bash
uv run python scripts/run_hardcoded_tasks.py --sites shopping shopping_admin reddit gitlab
```

Einzelne offizielle hardcoded Beispiele:

```bash
uv run python scripts/run_hardcoded_tasks.py --sites gitlab
uv run python scripts/run_hardcoded_tasks.py --sites shopping
uv run python scripts/run_hardcoded_tasks.py --sites shopping_admin
uv run python scripts/run_hardcoded_tasks.py --sites reddit
```

Dasselbe mit sichtbarem Browserfenster (`headed`):

```bash
uv run python scripts/run_hardcoded_tasks.py --sites shopping shopping_admin reddit gitlab --headed
```

Nur einen einzelnen Task sichtbar ausfuehren:

```bash
uv run python scripts/run_hardcoded_tasks.py --sites gitlab --headed
uv run python scripts/run_hardcoded_tasks.py --sites shopping --headed
uv run python scripts/run_hardcoded_tasks.py --sites shopping_admin --headed
uv run python scripts/run_hardcoded_tasks.py --sites reddit --headed
```

Das schreibt pro Site HAR, Trace, Metadata und `agent_response.json` nach:

```text
external/webarena-verified/output/hardcoded-tasks/
```

Fuer alle hardcoded Tasks mit echter Task-ID wird die offizielle WebArena-Verified-Evaluation ausgefuehrt. Aktuell loesen die hardcoded Tasks `shopping` 118, `shopping_admin` 157, `reddit` 27 und `gitlab` 44 jeweils mit `official_score=1.0`. `wikipedia` ist nur als Service-Probe enthalten, weil ohne Map keine passende `wikipedia`-only Official Task im aktuellen lokalen Scope verwendet wird.

Die wichtigsten Ergebnisdateien nach dem Hardcoded-Lauf:

```text
external/webarena-verified/output/hardcoded-tasks/summary.json
external/webarena-verified/output/hardcoded-tasks/hardcoded_log.jsonl
external/webarena-verified/output/hardcoded-tasks/<site>/<task_id>/network.har
external/webarena-verified/output/hardcoded-tasks/<site>/<task_id>/hardcoded_trace.jsonl
external/webarena-verified/output/hardcoded-tasks/<site>/<task_id>/agent_response.json
external/webarena-verified/output/hardcoded-tasks/<site>/<task_id>/eval_result.json
```

Planner-Preview ohne Browser-Ausfuehrung erzeugen:

```bash
uv run python scripts/preview_planner.py --planner-mode ollama --model gemma4:26b --sites shopping shopping_admin reddit gitlab wikipedia --h 0
```

Planner-Preview pro Site:

```bash
uv run python scripts/preview_planner.py --planner-mode ollama --model gemma4:26b --sites gitlab --h 0
uv run python scripts/preview_planner.py --planner-mode ollama --model gemma4:26b --sites shopping --h 0
uv run python scripts/preview_planner.py --planner-mode ollama --model gemma4:26b --sites shopping_admin --h 0
uv run python scripts/preview_planner.py --planner-mode ollama --model gemma4:26b --sites reddit --h 0
uv run python scripts/preview_planner.py --planner-mode ollama --model gemma4:26b --sites wikipedia --h 0
```

Planner-Preview mit begrenztem Planungshorizont:

```bash
uv run python scripts/preview_planner.py --planner-mode ollama --model gemma4:26b --sites gitlab --h 2
```

Die Planner-Artefakte liegen unter:

```text
external/webarena-verified/output/planner-preview/
```

Notebook-Kontrollpult fuer Service-Probes, hardcoded Tasks und Output-Tabellen:

```bash
code notebooks/07_services_and_hardcoded_tasks.ipynb
```

GitLab Task 44 als H/k-Architekturprototyp ausfuehren:

```bash
uv run python scripts/run_hk_task.py --site gitlab --planner-mode ollama --model gemma4:26b --h 0 --k 1
```

Shopping Task 118 als laengeres H/k-Beispiel mit mehreren Browser-Aktionen pro Subgoal ausfuehren:

```bash
uv run python scripts/run_hk_task.py --site shopping --planner-mode ollama --model gemma4:26b --h 0 --k 1 --max-steps 5
```

Kleinen H/k-Sweep fuer GitLab Task 44 ausfuehren:

```bash
uv run python scripts/run_hk_sweep.py --site gitlab --hs 0 1 2 --ks 1 2 --model gemma4:26b
```

### Main Execution fuer die Thesis-Laeufe

Der zentrale Einstiegspunkt fuer reproduzierbare H/k-Laeufe ist:

```bash
uv run python scripts/main_execution.py
```

Dieser Runner schreibt bewusst nicht nach `external/`, sondern nach:

```text
runs/hk-test/<experiment-name>/
```

Task 44 sichtbar als Smoke-Test ausfuehren:

```bash
WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/main_execution.py --task-ids 44 --experiment-name task44-headed-smoke --hs 0 --ks 1 --planner-mode ollama --model gemma4:26b --headed
```

LLM-basierten Action-Executor ohne Oracle-Zielhint testen:

```bash
WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/main_execution.py --task-ids 105 --experiment-name task105-llm-executor-nohint-smoke --hs 0 --ks 1 --planner-mode ollama --executor-mode llm --model gemma4:26b --target-hint-mode none --max-planner-calls 1 --max-steps 4
```

Die Architektur und ein Task-105-Beispiel sind dokumentiert in:

```bash
code docs/llm_executor_architecture.md
```

Mehrere Task-IDs mit mehreren H/k-Kombinationen ausfuehren:

```bash
WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/main_execution.py --task-ids 44 105 --experiment-name gitlab-hard-sample --hs 0 1 2 --ks 1 2 --planner-mode ollama --model gemma4:26b
```

Hard-Subset-Smoke mit den ersten fuenf Hard-Tasks:

```bash
WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/main_execution.py --subset-name webarena-verified-hard --limit 5 --experiment-name hard-subset-smoke --hs 0 --ks 1 --planner-mode ollama --model gemma4:26b
```

Vollstaendiger Hard-Subset-Lauf:

```bash
WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/main_execution.py --subset-name webarena-verified-hard --experiment-name hard-subset-gemma4-26b --hs 0 1 2 --ks 1 2 --planner-mode ollama --model gemma4:26b
```

Der Runner schreibt oben pro Experiment `experiment_config.json`,
`selected_tasks.json`, `summary.json` und `summary.csv`. Pro Task/H/k-Lauf
werden unter anderem `task_input.json`, `planner_prompt.md`,
`planner_raw_response.txt`, `planner_calls.jsonl`, `run_trace.json`,
`step_trace.jsonl`, `agent_response.json`, `eval_result.json` und
`network.har` gespeichert. Bei `--executor-mode llm` kommen
`executor_calls.jsonl` und `executor_calls/call_XX/` mit Executor-Prompt,
Raw Response, Aktion, Tokenzahlen und Laufzeit hinzu.

Wichtige Einschraenkung: Der aktuelle technische Stand kann Single-Site-Tasks
ohne Map lokal ausfuehren. Multi-Site- und Map-Tasks werden im Main-Runner
als `skipped` dokumentiert, bis Multi-Environment-Ausfuehrung und Map-Storage
Teil des Experiments sind. Dadurch bleibt der Hard-Subset-Task-Pool voll
nachvollziehbar, ohne dass nicht unterstuetzte Tasks still verschwinden.

Zweite wichtige Einschraenkung: Der aktuelle Planner/Executor-Pfad ist fuer
Smoke- und Kontrolllaeufe noch oracle-gestuetzt, weil Zielpfade aus
Evaluator-Metadaten als `target_hint` bzw. Navigationsziel genutzt werden
koennen. Das ist gut, um Logging, H/k-Ablauf und offizielle Evaluation zu
pruefen. Fuer faire autonome Agentenmessungen muss dieser Oracle-Anteil aus
Planner-Prompt und Executor entfernt oder als eigene Kontrollbedingung
ausgewiesen werden.

Hinweis zu laengeren offiziellen GitLab-Tasks: Das Demo-GitLab aus
`uv run invoke -r examples gitlab-start` laeuft auf `http://localhost:8012`
und enthaelt keine befuellten Benchmark-Projekte. Tasks wie 105 erwarten
das WebArena-Verified-GitLab-Image auf `http://localhost:8023`.

```bash
cd external/webarena-verified
uv run webarena-verified env start --site gitlab
cd ../..

WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/run_hk_sweep.py --site gitlab --task-id 105 --output-root output/hk-sweep/gitlab-long-task105 --hs 0 1 2 --ks 1 2 --model gemma4:26b
```

Deterministischer Gegencheck ohne LLM-Planner:

```bash
WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/run_hk_sweep.py --site gitlab --task-id 105 --output-root output/hk-sweep/gitlab-long-task105-scripted --hs 0 1 2 --ks 1 2 --planner-mode scripted --model scripted
```

Mehrere Task-IDs nacheinander ausfuehren und die Site automatisch aus dem
WebArena-Verified-Datensatz ableiten:

```bash
WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/run_hk_sweep.py --site auto --task-ids 44 105 --output-root output/hk-sweep/gitlab-hard-sample --hs 0 1 2 --ks 1 2 --planner-mode ollama --model gemma4:26b
```

Hard-Subset exportieren und als Evaluationsbasis verwenden:

```bash
cd external/webarena-verified
uv run webarena-verified subset-export --name webarena-verified-hard --output output/webarena-verified-hard.json
cd ../..

WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/run_hk_sweep.py --site auto --subset-file output/webarena-verified-hard.json --limit 5 --output-root output/hk-sweep/hard-subset-smoke --hs 0 --ks 1 --planner-mode ollama --model gemma4:26b
```

Hinweis: `scripts/run_hk_sweep.py` bleibt als kleiner Entwicklungsrunner
nuetzlich. Fuer Thesis-Laeufe mit sauberer Ablage und zusammenfassenden
Metriken ist `scripts/main_execution.py` der bevorzugte Einstiegspunkt.

Kleinen H/k-Sweep fuer Shopping Task 118 ausfuehren:

```bash
uv run python scripts/run_hk_sweep.py --site shopping --hs 0 --ks 1 2 --model gemma4:26b
```

Fuer die gemeinsame Notebook-Auswertung werden die Sweeps getrennt gespeichert:

```bash
uv run python scripts/run_hk_sweep.py --site gitlab --output-root output/hk-sweep/gitlab --hs 0 1 2 --ks 1 2 --model gemma4:26b
uv run python scripts/run_hk_sweep.py --site shopping --output-root output/hk-sweep/shopping --hs 0 --ks 1 2 --model gemma4:26b
```

Sweep-Ergebnisse:

```text
external/webarena-verified/output/hk-sweep/gitlab/summary.json
external/webarena-verified/output/hk-sweep/gitlab/summary.csv
external/webarena-verified/output/hk-sweep/shopping/summary.json
external/webarena-verified/output/hk-sweep/shopping/summary.csv
```

Zentrales Notebook fuer Ausfuehrung und Auswertung:

```bash
code notebooks/06_hk_task44_prototype.ipynb
```

Erste H/k-Sweep-Auswertung:

```bash
code notebooks/08_hk_sweep_analysis.ipynb
```

Aktueller H/k-Prozess mit Mermaid-Grafik:

```bash
code docs/current_hk_process.md
```

Die aktuellen Dataclasses, Site-Inputs und Hilfsfunktionen liegen unter `scripts/webarena_exp/`. Code-Quellen und lokale Verantwortlichkeiten sind in `docs/code_sources.md` dokumentiert.

## Aktuelle Abdeckung

| Site | Aufgabe | Pfad | Offizielle Evaluation |
|---|---:|---|---|
| `gitlab` | 44 | hardcoded + H/k-Orchestrator + Planner-Preview | ja |
| `shopping` | 118 | hardcoded + H/k-Orchestrator + Planner-Preview | ja |
| `shopping_admin` | 157 | hardcoded + Planner-Preview | ja |
| `reddit` | 27 | hardcoded Retrieve + Planner-Preview | ja |
| `wikipedia` | direct probe | Service-Probe + Planner-Preview | nein, keine genutzte wikipedia-only Task im aktuellen lokalen Scope |
| `map` | - | ausgeschlossen | nein |

## Resultate

Die wichtigsten WebArena-Verified-Dateien (`tasks.json`, `agent_response.json`, `network.har`, `eval_result.json`) sind in `docs/webarena_verified_cli_and_outputs.md` erklaert.

Das spaetere Experiment untersucht den Einfluss von Planungshorizont `H` und Validierungsintervall `k` auf Success Rate, Tokenverbrauch, Kostenproxy, Runtime, Replans, Loops, No-Progress-Events und Invalid Actions.
