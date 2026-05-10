"""Typed data contracts for the local WebArena-Verified experiment runners.

The classes in this module define the JSON shape written by the runners. They
are intentionally small dataclasses so notebooks can load the artifacts without
depending on a heavier framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Credentials:
    """Login credentials for a local benchmark environment."""

    username: str
    password: str


@dataclass(frozen=True)
class SiteInput:
    """Local configuration for one WebArena-Verified site.

    env_key is the placeholder used by WebArena-Verified task rendering, for
    example "__GITLAB__". base_url is the local URL where the matching site is
    expected to run.
    """

    name: str
    env_key: str
    base_url: str
    credentials: Credentials | None = None
    task_type: str = "NAVIGATE"
    fallback_task_types: tuple[str, ...] = ()
    enabled: bool = True
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class AgentTaskInput:
    """Rendered task input consumed by local BrowserGym runners."""

    task_id: int
    intent: str
    sites: list[str]
    start_urls: list[str]
    intent_template_id: int | None = None


@dataclass(frozen=True)
class Subgoal:
    """One high-level objective produced by the planner."""

    id: str
    objective: str
    expected_outcome: str
    success_criteria: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PlannerRequest:
    """Input passed to a planner implementation."""

    task: dict[str, Any]
    site_name: str
    h: int = 0
    target_hint: str | None = None
    retrieved_data_hint: list[dict] | None = None
    initial_observation: str | None = None
    previous_plan: dict[str, Any] | None = None
    evaluator_feedback: dict[str, Any] | None = None
    controller_decision: dict[str, Any] | None = None


@dataclass(frozen=True)
class Plan:
    """Planner output for a single task run."""

    planner_mode: str
    h: int
    task_id: int
    task_intent: str
    subgoals: list[Subgoal]
    rationale_summary: str | None = None
    assumptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutorStep:
    """One concrete executor transition in the environment."""

    step_index: int
    subgoal_id: str
    action: str
    url_before: str | None
    url_after: str | None
    status: str
    page_title: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class EvaluatorSignal:
    """Structured runtime signal produced by the internal evaluator."""

    step_index: int
    subgoal_id: str
    progress_score: float
    subgoal_done: bool
    constraint_violation_flag: bool
    action_validity_flag: bool
    loop_or_no_progress_flag: bool
    risk_score: float
    recoverability_score: float
    current_url: str
    reason: str
    constraint_violation: bool = False
    invalid_action: bool = False
    loop_detected: bool = False
    no_progress: bool = False
    recommended_intervention: str = "continue"
    rationale_summary: str | None = None


@dataclass(frozen=True)
class ControllerDecision:
    """Rule-based control decision derived from evaluator signals."""

    step_index: int
    decision: str
    reason_code: str
    subgoal_id: str
    rationale_summary: str | None = None


@dataclass(frozen=True)
class RunTrace:
    """Run-level metrics written by H/k prototype runners."""

    task_id: int
    site: str
    h: int
    k: int
    planner_mode: str
    model: str | None
    prompt_version: str | None
    total_steps: int
    total_runtime_ms: int
    total_tokens: int | None
    num_planner_calls: int
    num_plan_subgoals_generated: int
    num_replans: int
    num_no_progress_events: int
    num_invalid_actions: int
    num_loop_events: int
    final_status: str
    success: bool | None
    abort_reason: str | None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class SiteProbeResult:
    """Result of opening one rendered task input through BrowserGym."""

    site: str
    status: str
    task_id: int | None
    start_url: str | None
    final_url: str | None
    page_title: str | None
    output_dir: str
    task_intent: str | None = None
    task_type: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class HardcodedTaskSpec:
    """Deterministic smoke task used before full agent execution exists."""

    site: str
    task_id: int | None
    task_type: str
    intent: str
    target_path: str | None
    success_url_contains: str | None
    requires_login: bool = False
    run_official_eval: bool = False
    retrieved_data: list[dict] | None = None


@dataclass(frozen=True)
class HardcodedTaskResult:
    """Result of executing one deterministic hardcoded smoke task."""

    site: str
    status: str
    task_id: int | None
    task_type: str
    intent: str
    start_url: str
    target_url: str | None
    final_url: str | None
    page_title: str | None
    success: bool
    output_dir: str
    error: str | None = None
    official_score: float | None = None
    total_runtime_ms: int | None = None
    browser_runtime_ms: int | None = None
    official_eval_runtime_ms: int | None = None
    total_tokens: int | None = None
