Create a high-level plan for the following WebArena-Verified task.

Task metadata:
- task_id: {{task_id}}
- site: {{site}}
- start_urls: {{start_urls}}
- task_intent: {{task_intent}}
- planning_horizon_h: {{h}}

Initial observation:
{{initial_observation}}

Use the observation as the current browser state. If this is a replanning call,
reflect on whether previous actions appear successful from this observation and
plan only the remaining work.

Known site scope:
{{site_scope}}

Known constraints:
{{known_constraints}}

Previous plan, if any:
{{previous_plan}}

Evaluator feedback, if any:
{{evaluator_feedback}}

Controller decision, if this is replanning:
{{controller_decision}}

Planning requirements:
- Use numbered subgoals internally, but return them in the required JSON schema.
- Each subgoal should be a logical unit of work, not a single click or keystroke.
- Include concrete task values from the user request, such as repo names,
  labels, product terms, categories, forums, filters, or output fields.
- If the current page shows intermediate results, update the plan to use those
  results. If results are not visible yet, plan to search or filter first.
- If the task asks for a product page and the current page is a search results
  page, plan to open a concrete matching product detail link next.
- If the task asks for the most recent forum post and the current page is a
  forum overview, plan to use the newest-post view or a visible newest-post link
  before returning data.
- For RETRIEVE tasks, the final subgoal must be to return the exact requested
  fields in the WebArena-Verified response schema after they are visible.
- Do not use evaluator metadata, reference answers, hidden trajectories, or gold
  final URLs unless they are explicitly present in this prompt.

Return valid JSON only according to the required Planner schema.
