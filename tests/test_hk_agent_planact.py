from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from hk_agent.executor import (  # noqa: E402
    allow_single_repair_refresh_noop,
    base_url_from_url,
    compact_repair_brief_for_prompt,
    deterministic_gitlab_fork_repair_action,
    deterministic_reddit_action,
    deterministic_shopping_action,
    deterministic_shopping_order_detail_action,
    gitlab_state_diagnosis,
    normalize_structured_action_fields,
    normalize_finish_action_from_context,
    normalize_retrieve_final_response_schema,
    repeated_no_progress_actions,
    deterministic_shopping_review_retrieve_action,
    deterministic_shopping_policy_action,
    validate_browsergym_action,
    validate_grounded_final_response,
    validate_mutation_success_state_check,
)
from hk_agent.capabilities import capability_guidance, infer_official_task_type, infer_task_capability, capability_tier  # noqa: E402
from hk_agent.diagnostics import contamination_adjusted_eval_diagnostics, mutation_diagnostics  # noqa: E402
from hk_agent.runner import llm_backend_metadata, repeated_repair_failure_class  # noqa: E402
from hk_agent.grounding import GroundedCandidate, ax_candidates, dom_candidates, focus_modal_candidates, prioritize_candidates  # noqa: E402
from hk_agent.k_repair import _sanitize_repair_text, build_k_repair_brief  # noqa: E402
from hk_agent.prompt_builder import build_executor_system_prompt  # noqa: E402
from hk_agent.prompt_builder import resolve_agent_architecture  # noqa: E402
from hk_agent.recovery import build_recovery_hint, is_planact_like_architecture  # noqa: E402
from webarena_exp.types import Subgoal  # noqa: E402


class FakeLocator:
    def __init__(self, text: str):
        self.text = text

    def inner_text(self, timeout: int = 0) -> str:
        return self.text


class FakePage:
    def __init__(self, *, url: str = "http://shopping.local/", text: str = "", html: str = "", rows: list[dict] | None = None):
        self.url = url
        self.text = text
        self.html = html
        self.rows = rows or []

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.text)

    def content(self) -> str:
        return self.html

    def evaluate(self, script: str, limit: int):
        return self.rows[:limit]

    def eval_on_selector_all(self, selector: str, script: str):
        return self.rows


class CapabilityInferenceTests(unittest.TestCase):
    def test_like_all_submissions_is_bulk_vote_mutation(self) -> None:
        task = {
            "sites": ["reddit"],
            "intent": "Like all submissions created by UniversityofBath in forum IAmA",
            "eval": [],
        }

        capability = infer_task_capability(task, "reddit")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_forum_bulk_vote")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_single_upvote_stays_single_vote_capability(self) -> None:
        task = {
            "sites": ["reddit"],
            "intent": "Upvote the newest post in forum IAmA",
            "eval": [{"expected": {"task_type": "MUTATE"}}],
        }

        self.assertEqual(infer_task_capability(task, "reddit"), "mutate_vote")

    def test_shopping_contact_form_prepare_is_mutation_not_review_retrieve(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": (
                'Fill out the contact us form with this refund message for the Stereo Sound System bought Feb 2023: '
                '"I need a refund. Order: <order_id>. Amount: <amount>. Reason: It broke after three days of use." '
                "Leave the filled form ready for review and do not submit it."
            ),
            "eval": [{"expected": {"task_type": "MUTATE"}}],
        }

        capability = infer_task_capability(task, "shopping")

        self.assertEqual(capability, "mutate_shopping_contact_form_prepare")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_product_review_write_is_mutation_not_review_retrieve(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": (
                'Rate my recently purchased floor lamp with 5 stars using my nickname Emma Lopez, '
                'with the summary "Good purchase" and review "I like it"'
            ),
            "eval": [{"expected": {"task_type": "MUTATE"}}],
        }

        capability = infer_task_capability(task, "shopping")

        self.assertEqual(capability, "mutate_shopping_product_review")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_product_review_write_infers_mutation_from_intent(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": (
                'Rate my recently purchased PS3 accessory with 3 stars using my nickname GamingEmma, '
                'with the summary "Ok I guess" and review "Does the job"'
            ),
            "eval": [],
        }

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(infer_task_capability(task, "shopping"), "mutate_shopping_product_review")

    def test_shopping_admin_order_notify_is_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": 'Notify Grace Nguyen in their most recent pending order with message "hello"',
            "eval": [{"expected": {"task_type": "mutate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_order_notify")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_order_notify_reduced_task_type_is_respected(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": 'Notify Sarah Miller in their most recent pending order with message "hello"',
            "task_type": "MUTATE",
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_order_notify")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_order_tracking_is_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Update order #304 with the USPS tracking number 13849373987",
            "task_type": "MUTATE",
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_order_tracking")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_review_approval_is_moderation_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Approve reviews with four stars or higher to display in our store.",
            "eval": [{"expected": {"task_type": "mutate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_review_moderation")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_review_deletion_is_moderation_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Delete all pending reviews with less than 4 stars",
            "eval": [{"expected": {"task_type": "mutate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_review_moderation")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_review_author_deletion_is_moderation_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Delete all reviews from the scammer Carlo",
            "eval": [{"expected": {"task_type": "mutate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_review_moderation")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_review_moderation_guidance_handles_confirm_dialogs(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Delete all pending reviews with less than 4 stars",
            "eval": [{"expected": {"task_type": "mutate", "status": "SUCCESS"}}],
        }

        guidance = "\n".join(capability_guidance(task, "shopping_admin")).lower()

        self.assertIn("delete confirmations", guidance)
        self.assertIn("press enter", guidance)
        self.assertIn("stale dom id", guidance)

    def test_shopping_admin_cart_price_rule_is_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": (
                'Create a new marketing price rule called "Spring cart sale" '
                "for all registered customers that offers 15% discount on checkout on all their cart"
            ),
            "task_type": "MUTATE",
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_cart_price_rule")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_purchase_price_rule_is_cart_rule_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": (
                'Create a new marketing price rule called "Holiday sale" '
                "for all registered customers that offers $40 discount on all their purchase"
            ),
            "task_type": "MUTATE",
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_cart_price_rule")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_catalog_price_rule_is_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": (
                'Create a new marketing price rule called "Catalog sale" '
                "for all registered customers that offers 45% off on all products"
            ),
            "task_type": "MUTATE",
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_catalog_price_rule")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_received_inventory_is_quantity_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "We've received 378 brown Aero daily fitness tee in every size, please update the inventory",
            "task_type": "MUTATE",
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_inventory_quantity")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_variant_price_update_is_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Reduce the price of size 28 Sahara leggings by 13.5%",
            "eval": [{"expected": {"task_type": "mutate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_product_price_update")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_variant_price_update_guidance_uses_simple_rows(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Increase the price of all blue running tshirts in extra small and small sizes by 23%",
            "eval": [{"expected": {"task_type": "mutate", "status": "SUCCESS"}}],
        }

        guidance = "\n".join(capability_guidance(task, "shopping_admin")).lower()

        self.assertIn("product grid as a checklist", guidance)
        self.assertIn("simple product", guidance)
        self.assertIn("parent/configurable product save is incomplete", guidance)

    def test_shopping_admin_theme_settings_navigation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Go to the Magento Luma theme settings page",
            "eval": [{"expected": {"task_type": "navigate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "NAVIGATE")
        self.assertEqual(capability, "navigate_admin_theme_settings")
        self.assertEqual(capability_tier(capability), "navigation")

    def test_shopping_admin_completed_order_grid_navigation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Go to the list of orders that are completed",
            "eval": [{"expected": {"task_type": "navigate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "NAVIGATE")
        self.assertEqual(capability, "navigate_admin_order_grid_filter")
        self.assertEqual(capability_tier(capability), "navigation")

    def test_shopping_admin_sales_report_navigation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Show the sales order report for for last year (today is March 15, 2023).",
            "eval": [{"expected": {"task_type": "navigate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")
        guidance = "\n".join(capability_guidance(task, "shopping_admin")).lower()

        self.assertEqual(infer_official_task_type(task), "NAVIGATE")
        self.assertEqual(capability, "navigate_admin_sales_report_filter")
        self.assertEqual(capability_tier(capability), "navigation")
        self.assertIn("/admin/reports/report_sales/sales/", guidance)
        self.assertIn("/filter", guidance)
        self.assertIn("created_at_order", guidance)
        self.assertIn("2022-01-01", guidance)
        self.assertIn("2022-12-31", guidance)

    def test_shopping_admin_tax_report_navigation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Show the tax report for for this year (today is March 15, 2023).",
            "eval": [{"expected": {"task_type": "navigate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")
        guidance = "\n".join(capability_guidance(task, "shopping_admin")).lower()

        self.assertEqual(infer_official_task_type(task), "NAVIGATE")
        self.assertEqual(capability, "navigate_admin_sales_report_filter")
        self.assertEqual(capability_tier(capability), "navigation")
        self.assertIn("/admin/reports/report_sales/tax/", guidance)
        self.assertIn("/filter", guidance)
        self.assertIn("created_at_order", guidance)
        self.assertIn("2023-01-01", guidance)
        self.assertIn("2023-03-15", guidance)

    def test_shopping_admin_review_count_description_update_is_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": (
                'Update the product description of Selene Yoga Hoodie to "{count} customer(s) love it!" '
                "where count is the number of reviews with 4 stars or above."
            ),
            "task_type": "MUTATE",
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_product_description_from_review_count")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_simple_product_create_is_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": (
                'Add a simple product named "Energy-Bulk Women Shirt" with 50 in stock, '
                "available in size S and color blue, priced at $60 using the appropriate attribute set."
            ),
            "eval": [{"expected": {"task_type": "mutate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_simple_product_create")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_admin_configurable_product_options_is_mutation(self) -> None:
        task = {
            "sites": ["shopping_admin"],
            "intent": "Add a new size XXXL to green Minerva LumaTech V-Tee",
            "eval": [{"expected": {"task_type": "mutate", "status": "SUCCESS"}}],
        }

        capability = infer_task_capability(task, "shopping_admin")

        self.assertEqual(infer_official_task_type(task), "MUTATE")
        self.assertEqual(capability, "mutate_admin_configurable_product_options")
        self.assertEqual(capability_tier(capability), "mutation")

    def test_shopping_review_titles_infer_retrieve_from_intent(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Get all review titles with 2 stars or below for the product on the current page.",
            "eval": [],
        }

        self.assertEqual(infer_official_task_type(task), "RETRIEVE")
        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_reviews")

    def test_shopping_address_update_has_specific_mutation_capability(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": (
                "I recently moved, my address is 654 Aspen Road, House #3, Boston, MA, 02110, "
                "update my information on OneStopShopping accordingly"
            ),
            "eval": [{"expected": {"task_type": "MUTATE"}}],
        }

        self.assertEqual(infer_task_capability(task, "shopping"), "mutate_shopping_address_update")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "mutation")

    def test_shopping_category_filter_navigation_has_specific_capability(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": 'Open the "women shoes" category page filtered to under $25',
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }

        self.assertEqual(infer_task_capability(task, "shopping"), "navigate_shopping_category_filter")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "navigation")

    def test_shopping_sorted_category_product_navigation_has_specific_capability(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Go to the product page for the most expensive men's Uniforms, Work & Safety",
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }

        self.assertEqual(infer_task_capability(task, "shopping"), "navigate_shopping_sorted_category_product")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "navigation")

    def test_shopping_sorted_category_product_navigation_builds_price_sorted_search(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "View the product page for the least expensive ssd hard drive with a minimum storage capacity of 1TB.",
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }
        subgoal = Subgoal(id="sg1", objective="Open sorted product page", expected_outcome="Least expensive matching product visible")
        page = FakePage(url="http://shopping.local/")

        action = deterministic_shopping_action(task=task, site_name="shopping", subgoal=subgoal, page=page)

        self.assertEqual(
            action,
            'goto("http://shopping.local/catalogsearch/result/?q=ssd+hard+drive&product_list_order=price&product_list_dir=asc")',
        )

    def test_shopping_sorted_category_product_navigation_opens_matching_visible_detail(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "View the product page for the least expensive ssd hard drive with a minimum storage capacity of 1TB.",
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }
        subgoal = Subgoal(id="sg1", objective="Open sorted product page", expected_outcome="Least expensive matching product visible")
        page = FakePage(
            url="http://shopping.local/catalogsearch/result/?q=ssd+hard+drive+1TB&product_list_order=price&product_list_dir=asc",
            rows=[
                {
                    "href": "http://shopping.local/portable-ssd-hard-drive-512gb.html",
                    "text": "Portable SSD Hard Drive 512GB",
                },
                {
                    "href": "http://shopping.local/portable-ssd-hard-drive-2tb.html",
                    "text": "Portable SSD Hard Drive 2TB",
                },
            ],
        )

        action = deterministic_shopping_action(task=task, site_name="shopping", subgoal=subgoal, page=page)

        self.assertEqual(action, 'goto("http://shopping.local/portable-ssd-hard-drive-2tb.html")')

    def test_shopping_sorted_category_product_navigation_filters_pair_capacity(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "View the product page for the least expensive shoe storage with a minimum storage capacity of 12 pairs.",
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }
        subgoal = Subgoal(id="sg1", objective="Open sorted product page", expected_outcome="Least expensive matching product visible")
        page = FakePage(
            url="http://shopping.local/catalogsearch/result/?q=shoe+storage&product_list_order=price&product_list_dir=asc",
            rows=[
                {
                    "href": "http://shopping.local/small-shoe-rack-8-pairs.html",
                    "text": "Small Shoe Rack 8 Pairs",
                },
                {
                    "href": "http://shopping.local/over-door-shoe-storage-24-pockets.html",
                    "text": "Over Door Shoe Storage 24 Pockets",
                },
            ],
        )

        action = deterministic_shopping_action(task=task, site_name="shopping", subgoal=subgoal, page=page)

        self.assertEqual(action, 'goto("http://shopping.local/over-door-shoe-storage-24-pockets.html")')

    def test_shopping_sorted_search_listing_navigation_has_specific_capability(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": 'Pull up the page with all "mouth night guard" listings sorted by descending price.',
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }

        self.assertEqual(infer_task_capability(task, "shopping"), "navigate_shopping_sorted_search_listing")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "navigation")

    def test_shopping_order_detail_navigation_has_specific_capability(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Open the order details page for the most recent processing order",
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }

        self.assertEqual(infer_task_capability(task, "shopping"), "navigate_shopping_order_detail")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "navigation")

    def test_shopping_order_detail_navigation_returns_not_found_when_requested_status_absent(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Open the order details page for the most recent processing order",
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }
        page = FakePage(
            url="http://shopping.local/sales/order/history/",
            text="My Orders Order # 000189 Order Date Status Complete Total $10.00",
        )

        action = deterministic_shopping_order_detail_action(
            task=task,
            site_name="shopping",
            page=page,
            previous_steps=[{"url_after": "http://shopping.local/sales/order/history/"}],
        )

        self.assertIn('\\"status\\": \\"NOT_FOUND_ERROR\\"', action)

    def test_shopping_latest_order_status_has_specific_retrieve_capability(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Get the status of my latest order and when will it arrive.",
            "eval": [{"expected": {"task_type": "RETRIEVE"}}],
        }

        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_shopping_latest_order_status")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "visible_retrieve")

    def test_shopping_order_attribute_can_infer_retrieve_from_intent(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": 'Get the total cost of my latest order marked as "processing".',
            "eval": [],
        }

        self.assertEqual(infer_official_task_type(task), "RETRIEVE")
        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_shopping_order_attribute")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "visible_retrieve")

    def test_shopping_last_ordered_date_can_infer_retrieve_from_intent(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Return the date I last ordered my body butter. Return the date in YYYY-MM-DD format or null if not available, without any additional details.",
            "eval": [],
        }

        self.assertEqual(infer_official_task_type(task), "RETRIEVE")
        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_shopping_last_ordered_date")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "visible_retrieve")

    def test_shopping_purchased_product_attribute_has_specific_retrieve_capability(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Get the color of the picture frame I bought Sep 2022.",
            "eval": [{"expected": {"task_type": "RETRIEVE"}}],
        }

        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_shopping_purchased_product_attribute")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "visible_retrieve")

    def test_shopping_purchased_product_attribute_can_infer_retrieve_from_intent(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": 'Get the size of the picture frame I bought in 2022. Return a list of objects with keys "width" and "height".',
            "eval": [],
        }

        self.assertEqual(infer_official_task_type(task), "RETRIEVE")
        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_shopping_purchased_product_attribute")

    def test_shopping_price_range_can_infer_structured_retrieve(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": 'What is the price range for products from Amazon basic?. Return an object with keys "min" and "max" only.',
            "eval": [],
        }

        self.assertEqual(infer_official_task_type(task), "RETRIEVE")
        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_shopping_price_range")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "structured_retrieve")

    def test_shopping_refund_aggregate_can_infer_structured_retrieve(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "How much refund should I expect from my orders canceled, if any, in Feb 2023, including shipping fee.",
            "eval": [],
        }

        self.assertEqual(infer_official_task_type(task), "RETRIEVE")
        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_shopping_refund_aggregate")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "structured_retrieve")

    def test_shopping_category_spend_aggregate_can_infer_structured_retrieve(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Return how much I spent on hair care and hair style shopping during Jan 2023 without considering shipping and handling fee.",
            "eval": [],
        }

        self.assertEqual(infer_official_task_type(task), "RETRIEVE")
        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_shopping_category_spend_aggregate")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "structured_retrieve")

    def test_shopping_complete_order_amount_has_specific_aggregate_capability(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Get how many complete orders I have over the past year, and the total amount of money I spent.",
            "eval": [{"expected": {"task_type": "RETRIEVE"}}],
        }

        self.assertEqual(infer_task_capability(task, "shopping"), "retrieve_shopping_order_aggregate")
        self.assertEqual(capability_tier(infer_task_capability(task, "shopping")), "structured_retrieve")

    def test_shopping_category_filter_navigation_uses_specific_category_route(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": 'Open the "women shoes" category page filtered to under $25',
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }
        subgoal = Subgoal(id="sg1", objective="Open the category page", expected_outcome="Filtered category visible")
        page = FakePage(url="http://shopping.local/clothing-shoes-jewelry.html", text="Clothing, Shoes & Jewelry")

        action = deterministic_shopping_action(task=task, site_name="shopping", subgoal=subgoal, page=page)

        self.assertEqual(action, 'goto("http://shopping.local/clothing-shoes-jewelry/women/shoes.html?price=0-25")')

    def test_shopping_category_filter_navigation_supports_accent_furniture_route(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": 'Open the "furniture with accent" category page filtered to under $199',
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }
        subgoal = Subgoal(id="sg1", objective="Open the category page", expected_outcome="Filtered category visible")
        page = FakePage(url="http://shopping.local/home-kitchen.html", text="Home & Kitchen Furniture")

        action = deterministic_shopping_action(task=task, site_name="shopping", subgoal=subgoal, page=page)

        self.assertEqual(action, 'goto("http://shopping.local/home-kitchen/furniture/accent-furniture.html?price=0-199")')

    def test_shopping_category_filter_navigation_prefers_matching_visible_category_link(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": 'Open the "outdoor chairs" category page filtered to under $80',
            "eval": [{"expected": {"task_type": "NAVIGATE"}}],
        }
        subgoal = Subgoal(id="sg1", objective="Open the category page", expected_outcome="Filtered category visible")
        page = FakePage(
            url="http://shopping.local/",
            rows=[
                {
                    "href": "http://shopping.local/home-kitchen/patio-lawn-garden/outdoor-chairs.html",
                    "text": "Outdoor Chairs",
                }
            ],
        )

        action = deterministic_shopping_action(task=task, site_name="shopping", subgoal=subgoal, page=page)

        self.assertEqual(action, 'goto("http://shopping.local/home-kitchen/patio-lawn-garden/outdoor-chairs.html?price=0-80")')

    def test_shopping_review_title_retrieve_finishes_visible_low_rating_titles(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Get all review titles with 2 stars or below for the product on the current page.",
            "eval": [{"expected": {"task_type": "RETRIEVE"}}],
        }
        page = FakePage(
            url="http://shopping.local/example-product.html#reviews",
            rows=[
                {"title": "Too slow", "author": "Emma", "rating_title": "40%", "rating_style": "width: 40%", "text": "Too slow"},
                {"title": "Works well", "author": "Noah", "rating_title": "80%", "rating_style": "width: 80%", "text": "Works well"},
            ],
        )

        action = deterministic_shopping_review_retrieve_action(task=task, site_name="shopping", page=page)

        self.assertIn('\\"retrieved_data\\": [\\"Too slow\\"]', action)

    def test_shopping_review_title_retrieve_opens_magento_review_ajax_list(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Get all review titles with 2 stars or below for the product on the current page.",
            "eval": [{"expected": {"task_type": "RETRIEVE"}}],
        }
        page = FakePage(
            url="http://shopping.local/example-product.html#reviews",
            html='{"productReviewUrl": "http\\u003A\\u002F\\u002Fshopping.local\\u002Freview\\u002Fproduct\\u002FlistAjax\\u002Fid\\u002F38805\\u002F"}',
            rows=[],
        )

        action = deterministic_shopping_review_retrieve_action(task=task, site_name="shopping", page=page)

        self.assertEqual(action, 'goto("http://shopping.local/review/product/listAjax/id/38805/")')

    def test_shopping_review_author_retrieve_filters_visible_mentions_and_rating(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Get name(s) of reviewer(s) who mention print quality explicitly with a rating of 3 or less stars for the product on the current page.",
            "eval": [{"expected": {"task_type": "RETRIEVE"}}],
        }
        page = FakePage(
            url="http://shopping.local/example-product.html#reviews",
            rows=[
                {
                    "author": "Emma",
                    "rating_title": "60%",
                    "rating_style": "width: 60%",
                    "text": "Review by Emma. Print quality is poor and faded.",
                },
                {
                    "author": "Noah",
                    "rating_title": "80%",
                    "rating_style": "width: 80%",
                    "text": "Review by Noah. Print quality is great.",
                },
                {
                    "author": "Mia",
                    "rating_title": "40%",
                    "rating_style": "width: 40%",
                    "text": "Review by Mia. Shipping was slow.",
                },
            ],
        )

        action = deterministic_shopping_review_retrieve_action(task=task, site_name="shopping", page=page)

        self.assertIn('\\"retrieved_data\\": [\\"Emma\\"]', action)

    def test_shopping_review_title_retrieve_stops_after_repeated_empty_review_scrolls(self) -> None:
        task = {
            "sites": ["shopping"],
            "intent": "Get all review titles with 2 stars or below for the product on the current page.",
            "eval": [{"expected": {"task_type": "RETRIEVE"}}],
        }
        page = FakePage(url="http://shopping.local/example-product.html#reviews", rows=[])

        action = deterministic_shopping_review_retrieve_action(
            task=task,
            site_name="shopping",
            page=page,
            previous_steps=[
                {"action": "goto(\"http://shopping.local/example-product.html#reviews\")", "status": "success"},
                {"action": "scroll(0, 1200)", "status": "success"},
                {"action": "scroll(0, 1200)", "status": "success"},
                {"action": "scroll(0, 1200)", "status": "success"},
            ],
        )

        self.assertIn('\\"retrieved_data\\": []', action)


class PlanActGroundingTests(unittest.TestCase):
    def test_ax_candidates_support_single_and_double_quotes(self) -> None:
        obs = {
            "axtree_object": """
            [12] link '12 Reviews'
            [42] button "Search"
            """
        }

        candidates = ax_candidates(obs)

        self.assertEqual([candidate.bid for candidate in candidates], ["12", "42"])
        self.assertEqual(candidates[0].text, "12 Reviews")
        self.assertEqual(candidates[1].text, "Search")

    def test_dom_candidates_keep_only_executable_bids(self) -> None:
        page = FakePage(
            rows=[
                {
                    "bid": "42",
                    "tag": "input",
                    "role": "input",
                    "text": "",
                    "placeholder": "Search",
                    "outer_html": '<input data-label-id="42" placeholder="Search" class="x">',
                },
                {
                    "bid": "",
                    "tag": "button",
                    "role": "button",
                    "text": "No bid",
                    "outer_html": "<button>No bid</button>",
                },
            ]
        )

        candidates = dom_candidates(page)

        self.assertEqual([candidate.bid for candidate in candidates], ["42"])
        self.assertIn('data-label-id="42"', candidates[0].html or "")
        self.assertNotIn('class="x"', candidates[0].html or "")

    def test_prioritize_candidates_uses_task_and_row_context(self) -> None:
        candidates = [
            GroundedCandidate(bid="1", role="button", text="Edit", context="Product: Random backpack"),
            GroundedCandidate(bid="2", role="button", text="Edit", context="Product: Aeon Capri Stock Status In Stock"),
        ]

        ranked = prioritize_candidates(
            candidates,
            task={"intent": "Set Aeon Capri out of stock"},
            subgoal=Subgoal(id="sg1", objective="Open Aeon Capri row", expected_outcome="Product edit page"),
            site_name="shopping_admin",
        )

        self.assertEqual(ranked[0].bid, "2")

    def test_gitlab_editor_like_candidates_are_prioritized(self) -> None:
        candidates = [
            GroundedCandidate(bid="146", role="button", text="Preview", context="Edit file"),
            GroundedCandidate(
                bid="522",
                role="textbox",
                tag="div",
                text="",
                context="editor_like | code_editor_hint | editable_tag=textarea | editable_value=<title>Old</title>",
            ),
        ]

        ranked = prioritize_candidates(
            candidates,
            task={"intent": "Update and commit the website code using the simple online file editor to change the browser tab title"},
            subgoal=Subgoal(id="sg1", objective="Edit the title in index.html", expected_outcome="Title changed"),
            site_name="gitlab",
        )

        self.assertEqual(ranked[0].bid, "522")

    def test_gitlab_modal_candidates_outrank_background_filter(self) -> None:
        candidates = [
            GroundedCandidate(
                bid="450",
                role="input",
                tag="input",
                placeholder="Filter members",
                context="background_while_modal_visible | active_modal_text=Invite members Username or email address Select a role",
            ),
            GroundedCandidate(
                bid="626",
                role="combobox",
                tag="input",
                placeholder="Username or email address",
                context="inside_modal | modal_text=Invite members Username or email address Select a role Invite",
            ),
        ]

        ranked = prioritize_candidates(
            candidates,
            task={"intent": "create a new group with members JonasVautherin"},
            subgoal=Subgoal(id="sg2", objective="Invite members", expected_outcome="Members invited"),
            site_name="gitlab",
        )

        self.assertEqual(ranked[0].bid, "626")

    def test_focus_modal_candidates_hides_background_overlay_targets(self) -> None:
        candidates = [
            GroundedCandidate(
                bid="415",
                role="button",
                text="Invite members",
                context="background_while_modal_visible | active_modal_text=Invite members Username or email address",
            ),
            GroundedCandidate(
                bid="626",
                role="combobox",
                tag="input",
                placeholder="Username or email address",
                context="inside_modal | modal_text=Invite members Username or email address Select a role Invite",
            ),
        ]

        focused = focus_modal_candidates(candidates)

        self.assertEqual([candidate.bid for candidate in focused], ["626"])

    def test_dom_candidates_include_editor_hint_context(self) -> None:
        page = FakePage(
            rows=[
                {
                    "bid": "522",
                    "tag": "div",
                    "role": "textbox",
                    "text": "",
                    "editor_hint": "editor_like | code_editor_hint | editable_tag=textarea | editable_value=<title>Old</title>",
                    "outer_html": '<div data-label-id="522" role="textbox"><textarea><title>Old</title></textarea></div>',
                }
            ]
        )

        candidates = dom_candidates(page)

        self.assertEqual(candidates[0].bid, "522")
        self.assertIn("editor_like", candidates[0].context or "")
        self.assertIn("editable_value", candidates[0].context or "")

    def test_dom_candidates_include_codemirror_editor_hint_context(self) -> None:
        page = FakePage(
            rows=[
                {
                    "bid": "334",
                    "tag": "div",
                    "role": "textbox",
                    "text": "",
                    "editor_hint": "editor_like | code_editor_hint | editable_tag=div | editable_value=<title>Old</title>",
                    "outer_html": '<div data-label-id="334" role="textbox" class="cm-editor"><div class="cm-content" contenteditable="true"><title>Old</title></div></div>',
                }
            ]
        )

        candidates = dom_candidates(page)

        self.assertEqual(candidates[0].bid, "334")
        self.assertIn("code_editor_hint", candidates[0].context or "")


class V3RecoveryTests(unittest.TestCase):
    def test_v3_is_planact_like(self) -> None:
        self.assertTrue(is_planact_like_architecture("v3"))
        self.assertTrue(is_planact_like_architecture("v3_repair_brief"))
        self.assertTrue(is_planact_like_architecture("v3_repair_llm"))

    def test_v3_repair_llm_architecture_resolves_from_experiment_name(self) -> None:
        self.assertEqual(resolve_agent_architecture(None, "hk-agent-v3-repair-llm-smoke"), "v3_repair_llm")
        self.assertEqual(resolve_agent_architecture(None, "hk-agent-v3_repair_llm-smoke"), "v3_repair_llm")

    def test_recovery_hint_detects_gitlab_html_dump(self) -> None:
        page = FakePage(url="http://gitlab.local/-/ide/project/x/y/edit/main/-/index.html", text="IDE GitLab")
        hint = build_recovery_hint(
            task={"intent": "Update and commit the title in index.html"},
            site_name="gitlab",
            previous_steps=[
                {
                    "action": 'noop(1000)',
                    "error": 'Executor response did not contain usable JSON; response_preview=\'fill("518", "<!DOCTYPE html><html><head><meta charset=\\"utf-8\\"><title>Title Wanted</title>")\'',
                }
            ],
            page=page,
        )

        self.assertIsNotNone(hint)
        self.assertEqual(hint["error_class"], "gitlab_editor_html_dump")

    def test_gitlab_fork_repair_uses_keyboard_for_unbidded_namespace_options(self) -> None:
        task = {"intent": "Fork all repos from facebook.", "task_type": "MUTATE"}
        page = FakePage(
            url="http://gitlab.local/facebook/create-react-app/-/forks/new",
            text="Fork project Project URL Select a namespace Namespaces x-lab2 x-lab1",
        )

        self.assertEqual(
            deterministic_gitlab_fork_repair_action(task=task, site_name="gitlab", page=page, previous_steps=[]),
            'click("508")',
        )
        self.assertEqual(
            deterministic_gitlab_fork_repair_action(
                task=task,
                site_name="gitlab",
                page=page,
                previous_steps=[{"action": 'click("508")'}],
            ),
            'press("508", "ArrowDown")',
        )
        self.assertEqual(
            deterministic_gitlab_fork_repair_action(
                task=task,
                site_name="gitlab",
                page=page,
                previous_steps=[{"action": 'press("508", "ArrowDown")'}],
            ),
            'press("508", "Enter")',
        )

    def test_recovery_hint_detects_stale_bid_targets(self) -> None:
        page = FakePage(url="http://gitlab.local/facebook/create-react-app", text="Fork 0")
        hint = build_recovery_hint(
            task={"intent": "Fork all repos from facebook."},
            site_name="gitlab",
            previous_steps=[
                {
                    "action": "noop(1000)",
                    "error": "Action target '1127' is not a current interactive candidate bid",
                }
            ],
            page=page,
        )

        self.assertIsNotNone(hint)
        self.assertEqual(hint["error_class"], "invalid_bid_or_stale_candidate")
        self.assertEqual(hint["stale_bid_targets"], ["1127"])

    def test_recovery_hint_specializes_gitlab_invite_modal_stale_bid(self) -> None:
        page = FakePage(
            url="http://gitlab.local/groups/x-lab/-/group_members",
            text="Invite members Username or email address Select a role Filter members",
        )
        hint = build_recovery_hint(
            task={"intent": "create a new group with members JonasVautherin"},
            site_name="gitlab",
            previous_steps=[
                {
                    "action": "noop(1000)",
                    "error": "Action target '626' is not a current interactive candidate bid",
                }
            ],
            page=page,
        )

        self.assertIsNotNone(hint)
        self.assertEqual(hint["error_class"], "gitlab_invite_modal_missing_candidate")

    def test_k_repair_brief_detects_gitlab_invite_modal(self) -> None:
        page = FakePage(
            url="http://gitlab.local/groups/x-lab/-/group_members",
            text="Invite members Username or email address Select a role Filter members",
        )
        decision = type("Decision", (), {"decision": "local_replan"})()
        signal = type("Signal", (), {"reason": "action_error"})()

        brief = build_k_repair_brief(
            task={"intent": "create a new group with members JonasVautherin"},
            site_name="gitlab",
            page=page,
            previous_steps=[{"action": 'fill("450", "JonasVautherin")'}],
            evaluator_signal=signal,
            controller_decision=decision,
            recovery_hint={"error_class": "gitlab_invite_modal_wrong_input"},
            last_error="Action target is stale",
        )

        self.assertIsNotNone(brief)
        self.assertEqual(brief["repair_prompt_version"], "v3_repair_prompt")
        self.assertEqual(brief["failure_class"], "gitlab_invite_modal_repair")
        self.assertIn("Filter members", brief["avoid"])

    def test_k_repair_brief_detects_gitlab_fork_missing_submit(self) -> None:
        page = FakePage(url="http://gitlab.local/users/facebook/projects", text="facebook projects create-react-app")
        decision = type("Decision", (), {"decision": "local_replan"})()

        brief = build_k_repair_brief(
            task={"intent": "Fork all repos from facebook."},
            site_name="gitlab",
            page=page,
            previous_steps=[{"action": 'goto("http://gitlab.local/users/facebook/projects")'}],
            evaluator_signal=None,
            controller_decision=decision,
            recovery_hint=None,
        )

        self.assertIsNotNone(brief)
        self.assertEqual(brief["failure_class"], "gitlab_fork_missing_submit")
        self.assertIn("/-/forks/new", brief["needed_next_target"])

    def test_v3_repair_brief_compacts_to_operational_fields(self) -> None:
        compact = compact_repair_brief_for_prompt(
            {
                "failure_class": "gitlab_invite_modal_repair",
                "current_state": "Invite members modal is visible.",
                "wrong_actions": ['fill("450", "x")'],
                "avoid": ["Filter members"],
                "needed_next_target": "inside-modal username/email input",
                "repair_strategy": "Use modal candidates only.",
                "planner_instruction": "Repair modal step.",
                "executor_instruction": "Use inside_modal candidates.",
                "source_recovery_hint": {"large": "not needed in prompt"},
            }
        )

        self.assertEqual(compact["failure"], "gitlab_invite_modal_repair")
        self.assertEqual(compact["must_use"], "inside-modal username/email input")
        self.assertNotIn("source_recovery_hint", compact)

    def test_v3_repair_brief_allows_one_refresh_noop_for_modal_candidate_gap(self) -> None:
        repair_brief = {
            "failure_class": "gitlab_invite_modal_repair",
            "repair_strategy": "If modal candidates are missing, wait once for refreshed candidates.",
        }

        self.assertTrue(
            allow_single_repair_refresh_noop(
                architecture="v3_repair_brief",
                repair_brief=repair_brief,
                previous_steps=[],
            )
        )
        self.assertFalse(
            allow_single_repair_refresh_noop(
                architecture="v3_repair_brief",
                repair_brief=repair_brief,
                previous_steps=[{"action": "noop(1000)"}],
            )
        )

    def test_v3_repair_brief_repeated_failure_class_is_detected(self) -> None:
        plan_history = {
            "repair_briefs": [
                {"repair_brief": {"failure_class": "gitlab_invite_modal_repair"}},
                {"repair_brief": {"failure_class": "gitlab_invite_modal_repair"}},
                {"repair_brief": {"failure_class": "gitlab_invite_modal_repair"}},
                {"repair_brief": {"failure_class": "gitlab_invite_modal_repair"}},
            ]
        }

        self.assertEqual(repeated_repair_failure_class(plan_history), "gitlab_invite_modal_repair")

    def test_v3_repair_llm_sanitizes_actions_and_bids_from_critic_text(self) -> None:
        self.assertNotIn("click(", _sanitize_repair_text('click("1234") on the visible Fork button'))
        self.assertNotIn("1234", _sanitize_repair_text("Use bid: 1234 for the modal input"))
        self.assertIn("current grounded candidate", _sanitize_repair_text("Use bid: 1234 for the modal input"))


class PlanActValidatorTests(unittest.TestCase):
    def test_rejects_visible_label_and_selector_targets(self) -> None:
        base = base_url_from_url("http://shopping.local/")

        with self.assertRaisesRegex(ValueError, "selector or visible label"):
            validate_browsergym_action('click("Search")', base, {"42"}, strict_ui_targets=True)

        with self.assertRaisesRegex(ValueError, "selector or visible label"):
            validate_browsergym_action('click("12 Reviews")', base, {"12"}, strict_ui_targets=True)

        with self.assertRaisesRegex(ValueError, "selector or visible label"):
            validate_browsergym_action('click("input[placeholder=Search]")', base, {"42"}, strict_ui_targets=True)

    def test_accepts_current_bid_only(self) -> None:
        base = base_url_from_url("http://shopping.local/")

        self.assertEqual(validate_browsergym_action('click("42")', base, {"42"}, strict_ui_targets=True), 'click("42")')
        self.assertEqual(validate_browsergym_action("click(42)", base, {"42"}, strict_ui_targets=True), 'click("42")')
        with self.assertRaisesRegex(ValueError, "not a current interactive candidate"):
            validate_browsergym_action('click("99")', base, {"42"}, strict_ui_targets=True)

    def test_rejects_full_html_document_fill(self) -> None:
        base = base_url_from_url("http://gitlab.local/")
        action = 'fill("42", "<!DOCTYPE html><html><head><title>Title Wanted</title></head><body>content</body></html>")'

        with self.assertRaisesRegex(ValueError, "full HTML document dump"):
            validate_browsergym_action(action, base, {"42"}, strict_ui_targets=True)

    def test_normalizes_same_site_url_click_to_goto(self) -> None:
        base = base_url_from_url("http://gitlab.local/foo")

        action = validate_browsergym_action(
            'click("https://gitlab.com/openapitools/openapi-generator/-/issues?labels=OpenAPI%20Generator%20CLI")',
            base,
            {"42"},
            strict_ui_targets=True,
        )

        self.assertEqual(
            action,
            'goto("http://gitlab.local/openapitools/openapi-generator/-/issues?label_name%5B%5D=OpenAPI+Generator+CLI")',
        )

    def test_normalizes_directional_scroll(self) -> None:
        base = base_url_from_url("http://reddit.local/")

        self.assertEqual(validate_browsergym_action('scroll(direction="down")', base, {"42"}, strict_ui_targets=True), "scroll(0, 600)")
        self.assertEqual(validate_browsergym_action('scroll_to("reviews")', base, {"42"}, strict_ui_targets=True), "scroll(0, 1200)")
        self.assertEqual(validate_browsergym_action("scroll(500)", base, {"42"}, strict_ui_targets=True), "scroll(0, 500)")

    def test_normalizes_navigate_action_alias(self) -> None:
        base = base_url_from_url("http://shopping.local/")

        self.assertEqual(
            validate_browsergym_action('navigate("http://shopping.local/sales/order/history/")', base, {"42"}, strict_ui_targets=True),
            'goto("http://shopping.local/sales/order/history/")',
        )
        self.assertEqual(
            validate_browsergym_action('select("712", "delete")', base, {"712"}, strict_ui_targets=True),
            'select_option("712", "delete")',
        )

    def test_normalizes_structured_executor_action_fields(self) -> None:
        self.assertEqual(
            normalize_structured_action_fields({"action": "click", "action_target": "149", "action_type": "click"}),
            'click("149")',
        )
        self.assertEqual(
            normalize_structured_action_fields({"action": "type", "action_input": {"bid": "522", "text": "Title Wanted"}}),
            'type("522", "Title Wanted")',
        )
        self.assertEqual(
            normalize_structured_action_fields(
                {"action": "select", "action_type": "select", "action_input": {"bid": "712", "value": "delete"}}
            ),
            'select_option("712", "delete")',
        )
        self.assertEqual(
            normalize_structured_action_fields({"action": "click", "action_input": "333", "action_type": "click"}),
            'click("333")',
        )
        self.assertEqual(
            normalize_structured_action_fields(
                {"action": "fill", "action_input": '{"bid": "450", "value": "JonasVautherin"}', "action_type": "fill"}
            ),
            'fill("450", "JonasVautherin")',
        )
        self.assertEqual(
            normalize_structured_action_fields({"action": "press", "action_args": {"bid": "0", "key": "ArrowLeft"}}),
            'press("0", "ArrowLeft")',
        )
        self.assertEqual(
            normalize_structured_action_fields(
                {"action": "type", "action_id": "522", "action_params": {"text": "Title Wanted"}}
            ),
            'type("522", "Title Wanted")',
        )
        self.assertEqual(
            normalize_structured_action_fields({"action": "type", "action_id": "334", "action_input": "Title Wanted"}),
            'type("334", "Title Wanted")',
        )
        self.assertEqual(
            normalize_structured_action_fields({"action": "wait", "action_type": "wait"}),
            "noop(1000)",
        )
        self.assertEqual(
            normalize_structured_action_fields(
                {
                    "action": "finish()",
                    "action_type": "finish",
                    "expected_observation": '{"task_type":"MUTATE","status":"SUCCESS","retrieved_data":null,"error_details":null}',
                }
            ),
            'send_msg_to_user("{\\"task_type\\":\\"MUTATE\\",\\"status\\":\\"SUCCESS\\",\\"retrieved_data\\":null,\\"error_details\\":null}")',
        )
        self.assertEqual(
            normalize_structured_action_fields({"action": "navigate", "action_type": "navigate", "action_input": "http://shopping.local/cart"}),
            'goto("http://shopping.local/cart")',
        )

    def test_gitlab_state_detects_invite_modal(self) -> None:
        page = FakePage(
            url="http://gitlab.local/groups/x-lab/-/group_members",
            text="Invite members Username or email address Select a role Filter members",
        )
        state = gitlab_state_diagnosis(
            task={"intent": "create a new group with members JonasVautherin", "task_type": "MUTATE"},
            site_name="gitlab",
            page=page,
            candidates=[
                GroundedCandidate(
                    bid="626",
                    role="combobox",
                    placeholder="Username or email address",
                    context="inside_modal | modal_text=Invite members Username or email address",
                )
            ],
        )

        self.assertIsNotNone(state)
        self.assertEqual(state["workflow"], "group_invite_modal_visible")
        self.assertIn("626", state["preferred_current_bids"])

    def test_gitlab_state_detects_simple_editor(self) -> None:
        page = FakePage(
            url="http://gitlab.local/byteblaze/site/-/edit/main/index.html",
            text="Edit file Commit changes",
        )
        state = gitlab_state_diagnosis(
            task={
                "intent": "Update and commit using the simple online file editor to change the browser tab title",
                "task_type": "MUTATE",
            },
            site_name="gitlab",
            page=page,
            candidates=[
                GroundedCandidate(
                    bid="522",
                    role="textbox",
                    context="editor_like | code_editor_hint | editable_tag=textarea",
                )
            ],
        )

        self.assertIsNotNone(state)
        self.assertEqual(state["workflow"], "simple_file_editor_visible")
        self.assertIn("522", state["preferred_current_bids"])

    def test_retrieve_success_requires_visible_evidence(self) -> None:
        page = FakePage(text="Visible author: Jordan", html="<body>Visible author: Jordan</body>")
        action = (
            'send_msg_to_user("{\\"task_type\\":\\"RETRIEVE\\",\\"status\\":\\"SUCCESS\\",'
            '\\"retrieved_data\\":[{\\"author\\":\\"Emma Lopez\\"}],\\"error_details\\":null}")'
        )

        with self.assertRaisesRegex(ValueError, "not grounded"):
            validate_grounded_final_response(
                action=action,
                data={"rationale_summary": "value was visible"},
                task={"intent": "return a list of authors"},
                page=page,
            )

    def test_retrieve_finish_with_data_normalizes_to_final_response(self) -> None:
        action = normalize_finish_action_from_context(
            'finish(retrieved_data="git@localhost:convexegg/super_awesome_robot.git")',
            {"rationale_summary": "The SSH clone URL is visible."},
            {"intent": "Get the URL to clone Super_Awesome_Robot with SSH. Return the URL only."},
        )

        self.assertTrue(action.startswith("send_msg_to_user("))
        self.assertIn("RETRIEVE", action)
        self.assertIn("git@localhost:convexegg/super_awesome_robot.git", action)

    def test_review_title_final_response_normalizes_object_list_to_title_list(self) -> None:
        action = (
            'send_msg_to_user("{\\"task_type\\":\\"RETRIEVE\\",\\"status\\":\\"SUCCESS\\",'
            '\\"retrieved_data\\":[{\\"title\\":\\"Visible review title\\",\\"rating\\":2}],\\"error_details\\":null}")'
        )

        normalized = normalize_retrieve_final_response_schema(
            action,
            {"intent": "Get all review titles with 2 stars or below for the product on the current page."},
        )

        self.assertIn('\\"retrieved_data\\": [\\"Visible review title\\"]', normalized)

    def test_retrieve_success_accepts_input_value_evidence(self) -> None:
        page = FakePage(
            text="Clone SSH",
            html="<body><input name='ssh_project_clone'></body>",
            rows=[
                {
                    "bid": "723",
                    "name": "ssh_project_clone",
                    "value": "git@localhost:convexegg/super_awesome_robot.git",
                }
            ],
        )
        action = (
            'send_msg_to_user("{\\"task_type\\":\\"RETRIEVE\\",\\"status\\":\\"SUCCESS\\",'
            '\\"retrieved_data\\":[\\"git@localhost:convexegg/super_awesome_robot.git\\"],\\"error_details\\":null}")'
        )

        validate_grounded_final_response(
            action=action,
            data={"rationale_summary": "The value is visible in the SSH clone input field."},
            task={"intent": "Get the URL to clone Super_Awesome_Robot with SSH. Return the URL only."},
            page=page,
        )

    def test_numeric_retrieve_success_requires_evidence_note(self) -> None:
        page = FakePage(text="One Two Three", html="<body>One Two Three</body>")
        action = (
            'send_msg_to_user("{\\"task_type\\":\\"RETRIEVE\\",\\"status\\":\\"SUCCESS\\",'
            '\\"retrieved_data\\":[3],\\"error_details\\":null}")'
        )

        with self.assertRaisesRegex(ValueError, "evidence note"):
            validate_grounded_final_response(action=action, data={"rationale_summary": ""}, task={"intent": "return a list with the count"}, page=page)

        validate_grounded_final_response(
            action=action,
            data={"rationale_summary": "calculated count from visible matching rows"},
            task={"intent": "return a list with the count"},
            page=page,
        )

    def test_mutate_success_requires_state_evidence_note(self) -> None:
        action = (
            'send_msg_to_user("{\\"task_type\\":\\"MUTATE\\",\\"status\\":\\"SUCCESS\\",'
            '\\"retrieved_data\\":null,\\"error_details\\":null}")'
        )
        previous_steps = [{"step_index": 1, "action": 'click("42")', "status": "success", "error": None, "mutation_action_kind": "submit_click"}]

        with self.assertRaisesRegex(ValueError, "current-state evidence"):
            validate_mutation_success_state_check(
                action=action,
                data={"rationale_summary": "done"},
                task={"intent": "Create a new GitLab group"},
                site_name="gitlab",
                previous_steps=previous_steps,
            )

        validate_mutation_success_state_check(
            action=action,
            data={"rationale_summary": "The current page shows a visible created confirmation."},
            task={"intent": "Create a new GitLab group"},
            site_name="gitlab",
            previous_steps=[{**previous_steps[0], "visible_state_after": "Success Created group"}],
        )

    def test_mutate_success_requires_observation_after_submit(self) -> None:
        action = (
            'send_msg_to_user("{\\"task_type\\":\\"MUTATE\\",\\"status\\":\\"SUCCESS\\",'
            '\\"retrieved_data\\":null,\\"error_details\\":null}")'
        )
        previous_steps = [{"step_index": 1, "action": 'click("42")', "status": "success", "error": None, "mutation_action_kind": "submit_click"}]

        with self.assertRaisesRegex(ValueError, "observation/state check"):
            validate_mutation_success_state_check(
                action=action,
                data={"rationale_summary": "The current page shows a visible created confirmation."},
                task={"intent": "Create a new GitLab group"},
                site_name="gitlab",
                previous_steps=previous_steps,
                require_observed_after_submit=True,
            )

    def test_mutate_success_rejects_only_filling_fields(self) -> None:
        action = (
            'send_msg_to_user("{\\"task_type\\":\\"MUTATE\\",\\"status\\":\\"SUCCESS\\",'
            '\\"retrieved_data\\":null,\\"error_details\\":null}")'
        )
        previous_steps = [{"action": 'fill("42", "new value")', "status": "success", "error": None, "mutation_action_kind": "fill_field"}]

        with self.assertRaisesRegex(ValueError, "not only filling"):
            validate_mutation_success_state_check(
                action=action,
                data={"rationale_summary": "The current page shows a visible updated state."},
                task={"intent": "Update the GitLab file"},
                site_name="gitlab",
                previous_steps=previous_steps,
            )

    def test_shopping_order_history_without_edit_finishes_action_not_allowed(self) -> None:
        page = FakePage(
            url="http://shopping.local/sales/order/history/",
            text="My Orders Order # Date Ship To Order Total Status View Order",
            rows=[
                {
                    "bid": "42",
                    "tag": "a",
                    "role": "link",
                    "text": "View Order",
                    "outer_html": '<a data-label-id="42" href="/sales/order/view/order_id/188">View Order</a>',
                }
            ],
        )

        action = deterministic_shopping_policy_action(
            task={"intent": "Change the delivery address for my first order ever to 3 Oxford St, Cambridge, MA."},
            site_name="shopping",
            page=page,
            previous_steps=[],
        )

        self.assertIsNotNone(action)
        self.assertIn("ACTION_NOT_ALLOWED_ERROR", action or "")

    def test_shopping_purchase_success_requires_cart_clear_evidence(self) -> None:
        action = (
            'send_msg_to_user("{\\"task_type\\":\\"MUTATE\\",\\"status\\":\\"SUCCESS\\",'
            '\\"retrieved_data\\":null,\\"error_details\\":null}")'
        )
        previous_steps = [
            {
                "step_index": 1,
                "action": 'click("42")',
                "status": "success",
                "error": None,
                "mutation_action_kind": "submit_click",
                "state_change_hint": "visible_excerpt=My Cart 5 items",
                "visible_state_after": "My Cart 5 items",
            }
        ]

        with self.assertRaisesRegex(ValueError, "multiple cart items"):
            validate_mutation_success_state_check(
                action=action,
                data={"rationale_summary": "Thank you for your purchase. Order number visible."},
                task={"intent": "Buy a product. Discard any items in your cart if it is not empty."},
                site_name="shopping",
                previous_steps=previous_steps,
                page=FakePage(text="Thank you for your purchase! My Cart 5"),
            )

    def test_shopping_review_retrieve_extracts_visible_review_authors(self) -> None:
        page = FakePage(
            url="http://shopping.local/product.html#reviews",
            rows=[
                {"author": "Alice", "rating_title": "80%", "rating_style": "width: 80%;", "text": "Review by Alice 4 stars"},
                {"author": "Bob", "rating_title": "60%", "rating_style": "width: 60%;", "text": "Review by Bob 3 stars"},
                {"author": "Cally", "rating_title": "100%", "rating_style": "width: 100%;", "text": "Review by Cally 5 stars"},
            ],
        )

        action = deterministic_shopping_review_retrieve_action(
            task={
                "intent": "Who gave 4 or 5 stars for phone cases",
                "task_type": "RETRIEVE",
                "task_capability": "retrieve_reviews",
            },
            site_name="shopping",
            page=page,
        )

        self.assertIsNotNone(action)
        self.assertIn("Alice", action)
        self.assertIn("Cally", action)
        self.assertNotIn("Bob", action)

    def test_gitlab_file_edit_rejects_root_editor_candidate(self) -> None:
        page = FakePage(url="http://gitlab.local/byteblaze/site/-/edit/main/index.html", text="Edit file")
        subgoal = Subgoal(id="sg1", objective="Edit title", expected_outcome="Title changed")
        content = json.dumps(
            {
                "subgoal_id": "sg1",
                "action": 'type("0", "Title Wanted")',
                "action_type": "type",
                "rationale_summary": "Trying to edit the title",
                "expected_observation": "Title changed",
            }
        )

        from hk_agent.executor import _parse_executor_decision  # noqa: PLC0415

        with self.assertRaisesRegex(ValueError, "page root/body"):
            _parse_executor_decision(
                content=content,
                task={"intent": "Update and commit using the simple online file editor", "task_type": "MUTATE"},
                site_name="gitlab",
                subgoal=subgoal,
                obs={},
                page=page,
                previous_steps=[],
                architecture="v3",
                current_candidates=[
                    GroundedCandidate(
                        bid="0",
                        role="document",
                        tag="html",
                        context="",
                    )
                ],
            )

    def test_repeated_no_progress_actions_are_detected(self) -> None:
        previous_steps = [
            {"action": 'click("1288")', "url_before": "http://gitlab.local/-/ide", "url_after": "http://gitlab.local/-/ide", "title_before": "IDE", "title_after": "IDE"},
            {"action": 'click("1288")', "url_before": "http://gitlab.local/-/ide", "url_after": "http://gitlab.local/-/ide", "title_before": "IDE", "title_after": "IDE"},
        ]

        self.assertEqual(repeated_no_progress_actions(previous_steps), ['click("1288")'])

    def test_mutation_diagnostics_catch_premature_success(self) -> None:
        diagnostic = mutation_diagnostics(
            task_type="MUTATE",
            tier="mutation",
            action_kinds=["navigate", "finish"],
            errors=[],
            final_kind="finish",
            final_status="SUCCESS",
        )

        self.assertTrue(diagnostic["is_mutate_task"])
        self.assertTrue(diagnostic["final_success_without_mutation_action"])
        self.assertEqual(diagnostic["mutation_eval_focus"], "state_change_required")

    def test_contamination_adjusted_eval_accepts_only_duplicate_suffix_failure(self) -> None:
        eval_result = {
            "evaluators_results": [
                {
                    "evaluator_name": "AgentResponseEvaluator",
                    "status": "success",
                },
                {
                    "evaluator_name": "NetworkEventEvaluator",
                    "status": "failure",
                    "actual_normalized": [
                        {
                            "url": {"base_url": "__GITLAB__/groups", "query_params": {}},
                            "post_data": {"group[name]": "x lab", "group[path]": "x lab14"},
                            "response_status": 302,
                            "http_method": "POST",
                        }
                    ],
                    "expected": {
                        "url": {"base_url": "__GITLAB__/groups", "query_params": {}},
                        "post_data": {"group[name]": "x lab", "group[path]": "x lab"},
                        "response_status": 302,
                        "http_method": "POST",
                    },
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "eval_result.json").write_text(json.dumps(eval_result), encoding="utf-8")
            diagnostic = contamination_adjusted_eval_diagnostics(Path(tmpdir))

        self.assertTrue(diagnostic["official_eval_contamination_suffix_detected"])
        self.assertTrue(diagnostic["contamination_adjusted_success"])
        self.assertEqual(diagnostic["official_eval_nonadjustable_failures"], 0)

    def test_contamination_adjusted_eval_rejects_suffix_plus_missing_event(self) -> None:
        eval_result = {
            "evaluators_results": [
                {
                    "evaluator_name": "NetworkEventEvaluator",
                    "status": "failure",
                    "actual_normalized": [
                        {
                            "url": {"base_url": "__GITLAB__/groups", "query_params": {}},
                            "post_data": {"group[name]": "x lab", "group[path]": "x lab14"},
                            "response_status": 302,
                            "http_method": "POST",
                        }
                    ],
                    "expected": {
                        "url": {"base_url": "__GITLAB__/groups", "query_params": {}},
                        "post_data": {"group[name]": "x lab", "group[path]": "x lab"},
                        "response_status": 302,
                        "http_method": "POST",
                    },
                },
                {
                    "evaluator_name": "NetworkEventEvaluator",
                    "status": "failure",
                    "actual_normalized": None,
                    "expected": {
                        "url": {"base_url": "^__GITLAB__/api/v4/groups/\\d+/invitations$", "query_params": {}},
                        "post_data": {"user_id": ["340"]},
                        "response_status": 201,
                        "http_method": "POST",
                    },
                },
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "eval_result.json").write_text(json.dumps(eval_result), encoding="utf-8")
            diagnostic = contamination_adjusted_eval_diagnostics(Path(tmpdir))

        self.assertTrue(diagnostic["official_eval_contamination_suffix_detected"])
        self.assertFalse(diagnostic["contamination_adjusted_success"])
        self.assertEqual(diagnostic["official_eval_nonadjustable_failures"], 1)

    def test_contamination_adjusted_eval_accepts_har_referer_trailing_slash(self) -> None:
        eval_result = {
            "evaluators_results": [
                {"evaluator_name": "AgentResponseEvaluator", "status": "success"},
                {
                    "evaluator_name": "NetworkEventEvaluator",
                    "status": "failure",
                    "actual": [{"url": "http://localhost:7780/admin/sales/order/", "response_status": 200, "http_method": "GET"}],
                    "expected": {
                        "url": {
                            "base_url": "^__SHOPPING_ADMIN__/mui/index/render/.*$",
                            "query_params": {
                                "namespace": ["sales_order_grid"],
                                "filters[placeholder]": ["true"],
                                "filters[status]": ["complete"],
                                "search": [""],
                                "keywordUpdated": ["false"],
                            },
                        },
                        "headers": {"referer": {"base_url": "__SHOPPING_ADMIN__/sales/order", "query_params": {}}},
                        "response_status": 200,
                        "http_method": "GET",
                    },
                },
            ]
        }
        har = {
            "log": {
                "entries": [
                    {
                        "request": {
                            "method": "GET",
                            "url": (
                                "http://localhost:7780/admin/mui/index/render/?namespace=sales_order_grid"
                                "&filters%5Bplaceholder%5D=true&filters%5Bstatus%5D=complete"
                                "&search=&keywordUpdated=false&isAjax=true"
                            ),
                            "headers": [{"name": "Referer", "value": "http://localhost:7780/admin/sales/order/"}],
                        },
                        "response": {"status": 200},
                    }
                ]
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "eval_result.json").write_text(json.dumps(eval_result), encoding="utf-8")
            (Path(tmpdir) / "network.har").write_text(json.dumps(har), encoding="utf-8")
            diagnostic = contamination_adjusted_eval_diagnostics(Path(tmpdir))

        self.assertTrue(diagnostic["contamination_adjusted_success"])
        self.assertEqual(diagnostic["official_eval_nonadjustable_failures"], 0)
        self.assertIn("trailing-slash URL normalization", diagnostic["contamination_adjusted_reason"])

    def test_vertex_proxy_backend_metadata(self) -> None:
        metadata = llm_backend_metadata("http://127.0.0.1:11435")

        self.assertEqual(metadata["llm_backend"], "vertex_ollama_proxy")
        self.assertTrue(metadata["vertex_proxy_enabled"])

    def test_reddit_most_recent_forum_route_uses_new_listing(self) -> None:
        action = deterministic_reddit_action(
            task={"intent": "get the username and post title of the most recent post"},
            site_name="reddit",
            subgoal=Subgoal(id="sg1", objective="Find the most recent post", expected_outcome="Newest post visible"),
            page=FakePage(url="http://localhost:9999/f/personalfinance"),
        )

        self.assertEqual(action, 'goto("http://localhost:9999/f/personalfinance/new")')

    def test_reddit_no_comments_retrieve_is_grounded(self) -> None:
        page = FakePage(
            url="http://localhost:9999/f/personalfinance/130948/title",
            text="56 year old mom has no retirement. Where do I even start on her behalf?\nSubmitted by Hammer94 t3_1284icy\nNo comments",
        )
        page.title = lambda: "56 year old mom has no retirement. Where do I even start on her behalf?"  # type: ignore[method-assign]

        action = deterministic_reddit_action(
            task={"intent": "get the username and post_title and count of comments"},
            site_name="reddit",
            subgoal=Subgoal(id="sg1", objective="Return username post_title count", expected_outcome="Retrieved data returned"),
            page=page,
        )

        self.assertIn('\\"username\\": \\"Hammer94\\"', action or "")
        self.assertIn('\\"count\\": 0', action or "")

    def test_v2_planact_uses_webarena_verified_prompt_basis(self) -> None:
        prompt = build_executor_system_prompt(
            task={
                "intent": "Fork the target project",
                "sites": ["gitlab"],
                "start_urls": ["http://gitlab.local/"],
            },
            site_name="gitlab",
            prompt_path=REPO_ROOT / "prompts/executor_system.md",
            architecture="v2_planact",
        )

        self.assertIn("Prompt Provenance", prompt)
        self.assertIn("external/webarena-verified/examples/prompts/gitlab.md", prompt)
        self.assertIn("Task Objective:** `Fork the target project`", prompt)
        self.assertIn("WebArena-Verified Executor v2", prompt)


if __name__ == "__main__":
    unittest.main()
