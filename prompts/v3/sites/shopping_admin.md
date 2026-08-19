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
- For Shopping Admin tasks phrased as "Get the top N search term(s)" or
  "Get customer email(s)", do not finish as navigation after opening a grid or
  detail page. These are retrieval tasks: use the relevant admin grid/report,
  compute the requested ranking/count, and return exactly the requested list or
  scalar schema.
- For top search terms, rank by the visible use/search-count column in the
  Search Terms grid/report, not alphabetic order, recency, or a term detail
  page. For customer emails by order count, use the Sales Orders grid as the
  source of truth, group order rows by customer email, include all states when
  the task says any state, and return all emails tied at the requested count or
  rank.
- For customer-contact retrieval by phone number, use Customers > All Customers
  and filter/search the phone column by the exact number. Read the requested
  name and email from that same matching row or customer detail, then return
  only the requested object keys.
- For monthly order-count retrieval, use the Magento Sales Orders report/grid,
  apply the requested inclusive date range, choose Period Type = Month when
  available, apply the requested order status such as completed/complete, and
  return exactly the requested month/count object list in chronological order.
- For order payment/name retrieval, use Sales > Orders as the source of truth.
  Apply requested status filters exactly, such as complete/completed,
  canceled/cancelled, or non-cancelled. Sort by order date when the task asks
  for last/newest/oldest orders. For totals or differences, read Grand
  Total/Order Total/Paid values for the requested orders, compute the requested
  single numeric aggregate, and return one number only. For billing-name tasks,
  open the target order detail and read the Billing Address/Name field, not the
  shipping name or generic customer account name.
- For order-item retrieval, filter the Sales > Orders grid by the requested
  status and sort by the visible purchase/created-date column before opening
  the first matching order. Read item-level values from `Items Ordered`: a
  final/discounted item price is the `Price` column, not Original Price,
  Subtotal, Row Total, or Grand Total. Collect every item and numerically sort
  the result objects when the request specifies low-to-high or high-to-low.
- For inventory/product-attribute retrieval, use the admin Catalog > Products
  grid or product detail pages as the source of truth. Apply the requested
  quantity/stock condition exactly, such as 0 units left, 3 units left, or a
  2-3 unit range. Prefer concrete simple/variant product rows over configurable
  parent rows when the requested answer asks for variant attributes such as
  color, size, or material. For material, read the actual material/composition
  attribute rather than product technology, collection, or name tokens. Collect
  all matching rows/pages after filtering unless the task asks for only one
  item, then return only the requested fields/schema.
- For admin review nickname retrieval, use the Product Reviews/Customer Reviews
  admin grid, filter or inspect by product/category and rating threshold, and
  return only the requested customer nickname strings. Opening a review detail
  page is not completion. For plural nickname tasks, continue through all
  matching review rows/pages after filtering; returning only a visible subset is
  incomplete.
- For review title/rating retrieval, use the reviews grid or matching product's
  review context, collect every review matching the product and rating threshold,
  and return only the requested fields. A zero-result product text filter can be
  unsupported; clear it and inspect available review/product fields before
  concluding that no matching review exists.
- For review-count retrieval in a period, apply the requested created-date range
  in the review grid and use the refreshed total record count, not only the
  number of rows on the visible page. Return the single requested count in its
  required container.
