# H/k Capability- und Failure-Diagnostik

Diese Notiz beschreibt die neue Auswertungsschicht fuer die H/k-Agent-Runs.
Sie ersetzt nicht den offiziellen WebArena-Verified Score, sondern erklaert,
warum ein Run nahe dran war oder woran er gescheitert ist.

## Ziel

Die H/k-Frage soll nicht durch Executor-Grenzen verdeckt werden. Deshalb werden
Tasks jetzt vor und nach dem Run grob klassifiziert:

- `navigation`: reine Navigationsaufgaben
- `visible_retrieve`: sichtbare Retrieval-Aufgaben
- `structured_retrieve`: Aggregate, Reviews, mehrstufige Werte/Schemata
- `mutation`: Upvote, Fork, Commit, Kauf, Admin-Aenderungen
- `policy`: Aufgaben, bei denen eine nicht erlaubte Aktion erkannt werden muss

Fuer die eigentliche H/k-Hauptanalyse sind zunaechst `navigation` und
`visible_retrieve` am saubersten. Dort misst man eher Planungshorizont und
Validierungsintervall. `structured_retrieve`, `mutation` und `policy` werden
separat als Executor-/Robustheitsanalyse behandelt.

## Metriken

`official_success` und `official_score` bleiben die einzigen finalen
Benchmark-Metriken.

Zusaetzlich gibt es diagnostische Felder:

- `task_capability`
- `capability_tier`
- `diagnostic_completion`
- `failure_category`
- `failure_notes`
- `final_response_status`
- `final_action_kind`
- `num_executor_json_calls`
- `num_step_errors`
- `last_step_error`

`diagnostic_completion` ist nur eine heuristische Naehe-Schaetzung. Ein Wert
von `0.75` bedeutet nicht Benchmark-Erfolg, sondern z.B. "Daten wurden
zurueckgegeben, aber Schema/Wert passte nicht offiziell".

## Failure-Kategorien

Wichtige Kategorien:

- `official_success`: offizieller Erfolg
- `llm_json_or_action_parse_failure`: Modellantwort nicht parsebar
- `bad_route_or_not_found`: falsche Route oder 404
- `missing_retrieved_data`: Retrieve-Task ohne Daten beendet
- `schema_or_value_mismatch`: Daten vorhanden, aber offizielles Schema/Wert
  passt nicht
- `missing_required_mutation`: Mutate-Task beendet, aber keine offiziell
  beobachtete Mutation
- `missing_action_not_allowed`: Policy-Task ohne `ACTION_NOT_ALLOWED_ERROR`
- `step_budget_exhausted`: Schrittbudget ohne akzeptiertes Ergebnis verbraucht
- `loop_or_no_progress`: Runtime-Evaluator sah Loop/No-Progress

## Nutzung

Run nur fuer die Hauptanalyse-Capabilities:

```bash
uv run python scripts/run_hk_agent_experiment.py \
  --experiment-name hk-agent-main-analysis-smoke \
  --main-analysis-capabilities-only \
  --hs 0 2 5 \
  --ks 0 2 5 \
  --run-mode agent \
  --planner-model gemma4:26b \
  --executor-model gemma4:e4b \
  --max-planner-calls 3 \
  --max-steps 8 \
  --llm-timeout-seconds 600
```

Oder gezielt nach Tier filtern:

```bash
uv run python scripts/run_hk_agent_experiment.py \
  --experiment-name hk-agent-navigation-visible-retrieve \
  --capability-tiers navigation visible_retrieve \
  --hs 0 2 5 \
  --ks 0 2 5 \
  --run-mode agent \
  --planner-model gemma4:26b \
  --executor-model gemma4:e4b \
  --max-planner-calls 3 \
  --max-steps 8 \
  --llm-timeout-seconds 600
```

Nachtraegliche Failure-Analyse fuer ein Experiment:

```bash
uv run python scripts/analyze_hk_agent_failures.py \
  runs/hk-agent/hk-agent-browsergym-random-gemma4-smoke
```

Das schreibt:

- `failure_analysis.json`
- `failure_analysis.csv`
- pro Run ein `diagnostic.json`

Optionaler lokaler LLM-Judge fuer Erklaerungen:

```bash
uv run python scripts/analyze_hk_agent_failures.py \
  runs/hk-agent/hk-agent-browsergym-random-gemma4-smoke \
  --judge-mode ollama \
  --judge-model gemma4:26b
```

Der Judge darf nur erklaeren. Er darf `official_success` nicht ersetzen. Die
Ausgaben landen in Zusatzfeldern wie `judge_failure_reason` und
`judge_recommended_fix`.

## Methodische Einordnung

Die Diagnose ist bewusst sekundär:

```text
official_success = finale Benchmark-Wahrheit
diagnostic_completion = Erklaerung / Naehe / Fehlerklasse
```

Damit kann in der Arbeit gezeigt werden, ob ein H/k-Setting wirklich schlechter
plant oder ob der Executor an einer Aktionsklasse scheitert, die ausserhalb der
eigentlichen H/k-Frage liegt.
