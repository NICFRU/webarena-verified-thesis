# GitLab Executor Context

- GitLab project pages usually use `/<namespace>/<project>`.
- Issues usually use `/<namespace>/<project>/-/issues`.
- Files usually use `/<namespace>/<project>/-/blob/<branch>/<path>`.
- Dashboard todos are usually under `/dashboard/todos`.
- For open issues, use `state=opened`.
- For label filters, use `label_name[]=<label text>`, not `labels=` or
  `labels[]=`.
- For label exclusions such as "except BUG" or "without label X", use
  `not[label_name][]=<label text>`, not `label_name[]=-bug`.
- For clone URL retrieval tasks, open the named project, inspect the Clone
  control/dropdown or visible clone field, choose the requested protocol
  (SSH/HTTPS), and finish as RETRIEVE with only the URL string in
  `retrieved_data`.
- For commit, contributor, member, access, or repository metadata retrieval
  tasks, stay read-only. Inspect visible repository pages, filters, rows, and
  fields, then finish as RETRIEVE. Do not use edit, invite, save, commit, or
  submit controls unless the task is explicitly a state-changing MUTATE task.

## GitLab State-Changing Workflows

- GitLab buttons, dropdowns, modals, sidebars, and editors often regenerate
  `bid`s after each click. Use only exact current bids from `action_candidates`.
  If the needed control is not listed, open/refocus the visible container,
  wait once, scroll, or use a visible same-site href; do not guess old bids or
  visible labels.
- Fork tasks require opening the concrete project fork form and submitting the
  current Fork/Create control. A namespace or project list page is not enough.
- Group/member tasks require both the created group/project context and the
  requested member invitations. Do not use the members table Filter field as an
  invitation input.
- For member invitations with multiple named users, add every requested user to
  the invite modal before submitting. GitLab may show selected users as chips,
  tokens, or rows; do not click Invite/Add after only the first matching user is
  selected.
- File-edit tasks that mention the simple online file editor should use the
  simple edit form, not the full Web IDE when avoidable. Edit only the minimal
  requested text, then commit/save; never place a whole HTML document in JSON.
- Profile status/homepage tasks are user-profile settings tasks: open the
  profile/status/settings form, change the requested field, save, and verify
  the visible saved value.
- Star tasks require clicking the Star control on each requested project and
  tracking how many projects have changed state.
- For "top starred/stared repos" tasks, start from GitLab Explore/Projects and
  use the sort order for most stars, e.g. `/explore/projects?sort=stars_desc`
  when a same-site URL is needed. Treat the visible list order as the ranking,
  open each project page in order, and click only the current project-page
  `Star` control. Never click `Unstar`, `Starred`, starrers counts, forks,
  issues, or merge request links for a star task. If a project already shows
  `Unstar` or `Starred`, count it as already starred and return to the sorted
  Explore/Projects list for the next unprocessed project.
- Merge-request reply tasks require submitting the actual reply/comment. Issue
  assignment, issue creation, and milestone tasks require using the respective
  GitLab form controls and verifying the created/updated state.
- Merge-request creation/reviewer tasks may be permission- or state-gated. If
  the relevant repository has been inspected and no valid New merge request,
  submit, source/target branch, or reviewer assignment control is available,
  finish with `ACTION_NOT_ALLOWED_ERROR` rather than looping.
- Merge-request reply tasks are a fragile GitLab sub-class: the task phrase
  "assigned to me for <topic>" must resolve to the assigned MR matching that
  topic, not merely any global search result. Prefer assigned-MR/dashboard
  context over global GitLab search. If several MRs match the same topic, do not
  finish until the project, title/topic, last comment author, and submitted note
  are consistent with the task instruction.
