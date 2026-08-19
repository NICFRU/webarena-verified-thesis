# WebArena-Verified Setup

## Warum WebArena-Verified?

WebArena-Verified ist der Zielbenchmark fuer das spaetere Thesis-Experiment, weil er Web-Agent-Aufgaben mit ueberarbeiteten Task-Definitionen, deterministischen Evaluatoren und reproduzierbarer Auswertung verbindet. Das passt zu einem kontrollierten Vergleich von Planungshorizont `H` und Validierungsintervall `k`, ohne schon im Minimaldurchstich die komplette Experimentlogik zu bauen.

## Schichten

- WebArena-Verified: Benchmark, Task-Daten und Evaluation.
- BrowserGym: Environment Interface fuer Browser-basierte Agentenaufgaben.
- AgentLab: Experiment Runner, Result-Struktur und spaetere Inspektion.

## Python-Version

Empfohlen ist Python 3.12 in einer lokalen `.venv`. WebArena-Verified selbst dokumentiert Python 3.11+, die BrowserGym-WebArena-Verified-Paketierung kann aber Python 3.12 voraussetzen.

Auf diesem Rechner wurde Python 3.12 per Homebrew installiert:

```bash
brew install python@3.12
/opt/homebrew/bin/python3.12 --version
```

Die globale `python3`-Version muss dafuer nicht umgebogen werden. Die Projekt-venv wird explizit mit Python 3.12 erstellt:

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

Falls `python3.12` nicht verfuegbar ist, erst Python 3.12 lokal installieren oder mit einer isolierten Toolchain wie `uv` arbeiten. Python 3.11 kann fuer Teile funktionieren, ist fuer `browsergym-webarena-verified` aber eventuell nicht ausreichend.

## Docker-Workflow fuer WebArena-Verified

WebArena-Verified kann fuer Benchmark-Daten, Subsets, Agent-Input-Export und Evaluation der vorhandenen Agent-Outputs direkt per Docker genutzt werden. Das reduziert den lokalen Python-Bedarf fuer reine WebArena-Verified-CLI-Schritte.

Getesteter Help-Befehl:

```bash
docker run --rm ghcr.io/servicenow/webarena-verified:latest --help
```

Die CLI im Container stellt unter anderem diese Befehle bereit:

- `dataset-get`
- `agent-input-get`
- `subset-export`
- `subsets-ls`
- `eval-tasks`
- `create-submission-pkg`
- `env`

Verfuegbare Subsets pruefen:

```bash
docker run --rm ghcr.io/servicenow/webarena-verified:latest subsets-ls
```

Im Test waren verfuegbar:

- `webarena-verified-hard` mit 258 Tasks
- `webarena-verified-non-hard` mit 554 Tasks

Hard-Subset exportieren:

```bash
docker run --rm \
  -v "$PWD:/workspace" \
  ghcr.io/servicenow/webarena-verified:latest \
  subset-export \
  --name webarena-verified-hard \
  --output /workspace/runs/webarena_verified/webarena_verified_hard.json
```

Agent-Input fuer einen einzelnen Task exportieren:

```bash
docker run --rm \
  -v "$PWD:/workspace" \
  ghcr.io/servicenow/webarena-verified:latest \
  agent-input-get \
  --task-ids 108 \
  --config /workspace/configs/webarena_verified_config.example.json \
  --output /workspace/runs/webarena_verified/agent_input_task_108.json
```

Beispiel-Evaluation trocken vorbereiten:

```bash
docker run --rm \
  -v "$PWD:/workspace" \
  ghcr.io/servicenow/webarena-verified:latest \
  eval-tasks \
  --task-ids 108 \
  --output-dir /workspace/runs/webarena_verified/example_eval \
  --config /workspace/configs/webarena_verified_config.example.json \
  --dry-run
```

Im Container wurden keine separaten Beispiel-Agent-Run-Logs gefunden. Deshalb ist `--dry-run` aktuell die saubere Vorbereitung; eine echte Evaluation braucht vorher Agent-Outputs im erwarteten Output-Verzeichnis.

## Was laeuft ueber Docker?

- WebArena-Verified CLI-Hilfe und Version pruefen.
- Offizielle Dataset- und Subset-Daten abfragen.
- Hard-/Non-Hard-Subsets exportieren.
- Agent-Inputs mit gerenderten URLs exportieren.
- Evaluation vorbereiten oder ausfuehren, sobald Agent-Run-Logs vorhanden sind.
- Submission-Pakete aus vorhandenen Outputs erstellen.

## Was braucht weiterhin Python/AgentLab lokal?

- BrowserGym-Environments tatsaechlich starten.
- AgentLab als Experiment Runner verwenden.
- MiniWoB/OpenEnded-Fallback-Smoke-Test ohne WebArena-Server ausfuehren.
- Eigene Agentenlogik, spaeter `H`/`k`-Steuerung und Metrik-Logging entwickeln.
- Playwright/Chromium lokal fuer BrowserGym starten.

## Environment-URLs

Die folgenden Variablen werden spaeter fuer echte WebArena-Verified-Runs gebraucht:

```bash
AGENTLAB_EXP_ROOT=./agentlab-results
WA_SHOPPING=http://localhost:7770
WA_SHOPPING_ADMIN=http://localhost:7780/admin
WA_REDDIT=http://localhost:9999
WA_GITLAB=http://localhost:8012
WA_WIKIPEDIA=http://localhost:8888/wikipedia_en_all_maxi_2022-05/A/User:The_other_Kiwix_guy/Landing
WA_HOMEPAGE=http://localhost:4399
```

Kopiere dafuer `configs/minimal_demo.env.example` nach `.env` und ersetze `todo` durch echte lokale oder erreichbare Instanzen.

Hinweis: `map` wird in der ersten lokalen Experimentalversion nicht verwendet. Die Umgebung benoetigt sehr grosse Datenarchive und zusaetzlich entpackte Docker-Volumes; der Speicherbedarf ist fuer das aktuelle lokale Setup zu hoch.

## Beispiel-Config

Die Vorlage liegt unter `configs/webarena_verified_config.example.json`. Sie enthaelt nur Platzhalter und keine Secrets. GitLab-Credentials muessen fuer echte Runs separat gesetzt werden.

## Beispielbefehle

Setup pruefen:

```bash
python scripts/check_setup.py
```

WebArena-Verified Dataset vorbereiten:

```bash
webarena-verified dataset-get --output runs/webarena_verified/dataset.json
```

Oder per Docker:

```bash
docker run --rm -v "$PWD:/workspace" ghcr.io/servicenow/webarena-verified:latest dataset-get --output /workspace/runs/webarena_verified/dataset.json
```

Einzelnen Task evaluieren, sobald Config, Agent-Logs und URLs passen:

```bash
webarena-verified eval-tasks --task-ids 108 --config configs/webarena_verified_config.example.json --output-dir runs/webarena_verified/smoke
```

Fallback-Smoke-Test fuer die Toolchain:

```bash
python scripts/archive/legacy_runners/run_agentlab_smoke.py
```

Resultate inspizieren:

```bash
python scripts/archive/legacy_runners/inspect_results.py runs/minimal_summary.json
python scripts/archive/legacy_runners/inspect_results.py agentlab-results/minimal_smoke
```

## Offene Punkte

- WebArena-Server bereitstellen oder offizielle Container/CLI-Startbefehle nutzen.
- Environment-URLs und Credentials setzen.
- AgentLab-Beispielagenten und passende Benchmark-Namen in der installierten Version pruefen.
- Eigene Agentenlogik integrieren.
- Logging fuer `H`, `k`, Replans, Loops, No-Progress-Events und Invalid Actions ergaenzen.

WebArena-Verified und die BrowserGym-Integration werden aktiv weiterentwickelt. Die Installation kann sich daher aendern; bei Konflikten zuerst die offiziellen Repositories und Docs pruefen.
