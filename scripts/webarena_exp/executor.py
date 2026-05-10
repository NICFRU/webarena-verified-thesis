"""Minimal executor interfaces for BrowserGym/WebArena task prototypes."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from .types import ExecutorStep, Subgoal


def task44_target_url(start_url: str) -> str:
    """Return the GitLab Task-44 destination URL for the active environment."""

    parsed = urlparse(start_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid start_url: {start_url}")
    return f"{parsed.scheme}://{parsed.netloc}/dashboard/todos"


def absolute_url(start_url: str, path: str) -> str:
    """Build an absolute URL from a site start URL and a site-relative path."""

    return urljoin(start_url.rstrip("/") + "/", path.lstrip("/"))


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
        password_input.press("Enter")

    page.wait_for_load_state("networkidle")
    return True


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
            if any(keyword in subgoal_text for keyword in ["login", "auth", "authenticated", "sign in"]):
                did_login = login_gitlab_if_needed(page, self.credentials)
                action_label = "login_if_needed" if did_login else "login_skipped"
            elif any(keyword in subgoal_text for keyword in ["todo", "todos", "/dashboard/todos"]):
                action_label = f'goto("{self.target_url}")'
                env.step(action_label)
            else:
                action_label = "assert_current_page_relevant"
            page.wait_for_load_state("networkidle", timeout=10000)
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
            page.wait_for_load_state("networkidle", timeout=10000)
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

        page.wait_for_load_state("networkidle", timeout=10000)
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
