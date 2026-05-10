"""Planner implementations for local WebArena-Verified experiments.

The module keeps the planner contract independent from BrowserGym execution.
Ollama is the active planner path for H/k experiments. The planner only creates
subgoals; execution remains a separate module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .types import Plan, PlannerRequest, Subgoal


DEFAULT_PLANNER_PROMPT = Path("prompts/planner_system.md")
DEFAULT_USER_TEMPLATE = Path("prompts/prompt_user_template.md")


@dataclass(frozen=True)
class PlannerArtifacts:
    """Planner output plus optional prompt/debug information."""

    plan: Plan
    prompt: str | None = None
    model_name: str | None = None
    raw_response: str | None = None
    warnings: list[str] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


def apply_horizon(subgoals: list[Subgoal], h: int) -> list[Subgoal]:
    """Apply the planning horizon convention: h=0 means full plan."""

    if h < 0:
        raise ValueError("h must be >= 0")
    return subgoals if h == 0 else subgoals[:h]


def load_prompt(prompt_path: Path = DEFAULT_PLANNER_PROMPT) -> str:
    """Load the planner system prompt."""

    return prompt_path.read_text(encoding="utf-8")


def render_template(template: str, values: dict[str, Any]) -> str:
    """Render a small double-brace Markdown template."""

    rendered = template
    for key, value in values.items():
        if not isinstance(value, str):
            value = json.dumps(value, indent=2, ensure_ascii=False)
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def site_scope_for_planner(site_name: str, target_hint: str | None) -> str:
    """Return stable site-specific context that should always reach the planner."""

    if site_name == "gitlab":
        return "\n".join(
            [
                "GitLab tasks may start on a login page or an already authenticated dashboard.",
                "If login or authentication is possible from the observation, include an authentication subgoal before task navigation.",
                "For Task 44, the intended destination is the user's todos page.",
                f"Known target path hint: {target_hint or '/dashboard/todos'}",
            ]
        )
    if site_name == "shopping_admin":
        return "Magento admin tasks may require admin authentication before navigating to admin pages."
    if site_name == "reddit":
        return "Reddit clone retrieval tasks require preserving the requested output fields exactly."
    if site_name == "shopping":
        return "Shopping tasks should end on product or storefront pages that match the user intent."
    if site_name == "wikipedia":
        return "Wikipedia is used as a local content source; no login is expected."
    return "No extra site-specific execution context is defined."


def constraints_for_planner(request: PlannerRequest) -> str:
    """Return task constraints that should be visible to the planner."""

    constraints = [
        "Plan at the subgoal level only; do not output executable BrowserGym actions.",
        "Each subgoal must have an observable expected_outcome.",
        "Do not assume the user is already authenticated unless the observation explicitly shows that.",
    ]
    if request.target_hint:
        constraints.append(f"Use the target hint as an expected final state when relevant: {request.target_hint}")
    if request.retrieved_data_hint:
        constraints.append("For retrieval tasks, preserve the requested retrieved_data schema.")
    if request.site_name == "gitlab":
        constraints.append("For GitLab, include an authentication or already-authenticated verification subgoal before the final task navigation.")
    return "\n".join(f"- {item}" for item in constraints)


def build_planner_prompt(
    request: PlannerRequest,
    prompt_path: Path = DEFAULT_PLANNER_PROMPT,
    user_template_path: Path = DEFAULT_USER_TEMPLATE,
) -> str:
    """Build a complete prompt for an LLM planner."""

    system_prompt = load_prompt(prompt_path)
    user_template = user_template_path.read_text(encoding="utf-8")
    user_prompt = render_template(
        user_template,
        {
            "task_id": request.task.get("task_id"),
            "site": request.site_name,
            "start_urls": request.task.get("start_urls", []),
            "task_intent": request.task.get("intent", ""),
            "h": request.h,
            "initial_observation": request.initial_observation
            or "No live browser observation is available in planner preview mode. The run may start on a login page or on an already authenticated page.",
            "site_scope": site_scope_for_planner(request.site_name, request.target_hint),
            "known_constraints": constraints_for_planner(request),
            "previous_plan": request.previous_plan or "None",
            "evaluator_feedback": request.evaluator_feedback or "None",
            "controller_decision": request.controller_decision or "None",
        },
    )
    task_context = {
        "site_name": request.site_name,
        "h": request.h,
        "task": request.task,
        "target_hint": request.target_hint,
        "retrieved_data_hint": request.retrieved_data_hint,
    }
    return (
        f"{system_prompt}\n\n"
        f"{user_prompt}\n\n"
        f"Machine-readable task context:\n{json.dumps(task_context, indent=2, ensure_ascii=False)}\n"
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from plain or fenced model output."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Planner response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def plan_from_json(data: dict[str, Any], fallback_task: dict[str, Any], h: int, planner_mode: str) -> Plan:
    """Convert a planner JSON response to the local Plan dataclass."""

    task_id = data.get("task_id", fallback_task.get("task_id", -1))
    subgoals = [
        Subgoal(
            id=str(row.get("id", f"sg{idx + 1}")),
            objective=str(row.get("objective", "")).strip(),
            expected_outcome=str(row.get("expected_outcome", "")).strip(),
        )
        for idx, row in enumerate(data.get("subgoals", []))
    ]
    subgoals = [sg for sg in subgoals if sg.objective and sg.expected_outcome]
    if not subgoals:
        raise ValueError("Planner response did not contain usable subgoals")
    return Plan(
        planner_mode=planner_mode,
        h=h,
        task_id=int(task_id) if task_id is not None else -1,
        task_intent=str(data.get("task_intent", fallback_task.get("intent", ""))),
        subgoals=apply_horizon(subgoals, h),
        rationale_summary=data.get("rationale_summary"),
        assumptions=list(data.get("assumptions", [])),
    )


def validate_plan_for_request(plan: Plan, request: PlannerRequest) -> list[str]:
    """Return warnings for missing task-critical planning elements."""

    warnings: list[str] = []
    joined = " ".join(f"{sg.objective} {sg.expected_outcome}" for sg in plan.subgoals).lower()
    if request.site_name == "gitlab" and plan.task_id == 44:
        if "login" not in joined and "auth" not in joined and "authenticated" not in joined:
            warnings.append("gitlab_task44_missing_authentication_subgoal")
        if "todos" not in joined and "/dashboard/todos" not in joined:
            warnings.append("gitlab_task44_missing_todos_target")
    return warnings


def ollama_planner(
    request: PlannerRequest,
    model_name: str = "gemma4:26b",
    base_url: str = "http://localhost:11434",
    prompt_path: Path = DEFAULT_PLANNER_PROMPT,
    user_template_path: Path = DEFAULT_USER_TEMPLATE,
) -> PlannerArtifacts:
    """Call an Ollama chat model and parse the returned plan."""

    prompt = build_planner_prompt(request, prompt_path, user_template_path)
    payload = {
        "model": model_name,
        "stream": False,
        "messages": [
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.2},
    }
    req = Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except URLError as exc:
        raise RuntimeError(f"Ollama is not reachable at {base_url}: {exc}") from exc

    decoded = json.loads(raw)
    content = decoded.get("message", {}).get("content", "")
    plan_data = extract_json_object(content)
    plan = plan_from_json(plan_data, request.task, request.h, planner_mode="ollama")
    prompt_tokens = decoded.get("prompt_eval_count")
    completion_tokens = decoded.get("eval_count")
    total_tokens = None
    if prompt_tokens is not None or completion_tokens is not None:
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
    return PlannerArtifacts(
        plan=plan,
        prompt=prompt,
        model_name=model_name,
        raw_response=content,
        warnings=validate_plan_for_request(plan, request),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def build_plan(
    request: PlannerRequest,
    planner_mode: str = "ollama",
    model_name: str = "gemma4:26b",
    ollama_base_url: str = "http://localhost:11434",
    prompt_path: Path = DEFAULT_PLANNER_PROMPT,
    user_template_path: Path = DEFAULT_USER_TEMPLATE,
) -> PlannerArtifacts:
    """Build a plan through the selected planner implementation."""

    if planner_mode == "ollama":
        return ollama_planner(
            request,
            model_name=model_name,
            base_url=ollama_base_url,
            prompt_path=prompt_path,
            user_template_path=user_template_path,
        )
    raise ValueError(f"Unknown planner mode: {planner_mode}")
