# Minimal Smoke Test

## Zweck

Der Minimaldurchstich prueft zuerst die lokale Toolchain und Projektstruktur. Er startet keinen vollstaendigen WebArena-Verified-Benchmark und implementiert noch keine `H`/`k`-Logik.

## Startbefehle

```bash
source .venv/bin/activate
python scripts/check_setup.py
```

Optional, wenn Dependencies installiert sind:

```bash
python scripts/run_agentlab_smoke.py
python scripts/run_webarena_verified_smoke.py --config configs/webarena_verified_config.example.json --task-id 108
```

Docker-basierter WebArena-Verified-Check ohne lokale WebArena-Verified-Installation:

```bash
docker run --rm ghcr.io/servicenow/webarena-verified:latest --help
docker run --rm ghcr.io/servicenow/webarena-verified:latest subsets-ls
docker run --rm -v "$PWD:/workspace" ghcr.io/servicenow/webarena-verified:latest subset-export --name webarena-verified-hard --output /workspace/runs/webarena_verified/webarena_verified_hard.json
docker run --rm -v "$PWD:/workspace" ghcr.io/servicenow/webarena-verified:latest agent-input-get --task-ids 108 --config /workspace/configs/webarena_verified_config.example.json --output /workspace/runs/webarena_verified/agent_input_task_108.json
docker run --rm -v "$PWD:/workspace" ghcr.io/servicenow/webarena-verified:latest eval-tasks --task-ids 108 --output-dir /workspace/runs/webarena_verified/example_eval --config /workspace/configs/webarena_verified_config.example.json --dry-run
```

Resultate ansehen:

```bash
python scripts/inspect_results.py runs/minimal_summary.json
python scripts/inspect_results.py agentlab-results/minimal_smoke
```

## Erwartete Outputs

- `check_setup.py` zeigt `OK`, `fehlt`, `optional` und `naechster Schritt` pro Komponente.
- Bei fehlenden WebArena-URLs bricht der WebArena-Smoke-Test sauber ab und schreibt trotzdem `runs/minimal_summary.json`.
- Der AgentLab-Fallback prueft, ob AgentLab und BrowserGym importierbar sind, und startet `browsergym/openended` ohne LLM-Key.
- Der Docker-Workflow exportiert das Hard-Subset und Agent-Input-Dateien, startet aber ohne vorhandene Agent-Run-Logs nur eine Dry-Run-Evaluation.

## Troubleshooting

- Python ist 3.13: Eine lokale Python-3.12-venv verwenden.
- `browsergym.webarena_verified` fehlt: `pip install -r requirements.txt` in der passenden venv ausfuehren.
- Playwright/Chromium fehlt: `playwright install chromium` ausfuehren.
- Chromium bricht in der Sandbox mit `TargetClosedError` ab: den Smoke-Test ausserhalb der Sandbox bzw. normal im Terminal starten.
- WebArena-URLs fehlen: `.env` aus `configs/minimal_demo.env.example` erstellen und echte Instanzen eintragen.
- WebArena-Verified laeuft nicht: zuerst `webarena-verified --help` und `webarena-verified dataset-get --output runs/webarena_verified/dataset.json` testen.
- Docker hat keinen Daemon-Zugriff: Docker Desktop starten und den Befehl im normalen Terminal wiederholen.

## Naechste Schritte

1. AgentLab-Smoke-Test erfolgreich ausfuehren.
2. WebArena-Verified Config vervollstaendigen.
3. Einzelne WebArena-Verified Task testen.
4. Eigenen AgentArgs-Prototyp mit `h` und `k` vorbereiten.
5. Planner-Stub erstellen.
6. Evaluator-Stub erstellen.
7. Controller/Reason Codes ergaenzen.
8. Pilotexperiment starten.
