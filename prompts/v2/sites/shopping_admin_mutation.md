# Shopping Admin Mutation Context

- Mutation tasks in Magento admin require a durable state-changing control such
  as Save, Submit, Add Comment, Create, Add Option, or an equivalent visible
  admin action. Do not finish with SUCCESS after only opening a detail page,
  filling a field, clicking a tab, or navigating to a prepared form.
- Before saving, extract the task's required mutation facts into a short
  checklist and verify that every fact is represented in the visible form: the
  target object, scope/audience, status/enabled state, numeric value, action
  type, variant attributes, and whether the task means setting a value or adding
  to an existing value. Do not save or finish while any required fact from the
  task has only been mentioned in notes/description text but not entered into
  the matching admin field.
- After clicking a durable Save/Submit control, watch for a save confirmation,
  redirect, or matching network/state change. If the requested mutation was
  submitted and no further task facts remain, finish immediately with SUCCESS
  instead of continuing to navigate or looping until the step budget expires.
- If the relevant object is visible but the page exposes no grounded control for
  the requested state change after inspection, finish with
  `ACTION_NOT_ALLOWED_ERROR` instead of looping or returning `UNKNOWN_ERROR`.
- Order notification/message tasks usually start from `/admin/sales/order/`.
  Filter or search the orders grid for the requested customer and order status,
  open the most recent matching order detail, fill the order history/comment
  message exactly, enable the customer-notification control when present, and
  click Submit Comment/Add Comment before finishing. Do not use Send Email,
  Hold, Invoice, Ship, or other order action buttons as substitutes for the
  order-history comment submission.
- Order tracking tasks start from the requested order detail, then use the
  Ship/New Shipment workflow. Add tracking information, choose the requested
  carrier when available, fill the tracking number exactly, and submit/save the
  shipment. Do not finish after only opening the order or typing a tracking
  number. Leaving the carrier as Custom is not equivalent to choosing a named
  carrier such as USPS when the task asks for that carrier.
- Review moderation tasks should use the Magento admin product reviews grid,
  not storefront reviews. Filter/inspect by the visible criteria in the task:
  review status, star rating, reviewer/nickname, author name, title, or review
  text. For approve tasks, open each matching review and save it with Approved
  status. For delete tasks, delete only matching reviews. If the task says all
  reviews matching a reviewer/name or above/below a threshold, continue through
  visible matching rows/pages until all qualifying reviews have been acted on,
  then finish with SUCCESS.
- If the review grid exposes checkboxes plus an Actions/Mass Actions control,
  it is acceptable to select all currently visible rows that satisfy the
  requested status/rating threshold and apply the matching Approve/Delete action.
  If bulk actions are not clearly available, process each matching review
  individually and verify each save/delete before moving to the next review.
- For delete confirmations or modal dialogs, use only current visible dialog
  candidates. If an OK/Confirm candidate is not exposed after the dialog
  appears, press Enter once to accept the active confirmation. Do not reuse
  stale DOM ids or background buttons after a dialog opens.
- Marketing price rule tasks require the correct rule type before filling the
  form. Use Cart Price Rules / promo quote rules for checkout, cart, or shopping
  cart discounts. Use Catalog Price Rules / promo catalog rules for
  catalog-wide or all-products discounts. Do not switch between these rule
  types after the task wording identifies the target.
- For price rules, a durable success needs the rule saved with the rule name,
  active status, website, customer group, discount action, and numeric discount
  amount in the proper fields. For percentage discounts, choose the percent
  action and enter only the numeric percent in Discount Amount. For fixed
  amount discounts on a purchase/cart, choose the fixed/cart amount discount
  action and enter only the numeric amount in Discount Amount. Do not put the
  discount only in Description, and do not finish after only filling the rule
  name or clicking tabs.
- When a price rule says registered customers and no coupon is mentioned, look
  for the ordinary registered/general customer group option and a no-coupon
  coupon type. Select the normal/default website scope visible in the form, then
  verify these selections before saving. These are form-field requirements, not
  explanatory notes.
- Product-description tasks that depend on review counts require two phases:
  determine the requested count from the admin review grid using visible product
  and rating/status filters, then edit the named product in the product catalog.
  Save the description/short-description field with the exact task-specified
  phrase derived from that count. Do not stop after inspecting reviews.
- Stock-status tasks should filter the product grid by the exact product name
  from the task, prefer the matching configurable/parent product when a base
  product is named, set the stock status to the requested value such as Out of
  Stock, and save the product. Opening a related variant or only filtering the
  grid is not enough.
- Inventory quantity tasks should filter the product catalog by the exact
  product name and variant attributes from the task. If the task says inventory
  was received, add the received amount to the current visible quantity for each
  matching variant; do not replace the quantity with the shipment amount unless
  the task says to set it exactly. If the task says every size or every variant
  of a color/product, update and save each matching simple variant, not only the
  configurable parent.
- Product price update tasks should filter the product catalog by exact product
  name and variant attributes such as color and size. Edit the matching simple
  variants rather than only the configurable parent. Treat the product grid as a
  checklist: identify every simple-product row whose name/SKU/attribute columns
  match the requested product, color, and size condition, then open and save
  each matching simple product one by one. For percentage changes, read the
  current visible price and calculate the new price from it. For fixed amount
  changes, add or subtract the amount from the current visible price. Save every
  matching variant required by wording such as every size, size L and above, or
  extra small and small; one parent/configurable product save is incomplete.
- Product creation tasks usually start from `/admin/catalog/product/`. Use the
  Add Product/New Product flow, choose the requested product type, choose an
  attribute set compatible with the product type, fill required visible fields
  from the task intent such as name, price, quantity, stock status, size, and
  color, then save. Before filling fields, verify the page is a new product
  form, usually a `/catalog/product/new/.../type/simple` URL or New Product
  title. If you land on an existing product edit page, return to the product
  catalog and restart the Add Product/New Product flow instead of editing that
  product.
- Configurable product option/variant tasks should first make sure the requested
  option exists as a global product attribute option. For size tasks, open the
  visible Size product attribute/options workflow, add the missing option, and
  save the attribute before editing the configurable product variants.
- After required attribute options exist, open the named configurable product
  from the product catalog, add only the requested size/color variant
  combinations, preserve existing variants, and save the configurable product.
  Do not create an unrelated product.
- Magento admin dropdowns and comboboxes must use supported BrowserGym actions:
  click/focus the current dropdown candidate, fill/type visible option text only
  if an input is exposed, then click the current option bid or press Enter. Do
  not emit unsupported `select(...)` actions.
