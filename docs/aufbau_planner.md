# 5 Architektur


Projektseiten und GitHub-Repositories wurden ergänzend berücksichtigt, sofern sie von den jeweiligen Publikationen referenziert wurden und zusätzliche Informationen zu Implementierung, Benchmark oder Reproduzierbarkeit enthielten.


Denn in deinen Quellen gibt es drei verschiedene Formen von Bewertung:

- **environment-based / programmatic checks**, also beobachtbare Zustands- oder Erfolgsprüfung in der Umgebung, etwa ob ein Teilziel erreicht oder ein Zustand verletzt wurde. Das ist gerade in Web-Settings sehr wichtig.
- **controller-/reflection-basierte Bewertung**, bei der ein Modul Subtask-Fortschritt, Vollständigkeit oder Fehlversuche beurteilt und daraus Re-Execution oder Replanning ableitet.
- **LLM-as-Judge**, also semantische Bewertung durch ein LLM, etwa für Postcondition-Checks, Subgoal-Erfüllung oder finale Evaluation. Das wird in einigen Arbeiten explizit genutzt, ist aber nicht in allen Arbeiten der Runtime-Kern.
### Aufbau  
- 5.1 Designziele der Agentenarchitektur  
- 5.2 Gesamtarchitektur  
- 5.3 Planner  
- 5.4 Executor  
- 5.5 Evaluator  
- 5.6 Controller und Replanning-Logik  
- 5.7 Logging und Trace-Erfassung  
- 5.8 Prompting und Kontextmanagement


## 5.1 Designziele der Agentenarchitektur

- Trennung von strategischer Planung, operativer Ausführung, Bewertung und Kontrollentscheidung
- experimentelle Manipulierbarkeit von Planungshorizont `H` und Validierungsintervall `k`
- reproduzierbare und protokollierbare Laufzeitentscheidungen
- explizite Erfassung von Prozessmetriken wie Replanning, Loops, No-Progress und Invalid Actions
- konstante Prompt-, Modell- und Ausführungsbedingungen innerhalb eines Experimentalblocks
- Unterstützung einer späteren Effektivitäts-, Effizienz- und Prozessanalyse


## 5.2 Gesamtarchitektur

- Überblick über die Module:  
	- Planner  
	- Executor  
	- Evaluator  
	- Controller  
	- Logging / Trace Storage  
  
- Externe Systeme:  
	- WebArena / WebArena-Lite als Benchmark-Setting  
	- BrowserGym / AgentLab als Ausführungsumgebung  
	- LLM-API oder lokaler Modellserver  
	- Logging- und Analysekomponenten  
  
- Gesamtfluss:  
	- Task und Observation erfassen  
	- Plan bzw. Subgoals erzeugen  
	- Subgoal ausführen  
	- Zwischenzustand validieren  
	- Controller entscheidet über Continue, Replan oder Abort  
	- alle Schritte werden protokolliert

## 5.3 Planner


Dein Planner-Abschnitt ist sehr detailliert. Das ist gut, aber du solltest nicht zu viele Literaturdetails mitten in die Architektur schreiben. Plan-and-Act, WebATLAS, WebPilot gehören eher in Kapitel 3. In Kapitel 5 reicht: „In Anlehnung an planende Agentenansätze...“

```
## 5.3 Planner- **Rolle**  - Der Planner ist das strategische Planungsmodul.  - Er erzeugt aus Task Instruction und initialer Observation einen High-Level-Plan.  - Er zerlegt das globale Ziel in Subgoals.  - Er formuliert erwartete Zielzustände oder Success Criteria pro Subgoal.- **Input**  - Task Instruction  - initiale Observation  - optional: bisheriger Plan bei Replanning- **Output**  - strukturierter Plan  - geordnete Liste von Subgoals  - erwartete Outcomes pro Subgoal- **Bezug zu `H`**  - Der Planungshorizont `H` steuert, wie umfangreich der Planner vorausplant.  - Die konkrete Operationalisierung von `H` wird in Kapitel 6 beschrieben.
```


### **Definition**  
- LLM-basiertes High-Level-Planungsmodung --> **strategischer Ebene**
- erzeugt aus Aufgabenbeschreibung und initialer Observation (Zustand der Webseite ) einen ersten Lösungsplan
- zerlegt das globale Ziel in **Teilziele / Subgoals**
- ordnet diese in eine sinnvolle Reihenfolge
- formuliert pro Teilziel **erwartete Zielzustände** oder **Subgoal Objectives**
- stellt damit eine strategische Struktur für Ausführung und spätere Bewertung bereit

### Grundlage
- In **Plan-and-Act** erzeugt der Planner den High-Level-Plan vor allem aus der Nutzeranfrage; die Grundidee ist: Planner erzeugt eine Folge von High-Level-Schritten, Executor übersetzt diese in umgebungsgebundene Aktionen.
- In **WebATLAS** wird der Planner explizit mit der initialen Observation $o_0$​ formuliert: $P_0 = \text{Planner}(q, o_0)$. Dort ist die Anfangsbeobachtung also Teil des Planner-Inputs.
- In **WebPilot** ist die Planung insgesamt beobachtungsgetrieben und wird später mit neuen Beobachtungen verfeinert, aber der zentrale erste Schritt ist zunächst die hierarchische Zerlegung des Tasks in Subtasks.

### **Komponenten des Planners**

- **Task Interpreter**  
    extrahiert Ziel, Constraints, relevante Entitäten
- **Subgoal Decomposer**  
    zerlegt das Ziel in Teilziele
- **Ordering / Dependency Module**  
    bestimmt Reihenfolge und Abhängigkeiten
- **Expected Outcome Designer**
	- ergänzt Teilziele um grobe erwartete Outcomes, die später vom Evaluator geprüft werden können
- **Replanning Interface**  
    kann bestehende Pläne bei neuen Beobachtungen anpassen
### Nutzung 
- LLM 
### **Input**

- Task Instruction
- initiale Observation
- optionale frühere Planversion

### **Output**

- strukturierter High-Level-Plan
- Liste von Subgoals
- Success Criteria / Objectives pro Subgoal


## 5.4 Executor


### additionally

- **Rolle**
  - Der Executor setzt das aktive Subgoal in konkrete Webaktionen um.
  - Er arbeitet auf der operativen Ausführungsebene.
  - Er interagiert direkt mit BrowserGym/WebArena über ausführbare Aktionen.

- **Komponenten**
  - Subgoal Context Handler
  - Action Generator
  - Action Grounder / Formatter
  - Observation Parser
  - Trajectory Hook / Step Writer

- **Input**
  - aktuelle Observation
  - aktuelles Subgoal
  - kurzer Verlauf
  - ggf. letzte Evaluator-Signale

- **Output**
  - ausführbare Action für die Umgebung
  - Log-Eintrag zu Aktion, Observation und Laufzeitdaten

### **Definition**  

- Executor (**ausführende Agentenmodul**) --> direkte interagtion mit BrowserGym-WebArena
- Umsetzung des aktiven Teilziel in **konkrete primitive Webaktionen** 
- **lokale, operativer Ausführungsebene**
- Ziel: Subgoals in **umgebungsgebundene Aktionen** wie Klicken, Tippen oder Navigieren  übersetzen

### **Komponenten des Executors**


- **Subgoal Context Handler**
    - hält fest, welches Teilziel gerade aktiv ist
    - beschränkt den Kontext auf die für das aktuelle Teilziel relevanten Informationen
- **Action Generator**  
    LLM oder policy-basierte Erzeugung der nächsten Aktion
- **Action Grounder / Formatter**
    - übersetzt die intern erzeugte Aktion in das vom Environment erwartete Format
    - bindet die Aktion an konkrete, ausführbare Environment-Kommandos
-  **Trajectory Hook / Step Writer**
    - übergibt jeden Schritt an die Logging-Schicht
    - speichert Aktionen, Beobachtungen und Statusänderungen
- **Observation Parser** (Optional)
    - verarbeitet die aktuelle Observation aus BrowserGym-WebArena
    - extrahiert relevante Informationen über Seite, Zustand und sichtbare Elemente

### Nutzung
- direkte Interaktion mit BrowserGym-WebArena
- operative Nutzung von `env.step(action)`
- optionale LLM-Nutzung innerhalb des Action Generators

### **Input**

- aktuelle Observation
- aktuelles Subgoal
- kurze Schritt-Historie
- ggf. letzte Evaluator-Signale

### **Output**

- konkrete Action für `env.step(action)`
## 5.5 Evaluator

### zusatz

- **Rolle**  
- Der Evaluator ist ein hybrides Bewertungsmodul für Zwischenzustände und Prozessverlauf.  
- Er prüft, ob die aktuelle Ausführung noch mit globalem Ziel, aktuellem Subgoal, Constraints und bisherigem Verlauf konsistent ist.  
- Er ist nicht identisch mit dem offiziellen Benchmark-Evaluator für den finalen Task-Erfolg.  
  
- **Aktivierung**  
- nach jeweils `k` Aktionen  
- zusätzlich bei Triggerereignissen wie Loop, No-Progress, Invalid Action oder Constraint-Verletzung  
  
- **Komponenten**  
- Progress Checker  
- Subgoal Completion Checker  
- State / Outcome Comparator  
- Constraint Checker  
- Action Validity Checker  
- Loop / No-Progress Detector  
- optional: Semantic Judge  
  
- **Input**  
- aktuelles Subgoal  
- erwarteter Zielzustand  
- aktuelle Observation  
- Verlauf der letzten Schritte  
- letzte Aktionen  
- relevante Constraints  
  
- **Output**  
- Fortschrittssignal  
- Subgoal-Status  
- Fehler- oder Risikosignale  
- Loop-/No-Progress-Flag  
- Empfehlung an den Controller

**Definition**  
- Der Evaluator ist ein **hybrides Bewertungsmodul**.
- Er wird nach jeweils **kkk Schritten** oder bei **Triggerereignissen** aktiviert.
- Er überprüft, ob die Ausführung noch konsistent mit:
    - globalem Ziel
    - aktuellem Teilziel
    - Constraints
    - bisherigem Verlauf  
        ist.
- Er ist **nicht bloß ein einziges Judge-LLM**.

- Diese hybride Form ist wichtig, damit Validierung nicht zu teuer und gleichzeitig nicht zu ungenau wird.

Diese Rolle ist in der Literatur funktional vorhanden, auch wenn sie unterschiedlich benannt wird, etwa als Verifier, Appraiser, Critic oder Reflection-Komponente.

**Komponenten des Evaluators**

- **Progress Checker**  
    prüft, ob sichtbarer Fortschritt vorliegt
- **Subgoal Completion Checker**  
    prüft, ob das aktuelle Teilziel erreicht ist
- **State / Outcome Comparator**
    - vergleicht den beobachteten Zustand mit dem erwarteten Zielzustand des aktiven Subgoals
- **Constraint Checker**
    - erkennt Verletzungen von Regeln oder Anforderungen
- **Action Validity Checker**
    - erkennt ungültige, ineffiziente oder offensichtlich nicht zielführende Aktionen
- **Loop / No-Progress Detector**
    - erkennt Wiederholungen und Stagnation
- **Semantic Judge**
    - optionales LLM-as-Judge für semantisch offene Situationen
- **Risk / Recoverability Estimator**
    - schätzt, ob lokales oder globales Replanning nötig ist
### Nutzung

- Aufruf nach kkk Schritten oder bei Triggerereignissen
- Kombination aus programmatischen, heuristischen und optional semantischen Checks
- liefert strukturierte Bewertungssignale an den Controller


**Input**

- aktuelles Subgoal
- erwarteter Zielzustand / Objective des aktuellen Subgoals
- relevante Constraints
- aktuelle Observation
- frühere Observationen / Schritt-Historie
- letzte Aktion(en)
- 
**Output**

- `progress_score`
- `subgoal_completion_score` oder `subgoal_done`
- `constraint_violation_flag`
- `action_validity_flag`
- `loop_or_no_progress_flag`
- `risk_score`
- `recoverability_score`
- `recommended_intervention` _(optional)_



## 5.6 Controller und Replanning-Logik

### zusatz 
- **Rolle**  
- Der Controller interpretiert die Signale des Evaluators.  
- Er übersetzt Bewertungssignale in operative Kontrollentscheidungen.  
- Er wird regelbasiert umgesetzt, um Reproduzierbarkeit, Interpretierbarkeit und Auswertbarkeit sicherzustellen.  
  
- **Entscheidungen**  
- `continue`  
- `local_replan`  
- `global_replan`  
- `abort`  
  
- **Komponenten**  
- Decision Policy  
- Threshold Logic  
- Budget Guard  
- Replanning Trigger Handler  
- Fail-safe Module  
  
- **Input**  
- Evaluator-Signale  
- aktueller Planstatus  
- aktuelles Subgoal  
- Schrittzähler  
- Replanning-Historie  
- Token-, Zeit- und Schrittbudget  
  
- **Output**  
- Kontrollentscheidung  
- Reason Code, z. B. `no_progress`, `loop_detected`, `budget_exceeded`
### **Definition**

- Der Controller ist das **Entscheidungsmodul zwischen Bewertung und weiterer Ausführung**.
- Er interpretiert die Signale des Evaluators und übersetzt sie in eine operative Entscheidung.
- In der ersten Thesis-Version wird der Controller **regelbasiert und programmierbar** gestaltet.
- Er ist damit kein freies generatives LLM-Modul, sondern eine explizite Entscheidungslogik.
- Das macht ihn:
    - reproduzierbar
    - interpretierbar
    - auswertbar


AgentLab betont für Benchmarking ohnehin Reproduzierbarkeit, Versionierung und nachvollziehbare Studien-Setups.

### **Komponenten des Controllers**

- **Decision Policy**
    - bildet die grundlegende Entscheidungslogik ab
- **Threshold Logic**
    - verwendet feste Regeln und Schwellenwerte
- **Budget Guard**
    - überwacht Schrittbudget, Tokenbudget und Laufzeit
- **Replanning Trigger Handler**
    - ordnet Evaluator-Signale konkreten Eingriffen zu
- **Fail-safe Module**
    - beendet den Task kontrolliert bei Aussichtslosigkeit oder Budgetüberschreitung

### **Entscheidungen**

- **Continue**
    - Ausführung wird regulär fortgesetzt
- **Local Replan**
    - der aktuelle Restplan wird lokal angepasst
    - das übergeordnete Teilziel bleibt bestehen
- **Global Replan**
    - der High-Level-Plan wird neu erzeugt
    - neue Beobachtungen oder starke Abweichungen machen eine strategische Neuplanung nötig
- **Abort / Fail-safe**
    - kontrollierter Abbruch des Tasklaufs


Ein LLM-basierter Controller kann später als Variante ergänzt werden, aber nicht als Ausgangspunkt.

### Nutzung
- Aufruf nach jedem Evaluationszyklus
- regelbasierte Verarbeitung der Evaluator-Signale
- Entscheidung über Continue, Local Replan, Global Replan oder Abort
- Weitergabe der Entscheidung an Executor bzw. Planner

### **Input**

- strukturierte Evaluator-Signale, z. B.:
    - `progress_score`
    - `subgoal_done`
    - `constraint_violation_flag`
    - `action_validity_flag`
    - `loop_or_no_progress_flag`
    - `risk_score`
    - `recoverability_score`
- aktueller Planstatus / Restplan
- aktuelles Subgoal
- Schrittzähler bzw. aktueller Zeitpunkt im Lauf
- Replanning-Historie
- Budgetstatus:
    - bisherige Tokens
    - bisherige Laufzeit
    - verbleibendes Schrittbudget

### **Output**

- eine explizite Kontrollentscheidung:
    - `continue`
    - `local_replan`
    - `global_replan`
    - `abort`
- optional eine **Begründung / Reason Code**, z. B.:
    - `no_progress`
    - `constraint_violation`
    - `loop_detected`
    - `budget_exceeded`
    - `subgoal_completed`

## 5.7 Logging und Trace-Erfassung

- **Rolle**
  - Die Logging-Komponente erfasst alle relevanten Laufzeitdaten eines Agentenlaufs.
  - Sie ermöglicht spätere Rekonstruktion der Trajektorie und Berechnung von Prozessmetriken.

- **Erfasste Daten**
  - Task-ID
  - Konfiguration
  - Modell und Promptversion
  - Observations
  - Actions
  - Subgoals und Planversionen
  - Evaluator-Signale
  - Controller-Entscheidungen
  - Reason Codes
  - Tokenverbrauch
  - Laufzeiten und Latenzen
  - Endstatus

- **Bedeutung**
  - Die Trace-Erfassung bildet die Grundlage für Prozessmetriken wie Replanning-Frequenz, Loops, No-Progress, Invalid Actions und Abort Reasons.
  - Sie unterstützt Reproduzierbarkeit und spätere Fehleranalyse.
## 5.8 Prompting und Kontextmanagement

- **Rolle**
  - Prompting und Kontextmanagement steuern, welche Informationen die einzelnen Module erhalten.
  - Sie sind Teil der Implementierung, aber nicht eigenständiger Untersuchungsgegenstand.

- **Modulspezifischer Kontext**
  - Planner: Task, initiale Observation, ggf. bestehender Plan
  - Executor: aktuelle Observation, aktives Subgoal, kurzer Verlauf
  - Evaluator: aktuelles Subgoal, erwarteter Zielzustand, Verlauf, letzte Aktionen
  - Controller: strukturierte Evaluator-Signale, Budgetstatus, Planstatus

- **Experimentelle Bedeutung**
  - Promptstruktur und Kontextformat werden im Experiment konstant gehalten.
  - Dadurch sollen beobachtete Unterschiede möglichst auf `H` und `k` zurückgeführt werden.