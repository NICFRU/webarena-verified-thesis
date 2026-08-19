# Shopping Executor Context

- Catalog search usually uses `/catalogsearch/result/?q=<query>`.
- Filling a search box alone is not enough; submit with Enter, a search button,
  or direct search URL navigation.
- Product detail pages usually end in `.html`.
- Root-level `.html` product URLs are often detail pages; nested category paths
  and `catalogsearch/result` pages are usually intermediate.
- For product-page NAVIGATE tasks, search/browse first, then open a matching
  visible product detail link.
- For category-page NAVIGATE tasks with a price filter, open the requested
  specific category page rather than a search results page or broad parent
  category. Apply the requested filter on that category page; for "under X",
  preserve the bound as a `0-X` price filter when the URL uses `price=...`.
  Use the category phrase from the task to choose the most specific visible
  category link whose text or href contains those category terms, then add or
  preserve the price filter on that category URL.
- For product-page NAVIGATE tasks asking for the most/least expensive item in a
  category, open the specific category listing, sort by price in the requested
  direction, then open the matching product detail page. Do not finish on the
  sorted listing itself.
- For sorted-listing NAVIGATE tasks that ask to pull up all listings for a
  search phrase, search for the exact phrase and apply the requested sort on
  that results/listing page. Finish on the sorted listing; do not open a product
  detail page unless the task asks for a product page.
- For order-detail NAVIGATE tasks, open account order history, identify the
  requested order by visible status/date such as the most recent processing
  order, and open that order's detail/view page before finishing.
- For purchase or cart MUTATE tasks, perform the actual add-to-cart/checkout/cart
  action before finishing.
- For lowest-unit-price cart tasks, compare all relevant open/current product
  pages before adding anything. Use visible price and quantity/unit text to
  choose the lowest per-unit item, then add only that product to the cart. Once
  the chosen product is added and the cart or confirmation shows it, finish with
  `SUCCESS` immediately instead of revisiting product pages or adding more
  products.
- For wishlist MUTATE tasks, click the product detail Add to Wish List/Wishlist
  control and verify the wishlist confirmation/state; do not add the product to
  the cart. If the wishlist form exposes or carries a quantity field, keep or
  set the intended quantity to `1` unless the task asks for another quantity.
- For newsletter MUTATE tasks, fill and submit the newsletter/email subscription
  form and verify the confirmation.
- For account address-update MUTATE tasks, use the account address book/edit
  address form, not order-history delivery-address pages. Keep address line 1
  and line 2 separate: apartment, suite, unit, or house details belong in the
  second street/address line when the form provides one. Save the address and
  finish after the updated address or save confirmation is visible.
- For contact/refund/coupon form preparation tasks, collect required order/SKU/
  amount/product details from account/order pages, then fill the Contact Us form.
  If the task says "leave ready for review" or "do not submit", avoid the real
  site submission endpoint, but use any visible preview/check/capture/dummy form
  action that preserves the filled form state for review. Finish only when the
  filled fields are visibly ready or the non-final capture has recorded them.
- For product review-writing tasks, open the purchased product/review form,
  select the requested star rating, fill nickname/summary/review text exactly,
  submit, and verify confirmation. Do not treat review-writing as a RETRIEVE
  review-reading task.
- For review-reading RETRIEVE tasks, stay on the product review section/page,
  inspect visible review text, author, and star rating, and return only authors
  whose review text satisfies the requested mention terms and rating condition.
  If the task asks for review titles with a rating threshold such as 2 stars or
  below, collect only titles from reviews whose visible rating satisfies that
  threshold. Continue through visible review pagination when the task asks for
  all matching reviews, and return only the requested title/value schema. Once
  the review section is reached, do not repeatedly scroll forever: if scrolling
  exposes no new review rows or next-page controls, finalize with the matching
  requested values collected so far, or an empty list when visible review
  evidence shows no matching reviews.
- For latest-order RETRIEVE tasks, open account order history, open the most
  recent order detail page, and return the visible status plus arrival date.
  Use `null` for arrival date when no delivery/arrival date is visible or the
  latest order is canceled.
- For order-field RETRIEVE tasks, open account order history, identify the
  order by requested status/date wording such as latest, most recent,
  processing, under delivery, or a named date window, then open the order detail
  when needed. Return only the requested visible field such as order number,
  grand total/total cost, status, or date in the exact requested schema.
- For last-ordered-date RETRIEVE tasks, open account order history and inspect
  relevant order pages/details for the requested product name or product type
  from the task. Choose the most recent matching order item by visible order
  date and return only that date in the requested format, such as `YYYY-MM-DD`.
  Use `null` only when inspected visible order evidence shows no matching
  product. Do not finalize from memory or from a guessed expected value: the
  final answer must be grounded by visible order evidence containing the
  matching product/item text and the order date, or by the currently inspected
  order detail that connects them.
- For RETRIEVE tasks about an item the user bought or purchased, use account
  order history to find the relevant order by month/year, date window, product
  name, or product category. Open the order detail when needed, read visible
  product options or variants such as color, size, width, height, dimensions,
  or option labels from the matching item, and return only the requested
  attribute value(s) in the exact requested schema.
- For order aggregate RETRIEVE tasks, inspect all relevant order-history pages,
  count only orders matching the requested status/date window, and sum visible
  grand/order totals including shipping and handling. Do not use page counts,
  row counts, subtotals, or unrelated statuses as the final answer.
- For refund/canceled-order RETRIEVE tasks, inspect account order history for
  the requested canceled status and date window, open matching order details
  when needed, include shipping only when requested, and return only the numeric
  refund amount.
- For price-range RETRIEVE tasks, search or filter to the requested brand or
  product set, inspect matching visible product prices across pages when needed,
  and return exactly the requested minimum/maximum numeric schema.
- For spend-by-category RETRIEVE tasks, inspect account order history for the
  requested date window, open relevant order details, and include only items
  matching the requested category or product type. Respect shipping/handling
  wording exactly: exclude shipping and handling when the task says not to
  consider them; include them only when explicitly requested.
