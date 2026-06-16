Du sollst das bestehende Jupyter Notebook überarbeiten.

Datei:
`12_1_vertex_gemma_maas_task44_smoke copy 2.ipynb`

Ziel:
Ab Abschnitt 6 soll eine neue, saubere Final-Analysis aufgebaut werden. Die Analyse soll auf der vorhandenen `summary.csv` basieren und eine neue success-dominante Utility-Funktion berechnen. Zusätzlich sollen optimale H/k-Kombinationen, Top-Kandidaten, Gewichtungssensitivität und 3D-Spike-Maps visualisiert werden.

Wichtig:

* Alle Abschnitte vor `## 6. Read Summary` sollen unverändert bleiben.
* Ab Abschnitt 6 soll alles aufgeräumt und neu strukturiert werden.
* Entferne alte unstrukturierte Brainstorming-/Notiz-Zellen ab Abschnitt 6.
* Ersetze die bisherige Utility-/Kosten-Auswertung durch die neue Final-Analysis.
* Behalte nur Analysen, die sinnvoll in die neue Struktur passen.
* Falls alte Analysen wie Near-Miss, Failure-Kategorien oder Site-Vergleiche nützlich sind, integriere sie sauber in optionale Unterabschnitte oder Appendix-Zellen.
* Erzeuge robuste, wiederverwendbare Funktionen.
* Keine stillen Fehler: Wenn Spalten fehlen, gib verständliche Warnungen aus.
* Das Notebook soll nach der Änderung komplett lauffähig sein.

============================================================
ZENTRALE UTILITY-FUNKTION
=========================

Die neue Utility-Funktion lautet:

U(H,k) = S(H,k) · [α + β · (1 − T_norm(H,k)) + γ · (1 − τ_norm(H,k))]

mit:

α + β + γ = 1

Dabei:

* S(H,k) = mittlere Erfolgsrate je H/k-Kombination
* T_norm(H,k) = normalisierte Tokenkosten je H/k-Kombination
* τ_norm(H,k) = normalisierte Laufzeit je H/k-Kombination
* α = Gewicht der Erfolgsrate
* β = Gewicht der Token-Effizienz
* γ = Gewicht der Zeit-Effizienz

Wichtig:

* H und k werden NICHT direkt bestraft.
* H und k beeinflussen Utility nur über beobachtete Erfolgsrate, Tokenverbrauch und Laufzeit.
* Tokenkosten und Laufzeit sind sekundäre Effizienzkriterien.
* Fehlgeschlagene Konfigurationen sollen nicht positiv bewertet werden, nur weil sie schnell oder billig sind.
* Deshalb wird Success als Multiplikator außen verwendet.
* Clippe T_norm und τ_norm auf [0,1].
* Clippe NICHT die finale Utility.

Implementiere:

* `minmax_norm(series)`
* optional `robust_minmax_norm(series, upper_quantile=0.95)`, aber Standard soll min-max sein.
* Falls Token- oder Laufzeitspalten fehlen, setze die jeweilige Norm-Komponente auf 0 und gib eine Warnung aus.

============================================================
GEWICHTUNGSPROFILE
==================

Berechne folgende feste Gewichtungsprofile:

1. main_accuracy_first:
   α = 0.90
   β = 0.05
   γ = 0.05

2. cost_sensitive:
   α = 0.80
   β = 0.15
   γ = 0.05

3. time_sensitive:
   α = 0.80
   β = 0.05
   γ = 0.15

4. stress_80:
   α = 0.75
   β = 0.125
   γ = 0.125

Diese vier Profile sind die festen Bewertungsprofile der Arbeit.

Für jedes Profil berechne:

* Utility
* Rank
* beste H/k-Kombination
* Success Rate
* durchschnittliche Tokens
* durchschnittliche Laufzeit
* ob die beste Kombination identisch mit der Main-Gewichtung ist

Erzeuge eine Tabelle:

* persona
* alpha
* beta
* gamma
* best_h
* best_k
* success_rate
* avg_tokens
* avg_runtime_s
* utility
* same_as_main_best

============================================================
H/K-WERTE
=========

Die wichtigsten experimentellen H/k-Werte sind:

H ∈ {0, 2, 5, 10}
k ∈ {0, 2, 5, 10}

Wichtig:

* Wenn diese Werte vorhanden sind, sortiere Achsen genau in dieser Reihenfolge.
* Filtere nicht hart, wenn in `summary.csv` andere H/k-Werte vorhanden sind.
* Falls andere Werte vorhanden sind, nutze alle verfügbaren Werte und sortiere numerisch.
* k=0 soll als experimenteller Sonderfall behandelt werden, z. B. als Baseline/no-validation/kein explizites Validierungsintervall, falls die Daten so aufgebaut sind.
* Kommentiere im Markdown, dass k=0 methodisch als Sonderfall interpretiert werden muss.

============================================================
NEUE STRUKTUR AB ABSCHNITT 6
============================

Baue ab Abschnitt 6 folgende neue Struktur auf:

---

## 6. Read Summary

---

* Lade `summary.csv` aus dem bestehenden Experimentpfad.

* Nutze vorhandene Variablen aus dem Notebook wie `ROOT`, `EXPERIMENT_NAME` etc., falls vorhanden.

* Standardpfad soll sein:

  ROOT / "runs/hk-agent" / EXPERIMENT_NAME / "summary.csv"

* Wende weiterhin vorhandene Funktionen wie `apply_analysis_success_columns(df)` an, falls sie im Notebook existieren.

* Falls die Funktion nicht existiert, gib eine Warnung aus und nutze vorhandene Success-Spalten.

Erzeuge eine kompakte Übersicht:

* Anzahl Zeilen
* Anzahl eindeutiger Tasks
* vorhandene H-Werte
* vorhandene k-Werte
* vorhandene Sites/Kategorien
* globale Success Rate
* durchschnittliche Tokens
* durchschnittliche Laufzeit
* verwendete Success-Spalte
* verwendete Token-Spalte
* verwendete Laufzeit-Spalte

Nutze bevorzugt folgende Spalten, falls vorhanden:

* task_id
* site
* h
* k
* official_success_bool
* official_success
* contamination_adjusted_success
* total_tokens
* total_runtime_ms
* total_runtime_s
* runtime_seconds
* planner_tokens
* executor_tokens
* planner_calls
* executor_calls
* failure_category
* output_dir

Implementiere automatische Spaltenerkennung:

* Success-Spalte:

  1. official_success_bool
  2. official_success
  3. success
  4. contamination_adjusted_success

* Token-Spalte:

  1. total_tokens
  2. tokens
  3. total_token_count
  4. prompt_tokens + completion_tokens, falls beide vorhanden

* Runtime-Spalte:

  1. total_runtime_s
  2. runtime_seconds
  3. total_runtime_ms / 1000
  4. duration_s
  5. duration_ms / 1000

* H-Spalte:

  1. h
  2. H
  3. planning_horizon

* k-Spalte:

  1. k
  2. K
  3. validation_interval
  4. replanning_interval

---

## 7. Final Utility Definition

---

Füge eine Markdown-Zelle mit der Formel ein:

U(H,k) = S(H,k) · [α + β · (1 − T_norm(H,k)) + γ · (1 − τ_norm(H,k))]

mit α + β + γ = 1.

Erkläre kurz:

* Success ist die Hauptmetrik.
* Tokenkosten und Laufzeit sind sekundäre Effizienzkriterien.
* H und k werden nicht direkt bestraft.
* Die Utility bewertet empirische Auswirkungen von H und k auf Success, Tokens und Laufzeit.

Implementiere Funktionen:

* `minmax_norm(series)`
* `prepare_eval_df(summary)`
* `aggregate_hk(eval_df, group_cols=None)`
* `compute_utility_columns(hk_df, personas)`
* `get_persona_winners(hk_df, personas)`
* `get_top_candidates(hk_df, utility_col="U_main_accuracy_first", n=5)`

---

## 8. Aggregate H/k Results

---

Aggregiere global nach H und k:

Berechne:

* runs
* tasks
* success_rate
* avg_tokens
* median_tokens
* avg_runtime_s
* median_runtime_s
* avg_steps, falls Spalte vorhanden
* T_norm
* runtime_norm

Zeige:

* vollständige H/k-Tabelle
* sortiert nach `U_main_accuracy_first`, sobald Utility berechnet wurde

Wenn `site` vorhanden ist:

* zusätzlich Aggregation nach site, h, k vorbereiten
* noch nicht zwingend alles plotten, aber für spätere Site-Level-Analyse speichern

---

## 9. Utility Personas / Weight Profiles

---

Definiere exakt diese Profiles:

personas = {
"main_accuracy_first": {"alpha": 0.90, "beta": 0.05, "gamma": 0.05},
"cost_sensitive": {"alpha": 0.80, "beta": 0.15, "gamma": 0.05},
"time_sensitive": {"alpha": 0.80, "beta": 0.05, "gamma": 0.15},
"stress_80": {"alpha": 0.75, "beta": 0.125, "gamma": 0.125},
}

Für jede Persona:

* berechne Utility-Spalte:

  * U_main_accuracy_first
  * U_cost_sensitive
  * U_time_sensitive
  * U_stress_80

* berechne Rank-Spalte:

  * rank_main_accuracy_first
  * rank_cost_sensitive
  * rank_time_sensitive
  * rank_stress_80

Zeige:

* globale H/k-Tabelle mit allen Utilities und Ranks
* Persona-Winner-Tabelle

---

## 10. Top H/k Candidates

---

Bestimme auf Basis der Main-Gewichtung:

* Top 3 H/k-Kombinationen
* zusätzlich Top 5 H/k-Kombinationen

Top 3 sind für Interpretation.
Top 5 sind für Visualisierung optional.

Erzeuge `candidate_id`:

candidate_id = "H=<h>, k=<k>"

Zeige Tabelle für Top 5 mit:

* candidate_id
* h
* k
* runs
* tasks
* success_rate
* avg_tokens
* avg_runtime_s
* T_norm
* runtime_norm
* U_main_accuracy_first
* U_cost_sensitive
* U_time_sensitive
* U_stress_80
* rank_main_accuracy_first
* rank_cost_sensitive
* rank_time_sensitive
* rank_stress_80

---

## 11. 3D Spike Map: Utility over H/k

---

Erzeuge eine 3D-Spike-Map.

Ziel:

* x-Achse: Planungshorizont H
* y-Achse: Validierungsintervall k
* z-Achse: Utility
* Höhe der Spikes/Balken: Utility-Wert
* Farbe: Utility-Höhe oder Rang
* Top 3 oder Top 5 H/k-Kombinationen zusätzlich hervorheben
* Top-Kandidaten im Plot labeln

Wichtig:

* Nutze diskrete Spikes/Balken, keine geglättete Fläche.
* H und k sind diskrete experimentelle Parameter.
* Die Grafik soll zeigen, welche H/k-Kombination die höchste Utility erzeugt.

Implementierung:

* Nutze bevorzugt Plotly.
* Falls Plotly nicht verfügbar ist, Fallback auf matplotlib `bar3d`.
* Speichere Plotly-Plots als HTML:

  * final_analysis_3d_spike_main_accuracy_first.html
  * final_analysis_3d_spike_cost_sensitive.html
  * final_analysis_3d_spike_time_sensitive.html
  * final_analysis_3d_spike_stress_80.html

Erzeuge mindestens:

1. 3D-Spike-Map für main_accuracy_first
2. optional weitere 3D-Spike-Maps für cost_sensitive, time_sensitive, stress_80

Die Hauptgrafik im Notebook soll die Main-Gewichtung sein.

---

## 12. Weight Sensitivity of Top Candidates

---

Ziel:
Zeige, wie sich die Utility der Top-Kandidaten verändert, wenn sich α, β und γ verändern.

Nimm die Top 3 aus `main_accuracy_first`.
Optional: Top 5 als zusätzliche Linien anzeigen.

Erzeuge Sensitivitäts-Slices:

Slice A:

* alpha = 0.90
* beta läuft von 0.00 bis 0.10 in 0.01-Schritten
* gamma = 0.10 - beta

Slice B:

* alpha = 0.80
* beta läuft von 0.00 bis 0.20 in 0.01-Schritten
* gamma = 0.20 - beta

Slice C:

* alpha = 0.75
* beta läuft von 0.00 bis 0.25 in 0.01-Schritten
* gamma = 0.25 - beta

Für jede Top-H/k-Kombination berechne die Utility je Gewichtungspunkt.

Erzeuge:

1. eine Tabelle `weight_sensitivity_top_candidates`
2. einen Line-Plot je Alpha-Slice
3. optional einen kombinierten Plot mit Subplots

Achsen:

* x-Achse: beta, also Tokengewicht
* y-Achse: Utility
* pro Top-Kandidat eine Linie
* gamma soll im Titel oder als Hinweis erwähnt werden:
  gamma = 1 - alpha - beta

Interpretation:

* Wenn sich Linien kreuzen, verändert sich die optimale H/k-Kombination.
* Wenn eine H/k-Kombination in allen Slices oben bleibt, ist sie robust.
* Wenn bei höherem beta andere H/k-Kombinationen gewinnen, spricht das für einen Kostentrade-off.
* Wenn bei höherem gamma andere H/k-Kombinationen gewinnen, spricht das für einen Zeittrade-off.

---

## 13. Full Weight-Space Winner Map

---

Erzeuge eine vollständige Gewichtungsraum-Auswertung.

Grid:

* alpha von 0.75 bis 1.00 in 0.01-Schritten
* beta von 0.00 bis 1-alpha in 0.01-Schritten
* gamma = 1 - alpha - beta

Für jede Gewichtung:

* Berechne Utility für alle H/k-Kombinationen.
* Bestimme die beste H/k-Kombination.
* Speichere:

  * alpha
  * beta
  * gamma
  * best_h
  * best_k
  * best_candidate_id
  * best_utility

Visualisiere:

1. Winner-Map:

   * x-Achse: beta
   * y-Achse: gamma
   * Farbe: best_candidate_id
   * alpha ergibt sich implizit aus 1 - beta - gamma

2. Markiere zusätzlich die vier festen Profile als Punkte:

   * main_accuracy_first: 0.90 / 0.05 / 0.05
   * cost_sensitive: 0.80 / 0.15 / 0.05
   * time_sensitive: 0.80 / 0.05 / 0.15
   * stress_80: 0.75 / 0.125 / 0.125

3. Gewinnerhäufigkeit:

   * Balkendiagramm: Welche H/k-Kombination gewinnt in wie viel Prozent des Gewichtungsraums?

Optional:

* Wenn Plotly ternary verfügbar ist, baue zusätzlich eine ternäre Darstellung:

  * Ecke α = Success
  * Ecke β = Tokenkosten
  * Ecke γ = Laufzeit
  * Farbe = bestes H/k
* Falls nicht, nutze die beta/gamma Scatter-Map.

Wichtige Interpretation:

* alpha=1.00 ist nur ein theoretischer Success-only-Referenzpunkt.
* Die eigentliche Interpretation fokussiert auf Bereiche, in denen Tokenkosten und Laufzeit berücksichtigt werden.
* Wenn ein H/k über große Teile des Gewichtungsraums gewinnt, ist es robust.
* Wenn das Optimum stark wechselt, liegt ein starker Trade-off zwischen Success, Kosten und Zeit vor.

---

## 14. Site-Level Comparison

---

Wenn `site` vorhanden ist, wiederhole die Hauptanalyse je Site.

Mögliche Sites:

* reddit
* gitlab
* shopping
* shopping_admin
* unknown

Für jede Site:

* H/k-Aggregation
* Utility nach Main-Gewichtung
* bestes H/k
* Top 3
* optional Heatmap oder 3D-Spike-Map

Erzeuge Vergleichstabelle:

* site
* best_h
* best_k
* runs
* tasks
* success_rate
* avg_tokens
* avg_runtime_s
* U_main_accuracy_first

Ziel:
Zeigen, ob unterschiedliche Site-Kategorien unterschiedliche optimale Planungshorizonte und Validierungsintervalle haben.

---

## 15. Export Final Analysis Tables

---

Speichere zentrale Ergebnisse als CSV im Experimentordner:

* final_analysis_hk_global.csv
* final_analysis_persona_winners.csv
* final_analysis_top_candidates.csv
* final_analysis_weight_sensitivity_top_candidates.csv
* final_analysis_weight_space_winner_map.csv
* final_analysis_winner_counts.csv
* optional final_analysis_hk_by_site.csv
* optional final_analysis_site_winners.csv

Wenn Plotly verwendet wird, speichere HTML-Plots im gleichen Ordner.

---

## 16. Automated Markdown Interpretation

---

Füge nach den Tabellen/Plots kurze Markdown- oder Print-Ausgaben mit automatisierten Kernaussagen ein.

Diese Aussagen sollen aus den berechneten Daten generiert werden, nicht hart codiert.

Beispiele:

* "Die beste H/k-Kombination nach Main-Utility ist H=X, k=Y."
* "Diese Kombination erreicht eine Success Rate von S, durchschnittlich T Tokens und eine Laufzeit von τ Sekunden."
* "Diese Kombination bleibt über N von 4 festen Gewichtungsprofilen optimal."
* "Im vollständigen Gewichtungsraum gewinnt H=X,k=Y in Z Prozent der betrachteten Gewichtungen."
* "Bei stärkerer Gewichtung der Tokenkosten verschiebt sich das Optimum zu ..."
* "Bei stärkerer Gewichtung der Laufzeit verschiebt sich das Optimum zu ..."
* "Die Top-3-Kandidaten nach Main-Utility sind ..."

============================================================
CODE-QUALITÄT
=============

Schreibe wiederverwendbare Funktionen:

* `detect_column(df, candidates, required=False, label="")`
* `load_summary()`
* `prepare_eval_df(summary)`
* `minmax_norm(series)`
* `aggregate_hk(eval_df, group_cols=None)`
* `compute_utility(row, alpha, beta, gamma)`
* `compute_utility_columns(hk_df, personas)`
* `get_persona_winners(hk_df, personas)`
* `get_top_candidates(hk_df, utility_col="U_main_accuracy_first", n=5)`
* `compute_weight_sensitivity(top_candidates, personas_or_slices)`
* `compute_weight_space_winner_map(hk_df, alpha_min=0.75, alpha_max=1.0, step=0.01)`
* `plot_3d_spike_map(hk_df, utility_col, title, top_candidates=None)`
* `plot_top_candidate_sensitivity(sensitivity_df)`
* `plot_weight_space_winner_map(winner_map, fixed_profiles=None)`
* `plot_winner_counts(winner_map)`

Anforderungen:

* Keine unnötigen globalen Nebenwirkungen.
* Keine hart codierten Spalten ohne Fallback.
* Keine stillen Fehler.
* Tabellen mit `display()` anzeigen.
* Plots mit klaren Titeln, Achsenbeschriftungen und Legenden.
* Notebook soll nach Ausführung alle Tabellen und Plots erzeugen.
* Export-Dateien sollen im Experimentordner gespeichert werden.

============================================================
WICHTIGE METHODISCHE FORMULIERUNG
=================================

Füge im Notebook eine kurze methodische Erklärung ein:

Die Gewichtungsprofile sind keine gelernten Modellparameter, sondern Bewertungspräferenzen. Die Hauptanalyse verwendet eine success-dominante Gewichtung. Alternative Gewichtungen dienen der Sensitivitätsanalyse. Dadurch kann geprüft werden, ob die optimale H/k-Kombination robust bleibt, wenn Tokenkosten oder Laufzeit stärker berücksichtigt werden.

H und k werden nicht direkt als Kosten modelliert. Stattdessen wird untersucht, wie sich unterschiedliche H/k-Kombinationen empirisch auf Erfolgsrate, Tokenverbrauch und Laufzeit auswirken.

============================================================
ERWARTETES ERGEBNIS
===================

Am Ende des Notebooks sollen sichtbar sein:

1. Übersicht über die geladene summary.csv
2. Formel und methodische Erklärung der Utility-Funktion
3. Globale H/k-Ergebnistabelle
4. Persona-Winner-Tabelle
5. Top-3/Top-5 H/k-Kandidaten
6. 3D-Spike-Map für Main-Utility
7. Sensitivitätsanalyse der Top-Kandidaten über alpha/beta/gamma-Slices
8. Full Weight-Space Winner-Map
9. Gewinnerhäufigkeit im Gewichtungsraum
10. Optional Site-Level-Vergleich
11. Exportierte CSV-Dateien und HTML-Plots

Bitte setze diese Änderungen direkt im Notebook um.
