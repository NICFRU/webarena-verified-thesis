"""Post-run diagnostics for WebArena-Verified H/k experiments.

The diagnostics are explanatory only. They never replace the official
WebArena-Verified score.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen

from hk_agent.capabilities import capability_tier, infer_official_task_type, infer_task_capability
from webarena_exp.io_utils import read_json, read_jsonl, write_json


def _safe_read_json(path: Path) -> Any:
    try:
        return read_json(path)
    except Exception:
        return None


def _action_kind(action: str) -> str:
    action = action.strip()
    if action.startswith("send_msg_to_user("):
        return "finish"
    if action.startswith("goto("):
        return "navigate"
    if action.startswith("click("):
        return "click"
    if action.startswith("fill("):
        return "fill"
    if action.startswith("type("):
        return "type"
    if action.startswith("press("):
        return "press"
    if action.startswith("select_option("):
        return "select_option"
    if action.startswith("noop("):
        return "noop"
    return "other"


def _has_nonempty_retrieved_data(response: dict[str, Any] | None) -> bool:
    if not response:
        return False
    data = response.get("retrieved_data")
    return data not in (None, "", [], {})


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


MUTATION_ACTION_KINDS = {"click", "fill", "type", "press", "select_option"}
SUBMIT_HINT_RE = re.compile(
    r"\b("
    r"submit|save|create|commit|confirm|invite|fork|merge|assign|add|update|"
    r"apply|publish|star|unstar|send|reply|comment|close|delete"
    r")\b",
    re.IGNORECASE,
)
STATE_REACHED_HINT_RE = re.compile(
    r"("
    r"/-/forks/new|/-/edit/|/edit\b|/new\b|/create\b|/admin|/settings|"
    r"modal|dialog|form|editor|textarea|contenteditable|dropdown|namespace|"
    r"invite|member|issue|milestone|merge.request|profile|status"
    r")",
    re.IGNORECASE,
)
LOOP_HINT_RE = re.compile(
    r"("
    r"repeats a recent no-progress action|revisit a recent url cycle|url cycle|"
    r"executor returned noop|planner-call budget|step budget|stuck|same unrecovered"
    r")",
    re.IGNORECASE,
)


def _canonical_eval_value(value: Any) -> str:
    """Return a conservative comparison key for normalized evaluator values."""

    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_duplicate_suffix_variant(actual: Any, expected: Any) -> bool:
    """Return whether actual looks like expected plus an auto-generated numeric suffix."""

    expected_key = _canonical_eval_value(expected)
    actual_key = _canonical_eval_value(actual)
    if not expected_key or not actual_key:
        return False
    return bool(re.fullmatch(re.escape(expected_key) + r"\d+", actual_key))


def _url_matches(actual_url: Any, expected_url: Any) -> bool:
    if not isinstance(expected_url, dict):
        return True
    expected_base = str(expected_url.get("base_url") or "")
    if not expected_base:
        return True
    actual_base = ""
    if isinstance(actual_url, dict):
        actual_base = str(actual_url.get("base_url") or "")
    else:
        actual_base = str(actual_url or "")
    if not actual_base:
        return False
    if expected_base.startswith("^"):
        try:
            return re.fullmatch(expected_base, actual_base) is not None
        except re.error:
            return expected_base == actual_base
    return expected_base == actual_base


def _normalize_url_for_eval(value: Any) -> str:
    """Return a URL key that treats harmless trailing slashes as equivalent."""

    text = str(value or "")
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.scheme:
        return text.rstrip("/")
    path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{parsed.netloc}{path}{query}"


def _expected_base_pattern(expected_base: str) -> str:
    pattern = expected_base.replace("__SHOPPING_ADMIN__", r"https?://[^/]+/admin")
    pattern = pattern.replace("__SHOPPING__", r"https?://[^/]+")
    pattern = pattern.replace("__GITLAB__", r"https?://[^/]+")
    pattern = pattern.replace("__REDDIT__", r"https?://[^/]+")
    return pattern


def _pattern_matches_with_optional_trailing_slash(pattern: str, actual: str) -> bool:
    """Match a regex-like expected URL pattern while allowing one trailing slash drift."""

    if re.fullmatch(pattern, actual):
        return True
    return re.fullmatch(pattern.rstrip("/") + r"/?", actual.rstrip("/") + "/") is not None


def _har_url_matches_expected(actual_url: str, expected_url: Any) -> bool:
    if not isinstance(expected_url, dict):
        return True
    expected_base = str(expected_url.get("base_url") or "")
    if not expected_base:
        return True
    actual_base = actual_url.split("?", 1)[0]
    if expected_base.startswith("^"):
        pattern = _expected_base_pattern(expected_base)
        try:
            return re.fullmatch(pattern, actual_base) is not None
        except re.error:
            return _normalize_url_for_eval(pattern) == _normalize_url_for_eval(actual_base)
    expected_base = _expected_base_pattern(expected_base)
    if _shopping_admin_report_filter_base_equivalent(actual_base, expected_base):
        return True
    return _normalize_url_for_eval(actual_base) == _normalize_url_for_eval(expected_base)


def _shopping_admin_report_filter_base_equivalent(actual_base: str, expected_base: str) -> bool:
    """Treat Magento report landing URLs with filter query params as filter requests."""

    expected_match = re.search(r"/admin/reports/report_sales/(?P<kind>sales|tax)/filter$", expected_base.rstrip("/"))
    if not expected_match:
        return False
    kind = expected_match.group("kind")
    actual_path = urlparse(actual_base).path.rstrip("/")
    return actual_path in {
        f"/admin/reports/report_sales/{kind}",
        f"/admin/reports/report_sales/{kind}/filter",
    }


def _query_params_match(actual_url: str, expected_url: Any) -> bool:
    if not isinstance(expected_url, dict):
        return True
    expected_params = expected_url.get("query_params")
    if not isinstance(expected_params, dict):
        return True
    actual_params = parse_qs(urlparse(actual_url).query, keep_blank_values=True)
    for key, expected_values in expected_params.items():
        expected_list = [str(item) for item in (expected_values if isinstance(expected_values, list) else [expected_values])]
        actual_list = actual_params.get(str(key))
        if actual_list is None:
            return False
        if sorted(actual_list) != sorted(expected_list):
            return False
    return True


def _header_values(headers: Any, name: str) -> list[str]:
    if not isinstance(headers, list):
        return []
    wanted = name.lower()
    return [str(header.get("value") or "") for header in headers if str(header.get("name") or "").lower() == wanted]


def _headers_match_with_url_normalization(request_headers: Any, expected_headers: Any) -> tuple[bool, list[str]]:
    if not isinstance(expected_headers, dict):
        return True, []
    reasons: list[str] = []
    for name, expected_value in expected_headers.items():
        actual_values = _header_values(request_headers, str(name))
        if not actual_values:
            return False, reasons
        if isinstance(expected_value, dict) and "base_url" in expected_value:
            expected_base = _expected_base_pattern(str(expected_value.get("base_url") or ""))
            matched_exact = False
            matched_normalized = False
            for actual in actual_values:
                actual_base = actual.split("?", 1)[0]
                if expected_base.startswith("^"):
                    try:
                        if re.fullmatch(expected_base, actual_base):
                            matched_exact = True
                            break
                    except re.error:
                        pass
                elif any(token in expected_base for token in ("[^", ".*", "https?://")):
                    try:
                        if _pattern_matches_with_optional_trailing_slash(expected_base, actual_base):
                            matched_normalized = True
                    except re.error:
                        pass
                elif actual_base == expected_base:
                    matched_exact = True
                    break
                if _normalize_url_for_eval(actual_base) == _normalize_url_for_eval(expected_base):
                    matched_normalized = True
            if matched_exact:
                continue
            if matched_normalized:
                reasons.append(f"{name}: trailing-slash URL normalization")
                continue
            return False, reasons
        else:
            expected_text = str(expected_value)
            if expected_text not in actual_values:
                return False, reasons
    return True, reasons


def _network_event_url_normalization_near_miss(result: dict[str, Any], output_dir: Path | None) -> tuple[bool, list[str]]:
    """Return whether HAR contains the expected event modulo URL/header slash normalization."""

    if output_dir is None or result.get("evaluator_name") != "NetworkEventEvaluator":
        return False, []
    expected = result.get("expected")
    if not isinstance(expected, dict):
        return False, []
    har = _safe_read_json(output_dir / "network.har")
    entries = (((har or {}).get("log") or {}).get("entries")) if isinstance(har, dict) else None
    if not isinstance(entries, list):
        return False, []
    reasons: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        if expected.get("http_method") and request.get("method") != expected.get("http_method"):
            continue
        if expected.get("response_status") is not None and response.get("status") != expected.get("response_status"):
            continue
        actual_url = str(request.get("url") or "")
        if not _har_url_matches_expected(actual_url, expected.get("url")):
            continue
        if not _query_params_match(actual_url, expected.get("url")):
            continue
        headers_match, header_reasons = _headers_match_with_url_normalization(request.get("headers"), expected.get("headers"))
        if not headers_match:
            continue
        if header_reasons:
            reasons.extend(header_reasons)
        else:
            reasons.append("network event present in HAR with evaluator URL normalization")
        return True, reasons
    return False, reasons


def _post_data_matches_with_duplicate_suffix(actual_post_data: Any, expected_post_data: Any) -> tuple[bool, list[str]]:
    if not isinstance(expected_post_data, dict):
        return True, []
    if not isinstance(actual_post_data, dict):
        return False, []
    suffix_reasons: list[str] = []
    for key, expected_value in expected_post_data.items():
        if key not in actual_post_data:
            return False, suffix_reasons
        actual_value = actual_post_data.get(key)
        if isinstance(expected_value, list):
            expected_keys = {_canonical_eval_value(item) for item in expected_value}
            if _canonical_eval_value(actual_value) not in expected_keys:
                return False, suffix_reasons
            continue
        if _canonical_eval_value(actual_value) == _canonical_eval_value(expected_value):
            continue
        if _is_duplicate_suffix_variant(actual_value, expected_value):
            suffix_reasons.append(f"{key}: actual={actual_value!r} expected={expected_value!r}")
            continue
        return False, suffix_reasons
    return True, suffix_reasons


def _network_event_duplicate_suffix_near_miss(result: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return whether one failed network evaluator only differs by duplicate suffixes."""

    if result.get("evaluator_name") != "NetworkEventEvaluator":
        return False, []
    expected = result.get("expected")
    actual_events = result.get("actual_normalized") or result.get("actual")
    if not isinstance(expected, dict) or not isinstance(actual_events, list):
        return False, []
    reasons: list[str] = []
    for event in actual_events:
        if not isinstance(event, dict):
            continue
        if expected.get("http_method") and event.get("http_method") != expected.get("http_method"):
            continue
        if expected.get("response_status") is not None and event.get("response_status") != expected.get("response_status"):
            continue
        if not _url_matches(event.get("url"), expected.get("url")):
            continue
        post_matches, suffix_reasons = _post_data_matches_with_duplicate_suffix(
            event.get("post_data"),
            expected.get("post_data"),
        )
        if post_matches and suffix_reasons:
            reasons.extend(suffix_reasons)
            return True, reasons
    return False, reasons


def _as_list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, ""):
        return []
    if isinstance(value, str) and "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value)]


def _network_event_incomplete_multi_value(result: dict[str, Any], field: str) -> tuple[bool, str | None]:
    """Return whether an event submitted only a subset of an expected multi-value field."""

    if result.get("evaluator_name") != "NetworkEventEvaluator":
        return False, None
    expected = result.get("expected")
    actual_events = result.get("actual_normalized") or result.get("actual")
    if not isinstance(expected, dict) or not isinstance(actual_events, list):
        return False, None
    expected_post_data = expected.get("post_data")
    if not isinstance(expected_post_data, dict):
        return False, None
    expected_values = {_canonical_eval_value(item) for item in _as_list_value(expected_post_data.get(field))}
    expected_values.discard("")
    if len(expected_values) < 2:
        return False, None

    for event in actual_events:
        if not isinstance(event, dict):
            continue
        if expected.get("http_method") and event.get("http_method") != expected.get("http_method"):
            continue
        if expected.get("response_status") is not None and event.get("response_status") != expected.get("response_status"):
            continue
        if not _url_matches(event.get("url"), expected.get("url")):
            continue
        actual_post_data = event.get("post_data")
        if not isinstance(actual_post_data, dict):
            continue
        actual_values = {_canonical_eval_value(item) for item in _as_list_value(actual_post_data.get(field))}
        actual_values.discard("")
        if actual_values and actual_values < expected_values:
            missing = sorted(expected_values - actual_values)
            return True, f"{field}: actual subset={sorted(actual_values)} missing={missing}"
    return False, None


def incomplete_multi_invite_diagnostics(output_dir: Path | None) -> dict[str, Any]:
    """Diagnose GitLab invite runs that submitted only part of a multi-user invitation."""

    defaults = {
        "official_eval_incomplete_multi_invite_detected": False,
        "official_eval_incomplete_multi_invite_reason": None,
    }
    if output_dir is None:
        return defaults
    eval_result = _safe_read_json(output_dir / "eval_result.json")
    if not isinstance(eval_result, dict):
        return defaults
    results = eval_result.get("evaluators_results")
    if not isinstance(results, list):
        return defaults

    reasons: list[str] = []
    for result in results:
        if not isinstance(result, dict) or result.get("status") == "success":
            continue
        incomplete, reason = _network_event_incomplete_multi_value(result, "user_id")
        if incomplete and reason:
            reasons.append(reason)
    return {
        "official_eval_incomplete_multi_invite_detected": bool(reasons),
        "official_eval_incomplete_multi_invite_reason": "; ".join(dict.fromkeys(reasons)) or None,
    }


def contamination_adjusted_eval_diagnostics(output_dir: Path | None) -> dict[str, Any]:
    """Diagnose duplicate-name contamination without changing official scores.

    WebArena services can auto-suffix duplicate slugs when the same MUTATE task is
    run repeatedly without resetting the container, for example `x-lab` becoming
    `x-lab14`. This helper marks such cases as an adjusted diagnostic success only
    when every failed evaluator can be explained by that suffix. Official
    WebArena-Verified scores remain untouched.
    """

    defaults = {
        "contamination_adjusted_success": False,
        "official_eval_contamination_suffix_detected": False,
        "official_eval_adjustable_suffix_failures": 0,
        "official_eval_nonadjustable_failures": 0,
        "contamination_adjusted_reason": None,
    }
    if output_dir is None:
        return defaults
    eval_result = _safe_read_json(output_dir / "eval_result.json")
    if not isinstance(eval_result, dict):
        return defaults
    results = eval_result.get("evaluators_results")
    if not isinstance(results, list):
        return defaults

    failed_results = [result for result in results if isinstance(result, dict) and result.get("status") != "success"]
    if not failed_results:
        return defaults

    suffix_reasons: list[str] = []
    adjustable = 0
    nonadjustable = 0
    for result in failed_results:
        is_suffix_near_miss, reasons = _network_event_duplicate_suffix_near_miss(result)
        if is_suffix_near_miss:
            adjustable += 1
            suffix_reasons.extend(reasons)
            continue
        is_url_near_miss, url_reasons = _network_event_url_normalization_near_miss(result, output_dir)
        if is_url_near_miss:
            adjustable += 1
            suffix_reasons.extend(url_reasons)
        else:
            nonadjustable += 1
            _, partial_reasons = _network_event_duplicate_suffix_near_miss(result)
            suffix_reasons.extend(partial_reasons)

    detected = bool(suffix_reasons) or adjustable > 0
    adjusted_success = adjustable > 0 and nonadjustable == 0
    reason = "; ".join(dict.fromkeys(suffix_reasons))
    return {
        "contamination_adjusted_success": adjusted_success,
        "official_eval_contamination_suffix_detected": detected,
        "official_eval_adjustable_suffix_failures": adjustable,
        "official_eval_nonadjustable_failures": nonadjustable,
        "contamination_adjusted_reason": reason or None,
    }


def mutation_diagnostics(
    *,
    task_type: str,
    tier: str,
    action_kinds: list[str],
    errors: list[str],
    final_kind: str,
    final_status: str | None,
) -> dict[str, Any]:
    """Return mutation-focused signals for run and sweep analysis."""

    is_mutate = task_type == "MUTATE"
    mutation_action_indices = [idx for idx, kind in enumerate(action_kinds) if kind in MUTATION_ACTION_KINDS]
    final_index = len(action_kinds) - 1 if action_kinds else -1
    final_success = str(final_status or "").upper() == "SUCCESS"
    prior_mutation_actions = [idx for idx in mutation_action_indices if idx < final_index]
    mutation_actions_before_finish = len(prior_mutation_actions) if final_kind == "finish" else len(mutation_action_indices)
    finish_after_mutation_action = final_kind == "finish" and bool(prior_mutation_actions)
    final_success_without_mutation_action = is_mutate and final_success and final_kind == "finish" and not prior_mutation_actions
    recent_error_before_finish = final_kind == "finish" and bool(errors)
    return {
        "is_mutate_task": is_mutate,
        "mutation_tier_requires_state_change": tier == "mutation",
        "mutation_action_count": len(mutation_action_indices),
        "mutation_actions_before_finish": mutation_actions_before_finish,
        "finish_after_mutation_action": finish_after_mutation_action,
        "final_success_without_mutation_action": final_success_without_mutation_action,
        "recent_error_before_finish": recent_error_before_finish,
        "mutation_eval_focus": (
            "state_change_required"
            if tier == "mutation"
            else "policy_or_permission_check"
            if is_mutate
            else "not_mutate"
        ),
    }


def _compact_text(value: Any, *, limit: int = 200000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) > limit:
        return text[:limit]
    return text


def _har_mutation_methods(output_dir: Path | None, artifacts: dict[str, Any]) -> list[str]:
    if output_dir is None:
        return []
    har_path_value = artifacts.get("network_har") or output_dir / "network.har"
    har_path = Path(str(har_path_value))
    har = _safe_read_json(har_path)
    if not isinstance(har, dict):
        return []
    entries = (((har.get("log") or {}).get("entries")) or [])
    methods: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        request = entry.get("request")
        if not isinstance(request, dict):
            continue
        method = str(request.get("method") or "").upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            methods.append(method)
    return methods


def _first_state_reached_index(steps: list[dict[str, Any]], capability: str) -> int | None:
    for idx, step in enumerate(steps):
        blob = " ".join(
            str(step.get(key) or "")
            for key in ("url_before", "url_after", "page_title", "action", "error")
        )
        if STATE_REACHED_HINT_RE.search(blob):
            return idx
        if capability == "mutate_gitlab_fork" and "/-/forks/new" in blob:
            return idx
        if capability == "mutate_gitlab_file_edit" and "/-/edit/" in blob:
            return idx
        if capability == "mutate_gitlab_mr_reply" and "merge_requests" in blob:
            return idx
    return None


def _has_repeated_url_after_state(steps: list[dict[str, Any]], first_state_index: int | None) -> bool:
    if first_state_index is None:
        return False
    urls: dict[str, int] = {}
    for step in steps[first_state_index:]:
        url = str(step.get("url_after") or step.get("url_before") or "")
        if not url:
            continue
        urls[url] = urls.get(url, 0) + 1
        if urls[url] >= 4:
            return True
    return False


def _failure_class(
    *,
    site: str,
    capability: str,
    category: str,
    text_blob: str,
    state_reached: bool,
    loop_after_reaching_form: bool,
    incomplete_multi_invite: bool = False,
) -> str:
    lower_blob = text_blob.lower()
    if site == "gitlab" and capability in {"mutate_gitlab_members", "mutate_gitlab_group"}:
        if incomplete_multi_invite:
            return "gitlab_invite_multi_user_incomplete"
    if site == "gitlab" and capability == "mutate_gitlab_fork":
        if "/-/forks/new" in lower_blob and ("namespace" in lower_blob or "fork" in lower_blob):
            return "gitlab_fork_namespace_loop" if loop_after_reaching_form else "gitlab_fork_submission_missing"
    if site == "gitlab" and capability == "mutate_gitlab_file_edit":
        if "/-/edit/" in lower_blob or "simple file editor" in lower_blob or "editor-like" in lower_blob:
            if "unsupported browsergym action: type" in lower_blob or '"action": "type"' in lower_blob:
                return "gitlab_file_editor_unsupported_action"
            return "gitlab_file_editor_unresolved"
    if site == "gitlab" and capability == "mutate_gitlab_mr_reply":
        return "gitlab_mr_reply_ambiguous_assignment"
    if "unsupported browsergym action: type" in lower_blob or '"action": "type"' in lower_blob:
        return "unsupported_action_type"
    if loop_after_reaching_form:
        return "mutation_loop_after_reaching_form"
    if state_reached and category in {"step_budget_exhausted", "planner_call_budget_exhausted", "loop_or_no_progress"}:
        return "state_reached_without_valid_finish"
    return category


def near_miss_diagnostics(
    *,
    site: str,
    task_type: str,
    capability: str,
    tier: str,
    category: str,
    completion: float,
    official_success: bool,
    steps: list[dict[str, Any]],
    executor_calls: list[dict[str, Any]],
    errors: list[str],
    action_kinds: list[str],
    output_dir: Path | None,
    artifacts: dict[str, Any],
    incomplete_multi_invite: bool = False,
) -> dict[str, Any]:
    """Return explanatory near-miss signals without changing official success."""

    har_methods = _har_mutation_methods(output_dir, artifacts)
    first_state_index = _first_state_reached_index(steps, capability)
    compact_calls = [
        {
            "action": call.get("action"),
            "action_type": call.get("action_type"),
            "validation_error_category": call.get("validation_error_category"),
            "rationale_summary": call.get("rationale_summary"),
            "mutation_context": call.get("mutation_context"),
            "repair_brief": call.get("repair_brief"),
            "recovery_hint": call.get("recovery_hint"),
        }
        for call in executor_calls[-25:]
        if isinstance(call, dict)
    ]
    text_blob = "\n".join(
        [
            _compact_text(steps[-50:]),
            _compact_text(compact_calls),
            "\n".join(errors[-20:]),
        ]
    )
    state_reached = bool(first_state_index is not None)
    submit_reached = bool(SUBMIT_HINT_RE.search(text_blob)) or bool(har_methods)
    mutation_attempted = (
        any(kind in MUTATION_ACTION_KINDS for kind in action_kinds)
        or bool(har_methods)
        or any(kind in {"POST", "PUT", "PATCH", "DELETE"} for kind in har_methods)
    )
    loop_after_reaching_form = state_reached and (
        bool(LOOP_HINT_RE.search(text_blob)) or _has_repeated_url_after_state(steps, first_state_index)
    )
    failure_class = _failure_class(
        site=site,
        capability=capability,
        category=category,
        text_blob=text_blob,
        state_reached=state_reached,
        loop_after_reaching_form=loop_after_reaching_form,
        incomplete_multi_invite=incomplete_multi_invite,
    )
    near_miss_score = completion
    if not official_success and tier == "mutation":
        if mutation_attempted:
            near_miss_score = max(near_miss_score, 0.35)
        if state_reached:
            near_miss_score = max(near_miss_score, 0.55)
        if submit_reached:
            near_miss_score = max(near_miss_score, 0.65)
        if loop_after_reaching_form and not incomplete_multi_invite:
            near_miss_score = min(max(near_miss_score, 0.55), 0.75)
    return {
        "near_miss_score": _clamp(1.0 if official_success else near_miss_score),
        "failure_class": failure_class,
        "state_reached": state_reached,
        "submit_reached": submit_reached,
        "mutation_attempted": mutation_attempted,
        "loop_after_reaching_form": loop_after_reaching_form,
    }


def diagnose_run_summary(summary: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    """Return a compact diagnostic explanation for one run summary."""

    output_dir = output_dir or Path(str(summary.get("artifacts", {}).get("run_summary", "."))).parent
    artifacts = summary.get("artifacts", {})
    step_trace_path = Path(artifacts.get("step_trace") or output_dir / "step_trace.jsonl")
    executor_calls_path = Path(artifacts.get("executor_calls") or output_dir / "executor_calls.jsonl")
    agent_response_path = Path(artifacts.get("agent_response") or output_dir / "agent_response.json")

    steps = read_jsonl(step_trace_path)
    executor_calls = read_jsonl(executor_calls_path)
    agent_response = _safe_read_json(agent_response_path)
    task = {
        "task_id": summary.get("task_id"),
        "intent": summary.get("intent", ""),
        "sites": summary.get("sites", []),
    }
    site = str(summary.get("site") or (task["sites"][0] if task["sites"] else "unknown"))
    task_type = infer_official_task_type(task)
    capability = infer_task_capability(task, site)
    tier = capability_tier(capability)
    actions = [str(step.get("action", "")) for step in steps if step.get("action")]
    action_kinds = [_action_kind(action) for action in actions]
    errors = [str(step.get("error")) for step in steps if step.get("error")]
    final_action = actions[-1] if actions else ""
    final_kind = _action_kind(final_action)
    final_status = agent_response.get("status") if isinstance(agent_response, dict) else None
    official_success = summary.get("official_success") is True
    official_score = summary.get("official_score")
    contamination_diag = contamination_adjusted_eval_diagnostics(output_dir)
    incomplete_invite_diag = incomplete_multi_invite_diagnostics(output_dir)
    contamination_adjusted_success = official_success or bool(contamination_diag["contamination_adjusted_success"])
    mutate_diag = mutation_diagnostics(
        task_type=task_type,
        tier=tier,
        action_kinds=action_kinds,
        errors=errors,
        final_kind=final_kind,
        final_status=final_status,
    )

    if official_success:
        category = "official_success"
        notes = "Official evaluator marked the run as successful."
        completion = 1.0
    elif contamination_adjusted_success:
        category = "contamination_suffix_near_miss"
        notes = (
            "Official evaluator rejected a duplicate-name suffix such as x-lab14 vs x-lab. "
            "The adjusted diagnostic treats this as state contamination, not as an official success."
        )
        completion = 0.9
    elif summary.get("abort_reason") == "repeated_llm_timeout":
        category = "repeated_llm_timeout"
        notes = "Planner/executor calls timed out repeatedly without browser progress; the run was stopped by the v2_planact timeout guard."
        completion = 0.0
    elif str(summary.get("abort_reason") or "").startswith("repeated_repair_failure:"):
        repair_class = str(summary.get("abort_reason") or "").split(":", 1)[1]
        category = "repeated_repair_failure"
        notes = (
            f"The v3 repair controller stopped after repeatedly diagnosing the same unrecovered failure class: {repair_class}. "
            "This is an executor/grounding repair failure, not a literal step-budget exhaustion."
        )
        completion = 0.3
    elif summary.get("status") == "failed":
        category = "runtime_exception"
        notes = str(summary.get("error") or "Experiment runner failed before a complete official evaluation.")
        completion = 0.0
    elif errors and any("usable JSON object" in error or "usable subgoals" in error for error in errors):
        category = "llm_json_or_action_parse_failure"
        notes = "The model did not produce a parseable planner/executor JSON action for at least one step."
        completion = 0.2
    elif errors and any("404" in error or "not found" in error.lower() for error in errors):
        category = "bad_route_or_not_found"
        notes = "The run hit a route/page that looked invalid before completing the task."
        completion = 0.25
    elif tier == "policy" and final_status != "ACTION_NOT_ALLOWED_ERROR":
        category = "missing_action_not_allowed"
        notes = "The task appears to require recognizing that the requested action is not allowed, but the final response did not use ACTION_NOT_ALLOWED_ERROR."
        completion = 0.45 if "navigate" in action_kinds else 0.25
    elif task_type == "RETRIEVE" and final_kind == "finish" and not _has_nonempty_retrieved_data(agent_response):
        category = "missing_retrieved_data"
        notes = "The agent finished a RETRIEVE task without returning the requested data."
        completion = 0.5
    elif task_type == "RETRIEVE" and final_kind == "finish" and _has_nonempty_retrieved_data(agent_response):
        category = "schema_or_value_mismatch"
        notes = "The agent returned data, but the official evaluator rejected the value or schema."
        completion = 0.75
    elif capability == "mutate_gitlab_mr_reply":
        category = "gitlab_mr_reply_ambiguous_assignment"
        notes = (
            "GitLab merge-request reply tasks require selecting the assigned MR that matches a short topic phrase. "
            "Failures in this class usually come from ambiguous GitLab search/dashboard results, wrong MR selection, "
            "or replying to the right-looking project but the wrong merge request."
        )
        completion = 0.55 if final_kind == "finish" else 0.35
    elif incomplete_invite_diag["official_eval_incomplete_multi_invite_detected"]:
        category = "gitlab_invite_multi_user_incomplete"
        notes = (
            "The GitLab invite request reached the expected invitation endpoint and role, but submitted only a subset "
            "of the requested users. This is a near miss, not an official success."
        )
        completion = 0.8
    elif mutate_diag["final_success_without_mutation_action"]:
        category = "premature_mutation_success"
        notes = "The agent reported MUTATE SUCCESS before any click/fill/type/press/select_option action that could change state."
        completion = 0.2
    elif tier == "mutation" and final_kind == "finish":
        category = "missing_required_mutation"
        notes = "The agent finished a MUTATE task, but the official evaluator did not observe the required mutation event."
        completion = 0.55 if mutate_diag["finish_after_mutation_action"] else 0.35
    elif task_type == "MUTATE" and tier == "policy" and final_kind == "finish":
        category = "policy_mutation_eval_mismatch"
        notes = "The task is MUTATE-shaped but likely policy/permission-gated; inspect whether ACTION_NOT_ALLOWED_ERROR or visible allowed action was correct."
        completion = 0.55
    elif summary.get("planner_call_budget_reached") is True and final_kind != "finish":
        category = "planner_call_budget_exhausted"
        notes = (
            "The run stopped after exhausting the planner-call budget without an accepted final result. "
            "This is not necessarily a BrowserGym step-budget exhaustion."
        )
        completion = 0.3 if "navigate" in action_kinds else 0.15
    elif int(summary.get("total_steps") or 0) >= 8 and final_kind != "finish":
        category = "step_budget_exhausted"
        notes = "The run used the step budget without producing an accepted final result."
        completion = 0.35 if "navigate" in action_kinds else 0.15
    elif int(summary.get("runtime_no_progress_events") or 0) > 0 or int(summary.get("runtime_loop_events") or 0) > 0:
        category = "loop_or_no_progress"
        notes = "Runtime evaluator detected repeated/no-progress behavior."
        completion = 0.3
    else:
        category = "official_eval_mismatch"
        notes = "The run completed structurally, but the official evaluator rejected it. Inspect HAR, agent_response, and trace."
        completion = 0.6 if final_kind == "finish" else 0.35

    if not official_success:
        if "navigate" in action_kinds:
            completion += 0.1
        if final_kind == "finish":
            completion += 0.1
        if any("404" in str(step.get("page_title", "")) or "not found" in str(step.get("page_title", "")).lower() for step in steps):
            completion -= 0.2
        if contamination_diag["official_eval_contamination_suffix_detected"]:
            notes = (
                f"{notes} Duplicate-name suffix contamination was also detected, "
                "but at least one other evaluator failure remained."
            )

    near_miss_diag = near_miss_diagnostics(
        site=site,
        task_type=task_type,
        capability=capability,
        tier=tier,
        category=category,
        completion=_clamp(completion),
        official_success=official_success,
        steps=steps,
        executor_calls=executor_calls,
        errors=errors,
        action_kinds=action_kinds,
        output_dir=output_dir,
        artifacts=artifacts,
        incomplete_multi_invite=bool(incomplete_invite_diag["official_eval_incomplete_multi_invite_detected"]),
    )

    return {
        "task_type": task_type,
        "task_capability": capability,
        "capability_tier": tier,
        "diagnostic_completion": _clamp(completion),
        "failure_category": category,
        **near_miss_diag,
        "failure_notes": notes,
        "final_response_status": final_status,
        "final_action_kind": final_kind,
        "num_executor_json_calls": len(executor_calls),
        "num_step_errors": len(errors),
        "last_step_error": errors[-1] if errors else None,
        "official_score": official_score,
        "official_success": official_success,
        **contamination_diag,
        **incomplete_invite_diag,
        "contamination_adjusted_success": contamination_adjusted_success,
        **mutate_diag,
    }


def diagnose_run_dir(run_dir: Path) -> dict[str, Any]:
    """Read one run directory and write diagnostic.json next to run_summary.json."""

    summary_path = run_dir / "run_summary.json"
    summary = read_json(summary_path)
    diagnostic = diagnose_run_summary(summary, run_dir)
    write_json(run_dir / "diagnostic.json", diagnostic)
    return diagnostic


def summarize_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build aggregate diagnostic counts for experiment summaries."""

    by_category: dict[str, int] = {}
    by_failure_class: dict[str, int] = {}
    by_tier: dict[str, dict[str, Any]] = {}
    total_contamination_adjusted_success = 0
    total_evaluation_success = 0
    for row in rows:
        category = str(row.get("failure_category") or "unknown")
        failure_class = str(row.get("failure_class") or category or "unknown")
        tier = str(row.get("capability_tier") or "unknown")
        by_category[category] = by_category.get(category, 0) + 1
        by_failure_class[failure_class] = by_failure_class.get(failure_class, 0) + 1
        tier_row = by_tier.setdefault(
            tier,
            {
                "num_rows": 0,
                "num_success": 0,
                "num_evaluation_success": 0,
                "num_contamination_adjusted_success": 0,
                "mean_diagnostic_completion": 0.0,
            },
        )
        tier_row["num_rows"] += 1
        if row.get("official_success") in (True, "True", "true", 1, "1"):
            tier_row["num_success"] += 1
        if row.get("evaluation_success") in (True, "True", "true", 1, "1"):
            tier_row["num_evaluation_success"] += 1
            total_evaluation_success += 1
        if row.get("contamination_adjusted_success") in (True, "True", "true", 1, "1"):
            tier_row["num_contamination_adjusted_success"] += 1
            total_contamination_adjusted_success += 1
        try:
            tier_row["mean_diagnostic_completion"] += float(row.get("diagnostic_completion") or 0)
        except Exception:
            pass
    for tier_row in by_tier.values():
        if tier_row["num_rows"]:
            tier_row["success_rate"] = tier_row["num_success"] / tier_row["num_rows"]
            tier_row["evaluation_success_rate"] = tier_row["num_evaluation_success"] / tier_row["num_rows"]
            tier_row["contamination_adjusted_success_rate"] = (
                tier_row["num_contamination_adjusted_success"] / tier_row["num_rows"]
            )
            tier_row["mean_diagnostic_completion"] = round(tier_row["mean_diagnostic_completion"] / tier_row["num_rows"], 3)
    return {
        "by_failure_category": by_category,
        "by_failure_class": by_failure_class,
        "by_capability_tier": by_tier,
        "num_evaluation_success": total_evaluation_success,
        "num_contamination_adjusted_success": total_contamination_adjusted_success,
    }


def format_judge_context(summary: dict[str, Any], output_dir: Path) -> str:
    """Return a compact context string for an optional external/LLM judge."""

    artifacts = summary.get("artifacts", {})
    steps = read_jsonl(Path(artifacts.get("step_trace") or output_dir / "step_trace.jsonl"))[-10:]
    response = _safe_read_json(Path(artifacts.get("agent_response") or output_dir / "agent_response.json"))
    diagnostic = diagnose_run_summary(summary, output_dir)
    payload = {
        "instruction": "Explain why the official evaluator likely failed. Do not override official_success.",
        "task_id": summary.get("task_id"),
        "intent": summary.get("intent"),
        "site": summary.get("site"),
        "h": summary.get("h"),
        "k": summary.get("k"),
        "official_success": summary.get("official_success"),
        "official_score": summary.get("official_score"),
        "heuristic_diagnostic": diagnostic,
        "agent_response": response,
        "recent_steps": steps,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def call_ollama_diagnostic_judge(
    *,
    summary: dict[str, Any],
    output_dir: Path,
    model_name: str,
    base_url: str = "http://localhost:11434",
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Ask a local LLM for an explanatory diagnosis, never a benchmark score."""

    system_prompt = (
        "You are a diagnostic judge for WebArena-Verified H/k agent runs. "
        "Do not replace or reinterpret official_success. Explain likely failure "
        "causes from the trace. Return JSON only with keys: judge_completion, "
        "judge_failure_category, judge_failure_reason, judge_recommended_fix. "
        "judge_completion is a 0..1 near-miss estimate, not benchmark success."
    )
    user_prompt = format_judge_context(summary, output_dir)
    payload = {
        "model": model_name,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": 0.0,
            "num_predict": 500,
        },
    }
    req = Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except URLError as exc:
        raise RuntimeError(f"Ollama judge is not reachable at {base_url}: {exc}") from exc
    decoded = json.loads(raw)
    content = decoded.get("message", {}).get("content", "")
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Diagnostic judge did not return JSON: {content[:500]!r}")
    data = json.loads(content[start : end + 1])
    return {
        "judge_completion": data.get("judge_completion"),
        "judge_failure_category": data.get("judge_failure_category"),
        "judge_failure_reason": data.get("judge_failure_reason"),
        "judge_recommended_fix": data.get("judge_recommended_fix"),
    }
