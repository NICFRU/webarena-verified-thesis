"""Runtime repair hints for v3 H/k agent runs.

The hints are deliberately rule-based and task-local: they inspect only visible
state, recent actions/errors, and public task intent. They do not use evaluator
gold answers. The goal is to make k-step validation useful as a repair signal
instead of repeatedly asking the planner to rediscover the same failure.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def is_repair_architecture(architecture: str) -> bool:
    return architecture in {"v3", "v3_repair_brief", "v3_repair_llm"}


def is_planact_like_architecture(architecture: str) -> bool:
    return architecture in {"v2_planact", "v3", "v3_repair_brief", "v3_repair_llm"}


def recent_step_text(previous_steps: list[dict[str, Any]], limit: int = 6) -> str:
    rows = previous_steps[-limit:]
    return "\n".join(
        " ".join(
            str(value or "")
            for value in [
                row.get("action"),
                row.get("error"),
                row.get("target_candidate"),
                row.get("visible_state_after"),
            ]
        )
        for row in rows
    ).lower()


def recent_action_counts(previous_steps: list[dict[str, Any]], limit: int = 8) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in previous_steps[-limit:]:
        action = str(row.get("action") or "")
        if not action:
            continue
        counts[action] = counts.get(action, 0) + 1
    return counts


def stable_backtrack_url(previous_steps: list[dict[str, Any]], current_url: str) -> str | None:
    """Return a recent URL outside a modal/editor/fork dead-end when available."""

    bad_markers = [
        "/-/ide/",
        "/-/forks/new",
        "/group_members",
        "merge_requests/new",
    ]
    for row in reversed(previous_steps[:-1]):
        for key in ("url_before", "url_after"):
            url = str(row.get(key) or "")
            if not url or url == current_url:
                continue
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                continue
            if any(marker in url for marker in bad_markers):
                continue
            return url
    return None


def _page_text(page, limit: int = 4000) -> str:
    try:
        return " ".join(page.locator("body").inner_text(timeout=1000).split())[:limit]
    except Exception:
        return ""


def stale_bid_targets_from_text(text: str) -> list[str]:
    """Extract bid-like values from invalid/stale-target error messages."""

    targets: list[str] = []
    for pattern in [
        r"Action target '([^']+)' is not a current interactive candidate bid",
        r'Action target "([^"]+)" is not a current interactive candidate bid',
        r"target ([A-Za-z0-9_-]+)!? is not a current interactive candidate",
    ]:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            target = match.group(1)
            if target not in targets:
                targets.append(target)
    return targets


def build_recovery_hint(
    *,
    task: dict[str, Any],
    site_name: str,
    previous_steps: list[dict[str, Any]],
    page,
    last_error: str | None = None,
) -> dict[str, Any] | None:
    """Build one compact repair hint from the current state and recent failures."""

    if not previous_steps and not last_error:
        return None
    intent = str(task.get("intent") or "").lower()
    current_url = str(getattr(page, "url", "") or "")
    visible = _page_text(page).lower()
    recent = recent_step_text(previous_steps)
    combined = "\n".join([recent, str(last_error or "").lower(), current_url.lower(), visible])
    repeated = [action for action, count in recent_action_counts(previous_steps).items() if count >= 2]
    stale_targets = stale_bid_targets_from_text("\n".join([recent, str(last_error or "")]))
    hint: dict[str, Any] | None = None

    if stale_targets:
        hint = {
            "error_class": "invalid_bid_or_stale_candidate",
            "diagnosis": f"The executor used bid(s) that are not current candidates: {', '.join(stale_targets[:6])}.",
            "repair_goal": "Discard stale or guessed bids. Re-read the current action_candidates and choose only an exact current bid, or use a concrete same-site href from link_candidates with goto(...).",
            "prompt_note": "Do not reuse stale_bid_targets. If the desired UI target has no current bid, do not invent one; use a visible href, keyboard selection on the current focused control, scroll/wait for a refreshed observation, or backtrack.",
            "stale_bid_targets": stale_targets[:8],
        }
        if site_name == "gitlab" and "invite members" in combined and "username or email address" in combined:
            hint["error_class"] = "gitlab_invite_modal_missing_candidate"
            hint["diagnosis"] = (
                "The invite modal is visible, but the executor is using stale/background bids instead of a current modal input or submit bid."
            )
            hint["repair_goal"] = (
                "Use only current inside-modal candidates for username/email, role, or Invite/Add. Do not use Filter members or modal container bids. If multiple users are requested, select all user chips/tokens before submitting."
            )
            hint["prompt_note"] = (
                "The modal exists but its usable input was not grounded. Do not guess stale bids; use noop(1000) once for refreshed candidates or refocus a current modal control. Do not click Invite/Add until every named user is selected."
            )
        if site_name == "gitlab" and "simple online file editor" in intent and any(term in combined for term in ["body", "html", "editor", "line"]):
            hint["error_class"] = "gitlab_editor_missing_candidate"
            hint["diagnosis"] = (
                "The simple editor page is visible, but the executor is using symbolic editor targets or stale bids."
            )
            hint["repair_goal"] = (
                "Choose a current editor-like bid from action_candidates, such as a textarea/textbox/contenteditable candidate. Never target body/html/editor/line numbers."
            )
    elif site_name == "gitlab" and "simple online file editor" in intent and "/-/ide/" in current_url:
        hint = {
            "error_class": "gitlab_simple_editor_wrong_ide",
            "diagnosis": "The task asks for GitLab's simple online file editor, but the current page is the full Web IDE.",
            "repair_goal": "Leave the Web IDE and navigate to the simple file edit route for the target file: /<namespace>/<project>/-/edit/<branch>/<file>.",
            "prompt_note": "Do not continue editing in the Web IDE/Monaco view for simple-online-editor tasks. Use the simple edit page, then commit through the normal file update form.",
        }
    elif site_name == "gitlab" and (
        "<!doctype html" in combined or (combined.count("<html") >= 1 and combined.count("<meta") >= 2)
    ):
        hint = {
            "error_class": "gitlab_editor_html_dump",
            "diagnosis": "The previous executor response attempted to fill a full HTML document or page source.",
            "repair_goal": "Edit only the minimal target text/value requested by the task; never output full page source in JSON.",
            "prompt_note": "The last response contained an HTML dump. Return only a minimal BrowserGym action such as type/fill with the target string, not the whole file.",
        }
    elif site_name == "gitlab" and "create commit" in combined and "0 changed files" in combined:
        hint = {
            "error_class": "gitlab_editor_zero_changed_files",
            "diagnosis": "GitLab shows Create commit with 0 changed files, so the editor has not registered a real edit.",
            "repair_goal": "Do not click commit yet. Focus the current editor/code candidate and make the minimal requested text change first.",
            "prompt_note": "0 changed files means no durable edit. Repair by editing the visible file content before committing.",
        }
    elif site_name == "gitlab" and ("select a namespace" in combined or "/-/forks/new" in current_url) and repeated:
        hint = {
            "error_class": "gitlab_namespace_dropdown_stuck",
            "diagnosis": "The fork namespace dropdown is being opened/clicked repeatedly without selecting a namespace.",
            "repair_goal": "Stop repeating the dropdown toggle. If namespace options are visible inside the dropdown HTML but have no own bid, focus the current namespace dropdown bid and use keyboard selection.",
            "prompt_note": "The namespace selector is stuck. Do not click the same toggle forever. For GitLab fork dropdowns, use click on the current Select-a-namespace bid, then press ArrowDown/Enter on that same bid when options like x-lab are visible but unbidded.",
        }
    elif site_name == "gitlab" and ("filter members" in combined or "invite members" in combined) and (
        "username or email address" in combined or "click(\"invite\")" in combined or 'click("invite")' in combined
    ):
        hint = {
            "error_class": "gitlab_invite_modal_wrong_input",
            "diagnosis": "The agent is likely filling the members table filter or clicking visible text instead of the invite modal input/submit bid.",
            "repair_goal": "Open or refocus the Invite members modal, target only current dialog/modal candidates, add all requested users when multiple are named, and never use click(\"Invite\").",
            "prompt_note": "Do not fill Filter members for inviting users. Use the current modal Username/email input and current modal Invite button bid after every requested user is selected.",
        }
    elif repeated:
        hint = {
            "error_class": "repeated_no_progress_action",
            "diagnosis": "Recent actions repeat without observable page progress.",
            "repair_goal": "Choose a different current candidate, use a concrete visible href, or backtrack to the last stable URL before trying again.",
            "prompt_note": "The same action is looping. Do not repeat it; repair the plan or backtrack.",
        }

    if hint is None:
        return None
    hint["forbidden_actions"] = repeated[:6]
    backtrack = stable_backtrack_url(previous_steps, current_url)
    if backtrack:
        hint["suggested_backtrack_url"] = backtrack
    if site_name == "gitlab":
        parsed_current = urlparse(current_url)
        if parsed_current.scheme and parsed_current.netloc:
            base = f"{parsed_current.scheme}://{parsed_current.netloc}"
            hint["suggested_gitlab_home_url"] = f"{base}/"
            if any(term in intent for term in ["homepage", "website", "profile", "status"]):
                hint["suggested_gitlab_repair_url"] = f"{base}/-/profile"
            elif "star" in intent:
                hint["suggested_gitlab_repair_url"] = f"{base}/explore?sort=stars_desc"
    if "fork" in intent and hint["error_class"].startswith("gitlab_"):
        hint["task_repair_context"] = "Fork workflows must end with a submitted fork/create action and a visible forked project or confirmation."
    if any(term in intent for term in ["group", "member", "invite"]) and hint["error_class"].startswith("gitlab_"):
        hint["task_repair_context"] = "Group/member workflows must show the added member/invite confirmation or resulting member row."
    if any(term in intent for term in ["file", "commit", "title", "branch", "editor"]) and hint["error_class"].startswith("gitlab_"):
        hint["task_repair_context"] = "File-edit workflows require a real editor change before the commit action."
    return hint
