# Tables

This directory contains derived thesis table artifacts.

`notebooks/final_analysis.ipynb` does not overwrite these tables by default. The
notebook currently sets:

```python
EXPORT_TABLES = False
EXPORT_FIGURES = True
```

Reason: a test execution into `thesis_results_output_test/` reproduced 54 of the
91 existing table files. The remaining tables come from earlier analysis steps,
especially `notebooks/notebooks/results_discussion_chapter.ipynb`, and should not
be silently replaced by a partial export.

The tables use `../data/final_summary.csv` and `../data/final_summary.json` as
source artifacts. Those files are treated as read-only analysis inputs.

Main table groups:

- Success and utility comparisons: `comparison_metrics_*`, `success_*`,
  `standard_utility_*`, `additive_utility_*`.
- H/k and k>0 analyses: `configuration_group_*`,
  `standard_utility_axis_zero_comparison.csv`,
  `success_axis_zero_comparison_pct.csv`,
  `standard_utility_marginal_h_vs_k_comparison.csv`.
- Process and failure diagnostics: `process_by_hk.tex`,
  `runtime_checks_by_hk.tex`, `replan_by_hk.tex`, `failure_*`.
- Site and task metadata: `site_*`, `task_solvability*`,
  `intent_bucket_success.tex`, `evaluator_*`.
- Sensitivity and free-weight analyses: `weight_*`, `free_weight_*`,
  `spike_utility_*`.

To intentionally regenerate the subset implemented in `final_analysis.ipynb`,
set `EXPORT_TABLES = True` in the export section and run the notebook from top to
bottom. Keep a backup of the current table directory before doing that.
