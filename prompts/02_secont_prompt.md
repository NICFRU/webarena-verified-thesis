# Codex-Prompt: Minimaler WebArena-Verified / AgentLab / BrowserGym Durchstich

Du bist mein Coding Assistant für meine Masterarbeit zu LLM-basierten Webagenten.

## Projektpfad

Arbeite in folgendem lokalen Ordner:

```text
/Users/niclascramer/Privat/Uni/Uni-Reutlingen/Masterarbeit/05_Code
```

## Offizielle Grundlagen

Zielbenchmark:

```text
https://github.com/ServiceNow/webarena-verified
```

WebArena-Verified-Doku:

```text
https://servicenow.github.io/webarena-verified/v1.2.3/
```

BrowserGym:

```text
https://github.com/ServiceNow/BrowserGym
```

AgentLab:

```text
https://github.com/ServiceNow/AgentLab
```

## Kontext meiner Thesis

Ich untersuche in einem kontrollierten Benchmark-Experiment den Einfluss von:

- `H` = Planungshorizont
- `k` = Validierungsintervall

auf:

- Success Rate
- Tokenverbrauch
- API-Kostenproxy
- Runtime
- Replans
- Loops
- No-Progress-Events
- Invalid Actions

Der finale Benchmark soll **WebArena-Verified** sein. Die technische Durchführung soll möglichst über **BrowserGym/AgentLab** erfolgen.

Wichtig: Baue jetzt noch **nicht** das vollständige H/k-Experiment. Ich brauche zuerst eine minimale, nachvollziehbare Demo, mit der ich WebArena-Verified bzw. die dafür nötige BrowserGym-/AgentLab-Struktur lokal testen kann.

## Ausgangslage

- Der Projektordner enthält aktuell nur `prompts/01_initial prompt.md`.
- Es ist noch kein Git-Repo.
- Aktuell läuft Python `3.13.5`.
- AgentLab benötigt laut vorheriger Prüfung Python `3.11` oder `3.12`.
- Bitte keine globale Python-Installation verändern.
- Falls Python `3.12` lokal verfügbar ist, darfst du eine `.venv` im Projektordner anlegen.
- Falls Python `3.12` nicht verfügbar ist, erstelle trotzdem die Projektdateien und dokumentiere die Setup-Schritte.

## Ziel dieses Minimaldurchstichs

Ich möchte am Ende eine kleine Projektstruktur haben, die Folgendes ermöglicht:

1. WebArena-Verified als Zielbenchmark dokumentieren.
2. Prüfen, ob `webarena-verified` und `browsergym-webarena-verified` installiert werden können.
3. Eine `.env.example` bzw. Beispiel-Config für WebArena-Verified erzeugen.
4. Einen minimalen Smoke-Test vorbereiten:
   - bevorzugt WebArena-Verified, falls die nötigen Environment-URLs vorhanden sind;
   - sonst Fallback auf MiniWoB oder einfachen BrowserGym-Smoke-Test, damit AgentLab/BrowserGym grundsätzlich getestet werden kann.
5. Einen einfachen Result-/Trace-Pfad dokumentieren.
6. Eine vorbereitete Summary-Datei oder ein Summary-Script anlegen, das später um `H`, `k` und Prozessmetriken erweitert werden kann.
7. Dokumentieren, was als Nächstes nötig ist, um WebArena-Verified tatsächlich vollständig laufen zu lassen.

## Scope-Begrenzung

Bitte implementiere jetzt **nicht**:

- vollständigen Planner
- vollständigen Evaluator
- vollständigen Controller
- Replanning-Logik
- H/k-Faktorexperiment
- parallele Studien
- LLM-as-Judge
- statistische Auswertung
- komplette WebArena-Serverbereitstellung, falls sie lokal noch nicht existiert

Es geht nur um eine Minimal-Demo und saubere Setup-Dokumentation.

## Bitte erstelle diese Projektstruktur

```text
05_Code/
  README.md
  .gitignore
  requirements.txt
  configs/
    webarena_verified_config.example.json
    minimal_demo.env.example
  scripts/
    check_setup.py
    run_webarena_verified_smoke.py
    run_agentlab_smoke.py
    inspect_results.py
  docs/
    webarena_verified_setup.md
    minimal_smoke_test.md
  prompts/
    01_initial prompt.md
```

Falls du die Struktur anpassen musst, erkläre kurz warum.

---

## Anforderungen im Detail

### 1. Git und Grundstruktur

- Initialisiere ein Git-Repo, falls noch keines existiert.
- Erstelle `.gitignore` für:
  - `.venv/`
  - `__pycache__/`
  - `.env`
  - `runs/`
  - `results/`
  - `agentlab-results/`
  - `.DS_Store`

### 2. `requirements.txt`

Erstelle eine `requirements.txt`, die sich an den offiziellen Paketen orientiert.

Sie soll mindestens vorbereiten:

- `agentlab`
- `browsergym`
- `browsergym-webarena-verified`
- `python-dotenv`
- `pandas`

Falls `webarena-verified` laut offizieller Doku aus GitHub installiert werden muss, ergänze eine passende pip-Zeile, z. B.:

```text
git+https://github.com/ServiceNow/webarena-verified
```

Bitte kommentiere in der Doku, dass WebArena-Verified aktiv entwickelt wird und die Installation ggf. angepasst werden muss.

### 3. Setup-Check-Script

Erstelle `scripts/check_setup.py`.

Das Script soll prüfen:

- Python-Version
- ob `agentlab` importierbar ist
- ob `browsergym` importierbar ist
- ob `browsergym.webarena_verified` importierbar ist
- ob `webarena_verified` importierbar ist
- ob relevante Environment-Variablen gesetzt sind:
  - `AGENTLAB_EXP_ROOT`
  - `WA_SHOPPING`
  - `WA_SHOPPING_ADMIN`
  - `WA_REDDIT`
  - `WA_GITLAB`
  - `WA_WIKIPEDIA`
  - `WA_MAP`
  - `WA_HOMEPAGE`

Die Ausgabe soll klar anzeigen:

- `OK`
- `fehlt`
- `optional`
- `nächster Schritt`

Das Script soll nicht abbrechen, wenn WebArena-URLs fehlen. Es soll stattdessen erklären, dass dann nur der Fallback-Smoke-Test möglich ist.

### 4. WebArena-Verified Beispiel-Config

Erstelle `configs/webarena_verified_config.example.json`.

Die Datei soll eine Vorlage enthalten, z. B.:

```json
{
  "environments": {
    "__SHOPPING__": {
      "urls": ["http://localhost:7770"]
    },
    "__SHOPPING_ADMIN__": {
      "urls": ["http://localhost:7780/admin"]
    },
    "__REDDIT__": {
      "urls": ["http://localhost:9999"]
    },
    "__GITLAB__": {
      "urls": ["http://localhost:8012"],
      "credentials": {
        "username": "root",
        "password": "CHANGE_ME"
      }
    },
    "__WIKIPEDIA__": {
      "urls": ["http://localhost:8888/wikipedia_en_all_maxi_2022-05/A/User:The_other_Kiwix_guy/Landing"]
    },
    "__MAP__": {
      "urls": ["http://localhost:3000"]
    },
    "__HOMEPAGE__": {
      "urls": ["http://localhost:4399"]
    }
  }
}
```

Wenn du anhand der Doku bessere Platzhalter findest, nutze diese. Bitte keine echten Passwörter oder Secrets eintragen.

### 5. `minimal_demo.env.example`

Erstelle `configs/minimal_demo.env.example` mit Variablen:

```bash
AGENTLAB_EXP_ROOT=./agentlab-results

WA_SHOPPING=todo
WA_SHOPPING_ADMIN=todo
WA_REDDIT=todo
WA_GITLAB=todo
WA_WIKIPEDIA=todo
WA_MAP=todo
WA_HOMEPAGE=todo

# Optional:
PW_EXTRA_HEADERS=
```

### 6. WebArena-Verified Smoke Script

Erstelle `scripts/run_webarena_verified_smoke.py`.

Das Script soll:

- prüfen, ob WebArena-Verified importierbar ist;
- prüfen, ob eine Config-Datei angegeben wurde;
- beispielhaft versuchen, Task-Daten für eine kleine Auswahl zu laden oder den entsprechenden CLI-Befehl dokumentiert auszugeben;
- falls keine echten URLs vorhanden sind, verständlich abbrechen und erklären, was fehlt;
- keine große Benchmark-Ausführung starten;
- keine H/k-Logik implementieren.

Wenn es sinnvoller ist, nur einen CLI-Befehl zu erzeugen, gib diesen aus, z. B.:

```bash
webarena-verified agent-input-get --task-ids 1 --config configs/webarena_verified_config.example.json --output runs/webarena_verified/tasks.json
```

### 7. AgentLab/BrowserGym Fallback-Smoke-Test

Erstelle `scripts/run_agentlab_smoke.py`.

Das Script soll:

- AgentLab verwenden, falls installiert;
- einen kleinen Benchmark starten, z. B. `miniwob_tiny_test`, falls verfügbar;
- `n_jobs=1` verwenden;
- möglichst einen vorhandenen einfachen Agenten verwenden;
- keine WebArena-Server voraussetzen;
- am Ende ausgeben:
  - verwendeter Benchmark
  - verwendeter Agent
  - Result-Pfad
  - Hinweis auf `agentlab-xray` oder AgentLab-Result-Inspection

Wenn ein API-Key nötig wäre, soll das Script sauber abbrechen und erklären, welche Variable fehlt. Wenn ein nicht-API-basierter Beispielagent verfügbar ist, nutze diesen bevorzugt.

### 8. Result-Inspection

Erstelle `scripts/inspect_results.py`.

Das Script soll:

- einen Pfad zu Results entgegennehmen;
- versuchen, AgentLab-Results zu laden;
- falls das nicht geht, wenigstens Verzeichnisstruktur und relevante Dateien anzeigen;
- eine einfache Übersicht ausgeben.

### 9. Minimal-Summary für meine Thesis vorbereiten

Wenn möglich, soll eines der Scripts eine Datei erzeugen:

```text
runs/minimal_summary.json
```

mit Struktur:

```json
{
  "benchmark": null,
  "task_id": null,
  "agent_name": null,
  "h": null,
  "k": null,
  "success": null,
  "total_steps": null,
  "total_runtime_ms": null,
  "total_tokens": null,
  "num_invalid_actions": 0,
  "num_replans": 0,
  "num_no_progress_events": 0,
  "abort_reason": null,
  "result_path": null
}
```

Für Felder, die im Minimaldurchstich noch nicht verfügbar sind, setze `null` oder `0`.

### 10. Dokumentation

Erstelle `docs/webarena_verified_setup.md` mit:

- Warum WebArena-Verified als finaler Benchmark verwendet wird.
- Unterschied zwischen:
  - WebArena-Verified = Benchmark/Evaluation
  - BrowserGym = Environment Interface
  - AgentLab = Experiment Runner
- Python-Version
- Installationsschritte
- notwendige Environment-URLs
- Beispiel-Config
- Beispielbefehle:
  - Setup-Check
  - WebArena-Verified Task Input Export
  - Fallback AgentLab Smoke Test
- offene Punkte:
  - WebArena-Server bereitstellen
  - Credentials setzen
  - eigene Agentenlogik integrieren
  - H/k-Logging ergänzen

Erstelle `docs/minimal_smoke_test.md` mit:

- Zweck des Smoke Tests
- Startbefehle
- erwartete Outputs
- Troubleshooting
- nächste Schritte:
  1. AgentLab-Smoke-Test erfolgreich ausführen
  2. WebArena-Verified Config vervollständigen
  3. einzelne WebArena-Verified Task testen
  4. eigenen AgentArgs-Prototyp mit `h` und `k`
  5. Planner-Stub
  6. Evaluator-Stub
  7. Controller/Reason Codes
  8. Pilotexperiment

### 11. `README.md`

Erstelle eine kurze README mit:

- Projektzweck
- Zielbenchmark WebArena-Verified
- technische Schicht BrowserGym/AgentLab
- Setup-Kurzbefehle
- Hinweis, dass dies nur ein Minimaldurchstich ist
- Hinweis, dass das spätere Experiment `H` und `k` untersucht

---

## Ausführung

Bitte führe anschließend aus, soweit möglich:

1. `python scripts/check_setup.py`
2. Falls Python/Dependencies passen: Fallback-Smoke-Test mit AgentLab
3. Falls WebArena-Verified-Config fehlt: nicht scheitern, sondern dokumentieren

---

## Abschlussbericht

Berichte am Ende:

- welche Dateien erstellt/geändert wurden;
- ob Git initialisiert wurde;
- ob Python 3.12 verfügbar war;
- ob Dependencies installiert wurden;
- Ergebnis von `check_setup.py`;
- ob der AgentLab-Smoke-Test ausgeführt werden konnte;
- ob WebArena-Verified direkt testbar war;
- welche konkreten nächsten Schritte ich ausführen muss.

## Wichtiger Hinweis

WebArena-Verified direkt zu testen ist nur möglich, wenn die WebArena-Instanzen/URLs korrekt laufen. Deshalb soll diese Minimal-Demo WebArena-Verified als Ziel einrichten, aber einen AgentLab/MiniWoB-Smoke-Test als Fallback erlauben. Ziel ist: erst Toolchain testen, dann WebArena-Verified vollständig anbinden.
