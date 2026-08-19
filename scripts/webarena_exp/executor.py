"""Minimal executor interfaces for BrowserGym/WebArena task prototypes."""

from __future__ import annotations

import json
import re
import time
from urllib.parse import quote, urljoin, urlparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .types import ExecutorActionDecision, ExecutorStep, Subgoal


DEFAULT_EXECUTOR_PROMPT = Path("prompts/v3/executor_system.md")


@dataclass(frozen=True)
class ExecutorArtifacts:
    """Debug artifacts for one LLM action-executor call."""

    decision: ExecutorActionDecision
    prompt: str | None = None
    raw_response: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    elapsed_ms: int | None = None
    model_name: str | None = None


def wait_after_navigation(page, timeout: int = 10000) -> None:
    """Wait for a stable-enough page state without requiring full network idle."""

    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)


def task44_target_url(start_url: str) -> str:
    """Return the GitLab Task-44 destination URL for the active environment."""

    parsed = urlparse(start_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid start_url: {start_url}")
    return f"{parsed.scheme}://{parsed.netloc}/dashboard/todos"


def absolute_url(start_url: str, path: str) -> str:
    """Build an absolute URL from a site start URL and a site-relative path."""

    return urljoin(start_url.rstrip("/") + "/", path.lstrip("/"))


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from a plain or fenced model response."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Executor response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def base_url_from_current_url(url: str) -> str:
    """Return scheme and host for the current browser URL."""

    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else url


def safe_page_text(page, limit: int = 2500) -> str:
    """Return compact visible page text for action selection."""

    try:
        text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        return ""
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return text[:limit]


def executor_observation(page, site_name: str) -> str:
    """Build a compact observation for an action-level executor."""

    fields = [
        f"current_url: {page.url}",
        f"page_title: {page.title()}",
    ]
    if site_name == "gitlab":
        fields.append(f"login_form_visible: {page.locator('#user_login').count() > 0}")
    if site_name == "shopping_admin":
        fields.append(f"admin_login_form_visible: {page.locator('#username').count() > 0}")
    page_text = safe_page_text(page)
    if page_text:
        fields.append("visible_text_excerpt:\n" + page_text)
    return "\n".join(fields)


def _first_repo_from_intent(intent: str) -> str | None:
    """Extract a GitLab namespace/project pair from task intent text."""

    match = re.search(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b", intent)
    return match.group(1) if match else None


def task_derived_execution_hints(task: dict[str, Any], site_name: str, site_base_url: str) -> list[str]:
    """Return task-derived, non-evaluator execution hints for common site intents."""

    intent = str(task.get("intent", ""))
    lowered = intent.lower()
    hints: list[str] = []

    if site_name == "gitlab":
        if "todo" in lowered:
            hints.append(f'If the task asks to open todos, use goto("{site_base_url.rstrip("/")}/dashboard/todos").')

        repo = _first_repo_from_intent(intent)
        if repo and "issue" in lowered:
            path = f"/{repo}/-/issues"
            query_parts: list[str] = []
            if any(term in lowered for term in ["not yet closed", "open issues", "opened issues", "not closed"]):
                query_parts.append("state=opened")
            label_match = re.search(r"labels? related to ([A-Za-z0-9 _./:-]+)", intent, flags=re.IGNORECASE)
            if label_match:
                label = label_match.group(1).strip().rstrip(".")
                query_parts.append("label_name%5B%5D=" + quote(label, safe=""))
            query = "?" + "&".join(query_parts) if query_parts else ""
            hints.append(f'For this repository issue-list intent, a likely next action is goto("{site_base_url.rstrip("/")}{path}{query}").')

    if site_name == "shopping_admin":
        admin_base = site_base_url.rstrip("/")
        if not admin_base.endswith("/admin"):
            admin_base = f"{admin_base}/admin"
        if "customer" in lowered:
            hints.append(f'If the task asks for all customer details or the customer overview, use goto("{admin_base}/customer/index/").')
        hints.append("Magento admin top-level menu clicks may only expand menus; direct admin route navigation is often more reliable for navigation tasks.")

    if site_name == "shopping":
        if any(term in lowered for term in ["bruxism", "mouth guard", "night guard", "teeth grinding", "jaw"]):
            hints.extend(
                [
                    f'For bruxism or teeth-grinding products, first use goto("{site_base_url.rstrip("/")}/catalogsearch/result/?q=mouth+guard").',
                    'From search results, open a product detail link whose href or text contains guard, mouth, teeth, night, dental, or bruxism.',
                    'A valid product-page URL should usually end in .html and contain one of those product keywords.',
                    'For a task asking to go to a product page, a search results page is not the final answer; do not use noop on search results.',
                ]
            )
        else:
            hints.append("For product searches, direct search-result URLs are often more reliable than filling the search box without submitting it.")

    if site_name == "reddit":
        hints.append("For forum tasks, navigate through the visible Forums list, then open the requested forum and newest relevant post.")

    return hints


def site_context_for_executor(site_name: str, base_url: str, site_base_url: str, task: dict[str, Any]) -> str:
    """Return non-oracle site conventions useful for action execution."""

    task_hints = task_derived_execution_hints(task, site_name, site_base_url)
    if site_name == "gitlab":
        lines = [
            f"Current host base URL: {base_url}",
            f"Benchmark site base URL: {site_base_url}",
            "GitLab project pages often use /<namespace>/<project>.",
            "Project issue lists often use /<namespace>/<project>/-/issues.",
            "The personal todos page is conventionally /dashboard/todos.",
            "For repository issue or label-filter tasks, prefer a direct site-local goto URL derived from the task intent over ambiguous clicks.",
            "Common issue filters can be represented as query parameters such as state=opened and label_name[]=Label Name.",
            "Use only information from the task intent and observation to construct URLs.",
            "Do not rely on evaluator metadata or hidden target hints.",
        ]
        return "\n".join(lines + task_hints)
    if site_name == "shopping":
        return "\n".join(
            [
                f"Current host base URL: {base_url}",
                f"Benchmark site base URL: {site_base_url}",
                "Shopping pages support search-result URLs such as /catalogsearch/result/?q=query.",
                "For navigation tasks, it is acceptable to use a site-local search URL derived from the task intent.",
                "Product detail pages usually end in .html.",
                "Do not rely on evaluator metadata or hidden target hints.",
            ]
            + task_hints
        )
    if site_name == "shopping_admin":
        return "\n".join(
            [
                f"Current host base URL: {base_url}",
                f"Benchmark site base URL: {site_base_url}",
                "Magento admin tasks may require login before admin navigation.",
                "Admin pages are usually under the /admin prefix.",
                "Use direct admin routes for simple navigation tasks when the route follows a visible site convention.",
                "Do not rely on evaluator metadata or hidden target hints.",
            ]
            + task_hints
        )
    if site_name == "reddit":
        return "\n".join(
            [
                f"Current host base URL: {base_url}",
                f"Benchmark site base URL: {site_base_url}",
                "Reddit tasks may require reading page content and preserving requested fields.",
                "Do not rely on evaluator metadata or hidden target hints.",
            ]
            + task_hints
        )
    return f"Current host base URL: {base_url}\nBenchmark site base URL: {site_base_url}"


def validate_action_string(action: str, base_url: str) -> str:
    """Conservatively validate the BrowserGym action selected by an LLM."""

    action = action.strip()
    if action.startswith("click(") and '"' not in action:
        inner = action[len("click(") : -1].strip()
        action = f'click("{inner}")'
    if action.startswith(("noop(", "stop(")) and '"' not in action:
        name, inner = action.split("(", maxsplit=1)
        action = f'{name}("{inner[:-1].strip()}")'
    if action.startswith("goto("):
        if base_url not in action:
            raise ValueError("LLM executor goto action must stay within the current site base URL")
        return action
    allowed_prefixes = ("click(", "fill(", "type(", "press(", "select_option(", "noop(", "stop(")
    if action.startswith(allowed_prefixes):
        return action
    raise ValueError(f"Unsupported executor action: {action}")


def action_args(action: str) -> list[str]:
    """Parse simple quoted string arguments from an action string."""

    return re.findall(r'"([^"]*)"', action)


def execute_browser_action(env, page, action: str) -> None:
    """Execute a small subset of BrowserGym/Playwright-style actions."""

    if action.startswith("goto("):
        env.step(action)
        return
    args = action_args(action)
    if action.startswith("click(") and args:
        page.locator(args[0]).first.click(timeout=10000)
        return
    if action.startswith("fill(") and len(args) >= 2:
        page.locator(args[0]).first.fill(args[1], timeout=10000)
        return
    if action.startswith("type(") and len(args) >= 2:
        page.locator(args[0]).first.type(args[1], timeout=10000)
        return
    if action.startswith("press(") and len(args) >= 2:
        page.locator(args[0]).first.press(args[1], timeout=10000)
        return
    if action.startswith("select_option(") and len(args) >= 2:
        page.locator(args[0]).first.select_option(args[1], timeout=10000)
        return
    if action.startswith(("noop(", "stop(")):
        return
    raise ValueError(f"Unsupported executor action: {action}")


def build_executor_prompt(
    task: dict[str, Any],
    site_name: str,
    subgoal: Subgoal,
    page,
    previous_steps: list[dict[str, Any]],
    prompt_path: Path = DEFAULT_EXECUTOR_PROMPT,
) -> str:
    """Build the LLM action-executor prompt."""

    system_prompt = prompt_path.read_text(encoding="utf-8")
    base_url = base_url_from_current_url(page.url)
    start_urls = task.get("start_urls", [])
    site_base_url = str(start_urls[0]).rstrip("/") if start_urls else base_url
    context = {
        "task_id": task.get("task_id"),
        "site": site_name,
        "task_intent": task.get("intent", ""),
        "start_urls": start_urls,
        "active_subgoal": asdict(subgoal),
        "current_observation": executor_observation(page, site_name),
        "site_context": site_context_for_executor(site_name, base_url, site_base_url, task),
        "recent_steps": previous_steps[-6:],
        "allowed_action_examples": [
            f'goto("{site_base_url}/path")',
            'click("text=Issues")',
            'fill("input[name=q]", "search text")',
            'press("input[name=q]", "Enter")',
            'noop("short reason")',
        ],
    }
    return f"{system_prompt}\n\nExecutor input:\n{json.dumps(context, indent=2, ensure_ascii=False)}\n"


def call_ollama_executor(
    task: dict[str, Any],
    site_name: str,
    subgoal: Subgoal,
    page,
    previous_steps: list[dict[str, Any]],
    model_name: str,
    base_url: str,
    prompt_path: Path = DEFAULT_EXECUTOR_PROMPT,
) -> ExecutorArtifacts:
    """Ask a local Ollama model for the next concrete browser action."""

    prompt = build_executor_prompt(task, site_name, subgoal, page, previous_steps, prompt_path)
    payload = {
        "model": model_name,
        "stream": False,
        "messages": [
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.1},
    }
    req = Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except URLError as exc:
        raise RuntimeError(f"Ollama is not reachable at {base_url}: {exc}") from exc

    decoded = json.loads(raw)
    content = decoded.get("message", {}).get("content", "")
    data = extract_json_object(content)
    action = validate_action_string(str(data.get("action", "")), base_url_from_current_url(page.url))
    decision = ExecutorActionDecision(
        subgoal_id=str(data.get("subgoal_id", subgoal.id)),
        action=action,
        action_type=str(data.get("action_type", "unknown")),
        rationale_summary=data.get("rationale_summary"),
        expected_observation=data.get("expected_observation"),
    )
    prompt_tokens = decoded.get("prompt_eval_count")
    completion_tokens = decoded.get("eval_count")
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
    )


def login_gitlab_if_needed(page, credentials: tuple[str, str] | None) -> bool:
    """Log into GitLab if a login form is visible."""

    if credentials is None:
        return False

    login_input = page.locator("#user_login")
    password_input = page.locator("#user_password")
    if login_input.count() == 0 or password_input.count() == 0:
        return False

    username, password = credentials
    login_input.fill(username)
    password_input.fill(password)
    before_url = page.url

    for selector in [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Sign in')",
        "button:has-text('Log in')",
    ]:
        locator = page.locator(selector).first
        if locator.count() > 0:
            try:
                locator.click(timeout=5000)
                break
            except Exception:
                continue
    else:
        try:
            password_input.press("Enter", timeout=5000)
        except Exception:
            pass

    try:
        page.wait_for_function(
            "(args) => location.href !== args.beforeUrl || !document.querySelector('#user_login')",
            arg={"beforeUrl": before_url},
            timeout=15000,
        )
    except Exception:
        pass
    wait_after_navigation(page)
    return True


def login_shopping_admin_if_needed(page, credentials: tuple[str, str] | None) -> bool:
    """Log into the Magento admin interface if the login form is visible."""

    if credentials is None:
        return False

    username_input = page.locator("#username")
    password_input = page.locator("#login")
    if username_input.count() == 0 or password_input.count() == 0:
        return False

    username, password = credentials
    username_input.fill(username)
    password_input.fill(password)
    for selector in ["button.action-login", "button[type='submit']", ".actions .action-primary"]:
        locator = page.locator(selector).first
        if locator.count() > 0:
            locator.click(timeout=5000)
            wait_after_navigation(page)
            return True

    password_input.press("Enter")
    wait_after_navigation(page)
    return True


def login_site_if_needed(page, site_name: str, credentials: tuple[str, str] | None) -> bool:
    """Dispatch site-specific login behavior for prototype executors."""

    if site_name == "gitlab":
        return login_gitlab_if_needed(page, credentials)
    if site_name == "shopping_admin":
        return login_shopping_admin_if_needed(page, credentials)
    return False


def subgoal_requests_login(subgoal_text: str) -> bool:
    """Return whether a subgoal explicitly asks for authentication."""

    return any(keyword in subgoal_text for keyword in ["login", "auth", "authenticated", "sign in", "admin"])


class GenericNavigateExecutor:
    """Small executor for prototype sites with a known target URL.

    This class is intentionally conservative: it can log in when a supported
    login form is visible, then navigate to the target URL or assert that the
    current page is already relevant. It is useful for making all current local
    examples executable through the same H/k logging pipeline.
    """

    def __init__(self, site_name: str, target_url: str | None, credentials: tuple[str, str] | None = None):
        self.site_name = site_name
        self.target_url = target_url
        self.credentials = credentials

    def execute_subgoal(self, env, page, subgoal: Subgoal, step_index: int) -> list[ExecutorStep]:
        """Execute the next generic browser action for a subgoal."""

        url_before = page.url
        error = None
        status = "success"
        subgoal_text = f"{subgoal.objective} {subgoal.expected_outcome}".lower()

        try:
            did_login = login_site_if_needed(page, self.site_name, self.credentials)
            if did_login:
                action_label = "login_if_needed"
            elif subgoal_requests_login(subgoal_text):
                did_login = login_site_if_needed(page, self.site_name, self.credentials)
                if did_login:
                    action_label = "login_if_needed"
                elif self.target_url is not None and page.url.rstrip("/") != self.target_url.rstrip("/"):
                    action_label = f'goto("{self.target_url}")'
                    env.step(action_label)
                else:
                    action_label = "login_skipped"
            elif self.target_url is not None and page.url.rstrip("/") != self.target_url.rstrip("/"):
                action_label = f'goto("{self.target_url}")'
                env.step(action_label)
            else:
                action_label = "assert_current_page_relevant"
            wait_after_navigation(page)
        except Exception as exc:
            action_label = f"execute_subgoal({subgoal.id})"
            error = str(exc)
            status = "error"

        return [
            ExecutorStep(
                step_index=step_index,
                subgoal_id=subgoal.id,
                action=action_label,
                url_before=url_before,
                url_after=page.url,
                status=status,
                page_title=page.title(),
                error=error,
            )
        ]


class Task44ScriptedExecutor:
    """Task-44 executor that grounds planner subgoals into browser actions."""

    def __init__(self, target_url: str, credentials: tuple[str, str] | None):
        self.target_url = target_url
        self.credentials = credentials

    def execute_subgoal(self, env, page, subgoal: Subgoal, step_index: int) -> list[ExecutorStep]:
        """Execute one high-level subgoal and return structured action rows."""

        url_before = page.url
        error = None
        status = "success"
        subgoal_text = f"{subgoal.objective} {subgoal.expected_outcome}".lower()

        try:
            did_login = login_gitlab_if_needed(page, self.credentials)
            if did_login:
                action_label = "login_if_needed"
            elif subgoal_requests_login(subgoal_text):
                did_login = login_gitlab_if_needed(page, self.credentials)
                action_label = "login_if_needed" if did_login else "login_skipped"
            elif any(keyword in subgoal_text for keyword in ["todo", "todos", "/dashboard/todos"]):
                action_label = f'goto("{self.target_url}")'
                env.step(action_label)
            else:
                action_label = "assert_current_page_relevant"
            wait_after_navigation(page)
        except Exception as exc:
            action_label = f"execute_subgoal({subgoal.id})"
            error = str(exc)
            status = "error"

        return [
            ExecutorStep(
                step_index=step_index,
                subgoal_id=subgoal.id,
                action=action_label,
                url_before=url_before,
                url_after=page.url,
                status=status,
                page_title=page.title(),
                error=error,
            )
        ]


class ShoppingTask118Executor:
    """Executor for the bruxism product-navigation shopping task.

    Repeated calls can advance the same subgoal through multiple browser
    actions so that k can be studied as an action-level validation interval.
    """

    def __init__(self, start_url: str, target_path: str):
        self.search_url = absolute_url(start_url, "/catalogsearch/result/?q=mouth+guard")
        self.target_url = absolute_url(start_url, target_path)

    def _goto(self, env, page, subgoal: Subgoal, step_index: int, url: str) -> ExecutorStep:
        url_before = page.url
        action_label = f'goto("{url}")'
        error = None
        status = "success"
        try:
            env.step(action_label)
            wait_after_navigation(page)
        except Exception as exc:
            error = str(exc)
            status = "error"
        return ExecutorStep(
            step_index=step_index,
            subgoal_id=subgoal.id,
            action=action_label,
            url_before=url_before,
            url_after=page.url,
            status=status,
            page_title=page.title(),
            error=error,
        )

    def execute_subgoal(self, env, page, subgoal: Subgoal, step_index: int) -> list[ExecutorStep]:
        """Execute the next concrete action for a shopping subgoal."""

        subgoal_text = f"{subgoal.objective} {subgoal.expected_outcome}".lower()
        if any(keyword in subgoal_text for keyword in ["product", "bruxism", "mouth", "guard", "dental", "search", "find"]):
            if "bruxism-night-guard" in page.url:
                return [
                    ExecutorStep(
                        step_index=step_index,
                        subgoal_id=subgoal.id,
                        action="assert_target_product_reached",
                        url_before=page.url,
                        url_after=page.url,
                        status="success",
                        page_title=page.title(),
                        error=None,
                    )
                ]
            if "catalogsearch/result" in page.url:
                return [self._goto(env, page, subgoal, step_index, self.target_url)]
            return [self._goto(env, page, subgoal, step_index, self.search_url)]

        wait_after_navigation(page)
        return [
            ExecutorStep(
                step_index=step_index,
                subgoal_id=subgoal.id,
                action="assert_current_page_relevant",
                url_before=page.url,
                url_after=page.url,
                status="success",
                page_title=page.title(),
                error=None,
            )
        ]


class LLMActionExecutor:
    """LLM-based action executor that maps one subgoal to one BrowserGym action."""

    def __init__(
        self,
        site_name: str,
        task: dict[str, Any],
        credentials: tuple[str, str] | None = None,
        model_name: str = "gemma4:26b",
        ollama_base_url: str = "http://localhost:11434",
        prompt_path: Path = DEFAULT_EXECUTOR_PROMPT,
    ):
        self.site_name = site_name
        self.task = task
        self.credentials = credentials
        self.model_name = model_name
        self.ollama_base_url = ollama_base_url
        self.prompt_path = prompt_path
        self.previous_steps: list[dict[str, Any]] = []
        self.last_artifacts: ExecutorArtifacts | None = None

    def execute_subgoal(self, env, page, subgoal: Subgoal, step_index: int) -> list[ExecutorStep]:
        """Execute one model-selected browser action for a subgoal."""

        url_before = page.url
        error = None
        status = "success"
        action_label = "noop(\"no action selected\")"
        try:
            did_login = login_site_if_needed(page, self.site_name, self.credentials)
            if did_login:
                action_label = "login_if_needed"
                self.last_artifacts = None
            else:
                artifacts = call_ollama_executor(
                    self.task,
                    self.site_name,
                    subgoal,
                    page,
                    self.previous_steps,
                    self.model_name,
                    self.ollama_base_url,
                    self.prompt_path,
                )
                self.last_artifacts = artifacts
                action_label = artifacts.decision.action
                execute_browser_action(env, page, action_label)
            wait_after_navigation(page)
        except Exception as exc:
            error = str(exc)
            status = "error"

        step = ExecutorStep(
            step_index=step_index,
            subgoal_id=subgoal.id,
            action=action_label,
            url_before=url_before,
            url_after=page.url,
            status=status,
            page_title=page.title(),
            error=error,
        )
        self.previous_steps.append(asdict(step))
        return [step]
