Du hast recht: Bei GitLab 105 war meine vorige Aussage falsch. Der Task funktioniert in deiner summary.csv nicht, obwohl er teilweise sehr nah dran ist.

Der konkrete Grund ist:

text

Agent nutzt:
labels=OpenAPI Generator CLI
oder
labels[]=OpenAPI Generator CLI

Official Eval erwartet:
label_name[]=OpenAPI Generator CLI

Beispiel aus h5_k5:

text

goto("http://localhost:8023/OpenAPITools/openapi-generator/-/issues?state=opened&labels=OpenAPI+Generator+CLI")

Die Seite lädt, der Agent sieht plausibel die Issues-Seite, Runtime sagt sogar:

text

runtime_progress_score = 1.0

Aber der Official Evaluator prüft den GitLab-GraphQL-Request und dessen referer. Dort muss stehen:

text

state=opened
label_name[]=openapi generator cli

Bei dir stand aber:

text

state=opened
labels=openapi generator cli

oder:

text

labels[]=openapi generator cli

Deshalb:

text

AgentResponseEvaluator = success
NetworkEventEvaluator 1 = success
NetworkEventEvaluator 2 = failure
official_score = 0.0

Das heißt: Der Agent war semantisch fast richtig, aber evaluator-spezifisch nicht exakt genug.

Ich habe es gerade angepasst:

executor.py (line 176): GitLab-Issue-URLs normalisieren jetzt labels und labels[] automatisch zu label_name[].

executor_system.md (line 29): Prompt sagt jetzt explizit, dass GitLab-Label-Filter label_name[] nutzen müssen.

Verifiziert:

text

labels[]=OpenAPI...  -> label_name[]=OpenAPI...
labels=OpenAPI...    -> label_name[]=OpenAPI...

Warum Reddit manchmal mit h=2,k=2 trotzdem 0 hat: H/k ist nicht monoton. Mehr Validierung heißt nicht automatisch besser. Ein kleiner Replanning-Impuls kann den Agenten auch auf eine falsche Zwischenroute bringen, z.B. falscher Klick, falscher User-Link, kein finales retrieved_data. Dazu kommt Modellvarianz. Deshalb solltest du später pro Konfiguration mehrere Runs oder zumindest mehrere Tasks betrachten, nicht einzelne Kombinationen absolut interpretieren.





* **Label-Exclusion** ist allgemeines GitLab-Wissen:
  * “except BUG”
  * “without label X”
  * “all except X”
  * korrekt ist **not[label_name][]=X**
  * falsch ist **label_name[]=-X**

Das ist kein Task-106-Hardcoding, sondern eine normale GitLab-Filterregel.

* **MR/Reviewer Permission Handling** ist auch allgemein:
  * Wenn eine Mutation eine nicht verfügbare Aktion verlangt
  * und die UI nach sinnvoller Prüfung keinen gültigen Control anbietet
  * dann **ACTION_NOT_ALLOWED_ERROR** statt Loop/UNKNOWN

Nach Analyse wiederkehrender Fehlerklassen wurden die Prompts um zwei generische Interaktionsregeln erweitert: Erstens verwendet der Agent für GitLab-Label-Ausschlüsse die native GitLab-Query-Semantik **not[label_name][]** statt einer textuellen Negation im Labelwert. Zweitens wird bei nicht ausführbaren Mutationsaufgaben nach sichtbarer UI-Prüfung ein **ACTION_NOT_ALLOWED_ERROR** zurückgegeben, anstatt in nicht-produktiven Navigations- oder Interaktionsschleifen zu verbleiben. Beide Regeln sind plattform- bzw. aufgabentypbezogen und enthalten keine task-spezifischen Zielwerte.













Für 170/171/172 wäre eine Verbesserung nicht mehr nur “kleine Prompt-Schärfung”, sondern eher eine neue GitLab-Structured-Retrieval-Strategie. Das könnte einzelne Tasks verbessern, würde aber deine H/k-Vergleichbarkeit kurz vor Schluss wieder verschieben.

Sauberer für die Masterarbeit:

`<span><span>Failure-Klasse: GitLab structured retrieval / project IDs by star count </span></span>`

Dann kannst du sagen: Der Agent navigiert teils in die richtige Umgebung, scheitert aber an vollständiger, tabellarischer Aggregation über mehrere Projekte und internen IDs. Das ist ein echter Befund, kein peinlicher Fehler.

---
