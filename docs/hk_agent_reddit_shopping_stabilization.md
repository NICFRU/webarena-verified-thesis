# H/k Agent Stabilisierung fuer Reddit und Shopping

Diese Notiz dokumentiert die Anpassungen, die noetig waren, damit der
H/k Planner-Executor-Agent auf WebArena-Verified/BrowserGym nicht nur
semantisch richtig handelt, sondern auch die offiziellen Evaluatoren korrekt
bedient. Der zentrale Punkt: Viele Fehlversuche waren keine reinen
LLM-Verstaendnisfehler. Der Agent war oft nahe an der richtigen Handlung, aber
BrowserGym-Action-Grounding und WebArena-Verified-Evaluationskriterien sind
praezise. Deshalb mussten Prompt-Kontext, Link-Grounding und Final-State-Checks
stabilisiert werden.

## Ausgangsproblem

Bei GitLab und Shopping Admin funktionierten viele Tasks frueh, weil die
korrekten Zielseiten gut ueber stabile Routen erreichbar sind, etwa
`/dashboard/todos` oder `/admin/customer/index`.

Reddit/Postmill und Shopping waren schwieriger:

- Reddit-Tasks benoetigen oft Sortierungswissen wie "most recent" -> `/new`
  und eine finale `RETRIEVE`-Antwort im exakten JSON-Schema.
- Shopping-Tasks benoetigen nicht nur eine Suche, sondern eine konkrete
  Produktdetailseite. Kategorie-Seiten sehen fuer Menschen aehnlich plausibel
  aus, bestehen aber den `NetworkEventEvaluator` nicht.
- Das LLM gab gelegentlich semantisch sinnvolle, aber technisch falsche Actions
  aus, z.B. `click("http://...")` statt `goto("http://...")`.
- Lange Executor-Kontexte fuehrten bei `gemma4:e4b` zu nicht parsebaren oder
  leeren JSON-Antworten.

## Methodische Grenze

Die Anpassungen sind bewusst keine Gold- oder Oracle-Loesungen.

Nicht gemacht:

- keine task-id-spezifischen Ziel-URLs wie `if task_id == 118: goto(...)`
- keine Nutzung von `eval`, `reference_answer`, Gold-URL oder Official-Eval-
  Metadaten im Agent-Modus
- keine hardcodierten finalen Antworten fuer Retrieve-Tasks

Gemacht:

- allgemeines Action-Grounding
- allgemeine Website-Konventionen
- bessere Beobachtungsaufbereitung
- strengere Unterscheidung zwischen Zwischenzustand und finalem Zustand
- stabileres JSON-Ausgabeformat

Das ist fuer die Masterarbeit gut argumentierbar: Der Agent bekommt eine
Grounding- und Validierungsschicht, aber die konkrete Aufgabe wird weiterhin
aus Intent, Beobachtung, History und sichtbaren Kandidaten geloest.

## Wichtige Anpassungen

### 1. JSON-Mode und Output-Format

Problem:
Der Executor und Planner gaben teilweise Markdown-Fences, abgeschnittene Texte
oder gar kein parsebares JSON zurueck.

Anpassungen:

- Ollama-Calls nutzen `format: "json"` fuer Planner und Executor.
- Executor-Prompt verlangt: sichtbare Antwort startet mit `{` und endet mit `}`.
- Fehler beim Parsen enthalten jetzt `response_preview`, damit sichtbar wird,
  was das Modell ausgegeben hat.
- Planner-Ausgabelimit wurde erhoeht, weil manche Planantworten am Tokenlimit
  abgeschnitten wurden.

Betroffene Dateien:

- `scripts/hk_agent/executor.py`
- `scripts/webarena_exp/planner.py`
- `prompts/executor_system.md`

### 2. Executor-Kontext reduziert

Problem:
Der Executor-Kontext war fuer kleine/effiziente Modelle zu gross. Dadurch
wurden Antworten laenger, instabiler und haeufiger unparsebar.

Anpassungen:

- sichtbarer Seitentext gekuerzt
- AX-Tree/DOM-Kontext reduziert
- nur noch die letzten 4 statt 8 Schritte im Executor-Kontext
- relevante Links werden priorisiert, statt dem Modell eine lange ungeordnete
  Linkliste zu geben

Warum:
Fuer den naechsten Browser-Schritt sind meist die letzten Aktionen relevant,
nicht die gesamte Trajektorie. Die komplette Trajektorie bleibt trotzdem als
Artefakt erhalten.

Betroffene Datei:

- `scripts/hk_agent/executor.py`

### 3. Sichtbare Links als `link_candidates`

Problem:
BrowserGym-`bid`s sind nicht immer stabil fuer Navigation. Manchmal klickt das
LLM einen sichtbaren Kandidaten, aber die Seite navigiert nicht. Bei Shopping
gab es passende Produktlinks im HTML, aber sie standen nicht prominent genug im
Executor-Kontext.

Anpassungen:

- sichtbare `a[href]` Links werden als absolute URLs extrahiert.
- `link_candidates` werden nach Task-Woertern gerankt.
- Bei echter Linknavigation wird `goto("href")` im Prompt bevorzugt.
- `click("http://...")` wird in der Ausfuehrung zu `goto("http://...")`
  normalisiert, solange die URL auf demselben Benchmark-Host bleibt.

Warum das sauber ist:
Das Modell hat bereits eine sichtbare URL gewaehlt. Die Normalisierung korrigiert
nur die BrowserGym-Action-Funktion, nicht das Ziel.

Betroffene Dateien:

- `scripts/hk_agent/executor.py`
- `prompts/executor_system.md`

## Reddit/Postmill

### Fehlerbild

Bei Task 27 sollte der Agent im personal-finance-Forum den neuesten Post finden
und eine `RETRIEVE`-Antwort liefern.

Fruehe Fehler:

- Navigation nur zu `/f/personalfinance`, aber nicht zur neuesten Sortierung
- `click("http://localhost:9999/f/personalfinance/new")` statt `goto(...)`
- Agent blieb auf einer Listing-Seite oder klickte einen falschen User-Link
- finale Antwort blieb `retrieved_data: null`

### Anpassungen

- Prompt und Site-Konventionen ergaenzt:
  - Postmill nutzt `/f/<ForumName>`, nicht Reddit-typisch `/r/<name>`.
  - "most recent" sollte ueber `/new` oder sichtbaren New-Link erreicht werden.
- URL-Clicks werden zu `goto(...)` normalisiert.
- Retrieve-Regel im Executor-Prompt:
  - Wenn die benoetigten Felder sichtbar sind, direkt
    `send_msg_to_user(...)` mit dem angeforderten Schema ausgeben.

### Ergebnis

Beispiel erfolgreicher Lauf:

- Run: `hk-agent-reddit-shopping-debug-v3`
- Task: `27`
- Konfiguration: `h=2`, `k=1`
- Score: `1.0`
- Schritte:
  1. `goto("http://localhost:9999/f/personalfinance/new")`
  2. `send_msg_to_user(...)` mit `username`, `post_title`, `count`

Der Agent extrahierte:

```json
[
  {
    "username": "Hammer94",
    "post_title": "56 year old mom has no retirement. Where do I even start on her behalf?",
    "count": 0
  }
]
```

Interpretation:
`h=2`, `k=1` war hier stark, weil der Planner die zwei noetigen Subgoals
abbildet und der Runtime-Evaluator frueh genug kontrolliert, ob Fortschritt
sichtbar ist.

## Shopping

### Fehlerbild

Bei Task 118 sollte der Agent fuer ein Jaw-Bruxism-Problem auf eine passende
Produktdetailseite navigieren.

Fruehe Fehler:

- Suche wurde korrekt ausgefuehrt:
  `catalogsearch/result/?q=mouth+night+guard`
- Danach wurden Kategorie-Seiten als ausreichend betrachtet, z.B.
  `/beauty-personal-care/oral-care/dental-floss-picks.html`
  oder `/beauty-personal-care/oral-care/orthodontic-supplies.html`
- Der offizielle `NetworkEventEvaluator` erwartete aber eine Produktdetail-URL
  mit Slug-Begriffen wie `guard`, `mouth`, `teeth`, `night`, `dental` oder
  `bruxism`.

### Ursache

Unser Final-State-Check war zu weich:

```text
url.endswith(".html") = fertig
```

Das war falsch, weil auch Kategorie-Seiten auf `.html` enden.

### Anpassungen

- Produktseiten werden als root-level `.html` verstanden:
  - gut: `/dentemp-ora-guard-custom-fit-dental-guard-...html`
  - schlecht: `/beauty-personal-care/oral-care/dental-floss-picks.html`
- Nested Kategorie-URLs werden im Link-Ranking abgewertet.
- Root-level Produktlinks werden im Link-Ranking stark bevorzugt.
- `page_satisfies_subgoal` akzeptiert Shopping-Finalzustand nur noch, wenn:
  - URL endet auf `.html`
  - URL-Pfad ist root-level, also kein verschachtelter Kategoriepfad
- Prompt erklaert explizit:
  - Suchseite ist nur Zwischenzustand.
  - Kategorie-URL ist nicht final.
  - Produktdetailseite ist root-level `.html`.

Betroffene Stellen:

- `scripts/hk_agent/executor.py`
- `prompts/executor_system.md`

### Ergebnis

Beispiel erfolgreicher Lauf:

- Run: `hk-agent-shopping-debug-v5`
- Task: `118`
- Konfiguration: `h=2`, `k=1`
- Score: `1.0`
- Schritte:
  1. `goto("http://localhost:7770/catalogsearch/result/?q=mouth+night+guard")`
  2. `goto("http://localhost:7770/dentemp-ora-guard-custom-fit-dental-guard-bruxism-night-guard-for-teeth-grinding-two-pack-mouth-guard-for-clenching-teeth-at-night-mouth-guard-for-sleeping-relieve-soreness-in-jaw-muscles.html")`

Der `NetworkEventEvaluator` wurde dadurch erfolgreich, weil die URL direkt eine
passende Produktdetailseite ist.

## Rolle von H und k in diesen Beispielen

Reddit:

- `h=2`, `k=1` war sehr effizient.
- `k=0` war schwaecher, weil fehlende Validierung falsche Zwischenzustaende
  laenger bestehen laesst.
- Zu viele Replans koennen Kosten erhoehen, aber bei instabilen Seiten helfen
  kleine `k`-Werte beim Korrigieren.

Shopping:

- `h=2`, `k=1` war nach Grounding-Fix erfolgreich und effizient.
- `h=0`, `k=2` konnte auch erfolgreich sein, brauchte aber mehr Schritte und
  Tokens.
- Der Hauptgewinn kam nicht durch ein groesseres Modell, sondern durch bessere
  Grounding-Information und strengere Final-State-Checks.

## Was diese Anpassungen fuer die Auswertung bedeuten

Die offiziellen Scores sollen weiterhin nur aus WebArena-Verified kommen:

- `official_score`
- `official_success`
- `official_eval_status`

Runtime-Metriken erklaeren nur den Prozess:

- `runtime_replans`
- `runtime_no_progress_events`
- `runtime_invalid_actions`
- `runtime_loop_events`
- Tokens und Laufzeit

Wenn ein Agent semantisch nah dran ist, aber die offizielle Evaluierung 0 gibt,
ist das kein Widerspruch. Es bedeutet oft:

- falsches finales Antwortschema
- falscher URL-Typ
- Such-/Kategorie-Seite statt Produktseite
- sichtbares Ziel erreicht, aber nicht ueber den erwarteten Netzwerk-Event
- Navigation nicht wirklich ausgefuehrt, obwohl eine plausible Action erzeugt
  wurde

Deshalb muessen Kontext und Action-Grounding so gestaltet sein, dass die LLM-
Entscheidung in eine offiziell messbare Trajektorie umgesetzt wird.

## Fazit

Die Anpassungen sind keine unfairen Hilfen, sondern notwendige Bruecken zwischen
LLM-Intent und Benchmark-Ausfuehrung:

- Der Planner bleibt fuer Subgoals verantwortlich.
- Der Executor entscheidet die konkrete naechste Aktion.
- Die Grounding-Schicht prueft und normalisiert Actions.
- Der Runtime-Evaluator bewertet Fortschritt, aber setzt keinen offiziellen
  Erfolg.
- Der Official Evaluator bleibt die einzige Quelle fuer Benchmark-Success.

Damit ist das System wissenschaftlich sauberer: Es trennt semantisches
Task-Solving von technischer BrowserGym-Ausfuehrung und macht sichtbar, wann
Fehler aus Planung, Ausfuehrung, Grounding oder Evaluationsspezifik entstehen.
