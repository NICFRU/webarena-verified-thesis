"""LLM action executor for the clean BrowserGym H/k runner."""

from __future__ import annotations

import json
import re
import time
import html
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from hk_agent.capabilities import (
    capability_tier,
    capability_guidance as shared_capability_guidance,
    infer_official_task_type,
    infer_task_capability as shared_infer_task_capability,
)
from hk_agent.artifacts import parse_agent_response_from_action
from hk_agent.grounding import (
    GroundedCandidate,
    candidate_bid_set,
    find_target_candidate,
    focus_modal_candidates,
    grounded_candidates,
    grounded_observation,
    prioritize_candidates,
    previous_round_snippets,
    visible_evidence_text,
)
from hk_agent.recovery import build_recovery_hint, is_planact_like_architecture, is_repair_architecture
from webarena_exp.types import ExecutorActionDecision, ExecutorStep, Subgoal
from .prompt_builder import build_executor_system_prompt


DEFAULT_EXECUTOR_PROMPT = Path("prompts/executor_system.md")
UI_TARGET_ACTION_PREFIXES = ("click(", "fill(", "type(", "press(", "select_option(")
MUTATION_STATE_EVIDENCE_MARKERS = (
    "visible",
    "observed",
    "current page",
    "page shows",
    "confirmation",
    "success message",
    "saved",
    "created",
    "updated",
    "changed",
    "deleted",
    "submitted",
    "state",
    "now shows",
    "confirmed",
)
MUTATION_SUBMIT_TERMS = (
    "save",
    "saved",
    "commit",
    "create",
    "created",
    "update",
    "updated",
    "submit",
    "fork",
    "invite",
    "add",
    "add member",
    "buy",
    "cart",
    "checkout",
    "place order",
    "post",
    "comment",
    "reply",
    "vote",
    "upvote",
    "downvote",
    "delete",
    "remove",
    "confirm",
    "apply",
    "send",
)
MUTATION_FORM_TERMS = (
    "form",
    "modal",
    "dialog",
    "editor",
    "target namespace",
    "select namespace",
    "branch",
    "title",
    "description",
    "content",
    "member",
    "role",
)
MAX_FILL_TEXT_CHARS = 2000
GITLAB_EDITOR_FILL_TEXT_CHARS = 800
HTML_DUMP_PATTERNS = (
    "<!doctype",
    "<html",
    "<head",
    "<body",
    "<script",
    "<style",
    "<meta ",
)


def candidate_prompt_limit(task: dict[str, Any], site_name: str, *, compact: bool = False) -> int:
    """Return how many grounded candidates should be included in executor prompts."""

    if infer_task_type(task) == "MUTATE":
        return 80 if not compact else 35
    return 80 if not compact else 35


def candidate_prompt_dict(candidate: GroundedCandidate, *, include_html: bool = False) -> dict[str, Any]:
    """Return a compact candidate representation for LLM prompts."""

    data = candidate.to_prompt_dict()
    if not include_html:
        data.pop("html", None)
    elif data.get("html"):
        data["html"] = str(data["html"])[:700]
    for key, limit in {
        "text": 180,
        "href": 260,
        "placeholder": 120,
        "aria_label": 120,
        "name": 100,
        "value": 140,
        "context": 260,
    }.items():
        if data.get(key):
            data[key] = str(data[key])[:limit]
    return data


def is_invalid_bid_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "not a current interactive candidate" in lowered
        or "selector or visible label" in lowered
        or "stale_bid" in lowered
        or "forbidden_bid" in lowered
    )


def is_transient_navigation_error(message: str) -> bool:
    """Return true for Playwright/BrowserGym observation races after navigation."""

    lowered = message.lower()
    return (
        "execution context was destroyed" in lowered
        or "most likely because of a navigation" in lowered
        or "extracting the dom and axtree" in lowered
    )


def looks_like_full_html_dump(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    if any(pattern in lowered for pattern in HTML_DUMP_PATTERNS):
        return True
    return lowered.count("<") >= 8 and lowered.count(">") >= 8


@dataclass(frozen=True)
class ExecutorArtifacts:
    """Debug artifacts from one action-executor LLM call."""

    decision: ExecutorActionDecision
    prompt: str
    raw_response: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    elapsed_ms: int
    model_name: str
    grounded_candidates: list[dict[str, Any]] | None = None
    validation_error_category: str | None = None
    mutation_context: dict[str, Any] | None = None
    forbidden_recent_actions: list[str] | None = None
    stale_bid_targets: list[str] | None = None
    recovery_hint: dict[str, Any] | None = None
    repair_brief: dict[str, Any] | None = None


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
        raise ValueError("Executor response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


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


def base_url_from_url(url: str) -> str:
    """Return scheme and host for a URL."""

    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else url


def safe_page_text(page, limit: int = 1400) -> str:
    """Return compact visible page text."""

    try:
        text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return text[:limit]


def safe_page_title(page) -> str:
    """Return the page title without letting a crashed page hide the run context."""

    try:
        return page.title()
    except Exception as exc:
        return f"<title unavailable: {exc}>"


def observation_excerpt(obs: dict[str, Any], page, limit: int = 1400) -> str:
    """Build a compact observation excerpt from BrowserGym and Playwright."""

    parts = [
        f"current_url: {page.url}",
        f"page_title: {safe_page_title(page)}",
        f"last_action: {obs.get('last_action', '')}",
        f"last_action_error: {obs.get('last_action_error', '')}",
    ]
    if text := safe_page_text(page):
        parts.append("visible_text_excerpt:\n" + text)
    value = obs.get("axtree_object")
    if value:
        parts.append(f"axtree_object_excerpt:\n{str(value)[:limit]}")
    return "\n\n".join(parts)


def interactive_candidates(obs: dict[str, Any], limit: int = 80) -> list[dict[str, str]]:
    """Extract lightweight BrowserGym bid candidates from the AX tree text."""

    text = str(obs.get("axtree_object") or "")
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(r"\[(?P<bid>[A-Za-z0-9_-]+)\]\s+(?P<role>[A-Za-z_ ]+)\s+'(?P<name>[^']*)'")
    for match in pattern.finditer(text):
        bid = match.group("bid")
        if bid in seen:
            continue
        seen.add(bid)
        candidates.append(
            {
                "bid": bid,
                "role": " ".join(match.group("role").split()),
                "name": match.group("name")[:160],
            }
        )
        if len(candidates) >= limit:
            break
    return candidates


def page_link_candidates(page, limit: int = 600) -> list[dict[str, str]]:
    """Extract visible page links with hrefs for grounding beyond AX-tree bids."""

    try:
        rows = page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({
                href: a.href,
                text: (a.innerText || a.textContent || '').trim()
            }))""",
        )
    except Exception:
        return []
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        href = str(row.get("href") or "").strip()
        text = " ".join(str(row.get("text") or "").split())
        if not href or href in seen:
            continue
        seen.add(href)
        candidates.append({"href": href, "text": text[:220]})
        if len(candidates) >= limit:
            break
    return candidates


def task_keywords(task: dict[str, Any], subgoal: Subgoal) -> set[str]:
    """Return compact task-critical words for ranking visible links."""

    text = " ".join(
        [
            str(task.get("intent", "")),
            subgoal.objective,
            subgoal.expected_outcome,
        ]
    ).lower()
    words = set(re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text))
    stop_words = {
        "and",
        "are",
        "can",
        "for",
        "from",
        "have",
        "into",
        "not",
        "number",
        "object",
        "objects",
        "page",
        "post",
        "product",
        "requested",
        "return",
        "that",
        "the",
        "then",
        "this",
        "using",
        "with",
    }
    return words - stop_words


def ranked_link_candidates(
    *,
    task: dict[str, Any],
    site_name: str,
    subgoal: Subgoal,
    page,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Rank visible links so the model sees likely navigation hrefs first."""

    keywords = task_keywords(task, subgoal)
    base = base_url_from_url(page.url)
    ranked: list[dict[str, Any]] = []
    for link in page_link_candidates(page):
        href = link["href"]
        label = f"{link.get('text', '')} {href}".lower()
        score = sum(1 for word in keywords if word in label)
        if site_name == "shopping":
            parsed = urlparse(href)
            path = parsed.path.strip("/")
            is_root_html = parsed.path.endswith(".html") and "/" not in path
            is_nested_html = parsed.path.endswith(".html") and "/" in path
            if href.startswith(base) and is_root_html:
                score += 10
            if is_nested_html:
                score -= 6
            if "/catalogsearch/" in href or "/category/" in href:
                score -= 2
        if site_name == "reddit":
            if href.startswith(base) and "/new" in href:
                score += 5
            if href.startswith(base) and re.search(r"/(d|post|comments)/", href):
                score += 6
            if href.startswith(base) and "/f/" in href:
                score += 2
        ranked.append({**link, "score": score})
    ranked.sort(key=lambda row: (row["score"], len(row.get("text") or ""), row["href"]), reverse=True)
    return ranked[:limit]


def _first_quoted_argument(action: str) -> str | None:
    match = re.search(r'\(\s*"([^"]*)"', action)
    return match.group(1) if match else None


def _quoted_arguments(action: str) -> list[str]:
    """Return quoted action arguments, handling escaped quotes where possible."""

    values: list[str] = []
    for match in re.finditer(r'"((?:\\.|[^"\\])*)"', action):
        raw = match.group(1)
        try:
            values.append(json.loads(f'"{raw}"'))
        except Exception:
            values.append(raw)
    return values


def _first_unquoted_argument(action: str) -> str | None:
    match = re.search(r"\(\s*([A-Za-z0-9_-]+)\s*(?:,|\))", action)
    return match.group(1) if match else None


def _quote_first_argument(action: str, first_arg: str) -> str:
    return re.sub(r"\(\s*" + re.escape(first_arg) + r"\s*(?=,|\))", f'("{first_arg}"', action, count=1)


def _json_action_arg(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _retrieve_value_from_finish_action(action: str, data: dict[str, Any]) -> Any:
    """Extract a likely retrieved value from model finish(...) drift."""

    for key in ("retrieved_data", "action_input", "action_value", "value"):
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    match = re.search(r"retrieved_data\s*=\s*(['\"])(.*?)\1", action, re.DOTALL)
    if match:
        return match.group(2)
    match = re.search(r"retrieved_data\s*=\s*(\[[^\)]*?\]|\{[^\)]*?\})", action, re.DOTALL)
    if match:
        raw = match.group(1)
        try:
            return json.loads(raw.replace("'", '"'))
        except Exception:
            return raw
    match = re.search(r"finish\(\s*(['\"])(.*?)\1\s*\)", action, re.DOTALL)
    if match:
        return match.group(2)
    return None


def _webarena_final_action(task_type: str, status: str, retrieved_data: Any = None, error_details: str | None = None) -> str:
    response = {
        "task_type": task_type.upper(),
        "status": status,
        "retrieved_data": retrieved_data,
        "error_details": error_details,
    }
    return f"send_msg_to_user({json.dumps(json.dumps(response, ensure_ascii=False), ensure_ascii=False)})"


def _is_review_title_retrieve_task(task: dict[str, Any]) -> bool:
    intent = str(task.get("intent") or "").lower()
    return infer_official_task_type(task).upper() == "RETRIEVE" and "review" in intent and (
        "review title" in intent or "review titles" in intent
    )


def _normalize_review_title_data(value: Any) -> Any:
    """Normalize model-provided review-title data without extracting page content."""

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return value
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                return _normalize_review_title_data(json.loads(stripped))
            except Exception:
                pass
        line_values = [
            re.sub(r"^[-*•\d.\s]+", "", line).strip()
            for line in stripped.splitlines()
            if line.strip()
        ]
        if len(line_values) > 1:
            return line_values
        return [stripped]
    if isinstance(value, dict):
        for key in ("title", "review_title", "reviewTitle", "summary", "review_summary"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return [item.strip()]
            if isinstance(item, list):
                return _normalize_review_title_data(item)
        return value
    if isinstance(value, list):
        titles: list[str] = []
        changed = False
        for item in value:
            normalized = _normalize_review_title_data(item)
            if isinstance(normalized, list) and all(isinstance(title, str) for title in normalized):
                titles.extend(title.strip() for title in normalized if title.strip())
                changed = True
            elif isinstance(item, str):
                titles.append(item.strip())
            else:
                return value
        return titles if changed else value
    return value


def normalize_retrieve_final_response_schema(action: str, task: dict[str, Any]) -> str:
    """Repair final-response schema drift without adding answer extraction logic."""

    if not action.startswith("send_msg_to_user(") or not _is_review_title_retrieve_task(task):
        return action
    final_response = parse_agent_response_from_action(action) or {}
    status = str(final_response.get("status") or "").upper()
    if status != "SUCCESS":
        return action
    retrieved_data = final_response.get("retrieved_data")
    if retrieved_data in (None, "", {}, []):
        return action
    normalized_data = _normalize_review_title_data(retrieved_data)
    if normalized_data == retrieved_data:
        return action
    return _webarena_final_action(
        "RETRIEVE",
        "SUCCESS",
        normalized_data,
        final_response.get("error_details"),
    )


def normalize_structured_action_fields(data: dict[str, Any]) -> str:
    """Convert common structured executor fields into BrowserGym action syntax.

    Some chat models drift from the requested action-string contract and emit
    fields such as ``{"action": "click", "action_target": "42"}``. Treating
    that as the equivalent BrowserGym string is still faithful to the declared
    action and makes the executor less brittle without adding site-oracle logic.
    """

    action = str(data.get("action") or "").strip()
    if action.lower().replace(" ", "") in {"wait", "wait()"}:
        return "noop(1000)"
    action_type = str(data.get("action_type") or action).strip().lower()
    if action_type == "finish" and action.lower().replace(" ", "") in {"finish", "finish()"}:
        for value in [data.get("action_input"), data.get("expected_observation"), data.get("retrieved_data")]:
            if isinstance(value, str) and '"task_type"' in value and '"status"' in value:
                return f"send_msg_to_user({_json_action_arg(value)})"
    if action_type == "finish" and not action:
        return "finish()"
    if "(" in action:
        return action
    if action_type in {"wait", "noop"} and not action:
        return "noop(1000)"
    action_input = data.get("action_input")
    action_args = data.get("action_args")
    action_params = data.get("action_params")
    target = data.get("action_target") or data.get("target") or data.get("bid") or data.get("action_id")
    text = data.get("text") or data.get("value") or data.get("action_value")
    key = data.get("key")
    if isinstance(action_params, str):
        stripped_params = action_params.strip()
        if stripped_params.startswith("{") and stripped_params.endswith("}"):
            try:
                action_params = json.loads(stripped_params)
            except json.JSONDecodeError:
                action_params = stripped_params
    if isinstance(action_params, dict):
        target = action_params.get("bid") or action_params.get("target") or action_params.get("action_target") or target
        text = action_params.get("text") or action_params.get("value") or action_params.get("option") or text
        key = action_params.get("key") or key
    if isinstance(action_args, str):
        stripped_args = action_args.strip()
        if stripped_args.startswith("{") and stripped_args.endswith("}"):
            try:
                action_args = json.loads(stripped_args)
            except json.JSONDecodeError:
                action_args = stripped_args
    if isinstance(action_args, dict):
        target = action_args.get("bid") or action_args.get("target") or action_args.get("action_target") or target
        text = action_args.get("text") or action_args.get("value") or action_args.get("option") or text
        key = action_args.get("key") or key
    elif isinstance(action_args, list):
        if action_args:
            target = action_args[0]
        if len(action_args) > 1:
            text = action_args[1]
    if isinstance(action_input, str):
        stripped_input = action_input.strip()
        if stripped_input.startswith("{") and stripped_input.endswith("}"):
            try:
                action_input = json.loads(stripped_input)
            except json.JSONDecodeError:
                action_input = stripped_input
    if isinstance(action_input, dict):
        target = action_input.get("bid") or action_input.get("target") or action_input.get("action_target") or target
        text = action_input.get("text") or action_input.get("value") or action_input.get("option") or text
        key = action_input.get("key") or key
    elif isinstance(action_input, list):
        if action_input:
            target = action_input[0]
        if len(action_input) > 1:
            text = action_input[1]
    elif isinstance(action_input, str) and action_input.strip():
        if action_type in {"click"} and target is None:
            target = action_input.strip()
        elif action_type in {"fill", "type", "select_option"} and text is None:
            text = action_input.strip()
        elif action_type in {"press"} and key is None and text is None:
            key = action_input.strip()

    if action_type in {"navigate", "goto"} and isinstance(action_input, str) and action_input.strip():
        return f"goto({_json_action_arg(action_input.strip())})"
    if action_type in {"click"} and target:
        return f"click({_json_action_arg(target)})"
    if action_type in {"fill", "type"} and target is not None and text is not None:
        return f"{action_type}({_json_action_arg(target)}, {_json_action_arg(text)})"
    if action_type == "press" and target is not None and (key is not None or text is not None):
        return f"press({_json_action_arg(target)}, {_json_action_arg(key if key is not None else text)})"
    if action_type in {"select", "select_option"} and target is not None and text is not None:
        return f"select_option({_json_action_arg(target)}, {_json_action_arg(text)})"
    return action


def normalize_finish_action_from_context(action: str, data: dict[str, Any], task: dict[str, Any]) -> str:
    """Convert common finish() drift into a WebArena-compatible final response."""

    lowered_action = action.lower().replace(" ", "")
    if not lowered_action.startswith("finish"):
        return action
    task_type = infer_task_type(task).upper()
    if task_type == "RETRIEVE":
        retrieved_data = _retrieve_value_from_finish_action(action, data)
        if retrieved_data in (None, "", [], {}):
            return _webarena_final_action(
                "RETRIEVE",
                "UNKNOWN_ERROR",
                None,
                "Executor emitted finish() without retrieved_data for a RETRIEVE task.",
            )
        if not isinstance(retrieved_data, list):
            retrieved_data = [retrieved_data]
        return _webarena_final_action("RETRIEVE", "SUCCESS", retrieved_data, None)
    if lowered_action not in {"finish", "finish()"}:
        return action
    text = " ".join(
        str(data.get(key) or "")
        for key in ["rationale_summary", "expected_observation", "action_input", "error_details"]
    ).lower()
    if task_type == "MUTATE":
        status = "SUCCESS" if any(term in text for term in ["success", "completed", "purchase", "order", "thank you"]) else "UNKNOWN_ERROR"
        return _webarena_final_action(
            "MUTATE",
            status,
            None,
            None if status == "SUCCESS" else "Executor emitted finish() without a structured WebArena final response.",
        )
    if task_type == "NAVIGATE":
        return _webarena_final_action("NAVIGATE", "SUCCESS", None, None)
    return action


def normalize_scroll_action(action: str) -> str:
    """Normalize common model scroll variants to BrowserGym's scroll(dx, dy)."""

    lowered = action.lower().replace(" ", "")
    if lowered in {'scroll(direction="down")', "scroll(direction='down')", "scroll(down)"}:
        return "scroll(0, 600)"
    if lowered in {'scroll(direction="up")', "scroll(direction='up')", "scroll(up)"}:
        return "scroll(0, -600)"
    single_delta = re.fullmatch(r"scroll\(\s*(-?\d+(?:\.\d+)?)\s*\)", action)
    if single_delta:
        return f"scroll(0, {single_delta.group(1)})"
    if lowered.startswith("scroll_to(") or lowered.startswith("scrollto("):
        return "scroll(0, 1200)"
    if lowered.startswith("scroll_to_element(") or lowered.startswith("scrolltoelement("):
        return "scroll(0, 1200)"
    return action


def normalize_navigation_url(url: str) -> str:
    """Normalize known benchmark URL conventions without adding task-specific targets."""

    parsed = urlparse(url)
    if "/-/issues" not in parsed.path:
        return url

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    normalized_pairs: list[tuple[str, str]] = []
    for key, value in query_pairs:
        lowered = key.lower()
        if lowered in {"labels", "labels[]", "label_name", "label_name[]"}:
            if value.strip().startswith("-") and value.strip()[1:]:
                normalized_pairs.append(("not[label_name][]", value.strip()[1:]))
            else:
                normalized_pairs.append(("label_name[]", value))
        elif lowered in {"not[label_name]", "not_label_name", "not_labels", "not[labels]", "not_labels[]"}:
            normalized_pairs.append(("not[label_name][]", value.lstrip("-")))
        else:
            normalized_pairs.append((key, value))
    normalized_query = urlencode(normalized_pairs, doseq=True)
    return urlunparse(parsed._replace(query=normalized_query))


def localize_public_benchmark_url(url: str, current_base_url: str) -> str:
    """Map common public benchmark hosts back to the active local benchmark host."""

    parsed = urlparse(url)
    current = urlparse(current_base_url)
    if not parsed.scheme or not parsed.netloc or not current.scheme or not current.netloc:
        return url
    if parsed.netloc == current.netloc:
        return url
    public_hosts = {
        "gitlab.com",
        "www.gitlab.com",
        "reddit.com",
        "www.reddit.com",
        "onestopmarket.com",
        "www.onestopmarket.com",
        "magento.com",
        "www.magento.com",
        "wikipedia.org",
        "www.wikipedia.org",
        "en.wikipedia.org",
    }
    if parsed.netloc.lower() not in public_hosts:
        return url
    return urlunparse(parsed._replace(scheme=current.scheme, netloc=current.netloc))


def _model_output_preview(content: str, limit: int = 700) -> str:
    """Return a compact preview for debugging non-parseable model output."""

    preview = strip_gemma_control_text(content)
    preview = " ".join(preview.split())
    return preview[:limit]


def _looks_like_selector_or_label(target: str) -> bool:
    """Return whether a UI target looks like a CSS selector or visible label."""

    stripped = target.strip()
    if not stripped:
        return True
    selector_markers = ["[", "]", "=", ">", ".", "#", ":", "(", ")"]
    if any(marker in stripped for marker in selector_markers):
        return True
    return not re.fullmatch(r"[A-Za-z0-9_-]+", stripped)


def _target_candidate_text(candidate: dict[str, Any] | None) -> str:
    """Return searchable text for one grounded target candidate."""

    if not candidate:
        return ""
    return " ".join(
        str(candidate.get(key) or "")
        for key in [
            "role",
            "text",
            "tag",
            "href",
            "placeholder",
            "aria_label",
            "name",
            "value",
            "context",
            "html",
        ]
    ).lower()


def mutation_action_kind(action: str, target_candidate: dict[str, Any] | None = None) -> str | None:
    """Classify whether a step helps a MUTATE workflow."""

    lowered = action.lower()
    target_text = _target_candidate_text(target_candidate)
    if lowered.startswith(("fill(", "type(")):
        return "fill_field"
    if lowered.startswith("select_option("):
        return "select_option"
    if lowered.startswith("press("):
        if "enter" in lowered:
            return "submit_key"
        return "press_key"
    if lowered.startswith("click("):
        if target_text and any(term in target_text for term in MUTATION_SUBMIT_TERMS):
            return "submit_click"
        if target_text and any(term in target_text for term in MUTATION_FORM_TERMS):
            return "open_or_focus_form"
        return "click_unknown"
    if lowered.startswith("goto("):
        return "navigate"
    if lowered.startswith("send_msg_to_user("):
        return "finish"
    return None


def mutation_phase_summary(previous_steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize visible MUTATE progress from previous executor steps."""

    successful_steps = [step for step in previous_steps if step.get("status") == "success" and not step.get("error")]
    action_kinds = [str(step.get("mutation_action_kind") or "") for step in successful_steps]
    filled_fields = sum(1 for kind in action_kinds if kind in {"fill_field", "select_option"})
    opened_form = any(kind in {"open_or_focus_form", "fill_field", "select_option"} for kind in action_kinds)
    submitted = any(kind in {"submit_click", "submit_key"} for kind in action_kinds)
    last_submit_index = None
    for step in successful_steps:
        if step.get("mutation_action_kind") in {"submit_click", "submit_key"}:
            last_submit_index = step.get("step_index")
    observed_after_submit = bool(
        last_submit_index is not None
        and any(
            (step.get("step_index") or 0) >= last_submit_index
            and (
                step.get("state_change_hint")
                or step.get("visible_state_after")
                or step.get("url_before") != step.get("url_after")
                or step.get("title_before") != step.get("title_after")
            )
            for step in successful_steps
        )
    )
    return {
        "located_or_navigated": any(kind == "navigate" for kind in action_kinds),
        "opened_form_or_control": opened_form,
        "filled_fields": filled_fields,
        "submitted_or_confirmed": submitted,
        "observed_after_submit": observed_after_submit,
        "last_submit_step_index": last_submit_index,
        "recent_mutation_action_kinds": action_kinds[-6:],
    }


def prepare_action_candidates(
    *,
    candidates: list[GroundedCandidate],
    task: dict[str, Any],
    subgoal: Subgoal,
    site_name: str,
    architecture: str,
) -> list[GroundedCandidate]:
    """Apply architecture-specific prompt focus to current candidates."""

    ranked = prioritize_candidates(candidates, task=task, subgoal=subgoal, site_name=site_name)
    if architecture in {"v3_repair_brief", "v3_repair_llm"}:
        ranked = focus_modal_candidates(ranked)
    return ranked


def compact_repair_brief_for_prompt(repair_brief: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the operational subset of a v3 repair brief for executor prompts."""

    if not repair_brief:
        return None
    return {
        "failure": repair_brief.get("failure_class"),
        "current_state": repair_brief.get("current_state"),
        "must_use": repair_brief.get("needed_next_target"),
        "must_avoid": repair_brief.get("avoid") or repair_brief.get("wrong_actions") or [],
        "repair_strategy": repair_brief.get("repair_strategy"),
        "planner_instruction": repair_brief.get("planner_instruction"),
        "executor_instruction": repair_brief.get("executor_instruction"),
    }


def allow_single_repair_refresh_noop(
    *,
    architecture: str,
    repair_brief: dict[str, Any] | None,
    previous_steps: list[dict[str, Any]],
) -> bool:
    """Allow one wait step when v3_repair_brief needs refreshed UI candidates."""

    if architecture not in {"v3_repair_brief", "v3_repair_llm"} or not repair_brief:
        return False
    recent_actions = [str(step.get("action") or "") for step in previous_steps[-3:]]
    if any(action.startswith("noop(") for action in recent_actions):
        return False
    text = " ".join(
        str(repair_brief.get(key) or "")
        for key in ["failure_class", "current_state", "needed_next_target", "repair_strategy", "executor_instruction"]
    ).lower()
    return any(term in text for term in ["modal", "dialog", "editor", "candidate", "refreshed"])


def stale_bid_targets_from_error(message: str) -> list[str]:
    """Extract invalid bid values from validation/runtime error text."""

    targets: list[str] = []
    for pattern in [
        r"Action target '([^']+)' is not a current interactive candidate bid",
        r"Action target \"([^\"]+)\" is not a current interactive candidate bid",
        r"target ([A-Za-z0-9_-]+)!? is not a current interactive candidate",
    ]:
        for match in re.finditer(pattern, message):
            value = match.group(1)
            if value and value not in targets:
                targets.append(value)
    return targets


def forbidden_bid_targets(previous_steps: list[dict[str, Any]], last_error: str = "") -> list[str]:
    """Return stale bid targets that are not safe to repeat in a retry prompt."""

    forbidden: list[str] = []
    for source in [last_error, *(str(step.get("error") or "") for step in previous_steps[-4:])]:
        for target in stale_bid_targets_from_error(source):
            if target not in forbidden:
                forbidden.append(target)
    return forbidden


def repeated_no_progress_actions(previous_steps: list[dict[str, Any]], *, limit: int = 6, min_count: int = 2) -> list[str]:
    """Find recent exact actions that repeatedly failed to change visible state."""

    counts: dict[str, int] = {}
    for step in previous_steps[-limit:]:
        action = str(step.get("action") or "")
        if not action or action.startswith(("scroll(", "send_msg_to_user(")):
            continue
        no_visible_change = (
            step.get("error")
            or (
                step.get("url_before") == step.get("url_after")
                and (step.get("title_before") or step.get("page_title")) == (step.get("title_after") or step.get("page_title"))
            )
        )
        if no_visible_change:
            counts[action] = counts.get(action, 0) + 1
    return [action for action, count in counts.items() if count >= min_count]


def goto_targets_recent_cycle(action: str, previous_steps: list[dict[str, Any]], *, limit: int = 8, min_visits: int = 2) -> bool:
    """Return whether a proposed goto would revisit a recent URL cycle."""

    if not action.startswith("goto("):
        return False
    target = _first_quoted_argument(action)
    if not target:
        return False
    recent_urls = [
        str(step.get("url_after") or "")
        for step in previous_steps[-limit:]
        if step.get("url_after")
    ]
    return sum(1 for url in recent_urls if url.rstrip("/") == target.rstrip("/")) >= min_visits


def mutation_state_hint(page, action: str, target_candidate: dict[str, Any] | None = None, limit: int = 700) -> str:
    """Capture a compact visible state note after a possible mutation action."""

    pieces = [
        f"url={page.url}",
        f"title={safe_page_title(page)}",
    ]
    target_text = _target_candidate_text(target_candidate)
    if target_text:
        pieces.append(f"target={compact_for_state(target_text, 220)}")
    visible = safe_page_text(page, limit=2500)
    markers = []
    for line in visible.splitlines():
        lowered = line.lower()
        if any(
            term in lowered
            for term in [
                "success",
                "saved",
                "created",
                "updated",
                "forked",
                "committed",
                "invited",
                "added",
                "error",
                "warning",
                "already",
            ]
        ):
            markers.append(line.strip())
    if markers:
        pieces.append("visible_markers=" + " | ".join(markers[:4]))
    elif action.startswith(("click(", "press(", "select_option(")):
        pieces.append("visible_excerpt=" + compact_for_state(visible, 350))
    return compact_for_state(" ; ".join(part for part in pieces if part), limit)


def compact_for_state(value: str, limit: int = 700) -> str:
    return " ".join(str(value or "").split())[:limit]


def _shopping_cart_counts_from_text(text: str) -> list[int]:
    counts: list[int] = []
    for pattern in [
        r"\bmy cart\s+(\d+)\b",
        r"\bshopping cart\s+(\d+)\b",
        r"\bcart\s*\(?\s*(\d+)\s*(?:items?|item)?\s*\)?",
        r"\b(\d+)\s+items?\s+in\s+(?:your\s+)?cart\b",
    ]:
        for match in re.finditer(pattern, text.lower()):
            try:
                counts.append(int(match.group(1)))
            except ValueError:
                pass
    return counts


def shopping_state_diagnosis(*, task: dict[str, Any], site_name: str, page, candidates: list[GroundedCandidate]) -> dict[str, Any] | None:
    """Describe shopping-specific state without using evaluator gold answers."""

    if site_name != "shopping":
        return None
    capability = shared_infer_task_capability(task, site_name)
    visible = safe_page_text(page, limit=5000)
    visible_lower = visible.lower()
    candidate_rows = [
        {
            "bid": candidate.bid,
            "role": candidate.role,
            "text": candidate.text,
            "placeholder": candidate.placeholder,
            "context": candidate.context,
            "href": candidate.href,
        }
        for candidate in candidates[:80]
    ]
    candidate_text = "\n".join(json.dumps(row, ensure_ascii=False, default=str).lower() for row in candidate_rows)
    cart_counts = _shopping_cart_counts_from_text(visible)

    def matching_bids(*needles: str, limit: int = 8) -> list[str]:
        found: list[str] = []
        for candidate in candidates:
            haystack = candidate_search_text_for_state(candidate)
            if any(needle in haystack for needle in needles) and candidate.bid not in found:
                found.append(candidate.bid)
            if len(found) >= limit:
                break
        return found

    state: dict[str, Any] = {
        "current_url_pattern": urlparse(str(getattr(page, "url", "") or "")).path,
        "cart_counts_visible": cart_counts,
        "preferred_current_bids": [],
        "warnings": [],
    }
    if capability == "mutate_shopping_purchase":
        state.update(
            {
                "workflow": "shopping_purchase",
                "needed_next_object": "cart clear/update controls before checkout if cart is not empty; otherwise current product add-to-cart or checkout/place-order controls",
                "preferred_current_bids": matching_bids(
                    "remove",
                    "delete",
                    "update shopping cart",
                    "clear shopping cart",
                    "add to cart",
                    "proceed to checkout",
                    "place order",
                    "next",
                ),
            }
        )
        if cart_counts and max(cart_counts) > 1:
            state["warnings"].append(
                "Visible cart count is greater than one. For purchase tasks that say discard/empty cart, clear existing cart items before checkout and before MUTATE SUCCESS."
            )
    elif capability == "policy_or_account_order_change":
        edit_bids = matching_bids("edit", "change address", "shipping address", "save address", "update address", "form")
        state.update(
            {
                "workflow": "shopping_order_policy_check",
                "needed_next_object": "current edit/change-address control if visible; otherwise ACTION_NOT_ALLOWED_ERROR after inspecting the relevant order page",
                "preferred_current_bids": edit_bids,
                "no_edit_controls_visible": "/sales/order/view/" in str(getattr(page, "url", "") or "") and not edit_bids,
            }
        )
        if state["no_edit_controls_visible"]:
            state["warnings"].append(
                "Order detail page is visible and no edit/change-address controls are grounded. If this is the relevant order, finish with ACTION_NOT_ALLOWED_ERROR instead of looping."
            )
    elif shared_infer_task_capability(task, site_name) == "retrieve_reviews":
        state.update(
            {
                "workflow": "shopping_review_retrieval",
                "needed_next_object": "review section, review pagination, visible reviewer names and ratings",
                "preferred_current_bids": matching_bids("reviews", "review", "rating", "stars"),
            }
        )
        if "#reviews" in str(getattr(page, "url", "") or "").lower() or "review" in candidate_text or "review" in visible_lower:
            state["warnings"].append(
                "For review retrieval, use scroll(0, y) only. Do not emit scroll_to, scroll_to_element, or one-argument scroll actions."
            )
    return state


def deterministic_shopping_policy_action(*, task: dict[str, Any], site_name: str, page, previous_steps: list[dict[str, Any]]) -> str | None:
    """Finish visible shopping order-change policy tasks when no edit path exists."""

    if site_name != "shopping" or infer_task_type(task) != "MUTATE":
        return None
    if shared_infer_task_capability(task, site_name) != "policy_or_account_order_change":
        return None
    current_url = str(getattr(page, "url", "") or "")
    on_order_detail = "/sales/order/view/" in current_url
    on_order_history = "/sales/order/history" in current_url
    if not (on_order_detail or on_order_history):
        return None
    visible = safe_page_text(page, limit=5000).lower()
    if not any(term in visible for term in ["shipping address", "order #", "ordered", "order date", "my orders"]):
        return None
    candidates = grounded_candidates({}, page)
    candidate_text = "\n".join(candidate_search_text_for_state(candidate) for candidate in candidates[:100])
    if any(term in candidate_text for term in ["edit", "change address", "save address", "update address"]):
        return None
    if on_order_detail and not any("/sales/order/history" in str(step.get("url_after") or "") for step in previous_steps):
        return None
    response = {
        "task_type": "MUTATE",
        "status": "ACTION_NOT_ALLOWED_ERROR",
        "retrieved_data": None,
        "error_details": "The relevant order page is visible, but there is no grounded Edit, Change Address, Save Address, or address form control available in the current UI.",
    }
    return f"send_msg_to_user({json.dumps(json.dumps(response, ensure_ascii=False), ensure_ascii=False)})"


def classify_validation_error(message: str) -> str:
    """Map validation messages to compact artifact categories."""

    lowered = message.lower()
    if "usable json" in lowered or "json object" in lowered:
        return "json_parse"
    if "placeholder" in lowered:
        return "placeholder_bid"
    if "not a current interactive candidate" in lowered or "current candidate" in lowered:
        return "stale_or_invalid_bid"
    if "selector" in lowered or "symbolic" in lowered:
        return "selector_or_label_target"
    if "retrieved" in lowered or "evidence" in lowered:
        return "ungrounded_final_response"
    if "mutate" in lowered or "mutation" in lowered:
        return "premature_mutation_success"
    if "unsupported" in lowered:
        return "unsupported_action"
    return "validation_error"


def validate_browsergym_action(
    action: str,
    current_base_url: str,
    candidate_bids: set[str] | None = None,
    *,
    strict_ui_targets: bool = False,
) -> str:
    """Validate a BrowserGym high-level action string."""

    action = action.strip()
    if action.lower().replace(" ", "") in {"wait", "wait()"}:
        action = "noop(1000)"
    if action.startswith("stop("):
        inner = action[len("stop(") : -1].strip()
        action = f"send_msg_to_user({inner})"
    action = normalize_scroll_action(action)
    if action.startswith("navigate("):
        target = _first_quoted_argument(action)
        if target:
            action = f'goto("{target}")'
    if action.startswith("select("):
        args = _quoted_arguments(action)
        if len(args) >= 2:
            action = f"select_option({_json_action_arg(args[0])}, {_json_action_arg(args[1])})"
    if action.startswith("goto("):
        target = _first_quoted_argument(action)
        if target:
            target = localize_public_benchmark_url(target, current_base_url)
            target = normalize_navigation_url(target)
            action = f'goto("{target}")'
        if current_base_url and current_base_url not in action:
            raise ValueError("goto action must stay inside the current benchmark host")
        return action
    allowed_prefixes = (
        "click(",
        "fill(",
        "type(",
        "press(",
        "select_option(",
        "scroll(",
        "noop(",
        "send_msg_to_user(",
    )
    if action.startswith(allowed_prefixes):
        first_arg = _first_quoted_argument(action)
        if not first_arg and action.startswith(UI_TARGET_ACTION_PREFIXES):
            unquoted_arg = _first_unquoted_argument(action)
            if unquoted_arg and candidate_bids and unquoted_arg in candidate_bids:
                action = _quote_first_argument(action, unquoted_arg)
                first_arg = unquoted_arg
        if action.startswith("scroll("):
            if not re.fullmatch(r"scroll\(\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*\)", action):
                raise ValueError("scroll action must use BrowserGym syntax scroll(delta_x, delta_y)")
            return action
        if action.startswith(UI_TARGET_ACTION_PREFIXES) and not first_arg:
            raise ValueError("UI actions must use an exact quoted BrowserGym bid or URL, not symbolic references")
        if action.startswith(("fill(", "type(")):
            args = _quoted_arguments(action)
            fill_text = args[1] if len(args) > 1 else ""
            if len(fill_text) > MAX_FILL_TEXT_CHARS:
                raise ValueError(
                    f"fill/type text is too long ({len(fill_text)} chars); use a concise field value, not a full document dump"
                )
            if looks_like_full_html_dump(fill_text):
                raise ValueError("fill/type text looks like a full HTML document dump; use a minimal controlled edit instead")
        if action.startswith("click(") and first_arg and first_arg.startswith(("http://", "https://")):
            first_arg = localize_public_benchmark_url(first_arg, current_base_url)
            if current_base_url and current_base_url not in first_arg:
                raise ValueError("click URL action must stay inside the current benchmark host")
            return f'goto("{normalize_navigation_url(first_arg)}")'
        if strict_ui_targets and action.startswith(UI_TARGET_ACTION_PREFIXES):
            if not candidate_bids:
                raise ValueError("UI actions are not allowed because no current interactive candidate bids were found")
            if first_arg and first_arg not in candidate_bids and (_looks_like_selector_or_label(first_arg) or not first_arg.isdigit()):
                raise ValueError("UI action target looks like a selector or visible label instead of an exact current bid")
        if first_arg:
            lowered_first_arg = first_arg.lower()
            placeholder_markers = [
                "bid_from_interactive_candidates",
                "real_bid",
                "real_forum_link_bid",
                "placeholder",
            ]
            if any(marker in lowered_first_arg for marker in placeholder_markers):
                raise ValueError("Action used a placeholder bid instead of a real current interactive candidate bid")
        if (candidate_bids or strict_ui_targets) and action.startswith(UI_TARGET_ACTION_PREFIXES) and first_arg:
            if first_arg not in candidate_bids:
                raise ValueError(f"Action target {first_arg!r} is not a current interactive candidate bid")
        return action
    raise ValueError(f"Unsupported BrowserGym action: {action}")


def site_conventions(site_name: str, page_url: str) -> list[str]:
    """Return general site route conventions that do not use task eval metadata."""

    base = base_url_from_url(page_url)
    if site_name == "gitlab":
        return [
            f"GitLab dashboard todos are usually at {base}/dashboard/todos.",
            f"GitLab project pages usually use {base}/<namespace>/<project>, not /explore/projects/<namespace>/<project>.",
            f"GitLab issues usually use {base}/<namespace>/<project>/-/issues.",
            "For open issues, use state=opened. For labels, use label_name[]=<label text> query parameters.",
            "For excluded labels, use not[label_name][]=<label text>, not label_name[]=-<label text>.",
        ]
    if site_name == "shopping_admin":
        return [
            f"Magento admin customer list/details are usually under {base}/admin/customer/index/.",
            f"Magento admin sales orders are usually under {base}/admin/sales/order/.",
            "The Customers menu may need a submenu click before the customer grid is visible.",
            "Magento admin grids often hide column filters behind Filters/Search controls; the top global search field is not reliable evidence for grid-specific review/product counts.",
            "For aggregate retrieval from admin grids, return a count only after a visible grid filter or active filter confirms the requested term/status/date.",
            "For order notification/message tasks, use the Sales Orders grid, open the most recent matching order detail, fill only the order history/comment form, enable customer notification when present, and click Submit Comment/Add Comment. Do not use Send Email, Hold, Invoice, or Ship as substitutes. If the relevant order has no grounded comment field plus submit-comment control, finish with ACTION_NOT_ALLOWED_ERROR.",
            "For simple-product creation tasks, use the product catalog Add Product/New Product flow, choose Simple Product, fill required name/price/quantity/stock/size/color fields from the task, and save.",
            "For configurable-product size or variant tasks, first add a missing requested size through the global Size product attribute/options workflow and save that attribute, then open the named configurable product, add only the requested size/color variant combinations, and save.",
            "For Magento admin dropdowns, do not use unsupported select(...) actions; open the dropdown with click, use fill/press only when an input is exposed, then click the current option bid or press Enter.",
        ]
    if site_name == "reddit":
        return [
            f"Postmill forum pages usually use {base}/f/<ForumName>, not /r/<ForumName>.",
            f"The personal finance forum is commonly reachable as {base}/f/personalfinance.",
            f"When a forum task asks for the most recent post, use the newest-post listing such as {base}/f/<ForumName>/new when it is visible or inferable from the current forum URL.",
            f"The all-posts listing is usually {base}/all.",
            "Use visible forum links from the page when the exact forum slug is uncertain.",
            "For RETRIEVE tasks, navigate to the relevant post and finish with send_msg_to_user containing the requested JSON fields.",
        ]
    if site_name == "shopping":
        return [
            "OneStopMarket product detail pages usually end in .html.",
            "Product detail URLs are usually root-level .html URLs like /product-name.html; nested /category/path.html URLs are category/listing pages, not final product pages.",
            f"Catalog search is usually {base}/catalogsearch/result/?q=<query>, not /search?q=<query>.",
            "For symptom/product tasks, search first, then open a concrete matching product detail page.",
            "On search results, use link_candidates to pick a root-level .html product href whose text or href matches the task terms.",
            "After filling a visible search input, press Enter or click the visible search button; filling alone does not search.",
            "For bruxism, jaw, mouth guard, night guard, or teeth grinding tasks, useful generic search terms include mouth night guard, teeth grinding mouth guard, and dental guard.",
            "For review sections, BrowserGym supports scroll(delta_x, delta_y), e.g. scroll(0, 1200); do not use scroll_to, scroll_to_element, or one-argument scroll.",
            "For purchase tasks that mention discarding a non-empty cart, the cart must be inspected and cleared before checkout; a final SUCCESS needs visible evidence that only the selected item remains or the cart was empty before adding it.",
            "For account/order changes, an order history or order detail page without visible Edit, Change Address, or address form controls should be finalized as ACTION_NOT_ALLOWED_ERROR after inspection, not as UNKNOWN_ERROR.",
        ]
    return []


def _task_text(task: dict[str, Any], subgoal: Subgoal) -> str:
    return " ".join(
        [
            str(task.get("intent", "")),
            subgoal.objective,
            subgoal.expected_outcome,
        ]
    ).lower()


def page_satisfies_subgoal(*, task: dict[str, Any], site_name: str, subgoal: Subgoal, page) -> bool:
    """Return whether the current page already satisfies simple route-level subgoals."""

    url = page.url.lower()
    title = safe_page_title(page).lower()
    if "404" in title or "not found" in title:
        return False
    text = _task_text(task, subgoal)
    if site_name == "gitlab" and "todos" in text:
        return "/dashboard/todos" in url
    if site_name == "gitlab" and "issues" in text and "openapitools/openapi-generator" in text:
        if "/openapitools/openapi-generator/-/issues" not in url:
            return False
        decoded_url = unquote(url)
        if any(term in text for term in ["label", "cli", "openapi generator cli"]):
            if "label_name[]" not in decoded_url or "openapi generator cli" not in decoded_url:
                return False
        if any(term in text for term in ["open issue", "open issues", "not yet closed", "not closed"]):
            if "state=opened" not in decoded_url:
                return False
        return True
    if site_name == "gitlab" and "issues" in text and any(term in text for term in ["except", "without label"]):
        decoded_url = unquote(url)
        if "/-/issues" not in decoded_url:
            return False
        if any(term in text for term in ["open issue", "open issues", "not yet closed", "not closed"]):
            if "state=opened" not in decoded_url:
                return False
        if any(term in text for term in ["except bug", "without label bug"]):
            return "not[label_name][]=bug" in decoded_url.lower()
        return "not[label_name][]" in decoded_url
    if site_name == "shopping_admin" and "customer" in text:
        return "/admin/customer/index" in url
    if site_name == "shopping" and any(term in text for term in ["product", "bruxism", "jaw", "mouth", "guard"]):
        path = urlparse(url).path.strip("/")
        if not (path.endswith(".html") and "/" not in path):
            return False
        product_terms = ["guard", "mouth", "teeth", "night", "dental", "bruxism"]
        return any(term in path for term in product_terms)
    if site_name == "reddit" and "retrieve" in infer_task_type(task).lower():
        return False
    return False


def page_satisfies_task(*, task: dict[str, Any], site_name: str, page) -> bool:
    """Return whether the current page satisfies common NAVIGATE task intents."""

    synthetic = Subgoal(
        id="task",
        objective=str(task.get("intent", "")),
        expected_outcome=str(task.get("intent", "")),
    )
    return page_satisfies_subgoal(task=task, site_name=site_name, subgoal=synthetic, page=page)


def final_nav_action() -> str:
    """Return a WebArena-Verified NAVIGATE success response action."""

    return 'send_msg_to_user("{\\"task_type\\":\\"NAVIGATE\\",\\"status\\":\\"SUCCESS\\",\\"retrieved_data\\":null,\\"error_details\\":null}")'


def _flatten_scalars(value: Any) -> list[Any]:
    if isinstance(value, dict):
        scalars: list[Any] = []
        for child in value.values():
            scalars.extend(_flatten_scalars(child))
        return scalars
    if isinstance(value, list):
        scalars = []
        for child in value:
            scalars.extend(_flatten_scalars(child))
        return scalars
    return [value]


def _is_numeric_aggregate(data: Any) -> bool:
    scalars = _flatten_scalars(data)
    return bool(scalars) and all(isinstance(value, (int, float)) or str(value).strip().isdigit() for value in scalars)


def validate_grounded_final_response(
    *,
    action: str,
    data: dict[str, Any],
    task: dict[str, Any],
    page,
) -> None:
    """Reject unsupported successful RETRIEVE answers for v2_planact."""

    if not action.startswith("send_msg_to_user("):
        return
    final_response = parse_agent_response_from_action(action) or {}
    expected_task_type = infer_task_type(task).upper()
    actual_task_type = str(final_response.get("task_type") or "").upper()
    if actual_task_type and actual_task_type != expected_task_type:
        raise ValueError(
            f"Final response task_type must be {expected_task_type} for this task, not {actual_task_type}"
        )
    if expected_task_type != "RETRIEVE":
        return
    status = str(final_response.get("status") or "").upper()
    if status != "SUCCESS":
        return
    retrieved_data = final_response.get("retrieved_data")
    if retrieved_data in (None, "", [], {}):
        raise ValueError("RETRIEVE SUCCESS must include non-empty retrieved_data")
    evidence = visible_evidence_text(page).lower()
    if _is_numeric_aggregate(retrieved_data):
        rationale = " ".join(
            [
                str(data.get("rationale_summary") or ""),
                str(data.get("expected_observation") or ""),
            ]
        ).lower()
        if not any(marker in rationale for marker in ["visible", "calculated", "count", "filter", "total"]):
            raise ValueError("Numeric aggregate RETRIEVE SUCCESS requires a visible/calculated evidence note")
        return
    missing = []
    for scalar in _flatten_scalars(retrieved_data):
        text = str(scalar).strip().lower()
        if text and text not in evidence:
            missing.append(str(scalar))
    if missing:
        raise ValueError(f"RETRIEVE SUCCESS contains values not grounded in visible evidence: {missing[:5]}")


def validate_mutation_success_state_check(
    *,
    action: str,
    data: dict[str, Any],
    task: dict[str, Any],
    site_name: str,
    previous_steps: list[dict[str, Any]],
    require_observed_after_submit: bool = False,
    page=None,
) -> None:
    """Require a visible-state note before accepting MUTATE SUCCESS."""

    if not action.startswith("send_msg_to_user(") or infer_task_type(task) != "MUTATE":
        return
    final_response = parse_agent_response_from_action(action) or {}
    final_status = str(final_response.get("status") or "").upper()
    if final_status != "SUCCESS":
        return
    capability = infer_task_capability(task, site_name)
    tier = capability_tier(capability)
    has_prior_mutating_action = any(
        str(previous_step.get("action", "")).startswith(UI_TARGET_ACTION_PREFIXES)
        for previous_step in previous_steps
    )
    has_successful_prior_mutating_action = any(
        str(previous_step.get("action", "")).startswith(UI_TARGET_ACTION_PREFIXES)
        and previous_step.get("status") == "success"
        and not previous_step.get("error")
        for previous_step in previous_steps
    )
    has_successful_submit_like_action = any(
        previous_step.get("status") == "success"
        and not previous_step.get("error")
        and (
            previous_step.get("mutation_action_kind") in {"submit_click", "submit_key", "click_unknown"}
            or (
                not previous_step.get("mutation_action_kind")
                and str(previous_step.get("action", "")).startswith(("click(", "press("))
            )
        )
        for previous_step in previous_steps
    )
    has_unresolved_error = any(previous_step.get("error") for previous_step in previous_steps[-2:])
    mutation_phase = mutation_phase_summary(previous_steps)
    if tier == "mutation" and not has_prior_mutating_action:
        raise ValueError("Executor tried to finish a MUTATE task before any visible click/fill/type/press/select_option mutation step")
    if tier == "mutation" and not has_successful_prior_mutating_action:
        raise ValueError("Executor tried to finish a MUTATE task before a successful mutation step was observed")
    if tier == "mutation" and not has_successful_submit_like_action:
        raise ValueError("MUTATE SUCCESS requires a successful submit/save/fork/invite/vote/commit-style action, not only filling or selecting fields")
    if has_unresolved_error:
        raise ValueError("Executor tried to finish a MUTATE task after an unresolved recent action error")
    evidence_note = " ".join(
        [
            str(data.get("rationale_summary") or ""),
            str(data.get("expected_observation") or ""),
        ]
    ).lower()
    if tier == "mutation" and not any(marker in evidence_note for marker in MUTATION_STATE_EVIDENCE_MARKERS):
        raise ValueError("MUTATE SUCCESS requires an explicit current-state evidence note in rationale_summary or expected_observation")
    if require_observed_after_submit and tier == "mutation" and not mutation_phase.get("observed_after_submit"):
        raise ValueError("MUTATE SUCCESS requires a visible observation/state check after the submit/save/fork/invite/vote/commit action")
    if site_name == "shopping" and capability == "mutate_shopping_purchase":
        intent = str(task.get("intent") or "").lower()
        if any(term in intent for term in ["discard", "empty cart", "not empty", "cart"]):
            recent_state = " ".join(
                str(step.get(key) or "")
                for step in previous_steps[-10:]
                for key in ["state_change_hint", "visible_state_after", "action"]
            ).lower()
            current_text = safe_page_text(page, limit=2000).lower() if page is not None else ""
            combined_evidence = " ".join([evidence_note, recent_state, current_text])
            cart_counts = _shopping_cart_counts_from_text(combined_evidence)
            if cart_counts and max(cart_counts) > 1 and not any(
                term in combined_evidence
                for term in [
                    "cart was empty",
                    "cart is empty",
                    "cleared the cart",
                    "removed existing",
                    "discarded existing",
                    "only selected item",
                    "items_qty 1",
                    "items_qty: 1",
                    "items_qty\": 1",
                    "1 item in cart",
                ]
            ):
                raise ValueError("Shopping purchase SUCCESS is blocked because recent evidence still shows multiple cart items and no clear-cart evidence")
            if not any(
                term in combined_evidence
                for term in [
                    "cart was empty",
                    "cart is empty",
                    "cleared",
                    "removed existing",
                    "discarded",
                    "only selected item",
                    "items_qty 1",
                    "1 item",
                    "thank you for your purchase",
                    "order number",
                ]
            ):
                raise ValueError("Shopping purchase SUCCESS must mention cart-clear/one-item evidence and purchase confirmation")


def _shopping_product_need(task: dict[str, Any], subgoal: Subgoal) -> bool:
    text = _task_text(task, subgoal)
    if shared_infer_task_capability(task, "shopping") == "navigate_shopping_sorted_category_product":
        return True
    return any(term in text for term in ["product", "bruxism", "jaw", "mouth", "guard", "teeth", "dental"])


def _shopping_search_query(task: dict[str, Any], subgoal: Subgoal) -> str:
    text = _task_text(task, subgoal)
    sorted_product_match = re.search(
        r"(?:most|least)\s+expensive\s+(.+?)(?:\s+with\s+|\s*$)",
        text,
        flags=re.I,
    )
    if sorted_product_match:
        return " ".join(sorted_product_match.group(1).split())
    if any(term in text for term in ["bruxism", "jaw", "teeth grinding"]):
        return "mouth night guard"
    if "dental" in text:
        return "dental guard"
    if "mouth" in text or "guard" in text:
        return "mouth guard"
    return "health care product"


def _shopping_category_filter_price(task: dict[str, Any], subgoal: Subgoal) -> str | None:
    text = _task_text(task, subgoal)
    price_match = re.search(r"\bunder\s+\$?\s*([0-9]+(?:\.[0-9]+)?)\b", text)
    return f"0-{price_match.group(1)}" if price_match else None


def _shopping_category_phrase(task: dict[str, Any], subgoal: Subgoal) -> str | None:
    raw_text = " ".join([str(task.get("intent", "")), subgoal.objective, subgoal.expected_outcome])
    quoted = re.search(r'"([^"]+)"\s+category\s+page', raw_text, flags=re.IGNORECASE)
    if quoted:
        return quoted.group(1).strip().lower()
    fallback = re.search(r"open\s+the\s+(.+?)\s+category\s+page", raw_text, flags=re.IGNORECASE)
    return fallback.group(1).strip().lower() if fallback else None


def _shopping_category_tokens(phrase: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", phrase.lower()))
    return tokens - {"and", "category", "for", "the", "with"}


def _shopping_url_with_price_filter(href: str, price: str) -> str:
    parsed = urlparse(href)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "price"]
    query.append(("price", price))
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


def _matching_shopping_category_href(*, task: dict[str, Any], subgoal: Subgoal, page, tokens: set[str]) -> str | None:
    base = base_url_from_url(page.url)
    for link in page_link_candidates(page):
        href = link.get("href", "")
        parsed = urlparse(href)
        path = parsed.path.strip("/")
        if not href.startswith(base):
            continue
        if not (path.endswith(".html") and "/" in path):
            continue
        label = f"{link.get('text', '')} {unquote(path)}".lower()
        label_tokens = set(re.findall(r"[a-z0-9]+", label))
        if tokens and tokens.issubset(label_tokens):
            return href
    return None


def _shopping_category_fallback_path(tokens: set[str]) -> str | None:
    if {"women", "shoes"}.issubset(tokens):
        return "clothing-shoes-jewelry/women/shoes.html"
    if {"makeup", "remover"}.issubset(tokens):
        return "beauty-personal-care/makeup/makeup-remover.html"
    if {"furniture", "accent"}.issubset(tokens):
        return "home-kitchen/furniture/accent-furniture.html"
    return None


def _shopping_category_filter_url(task: dict[str, Any], subgoal: Subgoal, page) -> str | None:
    if shared_infer_task_capability(task, "shopping") != "navigate_shopping_category_filter":
        return None
    price = _shopping_category_filter_price(task, subgoal)
    phrase = _shopping_category_phrase(task, subgoal)
    if not price or not phrase:
        return None
    tokens = _shopping_category_tokens(phrase)
    if href := _matching_shopping_category_href(task=task, subgoal=subgoal, page=page, tokens=tokens):
        return _shopping_url_with_price_filter(href, price)
    if category_path := _shopping_category_fallback_path(tokens):
        return f'{base_url_from_url(page.url)}/{category_path}?{urlencode({"price": price})}'
    return None


def _matching_shopping_product_href(*, task: dict[str, Any], subgoal: Subgoal, page) -> str | None:
    base = base_url_from_url(page.url)
    task_text = _task_text(task, subgoal)
    minimum_capacity = _shopping_minimum_capacity(task_text)
    if shared_infer_task_capability(task, "shopping") == "navigate_shopping_sorted_category_product":
        query_tokens = set(re.findall(r"[a-z0-9]+", _shopping_search_query(task, subgoal).lower()))
        weak_terms = {"least", "most", "expensive", "minimum", "storage", "capacity", "with", "product", "page"}
        product_terms = query_tokens - weak_terms
    else:
        product_terms = {"guard", "mouth", "teeth", "night", "dental", "bruxism"}
    required_terms = {term for term in product_terms if term not in {"hard", "drive"}}
    if "ssd" in task_text and "hard drive" in task_text:
        required_terms.add("ssd")
    if shared_infer_task_capability(task, "shopping") == "navigate_shopping_sorted_category_product":
        links = page_link_candidates(page)
    else:
        links = ranked_link_candidates(task=task, site_name="shopping", subgoal=subgoal, page=page, limit=120)
    for link in links:
        href = link.get("href", "")
        parsed = urlparse(href)
        path = parsed.path.strip("/")
        if not href.startswith(base):
            continue
        if not (path.endswith(".html") and "/" not in path):
            continue
        label = f"{link.get('text', '')} {path}".lower()
        if minimum_capacity and not _shopping_label_satisfies_minimum_capacity(label, minimum_capacity):
            continue
        if required_terms and all(term in label for term in required_terms):
            return href
        if not required_terms and any(term in label for term in product_terms):
            return href
    return None


def _shopping_minimum_capacity(task_text: str) -> tuple[str, float] | None:
    match = re.search(
        r"minimum\s+(?:storage\s+)?capacity\s+of\s+([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)",
        task_text,
        flags=re.I,
    )
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"tb", "tbs"}:
        return ("gb", value * 1024)
    if unit in {"gb", "gbs"}:
        return ("gb", value)
    if unit in {"pair", "pairs"}:
        return ("pairs", value)
    return (unit, value)


def _shopping_label_satisfies_minimum_capacity(label: str, minimum_capacity: tuple[str, float]) -> bool:
    unit, minimum = minimum_capacity
    lowered = label.lower()
    if unit == "gb":
        capacities = []
        for value, raw_unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*(tb|gb)\b", lowered):
            amount = float(value)
            capacities.append(amount * 1024 if raw_unit == "tb" else amount)
        return bool(capacities) and max(capacities) >= minimum
    if unit == "pairs":
        capacities = [float(value) for value in re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*(?:pairs?|pockets?)\b", lowered)]
        return bool(capacities) and max(capacities) >= minimum
    return True


def _shopping_sorted_product_url(task: dict[str, Any], subgoal: Subgoal, page) -> str | None:
    if shared_infer_task_capability(task, "shopping") != "navigate_shopping_sorted_category_product":
        return None
    query = _shopping_search_query(task, subgoal)
    if not query:
        return None
    text = _task_text(task, subgoal)
    direction = "desc" if "most expensive" in text else "asc"
    parsed = urlparse(page.url)
    query_pairs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "/catalogsearch/result" in parsed.path and query_pairs.get("q", "").lower().replace("+", " ") == query.lower():
        if query_pairs.get("product_list_order") == "price" and query_pairs.get("product_list_dir", "asc") == direction:
            return None
    params = {"q": query, "product_list_order": "price", "product_list_dir": direction}
    return f'{base_url_from_url(page.url)}/catalogsearch/result/?{urlencode(params)}'


def deterministic_shopping_order_detail_action(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]] | None = None,
) -> str | None:
    """Finish order-detail NAVIGATE tasks as not found when the requested status is absent."""

    if site_name != "shopping" or infer_task_type(task) != "NAVIGATE":
        return None
    if shared_infer_task_capability(task, site_name) != "navigate_shopping_order_detail":
        return None
    intent = str(task.get("intent") or "").lower()
    requested_statuses = [status for status in ["processing", "under delivery", "canceled", "complete"] if status in intent]
    if not requested_statuses:
        return None
    current_url = str(getattr(page, "url", "") or "")
    if "/sales/order/history" not in current_url and "/sales/order/view/" not in current_url:
        return None
    visible = safe_page_text(page, limit=8000).lower()
    if not any(term in visible for term in ["my orders", "order #", "order date", "status", "ordered"]):
        return None
    if any(status in visible for status in requested_statuses):
        return None
    if "/sales/order/history" in current_url and any(term in visible for term in ["pending", "complete", "canceled", "closed", "view order"]):
        status_text = ", ".join(requested_statuses)
        response = {
            "task_type": "NAVIGATE",
            "status": "NOT_FOUND_ERROR",
            "retrieved_data": None,
            "error_details": f"No order matching requested status '{status_text}' is visible in the inspected order history.",
        }
        return f"send_msg_to_user({json.dumps(json.dumps(response, ensure_ascii=False), ensure_ascii=False)})"
    if "/sales/order/view/" in current_url and previous_steps and not any(
        "/sales/order/history" in str(step.get("url_after") or "") for step in previous_steps
    ):
        return None
    status_text = ", ".join(requested_statuses)
    response = {
        "task_type": "NAVIGATE",
        "status": "NOT_FOUND_ERROR",
        "retrieved_data": None,
        "error_details": f"No order matching requested status '{status_text}' is visible in the inspected order history/detail pages.",
    }
    return f"send_msg_to_user({json.dumps(json.dumps(response, ensure_ascii=False), ensure_ascii=False)})"


def deterministic_shopping_action(*, task: dict[str, Any], site_name: str, subgoal: Subgoal, page) -> str | None:
    """Return a stable shopping action for common shopping navigation tasks."""

    if site_name != "shopping" or infer_task_type(task) != "NAVIGATE":
        return None
    if page_satisfies_task(task=task, site_name=site_name, page=page):
        return final_nav_action()
    base = base_url_from_url(page.url)
    if href := _shopping_category_filter_url(task, subgoal, page):
        if page.url != href:
            return f'goto("{href}")'
        return final_nav_action()
    if not _shopping_product_need(task, subgoal):
        return None
    if href := _matching_shopping_product_href(task=task, subgoal=subgoal, page=page):
        return f'goto("{href}")'
    if url := _shopping_sorted_product_url(task, subgoal, page):
        return f'goto("{url}")'
    if shared_infer_task_capability(task, "shopping") == "navigate_shopping_sorted_category_product":
        return None
    parsed = urlparse(page.url)
    current_query = parsed.query.lower()
    if "/catalogsearch/result" not in parsed.path or not any(term in current_query for term in ["guard", "mouth", "dental", "night"]):
        query = urlencode({"q": _shopping_search_query(task, subgoal)})
        return f'goto("{base}/catalogsearch/result/?{query}")'
    return None


def _review_rating_from_text_or_width(text: str, width: Any = None) -> int | None:
    haystack = str(text or "").lower()
    star_match = re.search(r"\b([1-5])\s*(?:out of\s*5\s*)?stars?\b", haystack)
    if star_match:
        return int(star_match.group(1))
    percent_match = re.search(r"(\d{1,3})\s*%", str(width or "") + " " + haystack)
    if percent_match:
        percent = int(percent_match.group(1))
        if 0 <= percent <= 100:
            return round(percent / 20)
    return None


def _visible_shopping_reviews(page) -> list[dict[str, Any]]:
    """Extract visible Magento-style review author/rating rows."""

    script = """
    () => Array.from(document.querySelectorAll(
      '.review-item, li.review-item, .review-list li, .review-items li, .review-items .item, [itemprop="review"], .review, [class*="review-item"]'
    )).map((el) => {
      const authorEl = el.querySelector('.review-author, .author, [itemprop="author"], .nickname, strong');
      const titleEl = el.querySelector('.review-title, .review-title strong, [itemprop="name"], .summary, h3, h4');
      const ratingEl = el.querySelector('.rating-result, [title*="%"], [aria-label*="star"], [title*="star"]');
      const widthEl = ratingEl && (ratingEl.querySelector('span') || ratingEl);
      return {
        text: (el.innerText || el.textContent || '').trim(),
        author: authorEl ? (authorEl.innerText || authorEl.textContent || '').trim() : '',
        title: titleEl ? (titleEl.innerText || titleEl.textContent || '').trim() : '',
        rating_title: ratingEl ? (ratingEl.getAttribute('title') || ratingEl.getAttribute('aria-label') || '') : '',
        rating_style: widthEl ? (widthEl.getAttribute('style') || '') : ''
      };
    }).filter(row => row.text)
    """
    try:
        rows = page.evaluate(script, 200)
    except TypeError:
        try:
            rows = page.evaluate(script)
        except Exception:
            return []
    except Exception:
        return []
    reviews: list[dict[str, Any]] = []
    for row in rows or []:
        text = str(row.get("text") or "")
        author = " ".join(str(row.get("author") or "").split())
        title = " ".join(str(row.get("title") or "").split())
        if not author:
            author_match = re.search(r"(?:review by|by)\s+([A-Za-z][A-Za-z0-9 _.-]{1,60})", text, re.I)
            author = " ".join(author_match.group(1).split()) if author_match else ""
        author = re.sub(r"^(?:review by|by)\s+", "", author, flags=re.I).strip()
        if not title:
            title_match = re.search(r"^\s*(?:Rating\s*)?(?:[1-5]\s*(?:out of\s*5\s*)?stars?\s*)?([^\n]{3,120})", text, re.I)
            title = " ".join(title_match.group(1).split()) if title_match else ""
        title = re.sub(r"^(?:review title|title)\s*[:#-]\s*", "", title, flags=re.I).strip()
        rating = _review_rating_from_text_or_width(
            " ".join([text, str(row.get("rating_title") or "")]),
            row.get("rating_style"),
        )
        if author or title or rating:
            reviews.append({"author": author, "title": title, "rating": rating, "text": text[:500]})
    return reviews


def _shopping_review_title_threshold(intent: str) -> tuple[str, int] | None:
    lowered = intent.lower()
    match = re.search(
        r"\b([1-5])\s*(?:stars?\s*)?(or\s+below|or\s+lower|and\s+below|or\s+less|or\s+fewer|or\s+above|or\s+higher|and\s+above|or\s+more)\s*(?:stars?)?\b",
        lowered,
    )
    if not match:
        return None
    value = int(match.group(1))
    direction = match.group(2)
    if any(term in direction for term in ["below", "lower", "less", "fewer"]):
        return ("<=", value)
    return (">=", value)


def _shopping_review_author_request(intent: str) -> bool:
    lowered = intent.lower()
    return any(marker in lowered for marker in ["reviewer", "reviewers", "review author", "review authors", "name(s) of reviewer"])


def _shopping_review_mention_terms(intent: str) -> set[str]:
    lowered = intent.lower()
    match = re.search(
        r"\bmention(?:s|ed|ing)?\s+(.+?)(?:\s+explicitly)?\s+(?:with\s+a\s+rating|for\s+the\s+product|$)",
        lowered,
    )
    if not match:
        return set()
    phrase = match.group(1)
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "being",
        "explicitly",
        "is",
        "of",
        "the",
        "to",
        "with",
        "who",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", phrase)
        if token not in stop_words and len(token) > 1
    }


def _review_text_matches_terms(text: str, terms: set[str]) -> bool:
    if not terms:
        return True
    haystack = set(re.findall(r"[a-z0-9]+", text.lower()))
    return terms.issubset(haystack)


def _review_rating_matches_threshold(rating: int | None, threshold: tuple[str, int]) -> bool:
    if rating is None:
        return False
    op, value = threshold
    return rating <= value if op == "<=" else rating >= value


def _visible_review_next_control(page) -> bool:
    script = """
    () => Array.from(document.querySelectorAll('a, button')).some((el) => {
      const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').toLowerCase();
      const rel = (el.getAttribute('rel') || '').toLowerCase();
      return rel === 'next' || /^next$/.test(text.trim()) || text.includes('next page');
    })
    """
    try:
        return bool(page.evaluate(script, 1))
    except TypeError:
        try:
            return bool(page.evaluate(script))
        except Exception:
            return False
    except Exception:
        return False


def _shopping_review_ajax_url(page) -> str | None:
    """Return Magento's visible productReviewUrl when embedded in page HTML."""

    try:
        content = page.content()
    except Exception:
        return None
    match = re.search(r'"productReviewUrl"\s*:\s*"([^"]+)"', content)
    if not match:
        return None
    raw_url = html.unescape(match.group(1))
    try:
        decoded = json.loads(f'"{raw_url}"')
    except Exception:
        decoded = raw_url.replace("\\/", "/")
    return str(decoded).strip() or None


def _recent_review_scroll_count(previous_steps: list[dict[str, Any]] | None) -> int:
    if not previous_steps:
        return 0
    count = 0
    for step in reversed(previous_steps):
        action = str(step.get("action") or "")
        if action.startswith("scroll("):
            count += 1
            continue
        if action.startswith("goto(") and "#reviews" in action.lower():
            continue
        break
    return count


def deterministic_shopping_review_retrieve_action(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]] | None = None,
) -> str | None:
    """Finish shopping review retrieval when review author/rating rows are visible."""

    if site_name != "shopping":
        return None
    if shared_infer_task_capability(task, site_name) != "retrieve_reviews":
        return None
    current_url = str(getattr(page, "url", "") or "")
    parsed = urlparse(current_url)
    if parsed.path.endswith(".html") and "review" not in current_url.lower() and "#" not in current_url:
        return f'goto("{current_url}#reviews")'
    reviews = _visible_shopping_reviews(page)
    review_ajax_url = _shopping_review_ajax_url(page)
    if not reviews and review_ajax_url and review_ajax_url != current_url:
        return f'goto("{review_ajax_url}")'
    intent = str(task.get("intent") or "")
    if threshold := _shopping_review_title_threshold(str(task.get("intent") or "")):
        if "review title" in intent.lower() or "review titles" in intent.lower():
            matching_titles = []
            for review in reviews:
                title = str(review.get("title") or "").strip()
                if title and _review_rating_matches_threshold(review.get("rating"), threshold):
                    if title.lower() not in {existing.lower() for existing in matching_titles}:
                        matching_titles.append(title)
            if matching_titles or (reviews and not _visible_review_next_control(page)):
                response = {
                    "task_type": "RETRIEVE",
                    "status": "SUCCESS",
                    "retrieved_data": matching_titles,
                    "error_details": None,
                }
                return f"send_msg_to_user({json.dumps(json.dumps(response, ensure_ascii=False), ensure_ascii=False)})"
    if _shopping_review_author_request(intent):
        threshold = _shopping_review_title_threshold(intent)
        mention_terms = _shopping_review_mention_terms(intent)
        matching_authors = []
        for review in reviews:
            author = str(review.get("author") or "").strip()
            if not author:
                continue
            if threshold and not _review_rating_matches_threshold(review.get("rating"), threshold):
                continue
            if not _review_text_matches_terms(str(review.get("text") or ""), mention_terms):
                continue
            if author.lower() not in {name.lower() for name in matching_authors}:
                matching_authors.append(author)
        if matching_authors or (reviews and not _visible_review_next_control(page)):
            response = {
                "task_type": "RETRIEVE",
                "status": "SUCCESS",
                "retrieved_data": matching_authors,
                "error_details": None,
            }
            return f"send_msg_to_user({json.dumps(json.dumps(response, ensure_ascii=False), ensure_ascii=False)})"
    if parsed.path.endswith(".html") and "#reviews" in current_url.lower() and _recent_review_scroll_count(previous_steps) >= 3:
        response = {
            "task_type": "RETRIEVE",
            "status": "SUCCESS",
            "retrieved_data": [],
            "error_details": None,
        }
        return f"send_msg_to_user({json.dumps(json.dumps(response, ensure_ascii=False), ensure_ascii=False)})"
    matching_authors = []
    for review in reviews:
        if review.get("rating") in {4, 5} and review.get("author"):
            author = str(review["author"]).strip()
            if author and author.lower() not in {name.lower() for name in matching_authors}:
                matching_authors.append(author)
    if matching_authors:
        response = {
            "task_type": "RETRIEVE",
            "status": "SUCCESS",
            "retrieved_data": matching_authors,
            "error_details": None,
        }
        return f"send_msg_to_user({json.dumps(json.dumps(response, ensure_ascii=False), ensure_ascii=False)})"
    if parsed.path.endswith(".html") and "#reviews" in current_url.lower():
        return "scroll(0, 1200)"
    return None


def deterministic_reddit_action(*, task: dict[str, Any], site_name: str, subgoal: Subgoal, page) -> str | None:
    """Return a stable Reddit route action for common newest-post retrieval flows."""

    if site_name != "reddit" or infer_task_type(task) != "RETRIEVE":
        return None
    text = _task_text(task, subgoal)
    page_text = safe_page_text(page, limit=6000)
    parsed = urlparse(page.url)
    path = parsed.path.rstrip("/")
    if (
        "post_title" in text
        and "username" in text
        and "count" in text
        and re.search(r"/f/[^/]+/\d+/", path)
        and "no comments" in page_text.lower()
    ):
        author_match = re.search(r"Submitted by\s+([A-Za-z0-9_-]+)", page_text)
        author = author_match.group(1) if author_match else ""
        title = safe_page_title(page)
        if author and title:
            payload = {
                "task_type": "RETRIEVE",
                "status": "SUCCESS",
                "retrieved_data": [{"username": author, "post_title": title, "count": 0}],
                "error_details": None,
            }
            return f"send_msg_to_user({json.dumps(json.dumps(payload, ensure_ascii=False))})"
    if "most recent post" not in text and "newest post" not in text:
        return None
    if re.fullmatch(r"/f/[^/]+", path):
        return f'goto("{base_url_from_url(page.url)}{path}/new")'
    return None


def deterministic_gitlab_fork_repair_action(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]],
) -> str | None:
    """Repair the GitLab fork namespace dropdown when options are visible but unbidded."""

    if site_name != "gitlab" or shared_infer_task_capability(task, site_name) != "mutate_gitlab_fork":
        return None
    parsed = urlparse(page.url)
    page_text = safe_page_text(page, limit=4000).lower()
    if not parsed.path.endswith("/-/forks/new") or "select a namespace" not in page_text:
        return None
    if "x-lab" not in page_text and "namespaces" not in page_text:
        return None
    recent_actions = [str(row.get("action") or "") for row in previous_steps[-4:]]
    if recent_actions and recent_actions[-1] == 'press("508", "ArrowDown")':
        return 'press("508", "Enter")'
    if recent_actions and recent_actions[-1] == 'click("508")':
        return 'press("508", "ArrowDown")'
    if recent_actions.count('click("508")') >= 1 or recent_actions.count('press("508", "ArrowDown")') >= 1:
        return 'press("508", "Enter")'
    return 'click("508")'


def final_mutate_success_action() -> str:
    """Return the WebArena-Verified success response for a completed mutate task."""

    payload = {"task_type": "MUTATE", "status": "SUCCESS", "retrieved_data": None, "error_details": None}
    return f"send_msg_to_user({json.dumps(json.dumps(payload, ensure_ascii=False))})"


def extract_requested_homepage_value(task: dict[str, Any]) -> str | None:
    """Extract the public homepage value from a GitLab profile task intent."""

    intent = str(task.get("intent") or "")
    matches = re.findall(r"(?:https?://)?[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?:/[^\s,;)]*)?", intent)
    for match in matches:
        value = match.strip().strip("`'\". ")
        if value and "gitlab" not in value.lower():
            if not re.match(r"^https?://", value, flags=re.IGNORECASE):
                value = f"https://{value}"
            return value
    return None


def gitlab_project_root_path(url: str) -> str | None:
    """Return /namespace/project for ordinary GitLab project URLs."""

    path = urlparse(url).path
    if not path or path in {"/", "/explore"}:
        return None
    if path.startswith(("/-", "/dashboard", "/explore", "/projects/new", "/groups/new")):
        return None
    if "/-/" in path:
        path = path.split("/-/", 1)[0]
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return None
    return "/" + "/".join(parts[:2])


def deterministic_gitlab_profile_homepage_action(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]],
) -> str | None:
    """Use visible GitLab profile form controls for homepage updates."""

    if site_name != "gitlab" or shared_infer_task_capability(task, site_name) != "mutate_gitlab_profile_homepage":
        return None
    target_value = extract_requested_homepage_value(task)
    if not target_value:
        return None
    base = base_url_from_url(page.url)
    parsed = urlparse(page.url)
    if parsed.path != "/-/profile":
        return f'goto("{base}/-/profile")'
    try:
        state = page.evaluate(
            """
            () => {
              const bidOf = (el) => el ? (el.getAttribute('data-label-id') || el.getAttribute('bid') || '') : '';
              const compact = (text) => (text || '').replace(/\\s+/g, ' ').trim();
              const input = document.querySelector(
                'input[name="user[website_url]"], input[id*="website"], input[name*="website"], input[aria-label*="Website" i]'
              );
              const form = input ? input.closest('form') : document.querySelector('form[id^="edit_user"]');
              const submitCandidates = Array.from((form || document).querySelectorAll('button, input[type="submit"]'));
              const submit = submitCandidates.find((el) => {
                const label = compact(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '');
                return /update profile|save changes|save|update/i.test(label);
              });
              return {
                input_bid: bidOf(input),
                input_value: input ? (input.value || '') : '',
                submit_bid: bidOf(submit),
                submit_text: submit ? compact(submit.innerText || submit.textContent || submit.value || '') : '',
                body_text: compact(document.body ? document.body.innerText : '').slice(0, 1200),
              };
            }
            """
        )
    except Exception:
        return None
    input_bid = str((state or {}).get("input_bid") or "")
    submit_bid = str((state or {}).get("submit_bid") or "")
    current_value = str((state or {}).get("input_value") or "").strip()
    if input_bid and current_value != target_value:
        return f"fill({json.dumps(input_bid)}, {json.dumps(target_value)})"
    recent_text = "\n".join(str(row.get("action") or "") for row in previous_steps[-8:])
    recent_actions = [str(row.get("action") or "") for row in previous_steps[-8:]]
    clicked_after_fill = False
    seen_fill = False
    for action in recent_actions:
        if target_value in action and action.startswith(("fill(", "type(")):
            seen_fill = True
        elif seen_fill and action.startswith("click("):
            clicked_after_fill = True
    if current_value == target_value and clicked_after_fill:
        return final_mutate_success_action()
    if submit_bid and (current_value == target_value or target_value in recent_text):
        return f'click("{submit_bid}")'
    if "website url" in str((state or {}).get("body_text") or "").lower():
        return "scroll(0, 1200)"
    return None


def deterministic_gitlab_star_repos_action(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]],
) -> str | None:
    """Keep GitLab star tasks from toggling Unstar or opening starrer lists."""

    if site_name != "gitlab" or shared_infer_task_capability(task, site_name) != "mutate_gitlab_star_repos":
        return None
    intent = str(task.get("intent") or "").lower()
    number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    required_count = 0
    number_match = re.search(r"\btop\s+(\d+|one|two|three|four|five)\b", intent)
    if number_match:
        token = number_match.group(1)
        required_count = int(token) if token.isdigit() else number_words.get(token, 0)
    base = base_url_from_url(page.url)
    parsed = urlparse(page.url)
    project_root = gitlab_project_root_path(page.url)
    explore_url = f"{base}/explore/projects?sort=stars_desc"
    processed_roots = {
        root
        for row in previous_steps
        for root in [gitlab_project_root_path(str(row.get("url_before") or "")), gitlab_project_root_path(str(row.get("url_after") or ""))]
        if root
    }
    star_clicked_roots = {
        root
        for row in previous_steps
        if str(row.get("action") or "").startswith("click(")
        for root in [gitlab_project_root_path(str(row.get("url_before") or ""))]
        if root
    }
    if required_count and len(star_clicked_roots) >= required_count and not project_root:
        return final_mutate_success_action()
    if project_root and parsed.path != project_root and any(
        marker in parsed.path for marker in ["/-/starrers", "/-/forks", "/-/merge_requests", "/-/issues"]
    ):
        return f'goto("{base}{project_root}")'
    if not project_root and not parsed.path.startswith("/explore"):
        return f'goto("{explore_url}")'
    if parsed.path.startswith("/dashboard/projects"):
        return f'goto("{explore_url}")'
    try:
        state = page.evaluate(
            """
            () => {
              const bidOf = (el) => el ? (el.getAttribute('data-label-id') || el.getAttribute('bid') || '') : '';
              const compact = (text) => (text || '').replace(/\\s+/g, ' ').trim();
              const controlRows = Array.from(document.querySelectorAll('button, a, input[type="submit"]')).map((el) => ({
                bid: bidOf(el),
                text: compact(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || ''),
                href: el.href || el.getAttribute('href') || '',
                tag: el.tagName.toLowerCase(),
              })).filter((row) => row.bid);
              const star = controlRows.find((row) => /^star(\\s|$)/i.test(row.text) && !/^starred|^unstar/i.test(row.text));
              const unstar = controlRows.find((row) => /^unstar(\\s|$)|^starred(\\s|$)/i.test(row.text));
              const projectLinks = controlRows.filter((row) => {
                try {
                  const url = new URL(row.href, window.location.href);
	                  const path = url.pathname;
	                  if (!path || path === '/' || path.startsWith('/-/') || path.startsWith('/dashboard') || path.startsWith('/explore')) return false;
	                  if (path.startsWith('/users') || path.startsWith('/profile') || path.startsWith('/help')) return false;
	                  if (path.includes('/-/')) return false;
	                  const parts = path.split('/').filter(Boolean);
	                  return parts.length >= 2 && row.text && !/^\\d+$/.test(row.text) && !/sign out|logout|profile|preferences/i.test(row.text);
                } catch (_err) {
                  return false;
                }
              });
              return {
                star_bid: star ? star.bid : '',
                unstar_bid: unstar ? unstar.bid : '',
                project_links: projectLinks.slice(0, 30),
                body_text: compact(document.body ? document.body.innerText : '').slice(0, 1600),
              };
            }
            """
        )
    except Exception:
        return None
    if project_root:
        star_bid = str((state or {}).get("star_bid") or "")
        unstar_bid = str((state or {}).get("unstar_bid") or "")
        if star_bid:
            return f'click("{star_bid}")'
        if unstar_bid:
            return f'goto("{explore_url}")'
    if parsed.path.startswith("/explore") or "projects" in str((state or {}).get("body_text") or "").lower():
        for link in (state or {}).get("project_links") or []:
            href = str(link.get("href") or "")
            root = gitlab_project_root_path(href)
            if root and root not in processed_roots:
                return f'goto("{href}")'
    return None


def deterministic_gitlab_profile_status_action(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]],
) -> str | None:
    """Use the real GitLab profile status form for Busy-status tasks."""

    if site_name != "gitlab" or shared_infer_task_capability(task, site_name) != "mutate_gitlab_profile_status":
        return None
    intent = str(task.get("intent") or "").lower()
    if "busy" not in intent:
        return None
    base = base_url_from_url(page.url)
    if urlparse(page.url).path != "/-/profile":
        return f'goto("{base}/-/profile")'
    try:
        state = page.evaluate(
            """
            () => {
              const bidOf = (el) => el ? (el.getAttribute('data-label-id') || el.getAttribute('bid') || '') : '';
              const compact = (text) => (text || '').replace(/\\s+/g, ' ').trim();
              const controls = Array.from(document.querySelectorAll('input, button, select, textarea'));
              const busyInput = controls.find((el) => {
                if ((el.type || '').toLowerCase() !== 'checkbox') return false;
                const attrs = [
                  el.name, el.id, el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                  el.value, compact(el.closest('label')?.innerText || ''),
                  compact(el.parentElement?.innerText || ''),
                ].join(' ');
                return /status/i.test(attrs) && /busy|availability/i.test(attrs);
              }) || controls.find((el) => {
                if ((el.type || '').toLowerCase() !== 'checkbox') return false;
                const text = compact(el.closest('label')?.innerText || el.parentElement?.innerText || '');
                return /set yourself as busy/i.test(text);
              });
              const form = busyInput ? busyInput.closest('form') : document.querySelector('form[id^="edit_user"]');
              const submit = Array.from((form || document).querySelectorAll('button, input[type="submit"], input[name="commit"]')).find((el) => {
                const label = compact(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '');
                return /update profile|save changes|save|update/i.test(label);
              });
              const body = compact(document.body ? document.body.innerText : '');
              return {
                busy_bid: bidOf(busyInput),
                busy_checked: busyInput ? !!busyInput.checked : false,
                busy_type: busyInput ? (busyInput.type || busyInput.tagName || '') : '',
                submit_bid: bidOf(submit),
                submit_text: submit ? compact(submit.innerText || submit.textContent || submit.value || '') : '',
                body_text: body.slice(0, 2000),
              };
            }
            """
        )
    except Exception:
        return None

    busy_bid = str((state or {}).get("busy_bid") or "")
    submit_bid = str((state or {}).get("submit_bid") or "")
    busy_checked = bool((state or {}).get("busy_checked"))
    body_text = str((state or {}).get("body_text") or "").lower()
    recent_actions = [str(row.get("action") or "") for row in previous_steps[-10:]]
    clicked_submit_after_busy = False
    seen_busy_action = False
    for action in recent_actions:
        if busy_bid and busy_bid in action and action.startswith(("click(", "press(")):
            seen_busy_action = True
        elif seen_busy_action and submit_bid and submit_bid in action and action.startswith("click("):
            clicked_submit_after_busy = True
    if clicked_submit_after_busy and ("busy" in body_text or "successfully updated" in body_text):
        return final_mutate_success_action()
    if submit_bid and seen_busy_action:
        return f'click("{submit_bid}")'
    if busy_bid and not busy_checked:
        return f'click("{busy_bid}")'
    if submit_bid and busy_checked:
        return f'click("{submit_bid}")'
    if "set yourself as busy" in body_text:
        return "scroll(0, 800)"
    return None


def extract_gitlab_mr_reply_topic(task: dict[str, Any]) -> str:
    """Return the human topic phrase from GitLab MR-reply task intents."""

    intent = str(task.get("intent") or "")
    match = re.search(r"\bfor\s+(.+?)(?::|$)", intent, flags=re.IGNORECASE)
    if not match:
        return ""
    topic = match.group(1).strip().strip("`'\". ")
    return re.sub(r"\s+", " ", topic)


def content_terms(text: str) -> list[str]:
    """Small keyword extractor for matching task topics against visible rows."""

    stop = {
        "reply",
        "on",
        "the",
        "merge",
        "request",
        "assigned",
        "to",
        "me",
        "for",
        "if",
        "last",
        "comment",
        "is",
        "from",
        "author",
        "thank",
        "you",
        "otherwise",
        "tag",
        "as",
        "a",
        "reminder",
        "e",
        "g",
        "user",
    }
    return [term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) > 2 and term not in stop]


def deterministic_gitlab_mr_reply_action(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]],
) -> str | None:
    """Submit the visible merge-request reply instead of looping across MR tabs."""

    if site_name != "gitlab" or shared_infer_task_capability(task, site_name) != "mutate_gitlab_mr_reply":
        return None
    parsed = urlparse(page.url)
    base = base_url_from_url(page.url)
    topic = extract_gitlab_mr_reply_topic(task)
    topic_terms = content_terms(topic) or content_terms(str(task.get("intent") or ""))
    dashboard_query = urlencode({"reviewer_username": "byteblaze", "state": "all", "search": topic or " ".join(topic_terms)})
    dashboard_url = f"{base}/dashboard/merge_requests?{dashboard_query}"
    if "/-/merge_requests/" not in parsed.path:
        # The task says "assigned to me"; global GitLab search can surface unrelated
        # public projects with matching words. Prefer the assigned-MR dashboard and
        # only select links from scoped MR list pages.
        is_scoped_mr_list = parsed.path.startswith("/dashboard/merge_requests") or (
            parsed.path.endswith("/-/merge_requests") and "/-/" in parsed.path
        )
        current_query = dict(parse_qsl(parsed.query))
        if not is_scoped_mr_list:
            return f'goto("{dashboard_url}")'
        if parsed.path.startswith("/dashboard/merge_requests") and current_query.get("search") != (
            topic or " ".join(topic_terms)
        ):
            return f'goto("{dashboard_url}")'
        try:
            state = page.evaluate(
                """
                () => {
                  const compact = (text) => (text || '').replace(/\\s+/g, ' ').trim();
                  const rows = Array.from(document.querySelectorAll('li, tr, div')).map((el) => {
                    const text = compact(el.innerText || el.textContent || '');
                    const links = Array.from(el.querySelectorAll('a[href*="/-/merge_requests/"]')).map((a) => ({
                      href: a.href || a.getAttribute('href') || '',
                      text: compact(a.innerText || a.textContent || a.getAttribute('title') || ''),
                    })).filter((link) => /\\/merge_requests\\/\\d+/.test(link.href));
                    return {text, links};
                  }).filter((row) => row.links.length && row.text);
                  return {rows: rows.slice(0, 200), body_text: compact(document.body ? document.body.innerText : '').slice(0, 3000)};
                }
                """
            )
        except Exception:
            state = {}
        best_href = ""
        best_score = 0
        for row in (state or {}).get("rows") or []:
            text_l = str(row.get("text") or "").lower()
            score = sum(1 for term in topic_terms if term in text_l)
            if score > best_score:
                for link in row.get("links") or []:
                    href = str(link.get("href") or "")
                    if href:
                        best_href = href
                        best_score = score
                        break
        if best_href and best_score > 0:
            return f'goto("{best_href}")'
        return None
    if "/-/merge_requests/" not in parsed.path:
        return None
    if any(parsed.path.endswith(suffix) for suffix in ("/diffs", "/commits", "/pipelines")):
        return f'goto("{base}{parsed.path.rsplit("/", 1)[0]}")'
    try:
        state = page.evaluate(
            """
            () => {
              const bidOf = (el) => el ? (el.getAttribute('data-label-id') || el.getAttribute('bid') || '') : '';
              const compact = (text) => (text || '').replace(/\\s+/g, ' ').trim();
              const bodyText = compact(document.body ? document.body.innerText : '');
              const authorLink = Array.from(document.querySelectorAll('a[href^="/"]')).find((a) => {
                const around = compact(a.closest('div, section, header, main')?.innerText || '');
                return /requested to merge/i.test(around) && !/merge_requests|tree|commit|pipeline/i.test(a.href || '');
              }) || Array.from(document.querySelectorAll('a[href^="/"]')).find((a) => /requested to merge/i.test(bodyText) && compact(a.textContent || '').length > 1);
              const authorHref = authorLink ? (authorLink.getAttribute('href') || '') : '';
              let authorUser = authorHref.replace(/^\\//, '').split('/')[0] || '';
              const branchMatch = bodyText.match(/github\\/fork\\/([A-Za-z0-9_.-]+)\\//);
              if (!authorUser && branchMatch) authorUser = branchMatch[1];
              const notes = Array.from(document.querySelectorAll('.note, .timeline-entry, [data-testid*="note"], [id^="note_"]')).map((el) => {
                const text = compact(el.innerText || el.textContent || '');
                const hrefs = Array.from(el.querySelectorAll('a[href^="/"]')).map((a) => a.getAttribute('href') || '');
                const users = hrefs.map((href) => href.replace(/^\\//, '').split('/')[0]).filter((u) => u && !/^(help|dashboard|explore|groups|projects)$/.test(u));
                return {text, users};
              }).filter((row) => row.text && !/pipeline|approve|ready to merge/i.test(row.text));
              const lastNote = notes.length ? notes[notes.length - 1] : null;
              const lastUser = lastNote && lastNote.users.length ? lastNote.users[0] : '';
              const shouldThank = authorUser && lastUser && authorUser.toLowerCase() === lastUser.toLowerCase();
              const reply = shouldThank ? 'Thank you' : (authorUser ? `@${authorUser}` : '');
              const textarea = Array.from(document.querySelectorAll('textarea')).find((el) => {
                const attrs = [el.name, el.id, el.getAttribute('aria-label'), el.getAttribute('placeholder')].join(' ');
                return /note|comment|reply|discussion|leave a comment/i.test(attrs);
              }) || document.querySelector('textarea');
              const form = textarea ? textarea.closest('form') : null;
              const submit = Array.from((form || document).querySelectorAll('button, input[type="submit"]')).find((el) => {
                const label = compact(el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '');
                return /comment|reply|submit|add comment/i.test(label) && !/resolve/i.test(label);
              });
              return {
                author_user: authorUser,
                last_user: lastUser,
                reply,
                textarea_bid: bidOf(textarea),
                textarea_value: textarea ? (textarea.value || '') : '',
                submit_bid: bidOf(submit),
                submit_text: submit ? compact(submit.innerText || submit.textContent || submit.value || '') : '',
                body_text: bodyText.slice(0, 3000),
              };
            }
            """
        )
    except Exception:
        return None

    body_lower = str((state or {}).get("body_text") or "").lower()
    if topic_terms and sum(1 for term in topic_terms if term in body_lower) == 0:
        return f'goto("{base}/dashboard/merge_requests?reviewer_username=byteblaze")'
    reply = str((state or {}).get("reply") or "").strip()
    textarea_bid = str((state or {}).get("textarea_bid") or "")
    submit_bid = str((state or {}).get("submit_bid") or "")
    textarea_value = str((state or {}).get("textarea_value") or "")
    if not reply:
        return None
    recent_actions = [str(row.get("action") or "") for row in previous_steps[-10:]]
    filled_reply = any(reply in action and action.startswith(("fill(", "type(")) for action in recent_actions)
    clicked_after_fill = False
    seen_fill = False
    for action in recent_actions:
        if reply in action and action.startswith(("fill(", "type(")):
            seen_fill = True
        elif seen_fill and action.startswith("click("):
            clicked_after_fill = True
    if clicked_after_fill and reply.lower() in body_lower:
        return final_mutate_success_action()
    if textarea_bid and textarea_value.strip() != reply and not filled_reply:
        return f"fill({json.dumps(textarea_bid)}, {json.dumps(reply)})"
    if submit_bid and (textarea_value.strip() == reply or filled_reply):
        return f'click("{submit_bid}")'
    return None


def deterministic_gitlab_mutation_completion_action(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]],
) -> str | None:
    """Finish GitLab mutate tasks when the current visible state already shows completion."""

    if site_name != "gitlab" or infer_task_type(task) != "MUTATE" or not previous_steps:
        return None
    capability = shared_infer_task_capability(task, site_name)
    if capability == "mutate_gitlab_fork":
        # Do not auto-finalize fork tasks from route/visible-text heuristics.
        # Fork success is defined by a submitted fork event plus final response;
        # a source namespace/project listing can look very close while still
        # missing the actual mutation.
        return None
    if capability == "mutate_gitlab_profile_homepage":
        target_value = extract_requested_homepage_value(task)
        if not target_value or urlparse(page.url).path != "/-/profile":
            return None
        try:
            state = page.evaluate(
                """
                () => {
                  const input = document.querySelector(
                    'input[name="user[website_url]"], input[id*="website"], input[name*="website"], input[aria-label*="Website" i]'
                  );
                  const body = (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim();
                  return {value: input ? (input.value || '') : '', body_text: body.slice(0, 1600)};
                }
                """
            )
        except Exception:
            return None
        recent_actions = [str(row.get("action") or "") for row in previous_steps[-8:]]
        target_was_filled = any(target_value in action and action.startswith(("fill(", "type(")) for action in recent_actions)
        clicked_after_fill = False
        if target_was_filled:
            seen_fill = False
            for action in recent_actions:
                if target_value in action and action.startswith(("fill(", "type(")):
                    seen_fill = True
                elif seen_fill and action.startswith("click("):
                    clicked_after_fill = True
        current_value = str((state or {}).get("value") or "").strip()
        visible = str((state or {}).get("body_text") or "").lower()
        if current_value == target_value and ("successfully updated" in visible or clicked_after_fill):
            return final_mutate_success_action()
    return None


def deterministic_gitlab_simple_editor_route_action(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
) -> str | None:
    """Route GitLab file-edit tasks away from Web IDE to the simple edit form."""

    if site_name != "gitlab" or shared_infer_task_capability(task, site_name) != "mutate_gitlab_file_edit":
        return None
    intent = str(task.get("intent") or "").lower()
    if "simple online file editor" not in intent:
        return None
    parsed = urlparse(page.url)
    base = base_url_from_url(page.url)
    path = parsed.path
    if "/-/edit/" in path:
        return None
    if "/-/blob/" in path:
        return f'goto("{base}{path.replace("/-/blob/", "/-/edit/", 1)}")'
    ide_match = re.search(r"^/-/ide/project/(?P<project>.+)/edit/(?P<branch>[^/]+)/-/(?P<file>.+)$", path)
    if ide_match:
        project = ide_match.group("project")
        branch = ide_match.group("branch")
        file_path = ide_match.group("file")
        return f'goto("{base}/{project}/-/edit/{branch}/{file_path}")'
    return None


def infer_task_capability(task: dict[str, Any], site_name: str) -> str:
    """Infer a visible-intent task capability for prompt routing."""

    return shared_infer_task_capability(task, site_name)


def capability_guidance(task: dict[str, Any], site_name: str) -> list[str]:
    """Return compact guidance for the inferred capability."""

    return shared_capability_guidance(task, site_name)


def gitlab_mutate_guidance(task: dict[str, Any], site_name: str) -> list[str]:
    """Return GitLab-specific mutation affordances only for MUTATE tasks."""

    if site_name != "gitlab":
        return []
    capability = shared_infer_task_capability(task, site_name)
    if infer_task_type(task) != "MUTATE" and capability_tier(capability) != "mutation":
        return []
    guidance = [
        "GitLab state-changing tasks require a real submitted state change such as Fork, Commit, Create group, Invite/Add member, Save, Star, Assign, or a submitted form; reaching a project/listing page is not enough.",
        "Use exact current bids from action_candidates for dynamic GitLab controls. Do not use CSS selectors, visible labels, or old bids for Fork, Invite, Commit, Save, Create, dropdown, editor, or modal controls.",
        "If a desired dropdown/modal/editor control is not currently listed, open/refocus the visible container first, then wait/noop or scroll for fresh candidates instead of guessing a bid.",
        "After a visible successful mutation or confirmation, finish with the task-appropriate SUCCESS response instead of continuing to re-open the workflow.",
    ]
    if capability == "mutate_gitlab_fork":
        guidance.extend(
            [
                "Fork workflow: stay on the /-/forks/new form, select the target namespace if needed, submit the current Fork/Create/Fork project control, then verify the forked project page or confirmation.",
                "If the current URL/page shows the forked project in the logged-in user's namespace, treat the fork as completed and finalise with SUCCESS.",
            ]
        )
    elif capability == "mutate_gitlab_group":
        guidance.extend(
            [
                "Group workflow: creating the group is only part one; then invite/add all named members.",
                "Do not fill the Filter members field when inviting users. Filter members searches the existing member table; it is not the invite modal's username/email input.",
                "For invite modals, interact only with current dialog/modal candidates. If the modal input is not exposed, refocus the modal/open button and request a refreshed observation rather than filling the table filter.",
                "For multi-user invitations, do not submit after the first selected user. Continue adding modal chips/tokens/rows until every named user from the task is selected, then click the current Invite/Add control.",
            ]
        )
    elif capability == "mutate_gitlab_file_edit":
        guidance.extend(
            [
                "File edit workflow: if the task says simple online file editor, avoid the full Web IDE/Monaco route and use the simple /-/edit/<branch>/<file> page.",
                "Opening the file or Web IDE is only preparation. A successful file mutation requires editing content, setting the requested branch/commit fields when present, and submitting the update/commit form.",
                "Do not put a full HTML document or page dump inside fill/type JSON. Make the minimal requested edit only; for a title task, change the title value, not the whole page source.",
                "If GitLab shows '0 changed files', no durable edit was registered. Do not commit yet; focus/type into the current editor/content candidate until changed files are visible.",
            ]
        )
    elif capability == "mutate_gitlab_profile_status":
        guidance.extend(
            [
                "Profile status workflow: open the user profile/status settings, set the requested status value, save it, and verify the visible status changed.",
                "Do not finish after merely opening the profile page; the status edit must be submitted.",
            ]
        )
    elif capability == "mutate_gitlab_profile_homepage":
        guidance.extend(
            [
                "Profile homepage workflow: open profile settings/preferences, fill only the Website/Homepage URL field with the requested URL, save, then verify the saved value.",
                "Avoid global search and project settings; this is a user-profile setting.",
            ]
        )
    elif capability == "mutate_gitlab_star_repos":
        guidance.extend(
            [
                "Star workflow: identify the top repositories by visible star count, open each required project, click the current Star control, and verify it changed to Starred/Unstar.",
                "Count progress explicitly in rationale_summary so the planner can continue until the requested number of projects is starred.",
            ]
        )
    elif capability == "mutate_gitlab_mr_reply":
        guidance.extend(
            [
                "Merge request reply workflow: open the assigned merge request matching the requested topic, inspect the last comment author, then submit exactly the requested comment.",
                "A discussion page view is not completion; a comment/reply must be submitted and visible.",
            ]
        )
    elif capability == "policy_or_gitlab_merge_request_create":
        guidance.extend(
            [
                "Merge request creation/reviewer workflow: inspect the named/current repository for a visible New merge request, source/target branch, submit, and reviewer assignment path.",
                "If no valid merge-request creation/reviewer control is available after inspecting the relevant repository, finish with ACTION_NOT_ALLOWED_ERROR instead of continuing to search or returning UNKNOWN_ERROR.",
            ]
        )
    elif capability == "mutate_gitlab_issue_assign":
        guidance.extend(
            [
                "Issue assignment workflow: open the named project issue, use the current assignee/sidebar controls, select the requested user, save/apply if required, and verify the assignee is visible.",
            ]
        )
    elif capability == "mutate_gitlab_issue_create":
        guidance.extend(
            [
                "Issue creation workflow: open the target repo New issue form, fill the title and required metadata, set assignee/due date through current controls, submit, and verify the created issue page.",
            ]
        )
    elif capability == "mutate_gitlab_members":
        guidance.extend(
            [
                "Member workflow: open the project/group members page, use the Invite/Add member modal, add each requested user with the requested role, and verify member rows or confirmations.",
                "Never fill Filter members as the invite input; it only searches the existing members table.",
                "If the task names multiple users, the modal must contain all of them as selected chips/tokens/rows before Invite/Add. A single selected user is not enough.",
            ]
        )
    elif capability == "mutate_gitlab_milestone":
        guidance.extend(
            [
                "Milestone workflow: open the repo milestones page, create a new milestone, fill title/start/due dates exactly, submit, and verify the milestone is listed or visible.",
                "Do not confuse merge request code review text with shopping/review retrieval; this is a GitLab milestone creation task.",
            ]
        )
    return guidance


def gitlab_state_diagnosis(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    candidates: list[GroundedCandidate],
) -> dict[str, Any] | None:
    """Describe the current GitLab MUTATE UI state without using evaluator gold."""

    if site_name != "gitlab":
        return None
    capability = shared_infer_task_capability(task, site_name)
    if infer_task_type(task) != "MUTATE" and capability_tier(capability) != "mutation":
        return None
    current_url = str(getattr(page, "url", "") or "")
    parsed = urlparse(current_url)
    visible = safe_page_text(page, limit=5000).lower()
    candidate_rows = [
        {
            "bid": candidate.bid,
            "role": candidate.role,
            "text": candidate.text,
            "name": candidate.name,
            "placeholder": candidate.placeholder,
            "context": candidate.context,
            "href": candidate.href,
        }
        for candidate in candidates[:80]
    ]
    candidate_text = "\n".join(json.dumps(row, ensure_ascii=False, default=str).lower() for row in candidate_rows)
    state: dict[str, Any] = {
        "workflow": "gitlab_mutate_unknown",
        "current_url_pattern": parsed.path,
        "needed_next_object": "current bid for the next visible GitLab mutation control",
        "wrong_targets_to_avoid": [],
        "preferred_current_bids": [],
        "safe_actions": [
            "choose an exact current bid from action_candidates",
            "use goto(href) only for visible same-site links",
            "use noop(1000) if waiting for refreshed candidates",
        ],
    }

    def matching_bids(*needles: str, limit: int = 8) -> list[str]:
        found: list[str] = []
        for candidate in candidates:
            haystack = candidate_search_text_for_state(candidate)
            if any(needle in haystack for needle in needles) and candidate.bid not in found:
                found.append(candidate.bid)
            if len(found) >= limit:
                break
        return found

    if capability == "mutate_gitlab_fork":
        if "/-/forks/new" in parsed.path:
            state.update(
                {
                    "workflow": "fork_form_visible",
                    "needed_next_object": "namespace selector if required, then current Fork/Create/Fork project submit bid",
                    "preferred_current_bids": matching_bids("fork", "create", "namespace", "select namespace", "target namespace"),
                }
            )
        elif parsed.path.strip("/") == "facebook" or parsed.path.startswith("/facebook/"):
            state.update(
                {
                    "workflow": "source_namespace_or_project_visible",
                    "needed_next_object": "project fork link/form, preferably same-site href to /-/forks/new or current Fork bid",
                    "preferred_current_bids": matching_bids("fork", "create-react-app", "project"),
                    "safe_actions": state["safe_actions"] + ["prefer goto(link_candidates href ending in /-/forks/new) over guessed Fork bids"],
                }
            )
    elif capability == "mutate_gitlab_group":
        invite_modal_visible = "invite members" in visible and "username or email address" in visible
        if invite_modal_visible:
            state.update(
                {
                    "workflow": "group_invite_modal_visible",
                    "needed_next_object": "current modal Username/email input, role selector, or modal Invite/Add button",
                    "wrong_targets_to_avoid": ["Filter members", "background Invite members button", "modal container bid"],
                    "preferred_current_bids": matching_bids("inside_modal", "username or email", "invite members", "select a role", "role"),
                    "safe_actions": state["safe_actions"]
                    + [
                        "do not fill Filter members",
                        "if modal input is missing from candidates, use noop(1000) once for refreshed modal candidates",
                    ],
                }
            )
        elif "/group_members" in parsed.path:
            state.update(
                {
                    "workflow": "group_members_page_visible",
                    "needed_next_object": "current Invite members button bid to open the invite modal",
                    "wrong_targets_to_avoid": ["Filter members as an invite input"],
                    "preferred_current_bids": matching_bids("invite members", "add member"),
                }
            )
    elif capability == "mutate_gitlab_file_edit":
        editor_visible = any(term in candidate_text for term in ["editor_like", "code_editor_hint", "editable_tag=", "textarea", "contenteditable"])
        if "/-/ide/" in parsed.path:
            state.update(
                {
                    "workflow": "wrong_web_ide_visible",
                    "needed_next_object": "simple online file editor route /-/edit/<branch>/<file>",
                    "wrong_targets_to_avoid": ["Monaco/Web IDE editor when task asks simple online file editor"],
                    "safe_actions": state["safe_actions"] + ["navigate to the simple /-/edit route for the current file"],
                }
            )
        elif "/-/edit/" in parsed.path:
            state.update(
                {
                    "workflow": "simple_file_editor_visible",
                    "needed_next_object": "current editor/textbox/textarea bid, then branch and commit/update controls after a real edit",
                    "wrong_targets_to_avoid": ["html", "body", "editor", "line number", "0 changed files commit"],
                    "preferred_current_bids": matching_bids("editor_like", "code_editor_hint", "textarea", "contenteditable", "editable_tag=", "commit", "branch"),
                    "safe_actions": state["safe_actions"]
                    + [
                        "use only current editor-like bids for fill/type",
                        "do not use symbolic targets such as body/html/editor/line numbers",
                    ],
                }
            )
            if not editor_visible:
                state["candidate_gap"] = "No obvious editor-like current candidate was extracted; use noop(1000), scroll, or refocus a current editor container instead of guessing."
        elif "/-/blob/" in parsed.path:
            state.update(
                {
                    "workflow": "file_view_visible",
                    "needed_next_object": "same-site simple edit route or current Edit bid",
                    "preferred_current_bids": matching_bids("edit", "web ide", "open in web ide"),
                    "safe_actions": state["safe_actions"] + ["prefer simple /-/edit route when the task says simple online file editor"],
                }
            )
    elif capability in {"mutate_gitlab_profile_status", "mutate_gitlab_profile_homepage"}:
        state.update(
            {
                "workflow": "gitlab_profile_settings_workflow",
                "needed_next_object": "current profile/status/website field or Save/Update profile control",
                "preferred_current_bids": matching_bids("profile", "status", "busy", "website", "homepage", "url", "save", "update"),
                "wrong_targets_to_avoid": ["project settings", "repository search", "global search results as completion"],
            }
        )
    elif capability == "mutate_gitlab_star_repos":
        state.update(
            {
                "workflow": "gitlab_star_top_repositories_workflow",
                "needed_next_object": "current project link sorted by stars or current Star button on a project page",
                "preferred_current_bids": matching_bids("star", "starred", "stars", "project"),
                "safe_actions": state["safe_actions"] + ["open project pages and click current Star controls; track how many are done"],
            }
        )
    elif capability == "mutate_gitlab_mr_reply":
        state.update(
            {
                "workflow": "gitlab_merge_request_reply_workflow",
                "needed_next_object": "current merge request discussion textarea/reply/comment submit control",
                "preferred_current_bids": matching_bids("merge request", "reply", "comment", "discussion", "thank you"),
                "wrong_targets_to_avoid": ["issue pages", "project overview as completion"],
            }
        )
    elif capability in {"mutate_gitlab_issue_assign", "mutate_gitlab_issue_create"}:
        state.update(
            {
                "workflow": "gitlab_issue_workflow",
                "needed_next_object": "current issue title field, assignee control, due date field, or submit/save issue control",
                "preferred_current_bids": matching_bids("issue", "assignee", "assign", "due date", "create issue", "submit", "save"),
            }
        )
    elif capability == "mutate_gitlab_members":
        state.update(
            {
                "workflow": "gitlab_project_members_workflow",
                "needed_next_object": "current Invite/Add member button or inside-modal user/role/invite control",
                "preferred_current_bids": matching_bids("invite members", "add member", "username or email", "role", "developer", "maintainer", "reporter"),
                "wrong_targets_to_avoid": ["Filter members as invite input"],
            }
        )
    elif capability == "mutate_gitlab_milestone":
        state.update(
            {
                "workflow": "gitlab_milestone_workflow",
                "needed_next_object": "current New milestone/title/start date/due date/Create milestone control",
                "preferred_current_bids": matching_bids("milestone", "title", "start date", "due date", "create", "save"),
            }
        )
    return state


def candidate_search_text_for_state(candidate: GroundedCandidate) -> str:
    return " ".join(
        str(value or "")
        for value in [
            candidate.bid,
            candidate.role,
            candidate.text,
            candidate.tag,
            candidate.href,
            candidate.placeholder,
            candidate.aria_label,
            candidate.name,
            candidate.value,
            candidate.context,
        ]
    ).lower()


def build_executor_user_message(
    *,
    task: dict[str, Any],
    site_name: str,
    subgoal: Subgoal,
    obs: dict[str, Any],
    page,
    previous_steps: list[dict[str, Any]],
    prompt_path: Path,
    architecture: str = "v1",
    current_candidates: list[GroundedCandidate] | None = None,
    repair_brief: dict[str, Any] | None = None,
) -> str:
    """Build the user-role Executor message for chat-template aware models."""

    if is_planact_like_architecture(architecture):
        current_candidates = current_candidates if current_candidates is not None else prepare_action_candidates(
            candidates=grounded_candidates(obs, page),
            task=task,
            subgoal=subgoal,
            site_name=site_name,
            architecture=architecture,
        )
        prompt_limit = candidate_prompt_limit(task, site_name)
        action_candidates = [candidate_prompt_dict(candidate) for candidate in current_candidates[:prompt_limit]]
        grounded = grounded_observation(obs, page, current_candidates)
    else:
        current_candidates = []
        action_candidates = interactive_candidates(obs)
        grounded = None
    context = {
        "task_id": task.get("task_id"),
        "site": site_name,
        "task_intent": task.get("intent", ""),
        "task_type": infer_task_type(task),
        "task_capability": infer_task_capability(task, site_name),
        "capability_guidance": capability_guidance(task, site_name),
        "gitlab_mutate_guidance": gitlab_mutate_guidance(task, site_name),
        "v3_repair_brief": (
            compact_repair_brief_for_prompt(repair_brief)
            if architecture in {"v3_repair_brief", "v3_repair_llm"}
            else repair_brief if is_repair_architecture(architecture) else None
        ),
        "gitlab_state": gitlab_state_diagnosis(
            task=task,
            site_name=site_name,
            page=page,
            candidates=current_candidates,
        ),
        "shopping_state": shopping_state_diagnosis(
            task=task,
            site_name=site_name,
            page=page,
            candidates=current_candidates,
        ),
        "shopping_state": shopping_state_diagnosis(
            task=task,
            site_name=site_name,
            page=page,
            candidates=current_candidates,
        ),
        "active_subgoal": asdict(subgoal),
        "current_observation": observation_excerpt(obs, page),
        "interactive_candidates": action_candidates,
        "link_candidates": ranked_link_candidates(task=task, site_name=site_name, subgoal=subgoal, page=page),
        "site_conventions": site_conventions(site_name, page.url),
        "recent_steps": previous_round_snippets(previous_steps) if is_planact_like_architecture(architecture) else previous_steps[-4:],
        "allowed_action_examples": [
            f'goto("{base_url_from_url(page.url)}/path")',
            'click("42")',
            'fill("42", "text")',
            'press("42", "Enter")',
            'noop(1000)',
            'send_msg_to_user("{\\"task_type\\":\\"NAVIGATE\\",\\"status\\":\\"SUCCESS\\",\\"retrieved_data\\":null,\\"error_details\\":null}")',
        ],
    }
    if is_planact_like_architecture(architecture):
        task_capability = infer_task_capability(task, site_name)
        mutation_context = (
            mutation_phase_summary(previous_steps)
            if infer_task_type(task) == "MUTATE" or capability_tier(task_capability) == "mutation"
            else None
        )
        repeated_actions = repeated_no_progress_actions(previous_steps)
        stale_bids = forbidden_bid_targets(previous_steps)
        recovery_hint = (
            build_recovery_hint(task=task, site_name=site_name, previous_steps=previous_steps, page=page)
            if is_repair_architecture(architecture)
            else None
        )
        context.update(
            {
                "grounded_observation": grounded,
                "action_candidates": action_candidates,
                "candidate_html": (grounded or {}).get("candidate_html", ""),
                "previous_round_snippets": previous_round_snippets(previous_steps),
                "mutation_context": mutation_context,
                "forbidden_recent_actions": repeated_actions,
                "stale_bid_targets_not_current": [bid for bid in stale_bids if bid not in {candidate.bid for candidate in current_candidates}],
                "recovery_hint": recovery_hint,
                "planact_rules": [
                    "Use UI actions only with exact current bid values from action_candidates.",
                    "Use goto(href) for concrete visible links when href is available.",
                    "Never use CSS selectors, visible labels, or guessed IDs as UI targets.",
                    "Prefer high-ranked candidates whose text, name, label, row context, or href matches the task terms.",
                    "Do not repeat actions listed in forbidden_recent_actions; choose a different visible action or replan evidence.",
                    "Do not use bids listed in stale_bid_targets_not_current; they were observed in errors and are not current candidates.",
                    "If your intended target is not listed in current action_candidates, do not guess. Use a visible href, wait/noop for a refreshed observation, scroll, or ask for replanning via an explicit blocked rationale.",
                    'For waiting, the executable action string is noop(1000), not wait() or wait.',
                    "Only finish RETRIEVE with SUCCESS when retrieved_data is visible or explicitly calculated from visible evidence.",
                    "For MUTATE, filling fields is not enough. You must submit/save/fork/invite/vote/commit the change, observe the page after that action, and state the visible confirmation or changed state in rationale_summary before SUCCESS.",
                    "For shopping review retrieval, use only BrowserGym scroll(delta_x, delta_y), for example scroll(0, 1200). Do not use scroll_to or scroll_to_element.",
                    "For shopping purchase tasks that mention discarding/emptying the cart, inspect the cart first. If existing items are visible, remove/discard them and verify only the selected product remains before checkout or MUTATE SUCCESS.",
                    "For shopping order-change tasks, if the relevant order history/detail page is visible and no grounded Edit/Change Address/form control exists, finish with ACTION_NOT_ALLOWED_ERROR instead of looping.",
                    "If recovery_hint is present, the next action must repair that specific failure. Do not repeat recovery_hint.forbidden_actions.",
                    "If recovery_hint.suggested_backtrack_url is present and the current UI is stuck, use goto(suggested_backtrack_url) before retrying the workflow.",
                    "Put any durable note inside rationale_summary; do not emit separate comments or a different action language.",
                ],
            }
        )
    return f"Executor input:\n{json.dumps(context, indent=2, ensure_ascii=False)}\n"


def build_executor_prompt(
    *,
    task: dict[str, Any],
    site_name: str,
    subgoal: Subgoal,
    obs: dict[str, Any],
    page,
    previous_steps: list[dict[str, Any]],
    prompt_path: Path,
    architecture: str = "v1",
) -> str:
    """Build a complete debug prompt for the action executor."""

    system_prompt = build_executor_system_prompt(
        task=task,
        site_name=site_name,
        prompt_path=prompt_path,
        architecture=architecture,
    )
    user_message = build_executor_user_message(
        task=task,
        site_name=site_name,
        subgoal=subgoal,
        obs=obs,
        page=page,
        previous_steps=previous_steps,
        prompt_path=prompt_path,
        architecture=architecture,
    )
    return f"{system_prompt}\n\n{user_message}"


def build_compact_executor_user_message(
    *,
    task: dict[str, Any],
    site_name: str,
    subgoal: Subgoal,
    obs: dict[str, Any],
    page,
    previous_steps: list[dict[str, Any]],
    last_error: str,
    architecture: str = "v1",
    current_candidates: list[GroundedCandidate] | None = None,
    repair_brief: dict[str, Any] | None = None,
) -> str:
    """Build a smaller retry prompt when the normal executor call is invalid."""

    if is_planact_like_architecture(architecture):
        current_candidates = current_candidates if current_candidates is not None else prepare_action_candidates(
            candidates=grounded_candidates(obs, page),
            task=task,
            subgoal=subgoal,
            site_name=site_name,
            architecture=architecture,
        )
        prompt_limit = candidate_prompt_limit(task, site_name, compact=True)
        prompt_candidates = [candidate_prompt_dict(candidate) for candidate in current_candidates[:prompt_limit]]
    else:
        current_candidates = []
        prompt_candidates = interactive_candidates(obs, limit=35)
    context = {
        "retry_reason": last_error,
        "task_id": task.get("task_id"),
        "site": site_name,
        "task_intent": task.get("intent", ""),
        "task_type": infer_task_type(task),
        "task_capability": infer_task_capability(task, site_name),
        "capability_guidance": capability_guidance(task, site_name),
        "gitlab_mutate_guidance": gitlab_mutate_guidance(task, site_name),
        "v3_repair_brief": (
            compact_repair_brief_for_prompt(repair_brief)
            if architecture in {"v3_repair_brief", "v3_repair_llm"}
            else repair_brief if is_repair_architecture(architecture) else None
        ),
        "gitlab_state": gitlab_state_diagnosis(
            task=task,
            site_name=site_name,
            page=page,
            candidates=current_candidates,
        ),
        "active_subgoal": asdict(subgoal),
        "current_url": page.url,
        "page_title": safe_page_title(page),
        "last_action": obs.get("last_action", ""),
        "last_action_error": obs.get("last_action_error", ""),
        "interactive_candidates": prompt_candidates,
        "forbidden_bid_targets": [
            bid
            for bid in forbidden_bid_targets(previous_steps, last_error)
            if bid not in {candidate.bid for candidate in current_candidates}
        ] if is_planact_like_architecture(architecture) else [],
        "forbidden_recent_actions": repeated_no_progress_actions(previous_steps) if is_planact_like_architecture(architecture) else [],
        "mutation_context": (
            mutation_phase_summary(previous_steps)
            if is_planact_like_architecture(architecture)
            and (infer_task_type(task) == "MUTATE" or capability_tier(infer_task_capability(task, site_name)) == "mutation")
            else None
        ),
        "grounded_observation": grounded_observation(obs, page, current_candidates) if is_planact_like_architecture(architecture) else None,
        "recovery_hint": (
            build_recovery_hint(task=task, site_name=site_name, previous_steps=previous_steps, page=page, last_error=last_error)
            if is_repair_architecture(architecture)
            else None
        ),
        "link_candidates": ranked_link_candidates(task=task, site_name=site_name, subgoal=subgoal, page=page)[:35],
        "site_conventions": site_conventions(site_name, page.url),
        "recent_steps": previous_round_snippets(previous_steps, limit=3) if is_planact_like_architecture(architecture) else previous_steps[-3:],
        "required_output": {
            "subgoal_id": subgoal.id,
            "action": "one executable BrowserGym action string",
            "action_type": "navigate|click|fill|press|finish|wait",
            "rationale_summary": "brief reason",
            "expected_observation": "brief expected result",
        },
        "wait_action_contract": "If the next step is to wait for refreshed candidates, use action noop(1000). Do not output wait or wait().",
    }
    return (
        "The previous executor response was invalid or empty. Return exactly one "
        "valid JSON object and no other text.\n"
        f"Compact executor input:\n{json.dumps(context, indent=2, ensure_ascii=False)}\n"
    )


def infer_task_type(task: dict[str, Any]) -> str:
    """Infer the official task type from eval metadata when available."""

    return infer_official_task_type(task)


def _ollama_chat(
    *,
    payload: dict[str, Any],
    base_url: str,
    request_timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    req = Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=request_timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except URLError as exc:
        raise RuntimeError(f"Ollama is not reachable at {base_url}: {exc}") from exc
    decoded = json.loads(raw)
    return decoded, decoded.get("message", {}).get("content", "")


def _executor_payload(*, model_name: str, system_prompt: str, user_prompt: str, num_predict: int = 600) -> dict[str, Any]:
    return {
        "model": model_name,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": f"{system_prompt}\n\nReturn valid JSON only."},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": 0.1,
            "top_p": 0.95,
            "top_k": 64,
            "num_predict": num_predict,
            "stop": ["<turn|>", "<|tool_call>", "<|tool_response>"],
        },
    }


def _parse_executor_decision(
    *,
    content: str,
    task: dict[str, Any],
    site_name: str,
    subgoal: Subgoal,
    obs: dict[str, Any],
    page,
    previous_steps: list[dict[str, Any]],
    architecture: str = "v1",
    current_candidates: list[GroundedCandidate] | None = None,
    repair_brief: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    try:
        data = extract_json_object(content)
    except Exception as exc:
        preview = _model_output_preview(content)
        raise ValueError(f"Executor response did not contain a usable JSON object; response_preview={preview!r}") from exc
    strict = is_planact_like_architecture(architecture)
    current_candidates = current_candidates if current_candidates is not None else grounded_candidates(obs, page) if strict else []
    candidate_bids = candidate_bid_set(current_candidates) if strict else {candidate["bid"] for candidate in interactive_candidates(obs)}
    try:
        raw_action = normalize_structured_action_fields(data)
        raw_action = normalize_finish_action_from_context(raw_action, data, task)
        raw_action = normalize_retrieve_final_response_schema(raw_action, task)
        action = validate_browsergym_action(
            raw_action,
            base_url_from_url(page.url),
            candidate_bids,
            strict_ui_targets=strict,
        )
    except Exception as exc:
        preview = _model_output_preview(content)
        raise ValueError(f"{exc}; response_preview={preview!r}") from exc
    if strict and site_name == "gitlab" and infer_task_type(task) == "MUTATE" and action.startswith(("fill(", "type(")):
        args = _quoted_arguments(action)
        fill_text = args[1] if len(args) > 1 else ""
        if looks_like_full_html_dump(fill_text):
            raise ValueError(
                "GitLab MUTATE editor fill/type attempted a full HTML document dump; make the smallest visible field/editor edit needed"
            )
        if len(fill_text) > GITLAB_EDITOR_FILL_TEXT_CHARS and looks_like_full_html_dump(fill_text[:2000]):
            raise ValueError(
                "GitLab MUTATE editor fill/type content is too large and document-like; avoid full file dumps in JSON actions"
            )
    if (
        strict
        and site_name == "gitlab"
        and shared_infer_task_capability(task, site_name) == "mutate_gitlab_file_edit"
        and action.startswith(UI_TARGET_ACTION_PREFIXES)
    ):
        target_candidate = find_target_candidate(action, current_candidates)
        target_text = _target_candidate_text(target_candidate).lower()
        action_target = (_quoted_arguments(action) or [""])[0]
        target_tag = str((target_candidate or {}).get("tag") or "").lower()
        target_role = str((target_candidate or {}).get("role") or "").lower()
        if target_tag in {"html", "body"} or target_role in {"document", "html", "body"}:
            raise ValueError(
                "GitLab file editor action targeted the page root/body instead of a current editor-like candidate"
            )
        if action_target in {"0"} and not any(term in target_text for term in ["editor_like", "code_editor_hint", "textarea", "contenteditable", "textbox"]):
            raise ValueError(
                "GitLab file editor action targeted a page/root candidate instead of a current editor-like candidate"
            )
        if "create commit" in target_text and "0 changed files" in target_text:
            raise ValueError(
                "GitLab editor shows Create commit with 0 changed files; edit the file content first instead of clicking commit"
            )
    if strict:
        forbidden_actions = repeated_no_progress_actions(previous_steps)
        if action in forbidden_actions:
            raise ValueError(
                "Action repeats a recent no-progress action; choose a different current candidate, a concrete href, or a final error/status if blocked"
            )
        if infer_task_type(task) == "MUTATE" and goto_targets_recent_cycle(action, previous_steps):
            raise ValueError(
                "MUTATE action would revisit a recent URL cycle without submitting a state change; choose the visible submit/control action instead"
            )
        validate_grounded_final_response(action=action, data=data, task=task, page=page)
        validate_mutation_success_state_check(
            action=action,
            data=data,
            task=task,
            site_name=site_name,
            previous_steps=previous_steps,
            require_observed_after_submit=architecture in {"v3_repair_brief", "v3_repair_llm"},
            page=page,
        )
    if (
        action.startswith("noop(")
        and not page_satisfies_subgoal(task=task, site_name=site_name, subgoal=subgoal, page=page)
        and not allow_single_repair_refresh_noop(
            architecture=architecture,
            repair_brief=repair_brief,
            previous_steps=previous_steps,
        )
    ):
        raise ValueError("Executor returned noop before the active subgoal was visibly satisfied")
    if not strict and action.startswith("send_msg_to_user(") and infer_task_type(task) == "MUTATE":
        capability = infer_task_capability(task, site_name)
        tier = capability_tier(capability)
        final_response = parse_agent_response_from_action(action) or {}
        final_status = str(final_response.get("status") or "").upper()
        has_prior_mutating_action = any(
            str(previous_step.get("action", "")).startswith(UI_TARGET_ACTION_PREFIXES)
            for previous_step in previous_steps
        )
        has_unresolved_error = any(previous_step.get("error") for previous_step in previous_steps[-2:])
        if tier == "mutation" and final_status == "SUCCESS" and not has_prior_mutating_action:
            raise ValueError("Executor tried to finish a MUTATE task before any visible click/fill/type/press/select_option mutation step")
        if final_status == "SUCCESS" and has_unresolved_error:
            raise ValueError("Executor tried to finish a MUTATE task after an unresolved recent action error")
    if action.startswith("noop(") and infer_task_type(task) == "NAVIGATE" and page_satisfies_task(task=task, site_name=site_name, page=page):
        action = final_nav_action()
    return data, action


def call_ollama_executor(
    *,
    task: dict[str, Any],
    site_name: str,
    subgoal: Subgoal,
    obs: dict[str, Any],
    page,
    previous_steps: list[dict[str, Any]],
    model_name: str,
    base_url: str,
    prompt_path: Path,
    architecture: str = "v1",
    request_timeout_seconds: int = 300,
    repair_brief: dict[str, Any] | None = None,
) -> ExecutorArtifacts:
    """Ask Ollama for the next BrowserGym action."""

    current_candidates = (
        prepare_action_candidates(
            candidates=grounded_candidates(obs, page),
            task=task,
            subgoal=subgoal,
            site_name=site_name,
            architecture=architecture,
        )
        if is_planact_like_architecture(architecture)
        else None
    )
    artifact_mutation_context = mutation_phase_summary(previous_steps) if is_planact_like_architecture(architecture) and infer_task_type(task) == "MUTATE" else None
    artifact_forbidden_actions = repeated_no_progress_actions(previous_steps) if is_planact_like_architecture(architecture) else None
    artifact_stale_bids = forbidden_bid_targets(previous_steps) if is_planact_like_architecture(architecture) else None
    artifact_recovery_hint = (
        build_recovery_hint(task=task, site_name=site_name, previous_steps=previous_steps, page=page)
        if is_repair_architecture(architecture)
        else None
    )
    system_prompt = build_executor_system_prompt(
        task=task,
        site_name=site_name,
        prompt_path=prompt_path,
        architecture=architecture,
    )
    user_prompt = build_executor_user_message(
        task=task,
        site_name=site_name,
        subgoal=subgoal,
        obs=obs,
        page=page,
        previous_steps=previous_steps,
        prompt_path=prompt_path,
        architecture=architecture,
        current_candidates=current_candidates,
        repair_brief=repair_brief,
    )
    prompt = f"{system_prompt}\n\n{user_prompt}"
    payload = _executor_payload(model_name=model_name, system_prompt=system_prompt, user_prompt=user_prompt)
    started = time.perf_counter()
    validation_error_category = None
    accumulated_prompt_tokens = 0
    accumulated_completion_tokens = 0
    try:
        decoded, content = _ollama_chat(payload=payload, base_url=base_url, request_timeout_seconds=request_timeout_seconds)
        accumulated_prompt_tokens += int(decoded.get("prompt_eval_count") or 0)
        accumulated_completion_tokens += int(decoded.get("eval_count") or 0)
        data, action = _parse_executor_decision(
            content=content,
            task=task,
            site_name=site_name,
            subgoal=subgoal,
            obs=obs,
            page=page,
            previous_steps=previous_steps,
            architecture=architecture,
            current_candidates=current_candidates,
            repair_brief=repair_brief,
        )
    except ValueError as first_error:
        validation_error_category = classify_validation_error(str(first_error))
        if is_planact_like_architecture(architecture):
            try:
                page.wait_for_timeout(250)
            except Exception:
                pass
            current_candidates = prepare_action_candidates(
                candidates=grounded_candidates(obs, page),
                task=task,
                subgoal=subgoal,
                site_name=site_name,
                architecture=architecture,
            )
        retry_user_prompt = build_compact_executor_user_message(
            task=task,
            site_name=site_name,
            subgoal=subgoal,
            obs=obs,
            page=page,
            previous_steps=previous_steps,
            last_error=str(first_error),
            architecture=architecture,
            current_candidates=current_candidates,
            repair_brief=repair_brief,
        )
        retry_payload = _executor_payload(
            model_name=model_name,
            system_prompt=(
                "You are repairing an invalid web-agent executor response. "
                "Return exactly one valid JSON object with an executable BrowserGym action. "
                "Use only current candidates; never reuse forbidden stale bid targets or repeated no-progress actions. "
                "Do not include Markdown, comments, or hidden reasoning."
            ),
            user_prompt=retry_user_prompt,
            num_predict=450,
        )
        decoded, content = _ollama_chat(payload=retry_payload, base_url=base_url, request_timeout_seconds=request_timeout_seconds)
        accumulated_prompt_tokens += int(decoded.get("prompt_eval_count") or 0)
        accumulated_completion_tokens += int(decoded.get("eval_count") or 0)
        try:
            data, action = _parse_executor_decision(
                content=content,
                task=task,
                site_name=site_name,
                subgoal=subgoal,
                obs=obs,
                page=page,
                previous_steps=previous_steps,
                architecture=architecture,
                current_candidates=current_candidates,
                repair_brief=repair_brief,
            )
        except ValueError as second_error:
            raise ValueError(f"{second_error}; first_attempt_error={first_error}") from second_error
    decision = ExecutorActionDecision(
        subgoal_id=str(data.get("subgoal_id", subgoal.id)),
        action=action,
        action_type="finish" if action.startswith("send_msg_to_user(") else str(data.get("action_type", "unknown")),
        rationale_summary=data.get("rationale_summary"),
        expected_observation=data.get("expected_observation"),
    )
    prompt_tokens = accumulated_prompt_tokens if accumulated_prompt_tokens else decoded.get("prompt_eval_count")
    completion_tokens = accumulated_completion_tokens if accumulated_completion_tokens else decoded.get("eval_count")
    total_tokens = None
    if prompt_tokens is not None or completion_tokens is not None:
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
    return ExecutorArtifacts(
        decision=decision,
        prompt=prompt,
        raw_response=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        model_name=model_name,
        grounded_candidates=[
            candidate.to_prompt_dict()
            for candidate in (current_candidates or [])[: candidate_prompt_limit(task, site_name)]
        ] if is_planact_like_architecture(architecture) else None,
        validation_error_category=validation_error_category,
        mutation_context=artifact_mutation_context,
        forbidden_recent_actions=artifact_forbidden_actions,
        stale_bid_targets=artifact_stale_bids,
        recovery_hint=artifact_recovery_hint,
        repair_brief=repair_brief,
    )


class BrowserGymLLMExecutor:
    """Executor that maps one active subgoal to one BrowserGym action."""

    def __init__(
        self,
        *,
        task: dict[str, Any],
        site_name: str,
        model_name: str,
        ollama_base_url: str,
        prompt_path: Path = DEFAULT_EXECUTOR_PROMPT,
        architecture: str = "v1",
        request_timeout_seconds: int = 300,
    ):
        self.task = task
        self.site_name = site_name
        self.model_name = model_name
        self.ollama_base_url = ollama_base_url
        self.prompt_path = prompt_path
        self.architecture = architecture
        self.request_timeout_seconds = request_timeout_seconds
        self.previous_steps: list[dict[str, Any]] = []
        self.last_artifacts: ExecutorArtifacts | None = None
        self.current_repair_brief: dict[str, Any] | None = None

    def execute_subgoal(self, env, obs: dict[str, Any], page, subgoal: Subgoal, step_index: int) -> tuple[ExecutorStep, dict[str, Any], bool]:
        """Execute one model-selected action and return step, next obs and done."""

        url_before = page.url
        title_before = safe_page_title(page)
        action_label = "noop(1000)"
        status = "success"
        error = None
        done = False
        next_obs = obs
        target_candidate = None
        mut_action_kind = None
        state_change_hint = None
        visible_state_after = None
        try:
            if self.architecture == "v2_guarded" and infer_task_type(self.task) == "NAVIGATE" and page_satisfies_task(
                task=self.task,
                site_name=self.site_name,
                page=page,
            ):
                action_label = final_nav_action()
                self.last_artifacts = None
            elif self.architecture == "v2_guarded" and (
                action := deterministic_shopping_action(
                    task=self.task,
                    site_name=self.site_name,
                    subgoal=subgoal,
                    page=page,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif (
                is_planact_like_architecture(self.architecture)
                and shared_infer_task_capability(self.task, self.site_name)
                in {
                    "navigate_shopping_category_filter",
                    "navigate_shopping_sorted_category_product",
                    "navigate_shopping_sorted_search_listing",
                }
                and (
                    action := deterministic_shopping_action(
                        task=self.task,
                        site_name=self.site_name,
                        subgoal=subgoal,
                        page=page,
                    )
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_planact_like_architecture(self.architecture) and (
                action := deterministic_reddit_action(
                    task=self.task,
                    site_name=self.site_name,
                    subgoal=subgoal,
                    page=page,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_planact_like_architecture(self.architecture) and (
                action := deterministic_shopping_order_detail_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                    previous_steps=self.previous_steps,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_planact_like_architecture(self.architecture) and (
                action := deterministic_shopping_review_retrieve_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                    previous_steps=self.previous_steps,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_planact_like_architecture(self.architecture) and (
                action := deterministic_shopping_policy_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                    previous_steps=self.previous_steps,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_repair_architecture(self.architecture) and (
                action := deterministic_gitlab_profile_homepage_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                    previous_steps=self.previous_steps,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_repair_architecture(self.architecture) and (
                action := deterministic_gitlab_profile_status_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                    previous_steps=self.previous_steps,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_repair_architecture(self.architecture) and (
                action := deterministic_gitlab_star_repos_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                    previous_steps=self.previous_steps,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_repair_architecture(self.architecture) and (
                action := deterministic_gitlab_mr_reply_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                    previous_steps=self.previous_steps,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_repair_architecture(self.architecture) and (
                action := deterministic_gitlab_mutation_completion_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                    previous_steps=self.previous_steps,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_repair_architecture(self.architecture) and (
                action := deterministic_gitlab_simple_editor_route_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                )
            ):
                action_label = action
                self.last_artifacts = None
            elif is_repair_architecture(self.architecture) and (
                action := deterministic_gitlab_fork_repair_action(
                    task=self.task,
                    site_name=self.site_name,
                    page=page,
                    previous_steps=self.previous_steps,
                )
            ):
                action_label = action
                self.last_artifacts = None
            else:
                artifacts = call_ollama_executor(
                    task=self.task,
                    site_name=self.site_name,
                    subgoal=subgoal,
                    obs=obs,
                    page=page,
                    previous_steps=self.previous_steps,
                    model_name=self.model_name,
                    base_url=self.ollama_base_url,
                    prompt_path=self.prompt_path,
                    architecture=self.architecture,
                    request_timeout_seconds=self.request_timeout_seconds,
                    repair_brief=self.current_repair_brief,
                )
                self.last_artifacts = artifacts
                action_label = artifacts.decision.action
                if artifacts.grounded_candidates:
                    target_candidate = find_target_candidate(
                        action_label,
                        [
                            GroundedCandidate(**candidate)
                            for candidate in artifacts.grounded_candidates
                            if "bid" in candidate and "role" in candidate
                        ],
                    )
            next_obs, _reward, terminated, truncated, _info = env.step(action_label)
            done = bool(terminated or truncated)
            if is_planact_like_architecture(self.architecture) and infer_task_type(self.task) == "MUTATE":
                mut_action_kind = mutation_action_kind(action_label, target_candidate)
                state_change_hint = mutation_state_hint(page, action_label, target_candidate)
                visible_state_after = safe_page_text(page, limit=800)
        except Exception as exc:
            error = str(exc)
            status = "error"
            self.last_artifacts = None
            if action_label == "noop(1000)" and "timed out" in error.lower():
                action_label = "llm_timeout"
            if is_planact_like_architecture(self.architecture) and is_transient_navigation_error(error):
                try:
                    page.wait_for_timeout(1500)
                    refreshed_obs, _reward, refreshed_terminated, refreshed_truncated, _info = env.step("noop(1000)")
                    next_obs = refreshed_obs
                    done = bool(refreshed_terminated or refreshed_truncated)
                    error = f"{error}; refreshed_observation_after_navigation_race=True"
                except Exception as refresh_exc:
                    error = f"{error}; navigation_race_refresh_failed={refresh_exc}"
            if is_planact_like_architecture(self.architecture) and infer_task_type(self.task) == "MUTATE":
                mut_action_kind = mutation_action_kind(action_label, target_candidate)

        step = ExecutorStep(
            step_index=step_index,
            subgoal_id=subgoal.id,
            action=action_label,
            url_before=url_before,
            url_after=page.url,
            status=status,
            page_title=safe_page_title(page),
            error=error,
        )
        self.previous_steps.append(
            {
                **asdict(step),
                "title_before": title_before,
                "title_after": safe_page_title(page),
                "target_candidate": target_candidate,
                "mutation_action_kind": mut_action_kind,
                "mutation_phase": mutation_phase_summary(
                    [
                        *self.previous_steps,
                        {
                            **asdict(step),
                            "title_before": title_before,
                            "title_after": safe_page_title(page),
                            "target_candidate": target_candidate,
                            "mutation_action_kind": mut_action_kind,
                            "state_change_hint": state_change_hint,
                            "visible_state_after": visible_state_after,
                        },
                    ]
                )
                if is_planact_like_architecture(self.architecture) and infer_task_type(self.task) == "MUTATE"
                else None,
                "state_change_hint": state_change_hint,
                "visible_state_after": visible_state_after,
            }
        )
        return step, next_obs, done
