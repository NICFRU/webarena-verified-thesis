# HK-Agent v3 fuer WebArena-Verified

Dieses Repository enthaelt den finalen v3-Artefaktstand der Masterarbeit. Der Fokus liegt auf der reproduzierbaren Ausfuehrung des H/k-Agenten, der Erzeugung einer `summary.csv` und der anschliessenden Ergebnisaufbereitung fuer die Arbeit.

## Schnellzugriff

- Finale Ergebnis-CSV: `thesis_results_output/data/final_summary.csv`
- Finale Ergebnis-JSON: `thesis_results_output/data/final_summary.json`
- Finale Ergebnisartefakte und Abbildungen: `thesis_results_output/`
- Finale Analyse: `notebooks/final_analysis.ipynb`
- v3-Prompts: `prompts/v3/`
- Architekturabbildungen: `docs/architecture/`

## Struktur

```text
.
├── configs/                         # Beispielkonfigurationen
├── docs/
│   ├── architecture/                 # Eingebundene Architekturdiagramme
│   ├── architektur_und_umsetzung_hk_agent.md
│   └── task_44_durchfuehrung_beispiel.md
├── external/webarena-verified/       # lokale WebArena-Verified Codebasis/Dataset
├── notebooks/
│   └── final_analysis.ipynb          # finale Auswertung aus summary.csv
├── prompts/
│   └── v3/                           # Planner-, Executor- und Site-Prompts
├── scripts/
│   ├── main_execution.py             # reproduzierbarer Haupt-Runner
│   ├── run_hk_agent_experiment.py    # Thesis-Experimentrunner fuer v3
│   ├── hk_agent/                     # Controller, Executor, Evaluator, Recovery
│   └── webarena_exp/                 # WebArena-Verified Integration
└── thesis_results_output/            # finale CSV/JSON und exportierte Figures
```

Historische Notebooks, lokale Runs, Caches und die externe Plan-and-Act-Referenzimplementierung werden per `.gitignore` aus dem Upload herausgehalten. Sie muessen fuer die finale v3-Ausfuehrung nicht versioniert werden.

## Architektur

Die finalen Architekturdateien liegen gesammelt unter `docs/architecture/`:

- `hk_agent_gesamtarchitektur.png`
- `task44_complete_example_flow.drawio.pdf`
- `planner_prompt_composition.drawio.pdf`
- `runtime_hk_v3_precise_process_final.drawio.pdf`

Die Architektur beschreibt den v3-Agenten als H/k-Kontrollschleife: Der Planner erzeugt einen begrenzten Subgoal-Plan, der Executor fuehrt Browseraktionen aus, der Runtime-Evaluator bewertet Fortschritt und Fehler, und der Controller entscheidet anhand von `h` und `k`, ob weiter ausgefuehrt, repariert oder neu geplant wird.

## Setup

Voraussetzungen:

- Python 3.12
- Docker fuer die lokalen WebArena-Verified Services
- Playwright Chromium
- lokaler Ollama-kompatibler LLM-Endpunkt oder Vertex-Ollama-Proxy, je nach Experiment

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

## Lokale Services

Die WebArena-Verified Services werden aus `external/webarena-verified/` genutzt. Map ist im finalen lokalen Scope nicht enthalten.

```bash
uv run python scripts/start_enabled_services.py --sites gitlab shopping shopping_admin reddit
uv run python scripts/run_services_probe.py --sites gitlab shopping shopping_admin reddit
```

## Finale v3-Laeufe ausfuehren

Ein kleiner Smoke-Test fuer Task 44:

```bash
WA_GITLAB=http://localhost:8023 \
WA_GITLAB_USERNAME=byteblaze \
WA_GITLAB_PASSWORD=hello1234 \
uv run python scripts/main_execution.py \
  --task-ids 44 \
  --experiment-name task44-v3-smoke \
  --hs 0 \
  --ks 1 \
  --planner-mode ollama \
  --model gemma4:26b
```

Ein reproduzierbarer H/k-Lauf auf dem Hard-Subset:

```bash
uv run python scripts/main_execution.py \
  --subset-name webarena-verified-hard \
  --experiment-name hk-agent-browsergym-planact-main-v02_basis_v3 \
  --hs 0 2 5 10 \
  --ks 0 2 5 10 \
  --planner-mode ollama \
  --model gemma4:26b \
  --max-steps 40 \
  --max-planner-calls 5
```

Der Runner schreibt:

```text
runs/hk-test/<experiment-name>/summary.csv
runs/hk-test/<experiment-name>/summary.json
runs/hk-test/<experiment-name>/experiment_config.json
runs/hk-test/<experiment-name>/selected_tasks.json
```

`runs/` ist bewusst ignoriert. Soll eine finale CSV hochgeladen werden, wird sie nach `thesis_results_output/data/final_summary.csv` kopiert.

## Finale Ergebnisse erzeugen

Die vorhandene finale CSV liegt bereits hier:

```text
thesis_results_output/data/final_summary.csv
```

Die Ergebnisaufbereitung erfolgt ueber:

```bash
env JUPYTER_PATH=.jupyter .venv/bin/python -m jupyter nbconvert \
  --to notebook \
  --execute notebooks/final_analysis.ipynb \
  --output final_analysis.executed.ipynb
```

Die finale CSV/JSON liegt unter `thesis_results_output/data/`. Exportierte Abbildungen liegen unter:

```text
thesis_results_output/figures/
```

## Schnellcheck

Ein schneller Syntax-/Importcheck ohne echten Browserlauf:

```bash
uv run python scripts/main_execution.py --task-ids 44 --experiment-name dry-run-check --dry-run
```

## Upload-Hinweis

Vor dem GitHub-Upload sollte `git status --short` nur die gewollten Quellcode-, Prompt-, Dokumentations- und Ergebnisdateien zeigen. Lokale Caches, historische Notebooks, grosse Run-Verzeichnisse und nicht finale Referenzimplementierungen sind ueber `.gitignore` ausgeschlossen.
