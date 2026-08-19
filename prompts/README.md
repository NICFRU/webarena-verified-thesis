# Promptuebersicht fuer die v3-Agentenarchitektur

Die v3-Architektur nutzt getrennte Prompts fuer Planner, Executor und optionale Repair-Informationen. Alle lokal gepflegten v3-Prompts liegen gebuendelt unter `prompts/v3/`; zusaetzlich wird der offizielle WebArena-Verified-Site-Prompt aus dem externen Benchmark-Repository als Basisvertrag geladen. Die folgende Tabelle kann als Uebersicht fuer den Anhang verwendet werden.

| Name | Pfad | Modul / Rolle | Inhalt |
|---|---|---|---|
| Planner-Systemprompt | `prompts/v3/planner_system.md` | `webarena_exp.planner.build_plan` / Planner-Systemrolle | Definiert den Planner als strategische Komponente: Subgoal-Planung, kein Ausgeben von Browseraktionen, JSON-only, keine Hidden Chain-of-Thought, Regeln fuer Replanning und Nutzung von Runtime-Feedback. |
| Planner-Usertemplate | `prompts/v3/prompt_user_template.md` | `webarena_exp.planner.build_plan` / Planner-Userrolle | Rendert Task-ID, Site, Start-URLs, Task-Intent, Planungshorizont `H`, initiale Observation, vorherigen Plan, Runtime-Verifier-Feedback und Controller-Entscheidung in den konkreten Planner-Aufruf. |
| Executor-Systemprompt | `prompts/v3/executor_system.md` | `hk_agent.executor.BrowserGymLLMExecutor` / Executor-Systemrolle | Fallback- bzw. Basissystemprompt fuer die operative Executor-Rolle: genau eine BrowserGym-Aktion, strukturierte JSON-Ausgabe, keine Gold-/Evaluatorinformationen, site-lokale Navigation und allgemeine Ausfuehrungsregeln. |
| WebArena-Verified-Basisvertrag | `external/webarena-verified/examples/prompts/<site>.md` | `hk_agent.prompt_builder.webarena_verified_prompt_basis(...)` / Executor-Basis | Offizieller Site- und Taskvertrag aus WebArena-Verified; wird mit Task-Intent und Start-URLs gerendert und bildet bei v3 den ersten Teil des Executor-Systemprompts. |
| v3-Executor-Basisregeln | `prompts/v3/executor_base.md` | `hk_agent.prompt_builder.build_executor_system_prompt(...)` / Executor-Zusatz | Enthalt den BrowserGym-Action-Vertrag, erlaubte Actions, `bid`-Bindung, Grounding-Regeln, finale WebArena-Verified-Antwortstruktur und Validierungsanforderungen. |
| GitLab-Kontext | `prompts/v3/sites/gitlab.md` | Executor-Zusatz fuer GitLab | Beschreibt GitLab-Routen und Workflows, z. B. Dashboard-Todos, Issues, Label-Filter, Clone-URLs, Forks, Member-Invites, Datei-Edits und Profilaufgaben. |
| Shopping-Kontext | `prompts/v3/sites/shopping.md` | Executor-Zusatz fuer Shopping | Beschreibt Storefront-Konventionen fuer Suche, Kategorien, Produktseiten, Warenkorb, Reviews und sichtbare Retrieval-/Navigationsevidenz. |
| Shopping-Admin-Kontext | `prompts/v3/sites/shopping_admin.md` | Executor-Zusatz fuer Shopping Admin | Beschreibt Magento-Admin-Konventionen fuer Grids, Filter, Detailseiten, Tabs, Statusfelder und admin-spezifische Navigation. |
| Shopping-Admin-Mutation-Kontext | `prompts/v3/sites/shopping_admin_mutation.md` | Executor-Zusatz fuer Shopping-Admin-MUTATE | Wird fuer Mutation-Tiers ergaenzend geladen und konkretisiert dauerhafte Save-/Submit-/Create-/Comment-/Shipment-/Review-Workflows sowie Erfolg erst nach sichtbarer Zustandsaenderung. |
| Reddit-Kontext | `prompts/v3/sites/reddit.md` | Executor-Zusatz fuer Reddit/Postmill | Beschreibt Forum-, Post-, Kommentar-, Vote-, Sortier- und Retrieval-Konventionen fuer die lokale Reddit-aehnliche Webanwendung. |
| Map-Kontext | `prompts/v3/sites/map.md` | Executor-Zusatz fuer Map | Beschreibt Such-, Karten-, Routen- und Standortkonventionen fuer Aufgaben mit der Kartenanwendung. |
| Wikipedia-Kontext | `prompts/v3/sites/wikipedia.md` | Executor-Zusatz fuer Wikipedia | Beschreibt Wikipedia-spezifische Navigations- und Retrieval-Konventionen fuer Artikel-, Such- und Inhaltsaufgaben. |
| v3-Repair-Prompt | `prompts/v3/v3_repair_prompt.md` | `hk_agent.k_repair` / Repair-Brief-Schema | Definiert die Struktur eines Repair-Briefs nach k-Schritt-Feedback: Fehlerklasse, aktueller Zustand, falsche Aktionen, zu vermeidende Ziele, benoetigtes naechstes Ziel sowie Planner- und Executor-Reparaturanweisung. |

## Zusammensetzung des v3-Executor-Systemprompts

Bei `--agent-architecture v3` wird der Executor-Systemprompt im Code zusammengesetzt aus:

```text
external/webarena-verified/examples/prompts/<site>.md
prompts/v3/executor_base.md
prompts/v3/sites/<site>.md
prompts/v3/sites/<site>_<capability_tier>.md
```

Fuer Shopping-Admin-Mutationsaufgaben ist der tier-spezifische Zusatz:

```text
prompts/v3/sites/shopping_admin_mutation.md
```

Die alten, nicht fuer die v3-Hauptarchitektur verwendeten Promptnotizen liegen unter:

```text
prompts/archiv/
```

