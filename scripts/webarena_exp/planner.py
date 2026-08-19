"""Planner implementations for local WebArena-Verified experiments.

The module keeps the planner contract independent from BrowserGym execution.
Ollama is the active planner path for H/k experiments. The planner only creates
subgoals; execution remains a separate module.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .types import Plan, PlannerRequest, Subgoal


DEFAULT_PLANNER_PROMPT = Path("prompts/v3/planner_system.md")
DEFAULT_USER_TEMPLATE = Path("prompts/v3/prompt_user_template.md")


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
    elapsed_ms: int | None = None


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
        lines = [
            "GitLab tasks may start on a login page or an already authenticated dashboard.",
            "If login or authentication is possible from the observation, include an authentication subgoal before task navigation.",
        ]
        if target_hint:
            lines.append(f"Known target path hint: {target_hint}")
        return "\n".join(lines)
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
    if request.agent_architecture in {"v2_planact", "v3", "v3_repair_brief", "v3_repair_llm"}:
        constraints.extend(
            [
                "Use the plan history and runtime feedback to decide whether to keep, repair, or replace the current plan.",
                "Preserve H/k semantics: plan useful subgoals for the current horizon; do not force a new plan after every executor step.",
                "Prefer subgoals that make the next executor action groundable in the current page observation.",
                "Keep the existing Plan/Subgoal JSON schema exactly; do not emit BrowserGym action strings.",
            ]
        )
    if request.agent_architecture in {"v3", "v3_repair_brief", "v3_repair_llm"}:
        constraints.extend(
            [
                "If runtime feedback contains a recovery_hint, the next plan must explicitly repair that failure class before continuing.",
                "If runtime feedback contains a v3_repair_brief or repair_brief, use its planner_instruction as the next repair subgoal direction.",
                "Do not suggest repeating actions listed in recovery_hint.forbidden_actions.",
                "If recovery_hint.suggested_backtrack_url is present, consider a backtrack subgoal before retrying the UI workflow.",
            ]
        )
    if request.target_hint:
        constraints.append(f"Use the target hint as an expected final state when relevant: {request.target_hint}")
    if request.retrieved_data_hint:
        constraints.append("For retrieval tasks, preserve the requested retrieved_data schema.")
    if request.site_name == "gitlab":
        constraints.append("For GitLab, include an authentication or already-authenticated verification subgoal before the final task navigation.")
    return "\n".join(f"- {item}" for item in constraints)


def planact_planner_context(request: PlannerRequest) -> dict[str, Any] | None:
    """Return compact dynamic planning context for the v2_planact planner path."""

    if request.agent_architecture not in {"v2_planact", "v3", "v3_repair_brief", "v3_repair_llm"}:
        return None
    previous_actions = compact_context_value(request.previous_actions[-6:])
    history = request.plan_history or {}
    context = {
        "architecture": request.agent_architecture,
        "planner_instruction": (
            "Review the current plan, previous executor actions, evaluator feedback, and observation. "
            "Then choose whether the next plan should keep, repair, or replace the current direction. "
            "Output only the normal Plan JSON schema."
        ),
        "previous_plan": compact_context_value(request.previous_plan),
        "plan_history": {
            "initial_plan": compact_context_value(history.get("initial_plan")),
            "plans": compact_context_value(history.get("plans", [])[-3:]),
            "runtime_feedback": compact_context_value(history.get("runtime_feedback", [])[-4:]),
            "repair_briefs": compact_context_value(history.get("repair_briefs", [])[-3:]),
        },
        "previous_executor_actions": previous_actions,
        "latest_evaluator_feedback": compact_context_value(request.evaluator_feedback),
        "latest_controller_decision": compact_context_value(request.controller_decision),
    }
    if request.agent_architecture in {"v3", "v3_repair_brief", "v3_repair_llm"}:
        recent_feedback = history.get("runtime_feedback", [])[-4:]
        recovery_hints = [
            row.get("recovery_hint")
            for row in recent_feedback
            if isinstance(row, dict) and row.get("recovery_hint")
        ]
        context["recovery_mode"] = {
            "enabled": True,
            "instruction": "Use k-step feedback and v3_repair_brief as a repair signal. The next subgoals should avoid the diagnosed failure and recover from the current state.",
            "recent_recovery_hints": compact_context_value(recovery_hints[-3:]),
            "latest_repair_brief": compact_context_value((history.get("repair_briefs", [])[-1:] or [{}])[0]),
        }
    return context


def compact_context_value(value: Any, *, depth: int = 0, string_limit: int = 700) -> Any:
    """Keep dynamic planner context small enough for local/proxy models."""

    if depth > 4:
        return "<truncated>"
    if isinstance(value, str):
        return value if len(value) <= string_limit else value[:string_limit] + "...<truncated>"
    if isinstance(value, list):
        return [compact_context_value(item, depth=depth + 1, string_limit=string_limit) for item in value[:8]]
    if isinstance(value, dict):
        return {
            str(key): compact_context_value(child, depth=depth + 1, string_limit=string_limit)
            for key, child in list(value.items())[:24]
        }
    return value


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
    planact_context = planact_planner_context(request)
    task_context = {
        "site_name": request.site_name,
        "h": request.h,
        "task": request.task,
        "target_hint": request.target_hint,
        "retrieved_data_hint": request.retrieved_data_hint,
        "agent_architecture": request.agent_architecture,
    }
    if planact_context is not None:
        task_context["dynamic_planner_context"] = planact_context
    return (
        f"{system_prompt}\n\n"
        f"{user_prompt}\n\n"
        f"Machine-readable task context:\n{json.dumps(task_context, indent=2, ensure_ascii=False)}\n"
    )


def build_planner_user_message(
    request: PlannerRequest,
    user_template_path: Path = DEFAULT_USER_TEMPLATE,
) -> str:
    """Build the user-role Planner message for chat-template aware models."""

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
    planact_context = planact_planner_context(request)
    task_context = {
        "site_name": request.site_name,
        "h": request.h,
        "task": request.task,
        "target_hint": request.target_hint,
        "retrieved_data_hint": request.retrieved_data_hint,
        "agent_architecture": request.agent_architecture,
    }
    if planact_context is not None:
        task_context["dynamic_planner_context"] = planact_context
    return (
        f"{user_prompt}\n\n"
        f"Machine-readable task context:\n{json.dumps(task_context, indent=2, ensure_ascii=False)}\n"
    )


def strip_gemma_control_text(text: str) -> str:
    """Remove Gemma 4 thought/tool wrapper text before JSON extraction."""

    stripped = text.strip()
    if "<channel|>" in stripped:
        stripped = stripped.split("<channel|>", 1)[1]
    for token in [
        "<|turn>model",
        "<|turn>assistant",
        "<|turn>user",
        "<|turn>system",
        "<turn|>",
        "<|channel>thought",
        "<|channel>",
        "<channel|>",
        "<|tool_call>",
        "<tool_call|>",
        "<|tool_response>",
        "<tool_response|>",
    ]:
        stripped = stripped.replace(token, "")
    return stripped.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from plain or fenced model output."""

    stripped = strip_gemma_control_text(text)
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


def scripted_planner(request: PlannerRequest) -> PlannerArtifacts:
    """Return deterministic subgoals for environment/executor smoke checks."""

    task_id = request.task.get("task_id")
    if request.site_name == "gitlab" and task_id == 105:
        target_subgoal = Subgoal(
            id="sg2",
            objective="Open the filtered OpenAPITools/openapi-generator issues page",
            expected_outcome=(
                "The browser is on /OpenAPITools/openapi-generator/-/issues/ "
                "with state=opened and label_name[]=OpenAPI Generator CLI."
            ),
        )
        if "login_form_visible: false" in (request.initial_observation or "").lower():
            subgoals = [target_subgoal]
        else:
            subgoals = [
                Subgoal(
                    id="sg1",
                    objective="Authenticate to GitLab",
                    expected_outcome="The user is logged in or already authenticated.",
                ),
                target_subgoal,
            ]
    else:
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Authenticate if the current site requires login",
                expected_outcome="The browser is authenticated or no login is required.",
            ),
            Subgoal(
                id="sg2",
                objective="Navigate to the task target state",
                expected_outcome=f"The browser reaches the target hint: {request.target_hint or 'the requested site state'}.",
            ),
        ]

    plan = Plan(
        planner_mode="scripted",
        h=request.h,
        task_id=int(task_id) if task_id is not None else -1,
        task_intent=str(request.task.get("intent", "")),
        subgoals=apply_horizon(subgoals, request.h),
        rationale_summary="Deterministic planner used to isolate environment and executor behavior from LLM planning.",
        assumptions=[],
    )
    return PlannerArtifacts(plan=plan, warnings=validate_plan_for_request(plan, request), total_tokens=0, prompt_tokens=0, completion_tokens=0, elapsed_ms=0)


def fallback_plan_for_request(request: PlannerRequest, planner_mode: str, warning: str) -> Plan:
    """Build a conservative fallback plan when the LLM planner output is not parseable."""

    intent = str(request.task.get("intent", ""))
    intent_lower = intent.lower()
    subgoals: list[Subgoal]
    if request.site_name == "gitlab" and "todos" in intent_lower:
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Open the GitLab dashboard todos page",
                expected_outcome="The browser is on the GitLab dashboard todos page.",
            )
        ]
    elif request.site_name == "gitlab" and "openapitools/openapi-generator" in intent_lower and "issues" in intent_lower:
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Open the OpenAPITools/openapi-generator project issues page",
                expected_outcome="The browser shows the OpenAPITools/openapi-generator issues list.",
            ),
            Subgoal(
                id="sg2",
                objective="Filter the issue list for open issues with the OpenAPI Generator CLI label",
                expected_outcome="The issues page is filtered to not-yet-closed issues with label OpenAPI Generator CLI.",
            ),
        ]
    elif request.site_name == "gitlab" and "fork" in intent_lower:
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Open the source namespace or project list named in the task and identify the repositories to fork",
                expected_outcome="The source repository list or a concrete source project page is visible.",
            ),
            Subgoal(
                id="sg2",
                objective="Open the current source project's fork form and select the current user's namespace if the form requires a namespace",
                expected_outcome="The fork form is ready with a valid target namespace or shows the final Fork/Create control.",
            ),
            Subgoal(
                id="sg3",
                objective="Submit the fork and verify the forked project page or visible confirmation",
                expected_outcome="The repository is forked into the current user's namespace.",
            ),
            Subgoal(
                id="sg4",
                objective="Repeat the same fork workflow for any remaining repositories requested by the task",
                expected_outcome="All repositories requested by the task have been forked.",
            ),
        ]
    elif request.site_name == "gitlab" and "new group" in intent_lower:
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Open GitLab's new group creation flow",
                expected_outcome="The new group form is visible.",
            ),
            Subgoal(
                id="sg2",
                objective="Fill the requested group name/path/visibility fields and create the group",
                expected_outcome="The newly created group page or confirmation is visible.",
            ),
            Subgoal(
                id="sg3",
                objective="Invite or add each requested member with the requested role",
                expected_outcome="The requested members are visible in the group members list or invitation confirmation.",
            ),
        ]
    elif request.site_name == "gitlab" and any(term in intent_lower for term in ["commit", "branch", "file", "editor"]):
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Open the target GitLab project and locate the file mentioned in the task",
                expected_outcome="The target file page is visible.",
            ),
            Subgoal(
                id="sg2",
                objective="Open the web editor and make only the requested minimal content change",
                expected_outcome="The editor shows the requested change without replacing unrelated file content.",
            ),
            Subgoal(
                id="sg3",
                objective="Set the requested branch or commit fields and submit the commit",
                expected_outcome="GitLab shows a commit success state, branch page, or updated file view.",
            ),
        ]
    elif request.site_name == "shopping_admin" and "customer" in intent_lower:
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Open the Magento admin customer index",
                expected_outcome="The browser shows the customer list/details page.",
            )
        ]
    elif request.site_name == "shopping":
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Search the storefront for products matching the user need",
                expected_outcome="Search results show products relevant to the requested need.",
            ),
            Subgoal(
                id="sg2",
                objective="Open a matching product detail page",
                expected_outcome="The browser is on a concrete product detail page that matches the task intent.",
            ),
        ]
    elif request.site_name == "reddit":
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Find the requested discussion forum",
                expected_outcome="The browser shows the requested forum page with visible posts.",
            ),
            Subgoal(
                id="sg2",
                objective="Collect the requested post and comment information",
                expected_outcome="The requested evidence is visible and can be returned in the required schema.",
            ),
            Subgoal(
                id="sg3",
                objective="Return the retrieved data",
                expected_outcome="The final agent response contains the requested retrieved_data fields.",
            ),
        ]
    else:
        subgoals = [
            Subgoal(
                id="sg1",
                objective="Navigate toward the requested task state",
                expected_outcome="The current page visibly moves closer to the task intent.",
            ),
            Subgoal(
                id="sg2",
                objective="Verify the requested state and finish",
                expected_outcome="The browser state or final response satisfies the task intent.",
            ),
        ]
    return Plan(
        planner_mode=planner_mode,
        h=request.h,
        task_id=int(request.task.get("task_id", -1)),
        task_intent=intent,
        subgoals=apply_horizon(subgoals, request.h),
        rationale_summary="Fallback plan because the planner model did not return parseable subgoals.",
        assumptions=[warning],
    )


def planner_num_predict(request: PlannerRequest) -> int:
    """Use a smaller generation budget when the H horizon only permits a short plan."""

    if request.h == 0:
        return 1800
    if request.h <= 2:
        return 900
    if request.h <= 5:
        return 1300
    return 1600


def ollama_planner(
    request: PlannerRequest,
    model_name: str = "gemma4:26b",
    base_url: str = "http://localhost:11434",
    prompt_path: Path = DEFAULT_PLANNER_PROMPT,
    user_template_path: Path = DEFAULT_USER_TEMPLATE,
    request_timeout_seconds: int = 300,
) -> PlannerArtifacts:
    """Call an Ollama chat model and parse the returned plan."""

    system_prompt = load_prompt(prompt_path)
    user_prompt = build_planner_user_message(request, user_template_path)
    prompt = f"{system_prompt}\n\n{user_prompt}"
    payload = {
        "model": model_name,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": f"{system_prompt}\n\nReturn valid JSON only."},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": 0.2,
            "top_p": 0.95,
            "top_k": 64,
            "num_predict": planner_num_predict(request),
            "stop": ["<turn|>", "<|tool_call>", "<|tool_response>"],
        },
    }
    req = Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=request_timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except TimeoutError as exc:
        warning = f"planner_timeout_fallback:{request_timeout_seconds}s"
        plan = fallback_plan_for_request(request, planner_mode="ollama_timeout_fallback", warning=warning)
        return PlannerArtifacts(
            plan=plan,
            prompt=prompt,
            model_name=model_name,
            raw_response="",
            warnings=[warning, *validate_plan_for_request(plan, request)],
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
    except URLError as exc:
        if "timed out" in str(exc).lower():
            warning = f"planner_timeout_fallback:{request_timeout_seconds}s"
            plan = fallback_plan_for_request(request, planner_mode="ollama_timeout_fallback", warning=warning)
            return PlannerArtifacts(
                plan=plan,
                prompt=prompt,
                model_name=model_name,
                raw_response="",
                warnings=[warning, *validate_plan_for_request(plan, request)],
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        raise RuntimeError(f"Ollama is not reachable at {base_url}: {exc}") from exc

    decoded = json.loads(raw)
    content = decoded.get("message", {}).get("content", "")
    prompt_tokens = decoded.get("prompt_eval_count")
    completion_tokens = decoded.get("eval_count")
    total_tokens = None
    if prompt_tokens is not None or completion_tokens is not None:
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
    warnings: list[str]
    try:
        plan_data = extract_json_object(content)
        plan = plan_from_json(plan_data, request.task, request.h, planner_mode="ollama")
        warnings = validate_plan_for_request(plan, request)
    except Exception as exc:
        warning = f"planner_parse_failed:{type(exc).__name__}:{exc}"
        plan = fallback_plan_for_request(request, planner_mode="ollama_fallback", warning=warning)
        warnings = [warning, *validate_plan_for_request(plan, request)]
    return PlannerArtifacts(
        plan=plan,
        prompt=prompt,
        model_name=model_name,
        raw_response=content,
        warnings=warnings,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )


def build_plan(
    request: PlannerRequest,
    planner_mode: str = "ollama",
    model_name: str = "gemma4:26b",
    ollama_base_url: str = "http://localhost:11434",
    prompt_path: Path = DEFAULT_PLANNER_PROMPT,
    user_template_path: Path = DEFAULT_USER_TEMPLATE,
    request_timeout_seconds: int = 300,
) -> PlannerArtifacts:
    """Build a plan through the selected planner implementation."""

    if planner_mode == "scripted":
        return scripted_planner(request)
    if planner_mode == "ollama":
        return ollama_planner(
            request,
            model_name=model_name,
            base_url=ollama_base_url,
            prompt_path=prompt_path,
            user_template_path=user_template_path,
            request_timeout_seconds=request_timeout_seconds,
        )
    raise ValueError(f"Unknown planner mode: {planner_mode}")
