"""Runtime evaluator interfaces for H/k prototype runs.

This module is not the official WebArena-Verified evaluator. It only emits
intermediate runtime signals for controller decisions and process analysis.
"""

from __future__ import annotations

from .types import EvaluatorSignal, Subgoal


def evaluate_gitlab_task44_state(page, step_index: int, subgoal: Subgoal, previous_urls: list[str]) -> EvaluatorSignal:
    """Evaluate local progress for GitLab Task 44."""

    current_url = page.url
    at_todos = "/dashboard/todos" in current_url
    login_visible = page.locator("#user_login").count() > 0
    repeated_url = len(previous_urls) >= 2 and previous_urls[-1] == current_url and previous_urls[-2] == current_url
    subgoal_text = f"{subgoal.objective} {subgoal.expected_outcome}".lower()

    if any(keyword in subgoal_text for keyword in ["todo", "todos", "/dashboard/todos"]):
        done = at_todos
        reason = "todos_url_reached" if done else "todos_url_not_reached"
    elif any(keyword in subgoal_text for keyword in ["login", "auth", "authenticated", "sign in"]):
        done = not login_visible
        reason = "authenticated_or_no_login_form" if done else "login_form_still_visible"
    else:
        done = current_url.startswith("http")
        reason = "site_reachable" if done else "site_not_reachable"

    loop_detected = repeated_url and not done
    no_progress = loop_detected
    intervention = "continue" if done or not no_progress else "local_replan"
    return EvaluatorSignal(
        step_index=step_index,
        subgoal_id=subgoal.id,
        progress_score=1.0 if done else 0.25,
        subgoal_done=done,
        constraint_violation_flag=False,
        action_validity_flag=True,
        loop_or_no_progress_flag=no_progress,
        risk_score=0.0 if done else 0.4,
        recoverability_score=1.0,
        current_url=current_url,
        reason=reason,
        constraint_violation=False,
        invalid_action=False,
        loop_detected=loop_detected,
        no_progress=no_progress,
        recommended_intervention=intervention,
        rationale_summary=reason,
    )


def evaluate_shopping_task118_state(
    page,
    step_index: int,
    subgoal: Subgoal,
    previous_urls: list[str],
    target_path: str,
) -> EvaluatorSignal:
    """Evaluate local progress for the shopping bruxism product task."""

    current_url = page.url
    target_slug = target_path.rsplit("/", maxsplit=1)[-1].replace(".html", "")
    at_product = target_slug in current_url or "bruxism-night-guard" in current_url
    at_search = "catalogsearch/result" in current_url
    repeated_url = len(previous_urls) >= 2 and previous_urls[-1] == current_url and previous_urls[-2] == current_url
    subgoal_text = f"{subgoal.objective} {subgoal.expected_outcome}".lower()

    if any(keyword in subgoal_text for keyword in ["product", "bruxism", "mouth", "guard", "dental", "search", "find"]):
        done = at_product
        if done:
            reason = "target_product_page_reached"
            progress_score = 1.0
        elif at_search:
            reason = "shopping_search_results_reached"
            progress_score = 0.5
        else:
            reason = "target_product_page_not_reached"
            progress_score = 0.25
    else:
        done = current_url.startswith("http")
        reason = "site_reachable" if done else "site_not_reachable"
        progress_score = 1.0 if done else 0.25

    loop_detected = repeated_url and not done
    no_progress = loop_detected
    intervention = "continue" if done or not no_progress else "local_replan"
    return EvaluatorSignal(
        step_index=step_index,
        subgoal_id=subgoal.id,
        progress_score=progress_score,
        subgoal_done=done,
        constraint_violation_flag=False,
        action_validity_flag=True,
        loop_or_no_progress_flag=no_progress,
        risk_score=0.0 if done else 0.3,
        recoverability_score=1.0,
        current_url=current_url,
        reason=reason,
        constraint_violation=False,
        invalid_action=False,
        loop_detected=loop_detected,
        no_progress=no_progress,
        recommended_intervention=intervention,
        rationale_summary=reason,
    )


def evaluate_generic_site_state(
    page,
    step_index: int,
    subgoal: Subgoal,
    previous_urls: list[str],
    target_path: str | None = None,
    success_url_contains: str | None = None,
) -> EvaluatorSignal:
    """Evaluate generic local progress for simple prototype site tasks."""

    current_url = page.url
    repeated_url = len(previous_urls) >= 2 and previous_urls[-1] == current_url and previous_urls[-2] == current_url
    target_reached = current_url.startswith("http")
    if success_url_contains:
        target_reached = success_url_contains in current_url
    elif target_path and target_path != "/":
        target_reached = target_path.rstrip("/") in current_url.rstrip("/")

    done = target_reached
    reason = "target_reached" if done else "target_not_reached"
    loop_detected = repeated_url and not done
    no_progress = loop_detected
    intervention = "continue" if done or not no_progress else "local_replan"
    return EvaluatorSignal(
        step_index=step_index,
        subgoal_id=subgoal.id,
        progress_score=1.0 if done else 0.25,
        subgoal_done=done,
        constraint_violation_flag=False,
        action_validity_flag=True,
        loop_or_no_progress_flag=no_progress,
        risk_score=0.0 if done else 0.3,
        recoverability_score=1.0,
        current_url=current_url,
        reason=reason,
        constraint_violation=False,
        invalid_action=False,
        loop_detected=loop_detected,
        no_progress=no_progress,
        recommended_intervention=intervention,
        rationale_summary=reason,
    )
