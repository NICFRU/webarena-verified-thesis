# WebArena-Verified Minimaldurchstich

Dieses Projekt ist ein kleiner, nachvollziehbarer Minimaldurchstich fuer eine Masterarbeit zu LLM-basierten Webagenten. Der finale Zielbenchmark ist WebArena-Verified; BrowserGym dient als Environment-Schicht und AgentLab als spaeterer Experiment Runner.

Noch nicht enthalten sind Planner, Evaluator, Controller, Replanning-Logik oder das vollstaendige `H`/`k`-Faktorexperiment. Diese Struktur prueft zuerst, ob Toolchain, Config und Result-Pfade lokal tragfaehig sind.

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

Der reproduzierbare Docker-Smoke-Test liegt als Script und Notebook vor:

```bash
python scripts/run_docker_webarena_verified_smoke.py
```

Notebook: `notebooks/01_docker_webarena_verified_smoke.ipynb`

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

Der erste eigene Minimalrunner fuer Task 44 liegt hier:

```bash
python scripts/run_gitlab_task44_navigate_runner.py
```

Notebook dazu: `notebooks/03_minimal_runner_task44.ipynb`.

## Checks

```bash
python scripts/check_setup.py
python scripts/run_agentlab_smoke.py
python scripts/run_webarena_verified_smoke.py
python scripts/run_docker_webarena_verified_smoke.py
```

Die WebArena-Verified-Ausfuehrung braucht echte WebArena-Instanzen und passende URLs in `.env`. Kopiere dafuer:

```bash
cp configs/minimal_demo.env.example .env
```

und ersetze die `todo`-Werte.

## Resultate

Minimal-Summaries werden unter `runs/minimal_summary.json` vorbereitet. AgentLab-Resultate sollen spaeter unter `agentlab-results/` liegen.

```bash
python scripts/inspect_results.py runs/minimal_summary.json
```

Die wichtigsten WebArena-Verified-Dateien (`tasks.json`, `agent_response.json`, `network.har`, `eval_result.json`) sind in `docs/webarena_verified_cli_and_outputs.md` erklaert.

Das spaetere Experiment untersucht den Einfluss von Planungshorizont `H` und Validierungsintervall `k` auf Success Rate, Tokenverbrauch, Kostenproxy, Runtime, Replans, Loops, No-Progress-Events und Invalid Actions.
