"""Rule-based controller interfaces for runtime evaluator signals."""

from __future__ import annotations

from .types import ControllerDecision, EvaluatorSignal


def decide_next_action(signal: EvaluatorSignal, step_budget_exceeded: bool) -> ControllerDecision:
    """Map evaluator signals to one reproducible controller decision."""

    if step_budget_exceeded:
        return ControllerDecision(signal.step_index, "abort", "budget_exceeded", signal.subgoal_id, "Maximum step budget reached")
    if signal.constraint_violation_flag or signal.constraint_violation:
        return ControllerDecision(signal.step_index, "abort", "constraint_violation", signal.subgoal_id, "Constraint violation detected")
    if signal.loop_or_no_progress_flag or signal.loop_detected or signal.no_progress:
        return ControllerDecision(signal.step_index, "local_replan", "no_progress", signal.subgoal_id, "Loop or no-progress signal detected")
    if signal.subgoal_done:
        return ControllerDecision(signal.step_index, "continue", "subgoal_completed", signal.subgoal_id, "Subgoal completed")
    return ControllerDecision(signal.step_index, "continue", "in_progress", signal.subgoal_id, "Subgoal still in progress")
