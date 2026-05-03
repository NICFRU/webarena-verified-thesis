# WebArena-Verified CLI und Output-Dateien

## Warum `docker run --rm` funktioniert, obwohl kein Container laeuft

`docker run --rm ghcr.io/servicenow/webarena-verified:latest ...` startet jedes Mal kurz einen Container, fuehrt die WebArena-Verified-CLI aus und beendet den Container danach wieder. Durch `--rm` wird der Container direkt geloescht.

Das ist normal. Fuer CLI-Befehle wie `agent-input-get`, `dataset-get`, `subset-export` und viele `eval-tasks`-Faelle brauchst du keinen dauerhaft laufenden Webserver-Container.

## Image vs. laufender Webserver

- `ghcr.io/servicenow/webarena-verified:latest`: CLI-Image fuer Dataset, Task-Export, Evaluation und Submission-Verarbeitung.
- `wa-demo-gitlab`: Demo-GitLab-Container, der eine echte Website unter `http://localhost:8012` bereitstellt.

CLI-Beispiel:

```bash
docker run --rm ghcr.io/servicenow/webarena-verified:latest --help
```

Demo-GitLab starten:

```bash
cd external/webarena-verified
uv run invoke -r examples gitlab-start
```

Demo-GitLab stoppen:

```bash
uv run invoke -r examples gitlab-stop
```

## `agent-input-get`

`agent-input-get` erzeugt die Eingabedaten, die ein Agent fuer eine Aufgabe braucht:

- `task_id`
- `intent_template_id`
- `sites`
- `start_urls`
- `intent`

Beispiel fuer GitLab-Demo-Tasks:

```bash
docker run --rm \
  -v "$PWD:/workspace" \
  ghcr.io/servicenow/webarena-verified:latest \
  agent-input-get \
    --task-ids 44,45,46 \
    --config /workspace/examples/configs/config.demo.json \
    --output /workspace/output/tasks.json
```

Task 44 sieht danach z. B. so aus:

```json
{
  "sites": ["gitlab"],
  "task_id": 44,
  "intent_template_id": 303,
  "start_urls": ["http://localhost:8012"],
  "intent": "Open my todos page"
}
```

Das bedeutet: Der Agent startet bei `http://localhost:8012` und muss die Todos-Seite oeffnen. Manuell ist das in GitLab typischerweise `http://localhost:8012/dashboard/todos`.

## Warum `task-ids 1,2,3` mit `config.demo.json` Warnungen erzeugen

`config.demo.json` enthaelt nur GitLab:

```json
{
  "environments": {
    "__GITLAB__": {
      "urls": ["http://localhost:8012"]
    }
  }
}
```

Tasks `1,2,3` gehoeren aber zu `SHOPPING_ADMIN`. Deshalb kann WebArena-Verified diese URLs nicht mit Demo-GitLab rendern und meldet:

```text
Sites ['SHOPPING_ADMIN'] not found in environments. Using template URLs.
```

Das ist kein Docker-Fehler. Es heisst nur: Die Config passt nicht zu diesen Tasks. Fuer die Demo-GitLab-Config zuerst GitLab-Tasks wie `44,45,46` verwenden.

## `agent_response.json`

`agent_response.json` ist die finale Antwort des Agenten fuer eine Aufgabe. Sie ist besonders wichtig fuer `RETRIEVE`-Tasks, bei denen der Agent Daten aus der Website extrahieren muss.

Beispiel aus Task 108:

```json
{
  "task_type": "RETRIEVE",
  "status": "SUCCESS",
  "retrieved_data": [
    { "month": "Jan", "count": 12 },
    { "month": "Feb", "count": 7 }
  ],
  "error_details": null
}
```

Der Evaluator normalisiert diese Antwort und vergleicht sie mit der erwarteten Loesung.

Fuer spaetere Agenten bedeutet das: Dein Runner muss am Ende eine valide `agent_response.json` pro Task schreiben.

## `network.har`

`network.har` ist ein Netzwerk-Trace des Browser-Runs. HAR steht fuer HTTP Archive. Darin stehen Requests, Responses, URLs, Statuscodes und Timing-Informationen.

WebArena-Verified nutzt diesen Trace fuer Aufgaben, bei denen die Bewertung ueber Seitenzustand, Navigation oder beobachtete Netzwerkereignisse laeuft. In den Beispiel-Logs sieht man auch, dass der Evaluator daraus teilweise Basis-URLs rekonstruiert.

Fuer spaetere Agenten bedeutet das: Dein Browser-Runner muss pro Task einen HAR-Trace speichern, damit `eval-tasks` die Aufgabe bewerten kann.

## `eval_result.json`

`eval_result.json` ist das Ergebnis der Bewertung fuer einen Task. Es enthaelt u. a.:

- `task_id`
- `status`
- `score`
- `evaluators_results`
- Checksums fuer Version und Datenstand

Beispiel: Task 108 bekam `score: 1.0` und `status: success`.

## Minimaler Output-Ordner pro Task

Fuer eine spaetere Evaluation sollte dein Runner pro Task mindestens diese Struktur erzeugen:

```text
output/demo-run/
  44/
    agent_response.json
    network.har
    eval_result.json        # entsteht nach eval-tasks
```

Vor der Evaluation brauchst du mindestens:

```text
agent_response.json
network.har
```

`eval_result.json` wird von WebArena-Verified geschrieben.

## Wann AgentLab/BrowserGym anschliessen?

Du kannst jetzt mit BrowserGym/AgentLab anfangen, aber erst als naechsten Schritt nach dem Human-Agent-Demo-Test. Die Reihenfolge sollte sein:

1. `agent-input-get` fuer GitLab-Demo-Tasks funktioniert.
2. Demo-GitLab laeuft unter `http://localhost:8012`.
3. Task 44 wird einmal manuell mit dem offiziellen Human-Agent geloest.
4. Du siehst danach die erzeugten Dateien im Output-Ordner.
5. Erst dann baust du einen eigenen Runner oder AgentLab/BrowserGym-Runner, der dieselbe Dateistruktur erzeugt.

