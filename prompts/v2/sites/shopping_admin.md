# Shopping Admin Executor Context

- Magento admin grids are often under `/admin/customer`, `/admin/catalog`,
  `/admin/sales`, or `/admin/review`.
- Admin sidebars and menu links are often more reliable via their exact
  `link_candidates` `href`; use `goto("href")` for navigation when a matching
  admin link is visible.
- Use admin grids and filters before opening detail pages.
- Customer tasks usually start from `/admin/customer/index`.
- Magento admin sales/tax report navigation must end on the filtered report
  state, not the unfiltered report landing page. Sales order reports use
  `/admin/reports/report_sales/sales/filter`; tax reports use
  `/admin/reports/report_sales/tax/filter`. Use `report_type=created_at_order`
  and compute `from`/`to` from the date stated in the task using ISO
  `YYYY-MM-DD` dates. Example: if today is March 15, 2023, last year is
  `2022-01-01` to `2022-12-31`, while this year is `2023-01-01` to
  `2023-03-15`. Do not use the whole current year when the task says "this
  year" and gives today's date.
- Magento admin dropdowns and comboboxes must use supported BrowserGym actions:
  click/focus the current dropdown candidate, fill/type the visible option text
  only if an input is exposed, then click the current option bid or press Enter.
  Do not emit unsupported `select(...)` actions.
- For aggregate RETRIEVE tasks, apply the requested filters first and return the
  exact requested scalar/list/object schema.
