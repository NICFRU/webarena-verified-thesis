# Experiment Setup Plan

## Leitidee

Nutze WebArena-Verified offiziell fuer Benchmark-Daten, Server/Demo-Workflows und Evaluation. Entwickle Planner, Validator, Controller, H/k-Logik und Auswertung im eigenen Thesis-Projekt.

## Empfohlene Ordnertrennung

```text
05_Code/
  README.md
  configs/
  docs/
  notebooks/
  scripts/
  runs/
  agentlab-results/
  external/
    webarena-verified/
```

- `05_Code`: eigene Thesis-Artefakte, Experimente, Scripts, Notebooks.
- `external/webarena-verified`: offizielles Repo nur als Referenz und fuer offizielle Demo-Workflows.
- `runs/`: generierte Zwischenartefakte, nicht versioniert.
- `agentlab-results/`: spaetere AgentLab-Resultate, nicht versioniert.

## Phase 1: Docker-Smoke-Test

Ziel: Nachweisen, dass die offizielle WebArena-Verified-CLI ueber Docker laeuft.

```bash
python scripts/run_docker_webarena_verified_smoke.py
```

Erwartete Artefakte:

- `runs/webarena_verified/webarena_verified_hard.json`
- `runs/webarena_verified/agent_input_task_108.json`
- `runs/webarena_verified/example_eval/` als Dry-Run-Zielpfad

Diese Phase braucht keine WebArena-Server und keinen Agenten.

## Phase 2: Offizielles Demo-Repo testen

Ziel: Einmal den offiziellen Demo-GitLab-Workflow nachvollziehen.

```bash
mkdir -p external
git clone https://github.com/ServiceNow/webarena-verified.git external/webarena-verified
cd external/webarena-verified
uv run invoke -r examples --list
uv run playwright install chromium
uv run invoke -r examples gitlab-start
```

In manchen Doku-Snippets wird der Task als `demo-gitlab-start` bezeichnet. Im aktuell geklonten Repo heisst der Invoke-Task `gitlab-start`.

Danach den Human-Agent-Demo-Run aus der offiziellen Doku ausfuehren und mit `webarena-verified eval-tasks` evaluieren. Ein Notebook fuer diesen Flow liegt unter `notebooks/02_official_demo_gitlab_uv.ipynb`.

Fuer einen leichten 10er-Test ohne Agenten wurden GitLab-Agent-Inputs exportiert:

```bash
cd external/webarena-verified
uv run webarena-verified agent-input-get \
  --sites gitlab \
  --config examples/configs/config.demo.json \
  --output output/gitlab_agent_inputs.json
```

Die ersten 10 Task-IDs in diesem Export waren: `44, 45, 46, 102, 103, 104, 105, 106, 132, 133`.

## Phase 3: Eigener Runner

Ziel: Im eigenen Projekt einen minimalen Runner bauen, der dieselbe Output-Struktur erzeugt, die `webarena-verified eval-tasks` erwartet.

Noch ohne H/k:

- Task laden.
- BrowserGym-Environment starten.
- Agent-Aktion ausfuehren.
- Trace und final response speichern.
- Evaluation per offizieller CLI oder Docker ausfuehren.

Die erwarteten Dateien sind in `docs/webarena_verified_cli_and_outputs.md` beschrieben. Wichtig sind vor der Evaluation vor allem `agent_response.json` und `network.har`.

Der erste konkrete Minimalrunner ist `scripts/run_gitlab_task44_navigate_runner.py`; das begleitende Notebook ist `notebooks/03_minimal_runner_task44.ipynb`.

Status: Der Runner wurde gegen Demo-GitLab Task 44 getestet und erreichte `score: 1.0`. Damit ist der Human-Agent fuer diese einfache Navigationsaufgabe durch eigenen Code ersetzt.

## Phase 3b: BrowserGym-Anschluss

Ziel: Den direkten Playwright-Zugriff durch BrowserGym ersetzen, aber weiterhin WebArena-Verified-Artefakte erzeugen.

Der erste BrowserGym-Runner ist `scripts/run_browsergym_gitlab_task44_runner.py`; das begleitende Notebook ist `notebooks/04_browsergym_gitlab_task44.ipynb`.

Dieser Runner nutzt `browsergym/openended`, fuehrt die Navigation als BrowserGym-Action aus und evaluiert anschliessend wieder mit WebArena-Verified.

Status: Der BrowserGym-Runner wurde gegen Demo-GitLab Task 44 getestet und erreichte `score: 1.0`.

## Phase 3c: Zweite Site als Probe

Ziel: Nicht sofort eine weitere Benchmark-Aufgabe loesen, sondern eine zweite WebArena-Verified-Site kontrolliert starten und mit BrowserGym oeffnen.

Der Site-Probe-Runner ist `scripts/run_browsergym_site_probe.py`; das begleitende Notebook ist `notebooks/05_other_site_browsergym_probe.ipynb`.

Empfohlene Reihenfolge:

- `shopping` oder `shopping_admin` als naechste Site verwenden.
- `wikipedia` und `map` erst spaeter testen, weil sie Daten-Setup benoetigen.
- Erst wenn BrowserGym die Site sauber oeffnet, einen kleinen scripted Agent fuer einen konkreten Task bauen.

## Phase 4: H/k-Prototyp

Ziel: Nur die Prozesslogik ergaenzen, nicht den Benchmark veraendern.

Zu loggen:

- `h`
- `k`
- `num_replans`
- `num_no_progress_events`
- `num_invalid_actions`
- `total_steps`
- `total_runtime_ms`
- `total_tokens`
- `success`
- `abort_reason`

## Entscheidung

WebArena-Verified bleibt die offizielle Bewertungsinstanz. Dein Experiment kontrolliert nur, wie der Agent handelt und was zusaetzlich geloggt wird.
