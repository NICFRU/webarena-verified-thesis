# Saubere H/k Architektur fuer WebArena-Verified Hard

## Summary

Die neue Architektur trennt den bisherigen Task-44-Prototyp von der eigentlichen
H/k-Experimentpipeline. WebArena-Verified hat 812 registrierte Tasks insgesamt;
die Primaeranalyse nutzt den WebArena-Verified Hard Subset mit 258 Tasks.

Die Implementierung laeuft zunaechst als neue Spur unter `scripts/hk_agent/`.
Alte Prototypen bleiben bis zu einem erfolgreichen BrowserGym-Verified-Smoke
unveraendert und werden danach archiviert, nicht geloescht.

## Zielarchitektur

- `runner.py`: H/k Loop, BrowserGym-Task-Ausfuehrung, Stop- und Budgetlogik.
- `task_loader.py`: Hard-Subset laden, Task-Auswahl validieren, Gym IDs im
  Format `browsergym/webarena_verified.{intent_template_id}.{task_id}.{revision}`
  bauen.
- `runtime_evaluator.py`: Runtime-/Progress-Evaluator fuer Replanning und
  Prozessmetriken, ohne offiziellen Success-Anspruch.
- `official_evaluator.py`: WebArena-Verified `eval-tasks` als einzige Quelle
  fuer `official_score` und `official_success`.
- `artifacts.py`: strukturierte Artefakte, Laufzeittracking, Tokens, Replans,
  No-Progress, Invalid Actions, HAR und Agent Response.

## Schnittstellen und Metriken

Run-Modi:

- `agent`: fairer Modus ohne Eval-Metadaten, Gold-URLs oder Target-Hints im
  Planner/Executor.
- `oracle_debug`: Debug-Modus mit Eval-/Target-Hints.
- `analysis`: keine Agent-Ausfuehrung, nur bestehende Artefakte und Official
  Eval auswerten.

Summary-Felder:

- Official: `official_score`, `official_success`, `official_eval_status`
- Runtime: `runtime_progress_score`, `runtime_replans`,
  `runtime_no_progress_events`, `runtime_invalid_actions`,
  `runtime_loop_events`
- Kosten/Prozess: `total_tokens`, `planner_tokens`, `executor_tokens`,
  `total_runtime_ms`, `planner_calls`, `executor_calls`

Definitionen:

- `H=0`: vollstaendiger Plan.
- `H>0`: Planner gibt nur die naechsten `H` Subgoals aus.
- `k`: Runtime-Evaluator laeuft nach jeweils `k` ausgefuehrten Browser-Aktionen.

## Meilensteine

1. Diese Plan-Datei erstellen.
2. Hard-Subset-Loader und BrowserGym-ID-Aufloesung implementieren.
3. Single-Task Runner mit BrowserGym-Verified statt `browsergym/openended`
   implementieren.
4. Executor auf allgemeines Grounding umstellen: sichtbare Links/Buttons,
   DOM-/AX-Kandidaten, No-op-/Action-Failure-Rueckmeldung.
5. Notebook, Markdown-Dokumente und Prompts auf Runtime Evaluator, Official
   Evaluator, H, k, Trajectory und Utility ausrichten.

## First Smoke

Tasks:

- `44`: kurz, GitLab Navigate, "Open my todos page"
- `157`: mittel, Shopping Admin Navigate, "View the details of all customers"
- `105`: laenger, GitLab Navigate, filtered issue list

Zusaetzliche Cross-Site-Beispiele fuer Notebook-Smokes:

- `27`: Reddit Retrieve, nicht im Hard Subset
- `118`: Shopping Navigate, nicht im Hard Subset

Diese Zusatzbeispiele muessen explizit mit `--allow-non-hard-task-ids`
aktiviert werden, damit die Hauptanalyse weiterhin Hard-only bleibt.

Konfiguration:

- `--run-mode agent`
- `--hs 0 1 2`
- `--ks 1 2`
- Planner: `gemma4:26b`
- Executor: `gemma4:e4b`
- Official Eval immer nachgelagert.

Erfolgskriterien:

- BrowserGym-Verified Tasks starten ueber registrierte Gym IDs.
- Jeder Run erzeugt `network.har`, `agent_response.json`, `run_summary.json`
  und JSONL-Traces.
- Official Score und Runtime-Metriken sind getrennt sichtbar.
- Kein hardcodierter Target-Hint im Agent-Modus.

## H/k Evaluation Strategy

- Smoke: `H=[0,1,2]`, `k=[1,2]`
- Pilot: `H=[0,1,2,4]`, `k=[1,2,4]`
- Hauptanalyse: beste Kandidaten aus dem Pilot, um Kosten und Laufzeit zu
  kontrollieren.

Zielgroessen:

- Effektivitaet: `official_success`, `official_score`
- Effizienz: Tokens, Runtime, optional Kostenproxy
- Prozessqualitaet: Replans, Loops, No-Progress, Invalid Actions, Abort Reasons
- Utility: `Success - lambda_tok * Tokens - lambda_time * Time`

## Quellen

- WebArena-Verified Hard:
  https://servicenow.github.io/webarena-verified/latest/getting_started/hard_subset/
- BrowserGym WebArena-Verified Task IDs:
  https://github.com/ServiceNow/BrowserGym/blob/main/browsergym/webarena_verified/README.md
