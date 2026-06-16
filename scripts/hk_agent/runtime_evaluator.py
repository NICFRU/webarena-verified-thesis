"""Runtime progress evaluator for H/k control decisions.

This evaluator is intentionally not the official WebArena-Verified evaluator.
It produces intermediate signals for replanning and process analysis only.
"""

from __future__ import annotations

from webarena_exp.types import EvaluatorSignal, Subgoal


def _same_tail(values: list[str], size: int = 3) -> bool:
    if len(values) < size:
        return False
    tail = values[-size:]
    return all(value == tail[0] for value in tail)


def evaluate_progress(
    *,
    step_index: int,
    subgoal: Subgoal,
    current_url: str,
    previous_urls: list[str],
    last_action: str,
    last_action_error: str | None = None,
    url_before: str | None = None,
    title_before: str | None = None,
    title_after: str | None = None,
) -> EvaluatorSignal:
    """Evaluate runtime progress without deciding official task success."""

    action_error = bool(last_action_error)
    repeated_url = _same_tail(previous_urls)
    url_changed = bool(url_before and current_url and current_url != url_before)
    title_changed = bool(title_before and title_after and title_after != title_before)
    error_page = "404" in (title_after or "").lower() or "not found" in (title_after or "").lower()
    final_response_action = last_action.strip().startswith("send_msg_to_user(")
    noop_action = last_action.strip().startswith("noop(")

    has_observable_progress = (url_changed or title_changed or final_response_action) and not error_page
    invalid_action = action_error or error_page
    no_progress = (noop_action or repeated_url or not has_observable_progress or error_page) and not final_response_action
    loop_detected = repeated_url and not final_response_action
    # The progress score and reason are simplified heuristics based on the observed signals. They can be further refined with more complex logic or machine learning models if needed.
    if invalid_action:
        reason = "error_page" if error_page and not action_error else "action_error"
        progress_score = 0.0
    elif final_response_action:
        reason = "final_response_sent"
        progress_score = 1.0
    elif has_observable_progress:
        reason = "observable_progress"
        progress_score = 0.6
    else:
        reason = "no_observable_progress"
        progress_score = 0.2

    recommended = "local_replan" if no_progress or invalid_action else "continue"
    return EvaluatorSignal(
        step_index=step_index,
        subgoal_id=subgoal.id,
        progress_score=progress_score,
        subgoal_done=has_observable_progress or final_response_action,
        constraint_violation_flag=False,
        action_validity_flag=not invalid_action,
        loop_or_no_progress_flag=no_progress,
        risk_score=0.6 if invalid_action else 0.4 if no_progress else 0.1,
        recoverability_score=0.8 if invalid_action else 1.0,
        current_url=current_url,
        reason=reason,
        constraint_violation=False,
        invalid_action=invalid_action,
        loop_detected=loop_detected,
        no_progress=no_progress,
        recommended_intervention=recommended,
        rationale_summary=reason,
    )
