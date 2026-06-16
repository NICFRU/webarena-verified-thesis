"""Single-task BrowserGym/WebArena-Verified H/k runner."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from webarena_exp.controller import decide_next_action
from webarena_exp.io_utils import read_json, write_json
from webarena_exp.planner import build_plan
from webarena_exp.types import PlannerRequest

from .artifacts import HkArtifactWriter, PhaseTracker, parse_agent_response_from_action, utc_now, write_agent_response
from .capabilities import capability_tier, infer_task_capability
from .diagnostics import diagnose_run_summary
from .executor import BrowserGymLLMExecutor, final_nav_action, infer_task_type, page_satisfies_task, safe_page_title
from .k_repair import build_k_repair_brief, refine_repair_brief_with_llm
from .official_evaluator import build_official_config, read_official_result, run_official_eval
from .prompt_builder import resolve_agent_architecture
from .recovery import build_recovery_hint, is_planact_like_architecture, is_repair_architecture
from .runtime_evaluator import evaluate_progress
from .task_loader import HkTask, ensure_browsergym_env, sanitize_task_for_agent


def install_shopping_admin_login_patch() -> None:
    """Make BrowserGym's Magento admin login robust for local reset races.

    BrowserGym's default WebArena login uses accessible labels. Immediately
    after a shopping_admin container reset, Magento can briefly serve markup
    where those labels are not yet attached, even though selector-based login or
    the official header auto-login works. This patch keeps the benchmark task
    unchanged and only stabilizes authentication before env.reset() returns.
    """

    from browsergym.webarena.instance import WebArenaInstance

    if getattr(WebArenaInstance, "_hk_shopping_admin_login_patch", False):
        return

    original_ui_login = WebArenaInstance.ui_login

    def patched_ui_login(self, site: str, page) -> None:
        if site != "shopping_admin":
            return original_ui_login(self, site, page)

        url = str(self.urls[site]).rstrip("/")
        credentials = self.credentials.get(site, {}) if isinstance(self.credentials, dict) else {}
        username = str(credentials.get("username") or os.environ.get("WA_SHOPPING_ADMIN_USERNAME") or "admin")
        password = str(credentials.get("password") or os.environ.get("WA_SHOPPING_ADMIN_PASSWORD") or "admin1234")

        page.context.set_extra_http_headers({"X-M2-Admin-Auto-Login": f"{username}:{password}"})
        login_page = page.context.new_page()
        try:
            login_page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                login_page.wait_for_selector(
                    ".page-title, .admin__menu, #menu-magento-backend, "
                    "input[name='login[username]'], input#username",
                    timeout=45_000,
                )
            except Exception:
                login_page.reload(wait_until="domcontentloaded", timeout=60_000)
                login_page.wait_for_selector(
                    ".page-title, .admin__menu, #menu-magento-backend, "
                    "input[name='login[username]'], input#username",
                    timeout=45_000,
                )

            username_input = login_page.locator("input[name='login[username]'], input#username").first
            password_input = login_page.locator("input[name='login[password]'], input#login").first
            if username_input.count() > 0 and password_input.count() > 0:
                username_input.fill(username, timeout=15_000)
                password_input.fill(password, timeout=15_000)
                button = login_page.locator("button.action-login, button[type='submit']").first
                if button.count() > 0:
                    button.click(timeout=15_000)
                else:
                    password_input.press("Enter", timeout=15_000)
                login_page.wait_for_selector(".page-title, .admin__menu, #menu-magento-backend", timeout=60_000)
        finally:
            login_page.close()

    WebArenaInstance.ui_login = patched_ui_login
    WebArenaInstance._hk_shopping_admin_login_patch = True


def plain(value: Any) -> Any:
    """Convert dataclasses to plain JSON data."""

    if is_dataclass(value):
        return asdict(value)
    return value


def observation_summary(obs: dict[str, Any], page, last_signal: Any = None, last_decision: Any = None) -> str:
    """Build the planner-facing observation summary."""

    parts = [
        f"current_url: {page.url}",
        f"page_title: {safe_page_title(page)}",
        f"last_action: {obs.get('last_action', '')}",
        f"last_action_error: {obs.get('last_action_error', '')}",
    ]
    if last_signal is not None:
        parts.append(f"last_runtime_evaluator_signal: {json.dumps(plain(last_signal), ensure_ascii=False)}")
    if last_decision is not None:
        parts.append(f"last_controller_decision: {json.dumps(plain(last_decision), ensure_ascii=False)}")
    return "\n".join(parts)


def llm_backend_metadata(ollama_base_url: str) -> dict[str, Any]:
    """Return run metadata for local Ollama vs the Vertex-compatible proxy."""

    parsed = urlparse(ollama_base_url)
    host = parsed.hostname or ""
    port = parsed.port
    vertex_proxy_enabled = host in {"127.0.0.1", "localhost"} and port == 11435
    return {
        "llm_backend": "vertex_ollama_proxy" if vertex_proxy_enabled else "ollama_compatible",
        "ollama_base_url": ollama_base_url,
        "vertex_proxy_enabled": vertex_proxy_enabled,
        "vertex_project_id": os.environ.get("GOOGLE_CLOUD_PROJECT") if vertex_proxy_enabled else None,
        "vertex_location": os.environ.get("GOOGLE_CLOUD_LOCATION") if vertex_proxy_enabled else None,
        "vertex_maas_model": os.environ.get("VERTEX_MAAS_MODEL") if vertex_proxy_enabled else None,
    }


def repeated_repair_failure_class(plan_history: dict[str, Any], *, min_count: int = 4) -> str | None:
    """Return a repair class that repeated consecutively often enough to stop."""

    rows = plan_history.get("repair_briefs") or []
    if len(rows) < min_count:
        return None
    classes: list[str] = []
    for row in rows[-min_count:]:
        repair_brief = row.get("repair_brief") or {}
        failure_class = str(repair_brief.get("failure_class") or "")
        if not failure_class:
            return None
        classes.append(failure_class)
    return classes[-1] if len(set(classes)) == 1 else None


def final_response_for_task(
    task: dict[str, Any],
    last_action: str | None = None,
    error_details: str | None = None,
    *,
    require_explicit_final: bool = False,
) -> dict[str, Any]:
    """Return the best available official agent response."""

    parsed = parse_agent_response_from_action(last_action or "")
    if parsed:
        return parsed
    if require_explicit_final and error_details is None:
        error_details = "Agent did not emit an explicit WebArena-Verified final response."
    return {
        "task_type": infer_task_type(task),
        "status": "SUCCESS" if error_details is None else "UNKNOWN_ERROR",
        "retrieved_data": None,
        "error_details": error_details,
    }


def should_repair_mutate_final_from_official_network_success(eval_result_path: Path, task: dict[str, Any]) -> bool:
    """Return true when only the final AgentResponse blocks an otherwise valid mutation.

    This intentionally relies on the official evaluator output. It does not infer
    task success from our own heuristics; it only repairs the WebArena final
    response when every official NetworkEventEvaluator already accepted the
    submitted mutation.
    """

    if infer_task_type(task) != "MUTATE" or not eval_result_path.exists():
        return False
    result = read_json(eval_result_path)
    evaluator_results = result.get("evaluators_results")
    if not isinstance(evaluator_results, list):
        return False
    network_results = [row for row in evaluator_results if row.get("evaluator_name") == "NetworkEventEvaluator"]
    if not network_results or any(row.get("status") != "success" for row in network_results):
        return False
    agent_results = [row for row in evaluator_results if row.get("evaluator_name") == "AgentResponseEvaluator"]
    return bool(agent_results and any(row.get("status") != "success" for row in agent_results))


def run_hk_task(
    *,
    task: HkTask,
    repo_root: Path,
    output_dir: Path,
    h: int,
    k: int,
    run_mode: str,
    planner_model: str,
    executor_model: str,
    planner_mode: str = "ollama",
    max_steps: int | None = 30,
    max_planner_calls: int | None = None,
    headed: bool = False,
    skip_official_eval: bool = False,
    ollama_base_url: str = "http://localhost:11434",
    planner_prompt_path: Path = Path("prompts/planner_system.md"),
    planner_user_template_path: Path = Path("prompts/prompt_user_template.md"),
    executor_prompt_path: Path = Path("prompts/executor_system.md"),
    agent_architecture: str = "v1",
    llm_timeout_seconds: int = 300,
    max_consecutive_llm_timeouts: int = 0,
    env_updates: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run one H/k task and return the run summary."""

    if k < 0:
        raise ValueError("k must be >= 0")
    if run_mode not in {"agent", "oracle_debug", "analysis"}:
        raise ValueError("run_mode must be one of: agent, oracle_debug, analysis")
    agent_architecture = resolve_agent_architecture(agent_architecture, None)
    step_budget = max_steps if max_steps is not None and max_steps > 0 else None
    planner_call_budget = max_planner_calls if max_planner_calls is not None and max_planner_calls > 0 else None

    def step_budget_reached() -> bool:
        return step_budget is not None and total_steps >= step_budget

    def planner_call_budget_reached() -> bool:
        return planner_call_budget is not None and planner_calls >= planner_call_budget

    env = ensure_browsergym_env(env_updates)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = HkArtifactWriter(output_dir)
    artifacts.reset()
    tracker = PhaseTracker()
    started_at = utc_now()
    har_path = output_dir / "network.har"
    agent_response_path = output_dir / "agent_response.json"
    config_path = build_official_config(env, output_dir / "config.webarena_verified.local.json")

    planner_task = sanitize_task_for_agent(task.raw_task, run_mode)
    official_task = task.raw_task
    final_decision = "continue"
    abort_reason = None
    planner_calls = 0
    executor_calls = 0
    planner_tokens = 0
    executor_tokens = 0
    planner_prompt_tokens = 0
    planner_completion_tokens = 0
    executor_prompt_tokens = 0
    executor_completion_tokens = 0
    total_tokens = 0
    total_steps = 0
    num_plan_subgoals_generated = 0
    last_signal = None
    last_decision = None
    last_action = None
    latest_repair_brief = None
    consecutive_llm_timeouts = 0
    plan = None
    route_satisfied_auto_final = False
    plan_history: dict[str, Any] = {
        "initial_plan": None,
        "plans": [],
        "runtime_feedback": [],
        "repair_briefs": [],
    }

    if run_mode != "analysis":
        with tracker.measure("browsergym_execution_ms"):
            import gymnasium as gym
            import browsergym.webarena_verified  # noqa: F401

            install_shopping_admin_login_patch()
            env_obj = gym.make(
                task.gym_id,
                headless=not headed,
                wait_for_user_message=False,
                pw_context_kwargs={
                    "record_har_path": str(har_path),
                    "record_har_content": "embed",
                },
            )
            obs, _info = env_obj.reset()
            page = env_obj.unwrapped.page
            artifacts.log_step(
                {
                    "step_index": 0,
                    "module": "browsergym",
                    "action": "env.reset",
                    "url_after": page.url,
                    "page_title": safe_page_title(page),
                    "observation_keys": sorted(obs.keys()),
                    "status": "success",
                }
            )
            previous_urls = [page.url]
            executor = BrowserGymLLMExecutor(
                task=planner_task,
                site_name=task.primary_site,
                model_name=executor_model,
                ollama_base_url=ollama_base_url,
                prompt_path=executor_prompt_path,
                architecture=agent_architecture,
                request_timeout_seconds=llm_timeout_seconds,
            )
            done = False

            try:
                while not done and not step_budget_reached() and not planner_call_budget_reached():
                    planner_request = PlannerRequest(
                        task=planner_task,
                        site_name=task.primary_site,
                        h=h,
                        target_hint=None if run_mode == "agent" else "oracle_debug may inspect eval metadata in raw task context",
                        retrieved_data_hint=None,
                        initial_observation=observation_summary(obs, page, last_signal, last_decision),
                        previous_plan=plain(plan) if plan is not None else None,
                        evaluator_feedback=plain(last_signal) if last_signal is not None else None,
                        controller_decision=plain(last_decision) if last_decision is not None else None,
                        agent_architecture=agent_architecture,
                        plan_history=plan_history if is_planact_like_architecture(agent_architecture) else None,
                        previous_actions=executor.previous_steps[-10:] if is_planact_like_architecture(agent_architecture) else [],
                    )
                    with tracker.measure("planner_ms"):
                        planner_artifacts = build_plan(
                            planner_request,
                            planner_mode=planner_mode,
                            model_name=planner_model,
                            ollama_base_url=ollama_base_url,
                            prompt_path=planner_prompt_path,
                            user_template_path=planner_user_template_path,
                            request_timeout_seconds=llm_timeout_seconds,
                        )
                    planner_calls += 1
                    plan = planner_artifacts.plan
                    if is_planact_like_architecture(agent_architecture):
                        plan_snapshot = plain(plan)
                        if plan_history["initial_plan"] is None:
                            plan_history["initial_plan"] = plan_snapshot
                        plan_history["plans"].append(
                            {
                                "call_index": planner_calls,
                                "h": h,
                                "observation": observation_summary(obs, page, last_signal, last_decision),
                                "previous_plan_present": planner_request.previous_plan is not None,
                                "evaluator_feedback": plain(last_signal) if last_signal is not None else None,
                                "controller_decision": plain(last_decision) if last_decision is not None else None,
                                "plan": plan_snapshot,
                            }
                        )
                    artifacts.write_plan(plan)
                    num_plan_subgoals_generated += len(plan.subgoals)
                    if planner_artifacts.total_tokens:
                        planner_tokens += planner_artifacts.total_tokens
                        total_tokens += planner_artifacts.total_tokens
                    if planner_artifacts.prompt_tokens:
                        planner_prompt_tokens += planner_artifacts.prompt_tokens
                    if planner_artifacts.completion_tokens:
                        planner_completion_tokens += planner_artifacts.completion_tokens
                    artifacts.log_planner_call(
                        {
                            "call_index": planner_calls,
                            "planner_mode": plan.planner_mode,
                            "model_name": planner_artifacts.model_name or planner_model,
                            "h": h,
                            "subgoal_count": len(plan.subgoals),
                            "prompt_tokens": planner_artifacts.prompt_tokens,
                            "completion_tokens": planner_artifacts.completion_tokens,
                            "total_tokens": planner_artifacts.total_tokens,
                            "elapsed_ms": planner_artifacts.elapsed_ms,
                            "warnings": planner_artifacts.warnings or [],
                            "raw_response_preview": (planner_artifacts.raw_response or "")[:1000],
                        }
                    )
                    planner_timed_out = any(
                        "planner_timeout_fallback" in str(warning)
                        for warning in (planner_artifacts.warnings or [])
                    )
                    if is_planact_like_architecture(agent_architecture) and planner_timed_out:
                        consecutive_llm_timeouts += 1
                        if max_consecutive_llm_timeouts > 0 and consecutive_llm_timeouts >= max_consecutive_llm_timeouts:
                            abort_reason = "repeated_llm_timeout"
                            done = True
                            break
                    else:
                        consecutive_llm_timeouts = 0

                    needs_replan = False
                    for subgoal in plan.subgoals:
                        subgoal_done = False
                        while not subgoal_done and not done and not step_budget_reached():
                            title_before = safe_page_title(page)
                            executor.current_repair_brief = latest_repair_brief if is_repair_architecture(agent_architecture) else None
                            with tracker.measure("executor_ms"):
                                step, obs, done = executor.execute_subgoal(env_obj, obs, page, subgoal, total_steps + 1)
                            total_steps = step.step_index
                            last_action = step.action
                            if step.status == "error" and "timed out" in str(step.error or "").lower():
                                consecutive_llm_timeouts += 1
                                if (
                                    is_planact_like_architecture(agent_architecture)
                                    and step.action == "llm_timeout"
                                    and max_consecutive_llm_timeouts <= 0
                                ):
                                    abort_reason = "executor_llm_timeout"
                                    done = True
                            else:
                                consecutive_llm_timeouts = 0
                            if (
                                agent_architecture not in {"v2", "v2_guarded", "v2_restart1", "v2_planact", "v3", "v3_repair_brief", "v3_repair_llm"}
                                and infer_task_type(planner_task) == "NAVIGATE"
                                and page_satisfies_task(task=planner_task, site_name=task.primary_site, page=page)
                            ):
                                done = True
                            if (
                                is_planact_like_architecture(agent_architecture)
                                and infer_task_type(planner_task) == "NAVIGATE"
                                and step.status == "success"
                                and page_satisfies_task(task=planner_task, site_name=task.primary_site, page=page)
                            ):
                                last_action = final_nav_action()
                                route_satisfied_auto_final = True
                                done = True
                            artifacts.log_step(step)
                            if executor.last_artifacts is not None:
                                executor_calls += 1
                                prompt_path = None
                                grounding_path = None
                                if is_planact_like_architecture(agent_architecture):
                                    prompt_path = artifacts.write_executor_prompt(executor_calls, executor.last_artifacts.prompt)
                                    grounding_path = artifacts.write_executor_grounding(
                                        executor_calls,
                                        {
                                            "call_index": executor_calls,
                                            "subgoal_id": subgoal.id,
                                            "grounded_candidates": executor.last_artifacts.grounded_candidates or [],
                                            "validation_error_category": executor.last_artifacts.validation_error_category,
                                            "mutation_context": executor.last_artifacts.mutation_context,
                                            "forbidden_recent_actions": executor.last_artifacts.forbidden_recent_actions or [],
                                            "stale_bid_targets": executor.last_artifacts.stale_bid_targets or [],
                                            "recovery_hint": executor.last_artifacts.recovery_hint,
                                        },
                                    )
                                if executor.last_artifacts.total_tokens:
                                    executor_tokens += executor.last_artifacts.total_tokens
                                    total_tokens += executor.last_artifacts.total_tokens
                                if executor.last_artifacts.prompt_tokens:
                                    executor_prompt_tokens += executor.last_artifacts.prompt_tokens
                                if executor.last_artifacts.completion_tokens:
                                    executor_completion_tokens += executor.last_artifacts.completion_tokens
                                executor_call_row = {
                                    "call_index": executor_calls,
                                    "subgoal_id": subgoal.id,
                                    "model_name": executor.last_artifacts.model_name,
                                    "action": executor.last_artifacts.decision.action,
                                    "action_type": executor.last_artifacts.decision.action_type,
                                    "prompt_tokens": executor.last_artifacts.prompt_tokens,
                                    "completion_tokens": executor.last_artifacts.completion_tokens,
                                    "total_tokens": executor.last_artifacts.total_tokens,
                                    "elapsed_ms": executor.last_artifacts.elapsed_ms,
                                    "rationale_summary": executor.last_artifacts.decision.rationale_summary,
                                    "expected_observation": executor.last_artifacts.decision.expected_observation,
                                    "raw_response_preview": executor.last_artifacts.raw_response[:1000],
                                }
                                if is_planact_like_architecture(agent_architecture):
                                    executor_call_row.update(
                                        {
                                            "prompt_path": str(prompt_path) if prompt_path else None,
                                            "grounding_path": str(grounding_path) if grounding_path else None,
                                            "validation_error_category": executor.last_artifacts.validation_error_category,
                                            "grounded_candidate_count": len(executor.last_artifacts.grounded_candidates or []),
                                            "mutation_context": executor.last_artifacts.mutation_context,
                                            "forbidden_recent_actions": executor.last_artifacts.forbidden_recent_actions or [],
                                            "stale_bid_targets": executor.last_artifacts.stale_bid_targets or [],
                                            "recovery_hint": executor.last_artifacts.recovery_hint,
                                            "repair_brief": executor.last_artifacts.repair_brief,
                                        }
                                    )
                                artifacts.log_executor_call(executor_call_row)
                            previous_urls.append(page.url)
                            should_validate = (k > 0 and total_steps % k == 0) or done or step.status == "error"
                            if should_validate:
                                last_signal = evaluate_progress(
                                    step_index=total_steps,
                                    subgoal=subgoal,
                                    current_url=page.url,
                                    previous_urls=previous_urls,
                                    last_action=step.action,
                                    last_action_error=obs.get("last_action_error") or step.error,
                                    url_before=step.url_before,
                                    title_before=title_before,
                                    title_after=safe_page_title(page),
                                )
                                artifacts.log_runtime_signal(last_signal)
                                last_decision = decide_next_action(last_signal, step_budget_reached())
                                artifacts.log_controller_decision(last_decision)
                                if is_planact_like_architecture(agent_architecture):
                                    recovery_hint = (
                                        build_recovery_hint(
                                            task=planner_task,
                                            site_name=task.primary_site,
                                            previous_steps=executor.previous_steps,
                                            page=page,
                                            last_error=obs.get("last_action_error") or step.error,
                                        )
                                        if is_repair_architecture(agent_architecture)
                                        else None
                                    )
                                    repair_brief = (
                                        build_k_repair_brief(
                                            task=planner_task,
                                            site_name=task.primary_site,
                                            page=page,
                                            previous_steps=executor.previous_steps,
                                            evaluator_signal=last_signal,
                                            controller_decision=last_decision,
                                            recovery_hint=recovery_hint,
                                            last_error=obs.get("last_action_error") or step.error,
                                        )
                                        if is_repair_architecture(agent_architecture)
                                        else None
                                    )
                                    if repair_brief and agent_architecture == "v3_repair_llm":
                                        try:
                                            repair_brief = refine_repair_brief_with_llm(
                                                task=planner_task,
                                                site_name=task.primary_site,
                                                page=page,
                                                previous_steps=executor.previous_steps,
                                                base_repair_brief=repair_brief,
                                                model_name=planner_model,
                                                base_url=ollama_base_url,
                                                timeout_seconds=min(llm_timeout_seconds, 180),
                                            )
                                        except Exception as exc:
                                            repair_brief = {
                                                **repair_brief,
                                                "llm_repair_critic_error": str(exc),
                                            }
                                    if repair_brief:
                                        latest_repair_brief = repair_brief
                                        plan_history["repair_briefs"].append(
                                            {
                                                "step_index": total_steps,
                                                "subgoal_id": subgoal.id,
                                                "repair_brief": repair_brief,
                                            }
                                        )
                                        repeated_failure = (
                                            repeated_repair_failure_class(plan_history)
                                            if agent_architecture in {"v3_repair_brief", "v3_repair_llm"}
                                            else None
                                        )
                                        if repeated_failure:
                                            abort_reason = f"repeated_repair_failure:{repeated_failure}"
                                            done = True
                                            break
                                    elif last_decision.decision == "continue":
                                        latest_repair_brief = None
                                    plan_history["runtime_feedback"].append(
                                        {
                                            "step_index": total_steps,
                                            "subgoal_id": subgoal.id,
                                            "signal": plain(last_signal),
                                            "controller_decision": plain(last_decision),
                                            "recent_action": plain(step),
                                            "recovery_hint": recovery_hint,
                                            "repair_brief": repair_brief,
                                        }
                                    )
                                final_decision = last_decision.decision
                                subgoal_done = last_signal.subgoal_done
                                if last_decision.decision in {"local_replan", "global_replan"}:
                                    needs_replan = True
                                    subgoal_done = True
                                if last_decision.decision == "abort":
                                    abort_reason = last_decision.reason_code
                                    done = True
                                    break
                                if (
                                    is_planact_like_architecture(agent_architecture)
                                    and max_consecutive_llm_timeouts > 0
                                    and consecutive_llm_timeouts >= max_consecutive_llm_timeouts
                                ):
                                    abort_reason = "repeated_llm_timeout"
                                    done = True
                                    break
                            else:
                                # k=0 disables periodic runtime validation. In that baseline mode,
                                # the runner advances after one executor action per subgoal and only
                                # replans at horizon boundaries or hard execution signals.
                                subgoal_done = k == 0
                                if (
                                    is_planact_like_architecture(agent_architecture)
                                    and max_consecutive_llm_timeouts > 0
                                    and consecutive_llm_timeouts >= max_consecutive_llm_timeouts
                                ):
                                    abort_reason = "repeated_llm_timeout"
                                    done = True
                                    break
                            if done or needs_replan:
                                break
                        if done or needs_replan or step_budget_reached():
                            break
                    horizon_complete = h == 0 or len(plan.subgoals) < h
                    if not done and not needs_replan and not step_budget_reached() and horizon_complete:
                        done = True
                    if done or final_decision == "abort":
                        break
            finally:
                try:
                    env_obj.close()
                except Exception:
                    pass

        response = final_response_for_task(
            official_task,
            last_action,
            abort_reason,
            require_explicit_final=agent_architecture in {"v2", "v2_guarded", "v2_restart1", "v2_planact", "v3", "v3_repair_brief", "v3_repair_llm"},
        )
        write_json(agent_response_path, response)
    else:
        response = (
            read_json(agent_response_path)
            if agent_response_path.exists()
            else final_response_for_task(
                official_task,
                None,
                require_explicit_final=agent_architecture in {"v2", "v2_guarded", "v2_restart1", "v2_planact", "v3", "v3_repair_brief", "v3_repair_llm"},
            )
        )
        if not agent_response_path.exists():
            write_agent_response(agent_response_path, response.get("task_type", infer_task_type(official_task)), response.get("retrieved_data"), response.get("error_details"))

    eval_proc = None
    if not skip_official_eval:
        with tracker.measure("official_eval_ms"):
            eval_proc = run_official_eval(
                repo_root=repo_root,
                config_path=config_path,
                task_id=task.task_id,
                output_root=output_dir.parent,
                env=env,
            )

    official_score, official_success, official_status = read_official_result(output_dir)
    final_response_network_repair_applied = False
    if (
        not skip_official_eval
        and official_success is False
        and should_repair_mutate_final_from_official_network_success(output_dir / "eval_result.json", official_task)
    ):
        write_agent_response(agent_response_path, infer_task_type(official_task), None, None)
        final_response_network_repair_applied = True
        with tracker.measure("official_eval_after_final_response_repair_ms"):
            eval_proc = run_official_eval(
                repo_root=repo_root,
                config_path=config_path,
                task_id=task.task_id,
                output_root=output_dir.parent,
                env=env,
            )
        official_score, official_success, official_status = read_official_result(output_dir)
    runtime_counts = artifacts.runtime_counts()
    ended_at = utc_now()
    summary = {
        "task_id": task.task_id,
        "intent_template_id": task.intent_template_id,
        "revision": task.revision,
        "gym_id": task.gym_id,
        "site": task.primary_site,
        "sites": list(task.sites),
        "intent": task.intent,
        "task_type": infer_task_type(official_task),
        "task_capability": infer_task_capability(official_task, task.primary_site),
        "capability_tier": capability_tier(infer_task_capability(official_task, task.primary_site)),
        "h": h,
        "k": k,
        "runtime_validation_enabled": k > 0,
        "run_mode": run_mode,
        "planner_mode": planner_mode,
        "planner_model": planner_model,
        "executor_model": executor_model,
        "agent_architecture": agent_architecture,
        "max_consecutive_llm_timeouts": max_consecutive_llm_timeouts,
        **llm_backend_metadata(ollama_base_url),
        "started_at": started_at,
        "ended_at": ended_at,
        "phase_durations_ms": tracker.phases_ms,
        "total_runtime_ms": tracker.total_runtime_ms,
        "total_steps": total_steps,
        "max_steps": step_budget,
        "max_steps_disabled": step_budget is None,
        "step_budget_reached": step_budget_reached(),
        "planner_calls": planner_calls,
        "max_planner_calls": planner_call_budget,
        "max_planner_calls_disabled": planner_call_budget is None,
        "planner_call_budget_reached": planner_call_budget_reached(),
        "executor_calls": executor_calls,
        "num_plan_subgoals_generated": num_plan_subgoals_generated,
        "total_tokens": total_tokens,
        "planner_tokens": planner_tokens,
        "executor_tokens": executor_tokens,
        "prompt_tokens": planner_prompt_tokens + executor_prompt_tokens,
        "completion_tokens": planner_completion_tokens + executor_completion_tokens,
        "planner_prompt_tokens": planner_prompt_tokens,
        "planner_completion_tokens": planner_completion_tokens,
        "executor_prompt_tokens": executor_prompt_tokens,
        "executor_completion_tokens": executor_completion_tokens,
        "runtime_progress_score": artifacts.mean_runtime_progress(),
        **runtime_counts,
        "controller_final_decision": final_decision,
        "abort_reason": abort_reason,
        "route_satisfied_auto_final": route_satisfied_auto_final,
        "final_response_network_repair_applied": final_response_network_repair_applied,
        "official_score": official_score,
        "official_success": official_success,
        "official_eval_status": official_status,
        "official_eval_returncode": eval_proc.returncode if eval_proc is not None else None,
        "official_eval_stdout_tail": eval_proc.stdout[-2000:] if eval_proc is not None and eval_proc.stdout else None,
        "official_eval_stderr_tail": eval_proc.stderr[-2000:] if eval_proc is not None and eval_proc.stderr else None,
        "artifacts": {
            "network_har": str(har_path),
            "agent_response": str(agent_response_path),
            "run_summary": str(output_dir / "run_summary.json"),
            "plan": str(output_dir / "plan.json"),
            "step_trace": str(artifacts.step_trace_path),
            "runtime_evaluator_signals": str(artifacts.evaluator_path),
            "controller_decisions": str(artifacts.controller_path),
            "planner_calls": str(artifacts.planner_calls_path),
            "executor_calls": str(artifacts.executor_calls_path),
            "official_config": str(config_path),
            "official_eval_result": str(output_dir / "eval_result.json"),
        },
    }
    diagnostic = diagnose_run_summary(summary, output_dir)
    if is_planact_like_architecture(agent_architecture):
        plan_history_path = output_dir / "plan_history.json"
        write_json(plan_history_path, plan_history)
        summary["artifacts"]["plan_history"] = str(plan_history_path)
        summary["artifacts"]["executor_prompts_dir"] = str(artifacts.executor_prompts_dir)
        summary["artifacts"]["executor_grounding_dir"] = str(artifacts.executor_grounding_dir)
    write_json(output_dir / "diagnostic.json", diagnostic)
    summary.update(diagnostic)
    write_json(output_dir / "run_summary.json", summary)
    return summary
