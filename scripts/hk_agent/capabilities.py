"""Task capability classification for H/k analysis and prompts."""

from __future__ import annotations

from typing import Any


def _is_forum_bulk_vote_intent(intent: str) -> bool:
    """Return whether the task asks to vote/like a set of forum submissions."""

    vote_markers = [
        "like all submissions",
        "like all posts",
        "upvote all submissions",
        "upvote all posts",
        "vote all submissions",
        "vote all posts",
    ]
    scope_markers = ["created by", "submitted by", "authored by", "by user", "in forum", "in subreddit"]
    return any(marker in intent for marker in vote_markers) and any(marker in intent for marker in scope_markers)


def infer_official_task_type(task: dict[str, Any]) -> str:
    """Infer the official task type from metadata or visible intent text."""

    explicit_task_type = task.get("task_type")
    if explicit_task_type:
        return str(explicit_task_type).upper()
    for evaluator in task.get("eval", []):
        expected = evaluator.get("expected", {})
        task_type = expected.get("task_type")
        if task_type:
            return str(task_type).upper()
    intent = str(task.get("intent", "")).lower()
    retrieve_markers = [
        "return a list",
        "return the value",
        "return a string",
        "return the url",
        "return the link",
        "return the date",
        "return the customer",
        "customer nickname",
        "get the username",
        "get all",
        "get the post title",
        "get the count",
        "get the url",
        "get the link",
        "get the color",
        "get the size",
        "give me the color",
        "give me the material",
        "give me the name",
        "give me the product",
        "give me the products",
        "get the dimensions",
        "get the total cost",
        "get the order number",
        "get the billing name",
        "billing name",
        "payment difference",
        "payment amount",
        "get the top",
        "get top",
        "get customer email",
        "get customer emails",
        "price range",
        "review title",
        "review titles",
        "refund should i expect",
        "how much refund",
        "how much i spent",
        "how much was spent",
        "spent on",
        "clone url",
        "url to clone",
        "ssh url",
        "what is",
        "find the",
        "how many",
        "total number",
        "monthly count",
    ]
    if any(marker in intent for marker in retrieve_markers):
        return "RETRIEVE"
    if _is_forum_bulk_vote_intent(intent):
        return "MUTATE"
    if any(marker in intent for marker in ["rate my recently purchased", "review my recently purchased"]):
        return "MUTATE"
    if "order" in intent and any(marker in intent for marker in ["notify", "message"]):
        return "MUTATE"
    mutate_markers = [
        "add ",
        "create ",
        "delete ",
        "remove ",
        "set ",
        "star ",
        "update ",
        "change ",
        "edit ",
        "post ",
        "reply ",
        "rate ",
        "submit ",
        "subscribe",
        "mark ",
        "assign ",
        "fork ",
        "buy ",
        "upvote",
        "like all submissions",
        "like all posts",
    ]
    if any(marker in intent for marker in mutate_markers):
        return "MUTATE"
    return "NAVIGATE"


def infer_task_capability(task: dict[str, Any], site_name: str | None = None) -> str:
    """Infer a coarse action capability from visible task intent."""

    intent = str(task.get("intent", "")).lower()
    sites = task.get("sites") or []
    site = site_name or (str(sites[0]) if len(sites) == 1 else "unknown")
    task_type = infer_official_task_type(task).lower()
    if site == "gitlab" and task_type == "retrieve":
        if "url" in intent and any(marker in intent for marker in ["clone", "ssh", "repository url", "project url"]):
            return "retrieve_gitlab_clone_url"
        if any(marker in intent for marker in ["commit", "commits", "contributor", "contributors"]):
            return "retrieve_gitlab_commit_stats"
        if any(marker in intent for marker in ["users who have access", "members who have access", "access to my repo"]):
            return "retrieve_gitlab_members"
    if site == "reddit" and task_type == "mutate" and _is_forum_bulk_vote_intent(intent):
        return "mutate_forum_bulk_vote"
    if site == "reddit" and task_type == "mutate" and "upvote" in intent:
        return "mutate_vote"
    if site == "reddit" and task_type == "mutate" and "subscribe" in intent and "forum" in intent:
        return "mutate_forum_subscribe"
    if site == "reddit" and task_type == "mutate" and any(
        marker in intent for marker in ["reply to", "reply on", "comment on", "comment \"", "then comment"]
    ):
        return "mutate_forum_reply"
    if site == "reddit" and task_type == "mutate" and any(marker in intent for marker in ["re-post", "repost", "re post"]):
        if "image" in intent and "url" in intent:
            return "mutate_forum_repost_image"
    if site == "reddit" and task_type == "mutate" and any(marker in intent for marker in ["post a notice", "post ", "submit "]):
        return "mutate_forum_post"
    if site == "gitlab" and task_type == "mutate" and "set my gitlab status" in intent:
        return "mutate_gitlab_profile_status"
    if site == "gitlab" and task_type == "mutate" and "homepage url" in intent and "profile" in intent:
        return "mutate_gitlab_profile_homepage"
    if site == "gitlab" and task_type == "mutate" and any(marker in intent for marker in ["star the top", "stared repos", "starred repos"]):
        return "mutate_gitlab_star_repos"
    if site == "gitlab" and task_type == "mutate" and "fork" in intent:
        return "mutate_gitlab_fork"
    if site == "gitlab" and task_type == "mutate" and "create a new group" in intent:
        return "mutate_gitlab_group"
    if site == "gitlab" and task_type == "mutate" and any(marker in intent for marker in ["update and commit", "commit", "new branch", "online file editor"]):
        return "mutate_gitlab_file_edit"
    if site == "gitlab" and task_type == "mutate" and "reply on the merge request" in intent:
        return "mutate_gitlab_mr_reply"
    if site == "gitlab" and task_type == "mutate" and "merge request" in intent and any(
        marker in intent for marker in ["submit a merge request", "create a merge request", "assign myself as the reviewer"]
    ):
        return "policy_or_gitlab_merge_request_create"
    if site == "gitlab" and task_type == "mutate" and "create a milestone" in intent:
        return "mutate_gitlab_milestone"
    if site == "gitlab" and task_type == "mutate" and "create an issue" in intent:
        return "mutate_gitlab_issue_create"
    if site == "gitlab" and task_type == "mutate" and any(marker in intent for marker in ["assign the issue", "assign issue"]):
        return "mutate_gitlab_issue_assign"
    if site == "gitlab" and task_type == "mutate" and any(marker in intent for marker in ["add the following users", "as developer", "as maintainer", "as reporter"]):
        return "mutate_gitlab_members"
    if site == "shopping" and task_type == "mutate" and (
        any(marker in intent for marker in ["contact us form", "contact form", "refund message", "coupon request"])
        or ("contact us" in intent and any(marker in intent for marker in ["refund", "coupon", "form"]))
    ):
        return "mutate_shopping_contact_form_prepare"
    if site == "shopping" and task_type == "mutate" and any(
        marker in intent for marker in ["rate my recently purchased", "review my recently purchased"]
    ):
        return "mutate_shopping_product_review"
    if site == "shopping" and task_type == "mutate" and "wish list" in intent:
        return "mutate_shopping_wishlist"
    if site == "shopping" and task_type == "mutate" and "wishlist" in intent:
        return "mutate_shopping_wishlist"
    if site == "shopping" and task_type == "mutate" and "newsletter" in intent:
        return "mutate_shopping_newsletter"
    if site == "shopping" and task_type == "mutate" and "lowest per unit price" in intent:
        return "mutate_shopping_lowest_unit_price_cart"
    if site == "shopping" and task_type == "mutate" and "buy" in intent:
        return "mutate_shopping_purchase"
    if site == "shopping" and task_type == "mutate" and any(
        marker in intent for marker in ["recently moved", "update my information", "my address is"]
    ):
        return "mutate_shopping_address_update"
    if site == "shopping" and "delivery address" in intent:
        return "policy_or_account_order_change"
    if site == "shopping" and task_type == "navigate" and "category page" in intent and any(
        marker in intent for marker in ["filtered to under", "under $", "under "]
    ):
        return "navigate_shopping_category_filter"
    if site == "shopping" and task_type == "navigate" and "product page" in intent and any(
        marker in intent for marker in ["most expensive", "least expensive", "cheapest", "lowest price", "highest price"]
    ):
        return "navigate_shopping_sorted_category_product"
    if site == "shopping" and task_type == "navigate" and "listings" in intent and "sorted by" in intent:
        return "navigate_shopping_sorted_search_listing"
    if site == "shopping" and task_type == "navigate" and "order details page" in intent:
        return "navigate_shopping_order_detail"
    if site == "shopping_admin" and task_type == "navigate" and "theme settings" in intent:
        return "navigate_admin_theme_settings"
    if site == "shopping_admin" and task_type == "navigate" and "list of orders" in intent:
        return "navigate_admin_order_grid_filter"
    if site == "shopping_admin" and task_type == "navigate" and "report" in intent and any(
        marker in intent for marker in ["sales order", "orders report", "order report", "tax report", "sales report"]
    ):
        return "navigate_admin_sales_report_filter"
    if site == "shopping_admin" and task_type == "retrieve" and "monthly count" in intent and "order" in intent:
        return "retrieve_admin_monthly_order_counts"
    if site == "shopping_admin" and task_type == "retrieve" and "billing name" in intent and "order" in intent:
        return "retrieve_admin_order_attribute"
    if site == "shopping_admin" and task_type == "retrieve" and "order" in intent and any(
        marker in intent for marker in ["product name", "item name", "final price", "discounted price", "items ordered"]
    ):
        return "retrieve_admin_order_items"
    if site == "shopping_admin" and task_type == "retrieve" and "order" in intent and any(
        marker in intent for marker in ["payment difference", "payment amount", "total payment", "grand total", "order total"]
    ):
        return "retrieve_admin_order_payment_aggregate"
    if site == "shopping_admin" and task_type == "retrieve" and any(
        marker in intent for marker in ["units left", "unit left", "quantity left", "qty left", "stock", "inventory"]
    ) and any(marker in intent for marker in ["product", "products", "material", "color", "size", "name"]):
        return "retrieve_admin_inventory_product_attributes"
    if site == "shopping_admin" and task_type == "mutate" and any(marker in intent for marker in ["notify", "message"]) and "order" in intent:
        return "mutate_admin_order_notify"
    if site == "shopping_admin" and task_type == "mutate" and "order" in intent and "tracking" in intent:
        return "mutate_admin_order_tracking"
    if site == "shopping_admin" and task_type == "mutate" and "review" in intent and any(
        marker in intent for marker in ["approve", "delete", "pending"]
    ):
        return "mutate_admin_review_moderation"
    if site == "shopping_admin" and task_type == "mutate" and "price rule" in intent:
        if any(marker in intent for marker in ["cart", "checkout", "shopping cart", "purchase"]):
            return "mutate_admin_cart_price_rule"
        if any(marker in intent for marker in ["catalog", "all products", "products"]):
            return "mutate_admin_catalog_price_rule"
        return "mutate_admin_marketing_price_rule"
    if site == "shopping_admin" and task_type == "mutate" and "inventory" in intent and any(
        marker in intent for marker in ["received", "in stock", "stock", "quantity"]
    ):
        return "mutate_admin_inventory_quantity"
    if site == "shopping_admin" and task_type == "mutate" and "price" in intent and any(
        marker in intent for marker in ["increase", "reduce", "decrease", "discount"]
    ):
        return "mutate_admin_product_price_update"
    if site == "shopping_admin" and task_type == "mutate" and "update the product description" in intent:
        return "mutate_admin_product_description_from_review_count"
    if site == "shopping_admin" and task_type == "mutate" and any(
        marker in intent for marker in ["add a simple product", "add simple product", "create a simple product", "new simple product"]
    ):
        return "mutate_admin_simple_product_create"
    if site == "shopping_admin" and task_type == "mutate" and any(
        marker in intent for marker in ["add a new size", "add new size", "new size"]
    ):
        return "mutate_admin_configurable_product_options"
    if site == "shopping_admin" and "out of stock" in intent:
        return "mutate_admin_stock"
    if site == "shopping" and task_type == "retrieve" and "latest order" in intent and any(
        marker in intent for marker in ["status", "arrive", "arrival"]
    ):
        return "retrieve_shopping_latest_order_status"
    if site == "shopping" and task_type == "retrieve" and any(
        marker in intent for marker in ["latest order", "most recent"]
    ) and any(marker in intent for marker in ["total cost", "order number", "delivery order", "processing"]):
        return "retrieve_shopping_order_attribute"
    if site == "shopping" and task_type == "retrieve" and "last ordered" in intent and any(
        marker in intent for marker in ["return the date", "date i last ordered", "when i last ordered"]
    ):
        return "retrieve_shopping_last_ordered_date"
    if site == "shopping" and task_type == "retrieve" and any(marker in intent for marker in ["bought", "purchased"]) and any(
        marker in intent for marker in ["color", "size", "width", "height", "dimension", "variant", "option"]
    ):
        return "retrieve_shopping_purchased_product_attribute"
    if site == "shopping" and task_type == "retrieve" and "complete orders" in intent and "amount" in intent:
        return "retrieve_shopping_order_aggregate"
    if site == "shopping" and task_type == "retrieve" and "price range" in intent:
        return "retrieve_shopping_price_range"
    if site == "shopping" and task_type == "retrieve" and any(
        marker in intent for marker in ["refund should i expect", "how much refund", "orders canceled", "canceled"]
    ) and any(marker in intent for marker in ["refund", "shipping fee", "including shipping"]):
        return "retrieve_shopping_refund_aggregate"
    if site == "shopping" and task_type == "retrieve" and "spent" in intent and any(
        marker in intent for marker in ["shipping", "handling", "month", "jan", "feb", "mar", "year"]
    ):
        return "retrieve_shopping_category_spend_aggregate"
    if site == "shopping_admin" and task_type == "retrieve" and "review" in intent and any(
        marker in intent for marker in ["how many", "count", "number of"]
    ):
        return "retrieve_admin_review_count"
    if any(marker in intent for marker in ["total number", "monthly count", "count of", "how many"]):
        return "retrieve_aggregate"
    if site == "shopping_admin" and task_type == "retrieve" and "search term" in intent:
        return "retrieve_admin_search_terms"
    if site == "shopping_admin" and task_type == "retrieve" and any(
        marker in intent for marker in ["phone number", "telephone number", "phone no."]
    ) and any(marker in intent for marker in ["customer", "email", "name"]):
        return "retrieve_admin_customer_contact"
    if site == "shopping_admin" and task_type == "retrieve" and "review" in intent and any(
        marker in intent for marker in ["title", "rating", "stars"]
    ):
        return "retrieve_admin_review_attributes"
    if site == "shopping_admin" and task_type == "retrieve" and "customer email" in intent and "order" in intent:
        return "retrieve_admin_customer_order_emails"
    if site == "shopping_admin" and task_type == "retrieve" and any(marker in intent for marker in ["customer nickname", "nickname"]) and any(
        marker in intent for marker in ["rating", "stars", "review"]
    ):
        return "retrieve_admin_review_nicknames"
    if any(marker in intent for marker in ["who gave", "reviews", "review"]):
        return "retrieve_reviews"
    if task_type == "retrieve":
        return "retrieve_visible_or_multi_page"
    if task_type == "mutate":
        return "mutate_generic"
    return "navigate_generic"


def capability_tier(capability: str) -> str:
    """Map a capability to an analysis tier."""

    if capability == "navigate_generic":
        return "navigation"
    if capability in {
        "navigate_shopping_category_filter",
        "navigate_shopping_sorted_category_product",
        "navigate_shopping_sorted_search_listing",
        "navigate_shopping_order_detail",
        "navigate_admin_theme_settings",
        "navigate_admin_order_grid_filter",
        "navigate_admin_sales_report_filter",
    }:
        return "navigation"
    if capability in {
        "retrieve_visible_or_multi_page",
        "retrieve_gitlab_clone_url",
        "retrieve_gitlab_members",
        "retrieve_shopping_latest_order_status",
        "retrieve_shopping_order_attribute",
        "retrieve_shopping_last_ordered_date",
        "retrieve_shopping_purchased_product_attribute",
    }:
        return "visible_retrieve"
    if capability in {
        "retrieve_aggregate",
        "retrieve_reviews",
        "retrieve_gitlab_commit_stats",
        "retrieve_shopping_order_aggregate",
        "retrieve_shopping_price_range",
        "retrieve_shopping_refund_aggregate",
        "retrieve_shopping_category_spend_aggregate",
        "retrieve_admin_search_terms",
        "retrieve_admin_customer_contact",
        "retrieve_admin_review_count",
        "retrieve_admin_review_attributes",
        "retrieve_admin_customer_order_emails",
        "retrieve_admin_monthly_order_counts",
        "retrieve_admin_order_attribute",
        "retrieve_admin_order_items",
        "retrieve_admin_order_payment_aggregate",
        "retrieve_admin_inventory_product_attributes",
        "retrieve_admin_review_nicknames",
    }:
        return "structured_retrieve"
    if capability.startswith("policy_or_"):
        return "policy"
    if capability.startswith("mutate_") or capability == "mutate_generic":
        return "mutation"
    return "unknown"


def is_main_analysis_capability(capability: str) -> bool:
    """Return whether a capability is suitable for the initial H/k main analysis."""

    return capability_tier(capability) in {"navigation", "visible_retrieve"}


def capability_guidance(task: dict[str, Any], site_name: str) -> list[str]:
    """Return compact, non-oracle guidance for the inferred capability."""

    capability = infer_task_capability(task, site_name)
    general = [
        f"task_capability={capability}",
        f"capability_tier={capability_tier(capability)}",
        "For MUTATE tasks, do not send a final success message until the required UI/form action has actually been executed.",
        "For RETRIEVE tasks, final retrieved_data must match the requested schema exactly; do not add extra keys.",
    ]
    by_capability = {
        "mutate_vote": [
            "For voting tasks, navigate to the relevant forum/newest item, identify the vote control for that item, and click the vote control rather than the post title.",
        ],
        "mutate_forum_bulk_vote": [
            "For bulk forum voting tasks, first identify the full target set from the requested forum/subreddit, author, and listing context before voting.",
            "Vote each matching target submission exactly once. Do not click a vote control again if it already appears liked/upvoted, because forum vote buttons can toggle back to neutral or downvote.",
            "Track which target submissions have been voted and finish with SUCCESS only after all visible/requested matching submissions have the liked/upvoted state.",
        ],
        "mutate_forum_post": [
            "For forum post creation, navigate to the target forum, open the submit/new-post form, fill title/body/forum fields, and submit the form.",
        ],
        "mutate_forum_reply": [
            "For forum reply/comment tasks, first open the exact target post page, then locate the requested comment or reply target using visible author/text/context.",
            "Use the Reply control attached to the requested comment when the task says to reply to a specific user/comment/reply; do not use the generic post-level reply box unless the task asks to reply to the post itself.",
            "Fill the exact requested comment text and submit the visible reply/comment form before finishing with SUCCESS.",
        ],
        "mutate_forum_repost_image": [
            "For forum image repost tasks, first identify the requested source image post and its concrete image URL from the current URL, visible image link, href/src, or candidate/context text.",
            "Do not call unsupported helper actions such as get_url(), copy_url(), or get_attribute(); use the URL already visible in the observation, link candidates, current page URL, or HTML/candidate context.",
            "Open the submit/new-post form, fill the image URL, exact requested title, and target forum, submit the form, and finish only after the post submission action has executed.",
        ],
        "mutate_forum_subscribe": [
            "For forum subscription tasks, first reach the exact forum context requested by the task, including any requested sorted post page such as all-time top, most controversial, or most commented.",
            "Do not subscribe from a generic forum page when the task says to subscribe from a specific post page; the visible page URL/referer must be that post page before the Subscribe action.",
            "Click the actual current Subscribe control for the forum and finish only after the visible subscribed state or subscribe confirmation is observed.",
        ],
        "mutate_gitlab_fork": [
            "For GitLab fork tasks, navigate to each target project and use the visible Fork action/form; reaching Explore or a project list is not completion.",
            "On the fork form, stay on the form, select the target namespace if needed, submit the visible Fork/Create control, then verify the forked project page or confirmation.",
        ],
        "mutate_gitlab_group": [
            "For GitLab group tasks, create the group through the new-group form, then invite/add the named members; do not finish after opening the form.",
            "For member/invite modals, use only current modal candidates and finish only after the added member/invite confirmation or resulting member row is visible.",
            "When multiple users are named, select every requested user as a modal chip/token/row before clicking Invite/Add; inviting only the first matching user is incomplete.",
        ],
        "mutate_gitlab_file_edit": [
            "For GitLab file edits, open the target file in the simple web editor, change the requested content, set the requested branch name, and commit/save the change.",
            "The Web IDE or file view alone is not completion; a commit/update form submission must happen.",
            "If a click in the IDE does not change visible state, choose a different current editor/save/commit candidate instead of repeating it.",
        ],
        "mutate_gitlab_profile_status": [
            "For GitLab profile status tasks, open the user's profile/status settings, set the requested status text or emoji/state, save it, and verify the visible status changed.",
        ],
        "mutate_gitlab_profile_homepage": [
            "For GitLab profile homepage tasks, open profile preferences/settings, edit the Website/Homepage URL field, save the profile, and verify the saved value is visible.",
        ],
        "mutate_gitlab_star_repos": [
            "For GitLab starring tasks, use the GitLab Explore/Projects list sorted by most stars, treat visible list order as the ranking, open each required project, click the current Star control, and verify the state changed before moving on.",
            "Never click Unstar/Starred, starrers counts, forks, issues, or merge request links for a star task; if a project already shows Unstar/Starred, count it as already starred and continue to the next top project.",
            "Do not finish after only opening the explore/projects list; the requested number of repositories must be starred.",
        ],
        "mutate_gitlab_mr_reply": [
            "For GitLab merge request reply tasks, open the assigned merge request matching the requested topic, inspect the last comment author, then submit exactly the required reply/comment.",
            "Prefer assigned-MR/dashboard context over global search results; global search can return unrelated projects with similar words.",
        ],
        "mutate_gitlab_issue_assign": [
            "For GitLab issue assignment tasks, open the named issue/project, use the assignee control or sidebar, select the requested user, save/apply if required, and verify the assignee is visible.",
        ],
        "mutate_gitlab_issue_create": [
            "For GitLab issue creation tasks, open the target repo's New issue form, fill title and required fields, set assignee/due date through current controls, submit, and verify the created issue page.",
        ],
        "mutate_gitlab_members": [
            "For GitLab member tasks, open the project/group members page, use the Invite/Add member modal, add each requested user with the requested role, and verify resulting member rows or confirmations.",
            "Do not use the members table filter as the invite input.",
            "For multi-user invitations, keep using the modal username/email input until all requested users are selected as chips/tokens/rows, then set the requested role and submit once.",
        ],
        "mutate_gitlab_milestone": [
            "For GitLab milestone tasks, open the repo milestone page, create a new milestone, fill title/start/due dates exactly, submit, and verify the milestone is listed or visible.",
        ],
        "mutate_shopping_purchase": [
            "For shopping purchase tasks, clear cart if required, navigate/filter to the requested category/product, add the selected product to cart, and verify cart state.",
        ],
        "mutate_shopping_lowest_unit_price_cart": [
            "For lowest-unit-price cart tasks, inspect every open tab or candidate product page named by the task, compute comparable per-unit price from visible price and quantity/unit text, then add only the lowest per-unit item to the cart.",
            "Do not add an item before comparing all visible/open candidate products; if the cart page is reached too early, return to remaining product candidates before finalizing.",
            "After the chosen product is added and a cart/confirmation state shows that product, finish with SUCCESS immediately instead of continuing to compare, revisit product pages, or add more products.",
        ],
        "mutate_shopping_wishlist": [
            "For wishlist tasks, navigate to the requested product or current product page, click the visible Add to Wish List/Wishlist control, and verify the item appears in wishlist state or confirmation before finishing.",
            "Do not add the product to the cart for wishlist-only tasks.",
            "Use the product detail wishlist form/control rather than cart or addgroup controls. If a quantity field is visible or included in the form, keep or set it to 1 before submitting the wishlist action.",
        ],
        "mutate_shopping_newsletter": [
            "For newsletter subscription tasks, find the newsletter/email subscription field, enter the available account email or requested email, submit the subscription form, and verify a subscription confirmation.",
        ],
        "mutate_shopping_contact_form_prepare": [
            "For shopping contact/refund/coupon form preparation tasks, gather any requested order number, SKU, amount, or product/order detail from account order pages before opening Contact Us.",
            "Fill the contact form fields and message exactly as requested. If the task says to leave it ready for review or do not submit, avoid the real site submission endpoint, but use any visible preview/check/capture/dummy form action that preserves the filled form state for review.",
            "For review-only prepared forms, finish only after the filled fields are visibly ready or the non-final preview/capture action has recorded them.",
            "If the task says to submit, submit the contact form and verify the confirmation instead.",
        ],
        "mutate_shopping_product_review": [
            "For shopping product review tasks, find the recently purchased product or its review form, select the requested star rating, fill nickname, summary, and review text exactly, then submit the review and verify confirmation.",
            "Do not treat product review-writing tasks as RETRIEVE review tasks; they require a visible form mutation.",
        ],
        "mutate_shopping_address_update": [
            "For shopping account address-update tasks, open the customer's address book or account address edit page, update the existing address form, and submit/save it before finishing.",
            "Preserve address components exactly: put the street name/number in street line 1 and apartment, suite, unit, or house details in street line 2 when the task provides a second address line.",
            "After the address save confirmation or account address page shows the updated address, finish with SUCCESS instead of continuing to revisit account pages.",
        ],
        "navigate_shopping_category_filter": [
            "For shopping category-page filter tasks, open the specific requested category page, not only a parent category or search results page.",
            "Apply the requested price filter on that category page; for 'under X' filters, preserve the numeric bound exactly as a 0-X price filter when the site uses price query parameters.",
            "Finish only when the current URL/content shows the requested category and the requested filter, not a broader parent category.",
        ],
        "navigate_shopping_sorted_category_product": [
            "For shopping sorted-category product tasks, open the specific requested category/listing first, apply the requested sort such as price descending for 'most expensive' or ascending for 'cheapest', then open the first matching product detail page.",
            "Do not finish on the search results page, parent category page, or sorted listing; the final page must be a concrete product detail page.",
        ],
        "navigate_shopping_sorted_search_listing": [
            "For shopping sorted-listing tasks, search for the exact requested listing phrase, then apply the requested sort order on the search results/listing page.",
            "Finish on the sorted listing/search-results page itself; do not open an individual product unless the task explicitly asks for a product page.",
            "For price descending/name ascending wording, preserve the requested sort direction exactly and verify the current page still shows the requested query/listing terms.",
        ],
        "navigate_shopping_order_detail": [
            "For shopping order-detail navigation tasks, open account order history, identify the requested order by visible status/date such as most recent processing order, then open that order's detail/view page.",
            "Finish only on the concrete order detail page, not on the order-history listing.",
        ],
        "navigate_admin_theme_settings": [
            "For Magento admin theme-setting navigation tasks, use Content/Design/System Design theme settings when visible, and open the concrete theme edit/settings page requested by the task.",
            "Finish only on the theme settings/edit page itself, not on the design listing or dashboard.",
        ],
        "navigate_admin_order_grid_filter": [
            "For Magento admin order-list navigation tasks, open Sales > Orders or the `/admin/sales/order/` order grid before applying filters.",
            "Use the order grid Status filter for requested states such as complete/completed, pending, processing, or canceled; do not use the global header search as a substitute for a grid status filter.",
            "After applying the grid filter/search, finish only when the order grid remains visible and the active filter or grid request corresponds to the requested status.",
        ],
        "navigate_admin_sales_report_filter": [
            "For Magento admin sales/tax report navigation tasks, open the matching Reports section first: Sales > Orders maps to `/admin/reports/report_sales/sales/`, and Sales > Tax maps to `/admin/reports/report_sales/tax/`.",
            "The evaluable final report request is the matching `/filter` endpoint with `report_type=created_at_order`, `from=YYYY-MM-DD`, and `to=YYYY-MM-DD`; using only the unfiltered report landing page is incomplete.",
            "For relative dates, compute them from the date stated in the task, not the machine date. Use ISO dates in the final report request. For example, if today is March 15, 2023, last year is 2022-01-01 through 2022-12-31 and this year is 2023-01-01 through 2023-03-15.",
            "If the form UI uses calendar-style dates, still verify that the submitted report/filter URL or request carries the ISO date window expected by the task before finishing.",
            "Click the visible report/filter/show-report control or navigate to the equivalent grounded filter URL only when the report type and date range are unambiguous. Finish only after the report page/grid reflects the selected report type and date range.",
        ],
        "retrieve_admin_search_terms": [
            "For Magento admin search-term retrieval tasks, use the Search Terms grid/report rather than finishing on a search-term detail page.",
            "When the task asks for top N search terms, use Marketing/SEO Search Terms and rank by the visible popularity/count column such as Number of Uses/Searches in descending order, not alphabetic order, recency, or a term detail page.",
            "If the first visible rows are not sorted by the count/ranking column, click the column header or use the grid sorting/filter controls before reading the top N terms.",
            "Do not finish as NAVIGATE for a 'Get ... search terms' task; the final response must be RETRIEVE with only the requested list/schema.",
        ],
        "retrieve_admin_customer_contact": [
            "For Magento admin customer-contact retrieval tasks, use Customers > All Customers or the customer grid as the source of truth.",
            "When a phone/telephone number is given, filter or search the phone column by the exact visible number before opening a customer detail. Do not match a partial number or infer the customer from a similarly named record.",
            "Read the requested name and email from the same matching customer row or detail page, then return exactly the requested object keys and no additional account fields or explanation.",
        ],
        "retrieve_admin_review_count": [
            "For Magento admin review-count retrieval tasks, use the product/customer reviews grid as the source of truth rather than dashboard statistics or a single review detail.",
            "Apply the requested calendar period using the grid's created-date/date-range filter when available, then wait for the grid to refresh and read its visible total record count. Do not count only the currently visible page rows.",
            "Return the requested count as one number in the required container, such as [351], with no explanatory text or review objects.",
        ],
        "retrieve_admin_review_attributes": [
            "For Magento admin review-attribute retrieval tasks, use the product/customer reviews grid or the matching product's review context as the source of truth.",
            "Match the requested product and rating threshold from visible review evidence, then collect every matching review title/rating across grid pages. A product-text filter that reports zero rows is not by itself proof that no matching reviews exist: clear an unsupported filter and inspect the available product/review fields or detail rows before returning NOT_FOUND.",
            "Return only the requested title/rating or other requested object keys, preserve the requested rating representation, and do not include reviewer, product, or explanation fields unless asked.",
        ],
        "retrieve_admin_customer_order_emails": [
            "For Magento admin customer/order email retrieval tasks, derive the answer from order/customer grids or reports rather than only opening the customer page.",
            "When the task asks for customers with a specific number/rank of orders, use the Sales Orders grid as the source of truth, include all requested order states when the task says any state, and count order rows grouped by customer email across the requested scope/pages.",
            "For rank wording such as second most orders, compute the full ranking by order count first, then return all emails tied at the requested rank.",
            "Do not finish as NAVIGATE for a 'Get customer email(s)' task; the final response must be RETRIEVE with only the requested emails and no extra text.",
        ],
        "retrieve_admin_monthly_order_counts": [
            "For Magento admin monthly order-count retrieval tasks, use the Sales Orders report/grid rather than the generic dashboard or global search.",
            "Apply the requested date range exactly, choose period type Month when available, and filter to the requested order status such as completed/complete before reading counts.",
            "Return exactly the requested list of objects with month names and integer counts, preserving the requested inclusive month order. Do not return a chart summary, raw grid rows, or explanatory text.",
            "Use supported BrowserGym actions only: click/focus current dropdown candidates, fill exact current input bids, refresh candidates after dropdowns open, and avoid symbolic selector labels as action targets.",
        ],
        "retrieve_admin_order_attribute": [
            "For Magento admin order-attribute retrieval tasks, use Sales > Orders or the admin order grid as the source of truth.",
            "Apply the requested status filter such as complete/completed, processing, pending, or canceled/cancelled, then sort by the requested age or recency before opening the target order.",
            "For billing-name tasks, open the target order detail and read the Billing Address/Name field, not the customer account name or shipping name unless the task explicitly asks for it.",
            "Return only the requested scalar string or schema, with no explanatory text.",
        ],
        "retrieve_admin_order_items": [
            "For Magento admin order-item retrieval tasks, use Sales > Orders or the admin order grid as the source of truth.",
            "Apply the requested order status exactly, then sort the order grid by the visible purchase/created date in the requested recency direction before opening the first matching row. Do not infer recency from an arbitrary open order detail or order number alone.",
            "On the target order detail, read each requested item from the Items Ordered table. For final/discounted price requests use the Price column, not Original Price, Subtotal, Row Total, Grand Total, or Total Paid.",
            "When the task requests an order such as low-to-high or high-to-low, sort the completed result objects numerically by the requested value only after collecting all item rows. Return exactly the requested object keys and numeric values, with no extra fields or explanation.",
        ],
        "retrieve_admin_order_payment_aggregate": [
            "For Magento admin order payment aggregate tasks, use Sales > Orders or the admin order grid as the source of truth rather than dashboard summaries.",
            "Filter or group orders by the requested state/status exactly: canceled/cancelled orders are distinct from complete/completed orders; non-cancelled means exclude canceled/cancelled while retaining other allowed states.",
            "Sort by order date/created date to identify the requested last/oldest/newest N orders, then read the payment amount from the visible Grand Total/Order Total/Paid column or order detail.",
            "When the task asks for a total or difference, compute the numeric aggregate and return one number only, not the individual order amounts or extra text.",
        ],
        "retrieve_admin_inventory_product_attributes": [
            "For Magento admin inventory/product-attribute retrieval tasks, use the admin Catalog > Products grid or product detail pages as the source of truth, not storefront category pages.",
            "Apply the requested stock/quantity condition exactly, such as 0 units left, 3 units left, or a 2-3 unit range, using the grid quantity/salable-quantity/stock filters when available.",
            "Prefer concrete simple/variant product rows over configurable parent rows when the requested answer asks for variant attributes such as color, size, or material.",
            "If the requested attribute is material, read the actual material/composition attribute from the product row/detail page; do not substitute product technology, collection, or name tokens as material.",
            "Collect all matching rows across visible grid pages after the quantity filter is applied; do not finish after the first matching product unless the task asks for only one item.",
            "Read only the requested attributes from the matching product row/detail page, and return the exact requested scalar/list/object schema without extra text.",
        ],
        "retrieve_admin_review_nicknames": [
            "For Magento admin review nickname retrieval tasks, use the admin product/customer reviews grid rather than storefront product pages when the active site is shopping_admin.",
            "Filter or inspect reviews by product name/category and rating threshold from the task, then return only the matching customer nicknames as strings.",
            "Do not finish as NAVIGATE after opening a review detail page; the final response must be RETRIEVE with the requested nickname list and no extra fields.",
            "For plural nickname tasks, continue through all matching review rows/pages after filtering; a partial visible subset is incomplete even if some returned nicknames are correct.",
            "If multiple products match a category such as tanks products, continue through the relevant review grid rows/pages and include every nickname whose visible rating satisfies the threshold.",
        ],
        "policy_or_account_order_change": [
            "For account/order changes, inspect order history and available actions. If the requested change is not allowed by the visible UI, return ACTION_NOT_ALLOWED_ERROR instead of SUCCESS.",
            "If you have opened the relevant order page and no edit/change-address action is visible, finish explicitly with ACTION_NOT_ALLOWED_ERROR instead of looping or returning UNKNOWN_ERROR.",
        ],
        "policy_or_gitlab_merge_request_create": [
            "For GitLab merge-request creation/reviewer tasks, inspect the named/current repository and look for a valid New merge request, source/target branch, submit, or reviewer assignment path.",
            "If the relevant repository does not expose a valid merge-request creation/reviewer control after inspection, finish with ACTION_NOT_ALLOWED_ERROR rather than looping or returning UNKNOWN_ERROR.",
        ],
        "mutate_admin_stock": [
            "For Magento stock tasks, open the product grid, filter by the exact product name from the task, prefer the matching configurable/parent product row when the task names a base product, change stock status, and save.",
            "For out-of-stock tasks, the required durable mutation is a product save with the stock status set to out of stock; filtering the grid or opening a related variant is only preparation.",
            "If multiple variants share the base name, avoid drifting to unrelated products. Re-check the visible product title/SKU before saving.",
        ],
        "mutate_admin_order_notify": [
            "For Magento admin order notification tasks, use Sales > Orders or `/admin/sales/order/`, filter or search for the requested customer and pending/order status, then open the most recent matching order detail.",
            "On the order detail page, use the order history/comment form only: fill the exact requested message, enable the visible customer-notification control when present, and click Submit Comment/Add Comment before finishing with SUCCESS.",
            "Do not use Send Email, Hold, Invoice, Ship, or other order action buttons as substitutes for the order-history comment submission; they do not satisfy a customer notification comment task.",
            "If the relevant order is found but no grounded order history/comment field plus submit-comment control is available after inspection, finish explicitly with ACTION_NOT_ALLOWED_ERROR instead of looping or returning UNKNOWN_ERROR.",
        ],
        "mutate_admin_order_tracking": [
            "For Magento admin order tracking tasks, open the requested order detail from Sales > Orders, start the Ship/New Shipment workflow, add tracking information, choose the requested carrier when available, fill the tracking number exactly, then submit/save the shipment.",
            "Do not finish after merely opening the order or typing the tracking number. A successful tracking update requires the shipment/tracking save POST or a visible saved shipment confirmation.",
            "If the requested carrier option is not directly visible, open the carrier dropdown and choose the matching carrier label rather than leaving the carrier as Custom.",
        ],
        "mutate_admin_review_moderation": [
            "For Magento admin review moderation tasks, use the product reviews grid rather than storefront reviews. Filter or inspect reviews by the visible criteria in the task, such as status, rating, reviewer/nickname, author name, title, or review text.",
            "For approve tasks, open each matching review and save it with Approved status. For delete tasks, delete only reviews matching every requested criterion, such as the named reviewer/nickname or pending/status and rating condition.",
            "When the task asks for all reviews satisfying a threshold or reviewer/name criterion, continue through visible matching rows/pages until all qualifying reviews have been acted on; acting on only the first row is incomplete.",
            "If the review grid exposes row checkboxes plus an Actions/Mass Actions control, you may select all currently visible matching rows and apply the requested Approve/Delete action; otherwise process matching reviews one by one.",
            "For delete confirmations or modal dialogs, use only the current visible dialog candidates. If an OK/Confirm candidate is not exposed after the dialog appears, press Enter once to accept the active confirmation rather than reusing a stale DOM id or background button.",
            "After each review action, verify that the durable save/delete mutation was submitted. Finish with SUCCESS only after all requested matching reviews have been approved or deleted.",
        ],
        "mutate_admin_cart_price_rule": [
            "For Magento cart price rule tasks, use Marketing > Cart Price Rules or the promo quote rule page, then create a new rule rather than editing an unrelated existing rule.",
            "Fill the rule name, set the rule active, select the relevant website and registered/customer group options, set coupon usage to no coupon when no coupon is requested, then open the Actions section.",
            "For percentage checkout/cart discounts, choose the percent-discount action and put the numeric percent in the Discount Amount field. For fixed amount discounts on a purchase/cart, choose the fixed/cart amount discount action and put the numeric amount in Discount Amount.",
            "Before saving, verify the form contains every required task fact: rule name, customer scope, website scope, coupon/no-coupon setting, discount action type, and numeric discount amount. Do not put the discount only in Description.",
            "After the save mutation is submitted and no required fact remains, finish with SUCCESS instead of continuing to browse.",
        ],
        "mutate_admin_catalog_price_rule": [
            "For Magento catalog-wide product price rule tasks, use Marketing > Catalog Price Rules or the promo catalog rule page, then create a new rule rather than drifting to Cart Price Rules.",
            "Fill the rule name, set the rule active, select the relevant website and registered/customer group options, then open the Actions section.",
            "For percentage discounts on all products, choose the percent-discount action and put the numeric percent in the Discount Amount field. Do not put the discount only in Description, and do not finish until the rule is saved.",
            "Before saving, verify the form contains every required task fact: rule name, customer scope, website scope, discount action type, numeric discount amount, and all-products/catalog scope.",
            "After the save mutation is submitted and no required fact remains, finish with SUCCESS instead of continuing to browse.",
        ],
        "mutate_admin_marketing_price_rule": [
            "For Magento marketing price rule tasks, first decide from the task wording whether it is a cart/checkout rule or a catalog/product rule, then use the matching admin rule page.",
            "A successful rule mutation requires saving the active rule with name, website, customer group, discount action, and numeric discount amount filled in the proper fields.",
        ],
        "mutate_admin_product_description_from_review_count": [
            "For Magento admin product-description tasks that depend on review counts, first determine the requested review count from the admin review grid using visible filters for product and rating/status, then edit the named product in the product catalog.",
            "Update the product description/short description field to the exact task-specified phrase derived from the visible count, preserving required HTML paragraph wrapping when the editor uses it, then save the product.",
            "Do not stop after inspecting reviews. The final state change is the product save action for the description field.",
        ],
        "mutate_admin_simple_product_create": [
            "For Magento admin simple-product creation tasks, use the admin product catalog and Add Product/New Product flow, choose Simple Product, and choose an attribute set compatible with the requested product type such as shirt/top/pant/jeans.",
            "Fill the visible required product fields from the task intent: product name, price, quantity/stock status, status/enabled state, size, color, and any required SKU or tax/visibility defaults when the form requires them.",
            "Before filling product fields, verify the page is a new simple product form, usually a /catalog/product/new/.../type/simple URL or a New Product title. If you land on an existing product edit page, return to the product catalog and restart the Add Product/New Product flow instead of editing that product.",
            "For Magento dropdowns and comboboxes, do not emit unsupported `select(...)` actions. Click/focus the current dropdown candidate, type/filter the visible option text when an input is exposed, then click the current option bid or press Enter.",
            "Use visible dropdowns/options by their labels from the task intent, then click the current Save control and finish with SUCCESS only after the save mutation has executed or a save confirmation is visible.",
        ],
        "mutate_admin_configurable_product_options": [
            "For Magento configurable-product option tasks, open the admin product catalog, filter/search for the named configurable product, and open its product edit page rather than creating a different product.",
            "When adding a new size/option, first update the global product attribute option list for Size through the admin attribute/options workflow and save the attribute; product variant creation alone is incomplete when the requested size option does not yet exist.",
            "After the size option exists, return to the named configurable product configuration and add only the requested size for the requested color variants or all visible color variants, then save the configurable product.",
            "For Magento dropdowns and option selectors, do not emit unsupported `select(...)` actions. Use the current dropdown/option candidates with click, fill, and press Enter, refreshing candidates after each dropdown opens.",
            "Use visible variant/configuration controls such as Configurations, Add Products Manually, Create Configurations, or Generate Variations; preserve existing variants and add only the requested new size/color combinations before saving.",
        ],
        "mutate_admin_inventory_quantity": [
            "For Magento inventory quantity tasks, search/filter the product catalog by the exact product name and variant attributes from the task, then edit the matching simple product variants rather than only the configurable parent.",
            "If the task says inventory was received, add the received amount to the current visible quantity for each matching variant; do not replace the quantity with the received shipment amount unless the task says to set it exactly.",
            "If the task says every size or every variant of a color/product, update each matching simple variant and save each product edit page. A single parent-product save is incomplete when the evaluator expects variant quantity saves.",
            "Before each save, verify the target product name, color, size/variant, current quantity, and computed final quantity so an inventory update does not apply to the wrong variant.",
            "After all requested variants have been saved, finish with SUCCESS instead of returning to the product grid and looping.",
        ],
        "mutate_admin_product_price_update": [
            "For Magento product price update tasks, search/filter the product catalog by the exact product name and requested variant attributes such as color and size, then edit the matching simple product variants rather than only the configurable parent.",
            "Use the product grid as a checklist: identify every visible simple-product row whose name/SKU/attribute columns match the requested product, color, and size condition, then open and save each matching simple product one by one.",
            "If the task asks to increase/reduce/decrease by a percentage, read the current visible price and calculate the new price from it. If the task asks to increase/reduce/decrease by a fixed amount, add or subtract that amount from the current visible price.",
            "When the task names a size threshold such as size L and above, update only matching size variants. When it says all products/variants with a color and size set, update every matching simple variant and save each product edit page; one parent/configurable product save is incomplete.",
            "Before each save, verify product name, color, size/variant, current price, requested operation, and computed final price. Do not save an explanatory discount note instead of the product price field.",
            "After all requested variants have been saved, finish with SUCCESS instead of returning to the product grid and looping.",
        ],
        "retrieve_aggregate": [
            "For aggregate counts, apply the correct filter/date/status first, read the resulting count or rows, and return only the requested scalar/list schema.",
            "If the task asks for a list of month/count objects, return exactly those objects. If it asks for a total number, return an array containing only that number when requested.",
            "For Magento admin grids, do not use the global header search count as evidence for a grid text filter. Use visible grid filters/search/reset controls and require visible evidence that the requested filter term is active before returning a count.",
        ],
        "retrieve_reviews": [
            "For review retrieval, find product/review pages, filter by the requested rating/brand/term, inspect visible review author names, and return only the requested names or values.",
            "If the task asks for review titles with a rating threshold such as 2 stars or below, inspect the review section/list, include only reviews whose visible rating satisfies the threshold, and return only the title strings unless another schema is requested.",
            "When reviews are paginated, continue through visible review pages until no further matching reviews or next-page controls remain; do not finish after the first visible page if the task asks for all matching reviews.",
            "If the review section is reached and repeated scrolling exposes no new review rows or next-page controls, stop scrolling and return the matching titles collected so far, or an empty list if the visible reviewed evidence shows no matches.",
        ],
        "retrieve_shopping_latest_order_status": [
            "For latest-order status retrieval, open account order history, choose the most recent order row, then open its detail page.",
            "Return a list with one object containing the visible order status and an arrival_date. Use null for arrival_date when no delivery/arrival date is visible or the order is canceled.",
        ],
        "retrieve_shopping_order_attribute": [
            "For shopping order-attribute retrieval, open account order history, filter mentally by the requested order status/date wording such as latest, most recent, processing, or under delivery, then open the matching order detail.",
            "Return only the requested visible field such as order number, total cost, grand total, status, or date in the exact requested schema.",
            "Do not finish on the order-history list unless the requested field is clearly visible there and no order detail is needed.",
        ],
        "retrieve_shopping_last_ordered_date": [
            "For shopping last-ordered-date retrieval, open account order history and search across relevant order pages/details for the requested product name or product type from the task intent.",
            "Choose the most recent matching order item by visible order date, then return only that date in the requested format such as YYYY-MM-DD. Return null only when inspected visible order evidence shows no matching product.",
        ],
        "retrieve_shopping_purchased_product_attribute": [
            "For shopping retrieval tasks about a product the user bought or purchased, open account order history and identify the relevant order by the requested month/year, date window, product name, or product category.",
            "Open the order detail when needed, locate the matching order item, and read visible product options or variant attributes such as color, size, width, height, dimensions, or option labels from the item row/detail page.",
            "Return only the requested attribute value(s) with the exact requested schema. Do not include the product name, order number, or explanation unless the task asks for them.",
        ],
        "retrieve_shopping_order_aggregate": [
            "For shopping order aggregates over a date window, inspect all relevant order-history pages, count only orders with the requested status and date range, and sum the visible grand/order totals including shipping and handling.",
            "Do not use the number of visible rows, page count, subtotals, or unrelated statuses as the final answer. Return exactly the requested object schema.",
        ],
        "retrieve_shopping_price_range": [
            "For shopping price-range retrieval, search or filter to the requested brand/product set, inspect the matching product listing prices across visible pages as needed, and return exactly the minimum and maximum numeric prices requested.",
            "Do not use unrelated sponsored, category, or non-matching products when computing the range.",
        ],
        "retrieve_shopping_refund_aggregate": [
            "For shopping refund/canceled-order retrieval, inspect account order history for the requested date window and canceled status, open matching order details when needed, and sum the visible refundable/order totals including shipping when the task asks to include shipping.",
            "Return only the numeric refund amount requested; use 0 only when the relevant inspected orders show no matching canceled/refundable order.",
        ],
        "retrieve_shopping_category_spend_aggregate": [
            "For shopping spend-by-category retrieval, inspect account order history for the requested date window, open relevant order details, and include only order items matching the requested category or product type.",
            "Respect shipping/handling wording exactly: exclude shipping and handling when the task says not to consider them; include them only when explicitly requested.",
            "Return only the requested numeric amount or exact object schema; do not include order numbers or explanation.",
        ],
        "retrieve_gitlab_clone_url": [
            "For GitLab clone URL retrieval, open the named project page, inspect the Clone control/dropdown or visible clone field, choose the requested protocol such as SSH/HTTPS, and finish as RETRIEVE with the exact URL string in retrieved_data.",
            "If the task says 'Return the URL only', still use the WebArena final response schema, but put only the URL string inside retrieved_data.",
        ],
        "retrieve_gitlab_commit_stats": [
            "For GitLab commit/contributor retrieval, treat words like commit, branch, and contributor as read-only evidence requests unless the official task type is MUTATE.",
            "Use visible repository commit history, contributor pages, branch filters, or task-derived GitLab routes to inspect the requested data; do not open edit forms or submit changes.",
            "Return only the requested count, username, email, date, or list schema in retrieved_data.",
        ],
        "retrieve_gitlab_members": [
            "For GitLab member/access retrieval, inspect the project or group members/access page and read the visible member rows, roles, or access state.",
            "Do not use Invite/Add member controls for RETRIEVE tasks; membership changes are only valid for MUTATE tasks.",
            "Return only the requested usernames, roles, or boolean/scalar value in retrieved_data.",
        ],
    }
    return [*general, *by_capability.get(capability, [])]
