"""k-step repair briefs for v3 H/k agent control.

The repair brief is deliberately deterministic. It is a compact, prompt-shaped
diagnosis derived from current state, recent actions, runtime feedback, and
recovery hints. It does not use official evaluator gold answers.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from hk_agent.capabilities import infer_task_capability

REPAIR_PROMPT_VERSION = "v3_repair_prompt"
REPAIR_LLM_PROMPT_VERSION = "v3_repair_llm"
_ACTION_LIKE_RE = re.compile(
    r"\b(?:click|fill|type|press|select_option|goto|noop|send_msg_to_user)\s*\(",
    re.IGNORECASE,
)
_BID_LIKE_RE = re.compile(r"\b(?:bid|action_id|candidate)\s*[:=]\s*['\"]?\d{2,}['\"]?", re.IGNORECASE)


def _page_text(page, limit: int = 4000) -> str:
    try:
        return " ".join(page.locator("body").inner_text(timeout=1000).split())[:limit]
    except Exception:
        return ""


def _recent_actions(previous_steps: list[dict[str, Any]], limit: int = 8) -> list[str]:
    actions: list[str] = []
    for row in previous_steps[-limit:]:
        action = str(row.get("action") or "")
        if action:
            actions.append(action)
    return actions


def _repeated_actions(actions: list[str]) -> list[str]:
    repeated: list[str] = []
    for action in actions:
        if actions.count(action) >= 2 and action not in repeated:
            repeated.append(action)
    return repeated


def _recent_step_snippets(previous_steps: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    for row in previous_steps[-limit:]:
        snippets.append(
            {
                "step_index": row.get("step_index"),
                "action": row.get("action"),
                "status": row.get("status"),
                "error": row.get("error"),
                "url_before": row.get("url_before"),
                "url_after": row.get("url_after"),
                "target_candidate": row.get("target_candidate"),
                "mutation_action_kind": row.get("mutation_action_kind"),
                "visible_state_after": str(row.get("visible_state_after") or "")[:700],
            }
        )
    return snippets


def _extract_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Repair critic response did not contain JSON")
    return json.loads(text[start : end + 1])


def _as_string_list(value: Any, *, fallback: list[str] | None = None, limit: int = 10) -> list[str]:
    if isinstance(value, list):
        rows = value
    elif isinstance(value, str) and value.strip():
        rows = [value]
    else:
        rows = fallback or []
    return [str(row).strip() for row in rows if str(row).strip()][:limit]


def _sanitize_repair_text(value: Any, *, fallback: str = "") -> str:
    """Keep the LLM critic as a critic, not as a hidden executor.

    The repair LLM may describe target classes and strategy, but it must not
    provide BrowserGym actions or exact bids. Those remain grounded by the
    normal executor prompt and validator.
    """

    text = " ".join(str(value or fallback or "").split())
    if not text:
        return ""
    if _ACTION_LIKE_RE.search(text):
        return (
            "Use the described current UI target class only; do not emit direct "
            "BrowserGym actions in the repair brief."
        )
    text = _BID_LIKE_RE.sub("current grounded candidate", text)
    text = re.sub(r"\b(?:use|choose|click|fill)\s+['\"]?\d{2,}['\"]?", "use a current grounded candidate", text, flags=re.I)
    return text[:700]


def _sanitize_repair_list(value: Any, *, fallback: list[str] | None = None, limit: int = 10) -> list[str]:
    return [_sanitize_repair_text(row) for row in _as_string_list(value, fallback=fallback, limit=limit) if _sanitize_repair_text(row)]


def _ollama_chat_json(
    *,
    base_url: str,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
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
    with urlopen(req, timeout=timeout_seconds) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    return decoded, str(decoded.get("message", {}).get("content") or "")


def _base_brief(
    *,
    failure_class: str,
    current_state: str,
    wrong_actions: list[str],
    avoid: list[str],
    needed_next_target: str,
    repair_strategy: str,
    planner_instruction: str,
    executor_instruction: str,
    recovery_hint: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "repair_prompt_version": REPAIR_PROMPT_VERSION,
        "failure_class": failure_class,
        "current_state": current_state,
        "wrong_actions": wrong_actions[:8],
        "avoid": avoid[:10],
        "needed_next_target": needed_next_target,
        "repair_strategy": repair_strategy,
        "planner_instruction": planner_instruction,
        "executor_instruction": executor_instruction,
        "source_recovery_hint": recovery_hint,
    }


def build_k_repair_brief(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]],
    evaluator_signal: Any | None,
    controller_decision: Any | None,
    recovery_hint: dict[str, Any] | None,
    last_error: str | None = None,
) -> dict[str, Any] | None:
    """Build a structured repair brief after a k-step evaluator signal."""

    decision = getattr(controller_decision, "decision", None)
    if decision not in {"local_replan", "global_replan"} and not recovery_hint and not last_error:
        return None

    intent = str(task.get("intent") or "").lower()
    capability = infer_task_capability(task, site_name)
    current_url = str(getattr(page, "url", "") or "")
    parsed = urlparse(current_url)
    visible = _page_text(page).lower()
    actions = _recent_actions(previous_steps)
    repeated = _repeated_actions(actions)
    signal_reason = str(getattr(evaluator_signal, "reason", "") or "")
    wrong_actions = repeated or actions[-3:]
    combined = "\n".join([intent, current_url.lower(), visible, str(last_error or "").lower(), signal_reason.lower()])
    hint_class = str((recovery_hint or {}).get("error_class") or "")

    if site_name == "gitlab" and capability == "mutate_gitlab_fork":
        if "/-/forks/new" in parsed.path:
            return _base_brief(
                failure_class="gitlab_fork_form_repair",
                current_state="GitLab fork form is visible or recently used.",
                wrong_actions=wrong_actions,
                avoid=["source namespace page as final success", "project listing as final success", "repeating stale Fork/Form bids"],
                needed_next_target="current namespace selector or current Fork/Create submit bid on the fork form",
                repair_strategy="Stay on the fork form. Select namespace if needed, then submit using a current visible candidate. Do not finalize before the fork form is submitted.",
                planner_instruction="Repair the existing fork form workflow; do not restart from search unless the form is unreachable.",
                executor_instruction="Use exact current fork-form candidates only. Prefer visible same-site /-/forks/new hrefs over guessed Fork bids. Do not emit MUTATE SUCCESS from facebook/users pages.",
                recovery_hint=recovery_hint,
            )
        return _base_brief(
            failure_class="gitlab_fork_missing_submit",
            current_state="GitLab source namespace/project area is visible, but no fork mutation has been submitted.",
            wrong_actions=wrong_actions,
            avoid=["MUTATE SUCCESS from source namespace or project list", "looping search/explore pages"],
            needed_next_target="target project fork page or /-/forks/new form",
            repair_strategy="Navigate from the source project to its fork form and submit the fork. A correct route alone is only a near miss.",
            planner_instruction="Plan the next subgoal as opening/submitting the fork form, not as finding facebook again.",
            executor_instruction="Use current project/fork href candidates. If a concrete /-/forks/new link exists, use goto(href).",
            recovery_hint=recovery_hint,
        )

    if site_name == "gitlab" and capability in {"mutate_gitlab_group", "mutate_gitlab_members"}:
        if "invite members" in combined and "username or email address" in combined:
            return _base_brief(
                failure_class="gitlab_invite_modal_repair",
                current_state="Invite members modal is visible.",
                wrong_actions=wrong_actions,
                avoid=["Filter members", "background Invite members button", "modal container bid", "global search unless it is inside the modal"],
                needed_next_target="current inside-modal username/email input, role selector, suggestion, or Invite/Add button",
                repair_strategy="Continue inside the open modal. If modal candidates are missing, wait once with noop(1000) for refreshed candidates; do not fill background fields.",
                planner_instruction="Repair the invite-modal step; do not recreate the group or navigate away from the members page.",
                executor_instruction="Choose only current candidates marked inside_modal or whose placeholder/context mentions Username/email, role, or Invite. For multi-user invites, add every requested user chip/token before submitting. Never reuse stale modal bids.",
                recovery_hint=recovery_hint,
            )
        return _base_brief(
            failure_class="gitlab_group_members_repair",
            current_state="GitLab group/member workflow is active.",
            wrong_actions=wrong_actions,
            avoid=["ending after group creation if members are still requested", "using Filter members as invite input"],
            needed_next_target="Invite members button or member invitation modal",
            repair_strategy="Open the members/invite flow and add every requested user through the modal before submitting.",
            planner_instruction="Keep the created group context and plan the invitation step only.",
            executor_instruction="Use current member-page or modal candidates; do not restart group creation. Do not submit after only the first requested user is selected.",
            recovery_hint=recovery_hint,
        )

    if site_name == "gitlab" and capability == "mutate_gitlab_file_edit":
        if "/-/ide/" in parsed.path:
            return _base_brief(
                failure_class="gitlab_wrong_web_ide_repair",
                current_state="Full Web IDE is visible, but the task asks for the simple online file editor.",
                wrong_actions=wrong_actions,
                avoid=["Web IDE/Monaco route for simple editor tasks", "large HTML dumps"],
                needed_next_target="simple /-/edit/<branch>/<file> page",
                repair_strategy="Navigate to the simple file editor route before editing and committing.",
                planner_instruction="Replace the Web IDE direction with a simple-editor repair subgoal.",
                executor_instruction="Use goto to the simple /-/edit route when derivable from the current file path; do not continue in /-/ide.",
                recovery_hint=recovery_hint,
            )
        if "/-/edit/" in parsed.path or any(term in combined for term in ["editor_like", "code_editor_hint", "textarea", "contenteditable"]):
            symbolic = [a for a in actions if re.search(r'"(?:0|body|html|editor|\d+)"', a)]
            return _base_brief(
                failure_class="gitlab_simple_editor_target_repair",
                current_state="Simple file editor workflow is active, but the editable target/action is not stable.",
                wrong_actions=symbolic or wrong_actions,
                avoid=["html/body/root bid", "symbolic editor target", "line-number target", "commit with 0 changed files", "full HTML document dump"],
                needed_next_target="current editor-like textarea/textbox/contenteditable candidate, then branch/commit controls after a real edit",
                repair_strategy="Use only current editor-like candidates for the minimal title/text edit. After a real change is visible, set branch/commit fields and submit.",
                planner_instruction="Repair the current simple-editor step; do not bounce between blob/tree/edit routes.",
                executor_instruction="Target only current candidates with editor_like/code_editor_hint/textarea/contenteditable context. If none exists, noop(1000) or refocus a current editor container; never use body/html/editor as a bid.",
                recovery_hint=recovery_hint,
            )

    if site_name == "gitlab" and capability == "mutate_gitlab_milestone":
        return _base_brief(
            failure_class="gitlab_milestone_form_repair",
            current_state="GitLab milestone workflow is active.",
            wrong_actions=wrong_actions,
            avoid=["file editor repair", "Web IDE", "repeating noop", "leaving the new milestone form before submit"],
            needed_next_target="current milestone Title, Start date, Due date, or Create milestone/Save control",
            repair_strategy="Stay on the new milestone form. Fill the milestone title and date fields, then submit the current Create/Save milestone control.",
            planner_instruction="Repair the milestone form step; do not switch to file-edit/editor logic.",
            executor_instruction="Use exact current form-field bids for title/start/due date and then the current Create/Save milestone bid. Do not emit noop unless a submitted page is loading.",
            recovery_hint=recovery_hint,
        )

    if site_name == "gitlab" and capability == "mutate_gitlab_issue_create":
        return _base_brief(
            failure_class="gitlab_issue_create_form_repair",
            current_state="GitLab issue creation workflow is active.",
            wrong_actions=wrong_actions,
            avoid=["project members workflow unless the assignee is truly unavailable", "leaving a partially filled issue form", "repeating no-progress navigation"],
            needed_next_target="current New issue title/assignee/due date field or Create issue submit control",
            repair_strategy="Prefer completing the New issue form. If the assignee control is unavailable but the user appears accessible, continue with the issue form rather than reopening members.",
            planner_instruction="Repair the issue creation form step and avoid member-invite detours unless strictly required by visible UI.",
            executor_instruction="Use exact current issue form candidates for title, assignee, due date, and Create issue. Do not use member filter fields as issue form inputs.",
            recovery_hint=recovery_hint,
        )

    if site_name == "gitlab" and capability == "mutate_gitlab_issue_assign":
        return _base_brief(
            failure_class="gitlab_issue_assign_repair",
            current_state="GitLab issue assignment workflow is active.",
            wrong_actions=wrong_actions,
            avoid=["global search as completion", "members page unless assignment controls require it", "stale sidebar bids"],
            needed_next_target="current issue assignee/sidebar control and requested user option",
            repair_strategy="Stay on or return to the issue page, open the assignee control, select the requested user, and verify the assignee.",
            planner_instruction="Repair the issue assignment step rather than restarting navigation.",
            executor_instruction="Use exact current issue sidebar/dropdown candidates for assignee selection and save/apply controls.",
            recovery_hint=recovery_hint,
        )

    if site_name == "gitlab" and capability in {"mutate_gitlab_profile_status", "mutate_gitlab_profile_homepage"}:
        return _base_brief(
            failure_class="gitlab_profile_settings_repair",
            current_state="GitLab profile/settings workflow is active.",
            wrong_actions=wrong_actions,
            avoid=["cycling between profile and preferences", "project settings", "global search"],
            needed_next_target="current profile/status/website field or current Save/Update profile control",
            repair_strategy="Stop cycling between profile pages. If the form is unreachable, return to the same-site GitLab home/profile route. Once on /-/profile, fill the requested field, submit the profile/status form, and verify the saved value.",
            planner_instruction="Repair the current profile settings form step; use the known same-site /-/profile route if the browser is on the wrong GitLab page.",
            executor_instruction="Use exact current form candidates for status/website and Save/Update. If the form is open, submit it instead of navigating away; if the wrong page is open, go to the same-site /-/profile route.",
            recovery_hint=recovery_hint,
        )

    if site_name == "gitlab" and capability == "mutate_gitlab_star_repos":
        return _base_brief(
            failure_class="gitlab_star_repos_repair",
            current_state="GitLab repository starring workflow is active.",
            wrong_actions=wrong_actions,
            avoid=["cycling between Explore and the same project", "ending after navigation only"],
            needed_next_target="current Star button on a project page or next unstarred top-project link",
            repair_strategy="If on a project page, click the current Star control only when it says Star. If it says Unstar/Starred, count that project as already done and return to the Explore Most stars route for the next project.",
            planner_instruction="Repair by continuing the star-count workflow, not by repeating Explore/project navigation.",
            executor_instruction="Use exact current Star button bids on project pages. Never click Unstar for a star task. If the browser is on starrers/forks/issues or a wrong GitLab page, return to the same-site /explore?sort=stars_desc route.",
            recovery_hint=recovery_hint,
        )

    if site_name == "gitlab" and capability == "mutate_gitlab_mr_reply":
        return _base_brief(
            failure_class="gitlab_mr_reply_repair",
            current_state="GitLab merge request reply workflow is active.",
            wrong_actions=wrong_actions,
            avoid=["issue pages", "project overview as completion", "repeating noop"],
            needed_next_target="current merge request discussion textarea/reply field or Comment/Submit control",
            repair_strategy="Stay on the relevant merge request discussion, fill the required reply, and submit the comment.",
            planner_instruction="Repair the MR discussion reply step.",
            executor_instruction="Use exact current discussion textarea and submit/comment bids. Do not finish before the posted reply is visible.",
            recovery_hint=recovery_hint,
        )

    if hint_class:
        return _base_brief(
            failure_class=hint_class,
            current_state="Runtime recovery hint is available.",
            wrong_actions=wrong_actions,
            avoid=list((recovery_hint or {}).get("forbidden_actions") or []),
            needed_next_target=str((recovery_hint or {}).get("repair_goal") or "repair the diagnosed failure"),
            repair_strategy=str((recovery_hint or {}).get("prompt_note") or "follow the recovery hint before continuing"),
            planner_instruction="Plan one repair subgoal for the latest recovery_hint before continuing.",
            executor_instruction="Follow recovery_hint exactly and do not repeat forbidden actions or stale bids.",
            recovery_hint=recovery_hint,
        )

    return _base_brief(
        failure_class="generic_k_repair",
        current_state=f"Runtime evaluator requested replanning because {signal_reason or 'progress was insufficient'}.",
        wrong_actions=wrong_actions,
        avoid=repeated,
        needed_next_target="a different current candidate or stable same-site href",
        repair_strategy="Do not repeat no-progress actions. Use current candidates, backtrack if needed, or choose a new subgoal grounded in the current page.",
        planner_instruction="Repair the current state rather than restarting the whole workflow.",
        executor_instruction="Avoid forbidden repeated actions and stale bids; use exact current candidates only.",
        recovery_hint=recovery_hint,
    )


def refine_repair_brief_with_llm(
    *,
    task: dict[str, Any],
    site_name: str,
    page,
    previous_steps: list[dict[str, Any]],
    base_repair_brief: dict[str, Any],
    model_name: str,
    base_url: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Use a small LLM critic to refine a deterministic repair brief.

    The critic never emits BrowserGym actions directly and receives no official
    evaluator gold answer. Its output is a compact diagnosis fed back into the
    normal planner/executor prompts.
    """

    system_prompt = (
        "You are a constrained repair critic for a WebArena browser agent. "
        "Your job is to classify why progress failed and produce a compact repair brief. "
        "You are not the executor. Do not solve the task directly. Do not output BrowserGym actions. "
        "Never write click(...), fill(...), type(...), press(...), select_option(...), goto(...), noop(...), "
        "or send_msg_to_user(...). Never invent or reuse exact bids/action_id numbers. "
        "Refer only to target classes such as current modal username input, current submit button, "
        "current editor-like textarea, current role dropdown, or current same-site href. "
        "Return JSON only with exactly these fields: failure_class, diagnosis, must_avoid, "
        "must_use_current_candidate_type, repair_strategy, planner_instruction, executor_instruction, "
        "confidence. Keep every field concise and operational."
    )
    context = {
        "task_intent": task.get("intent", ""),
        "site": site_name,
        "current_url": str(getattr(page, "url", "") or ""),
        "visible_text_excerpt": _page_text(page, limit=2500),
        "recent_steps": _recent_step_snippets(previous_steps),
        "deterministic_repair_brief": base_repair_brief,
        "constraints": [
            "Do not use evaluator gold answers.",
            "Do not invent exact bids or action_id values.",
            "Do not output BrowserGym action strings or action JSON.",
            "Prefer instructions that force use of current candidates or concrete visible hrefs.",
            "For visible modals, the next target class must be inside the modal, not a background control.",
            "For GitLab editors, request minimal intended text changes only; never request full HTML/code dumps unless the task explicitly asks for full-file replacement.",
            "For MUTATE, do not allow SUCCESS until a submit/confirm action has happened and the post-submit page visibly confirms the state.",
            "If current UI lacks the needed candidate, say how to refresh/refocus/backtrack safely.",
        ],
    }
    decoded, content = _ollama_chat_json(
        base_url=base_url,
        model_name=model_name,
        system_prompt=system_prompt,
        user_prompt=json.dumps(context, indent=2, ensure_ascii=False),
        timeout_seconds=timeout_seconds,
    )
    data = _extract_json_object(content)
    executor_instruction = _sanitize_repair_text(
        data.get("executor_instruction") or data.get("next_executor_instruction"),
        fallback=str(base_repair_brief.get("executor_instruction") or ""),
    )
    repair_strategy = _sanitize_repair_text(
        data.get("repair_strategy") or data.get("next_executor_instruction"),
        fallback=str(base_repair_brief.get("repair_strategy") or ""),
    )
    refined = dict(base_repair_brief)
    refined.update(
        {
            "repair_prompt_version": REPAIR_LLM_PROMPT_VERSION,
            "base_repair_brief": base_repair_brief,
            "failure_class": _sanitize_repair_text(
                data.get("failure_class"),
                fallback=str(base_repair_brief.get("failure_class") or "llm_repair"),
            ),
            "current_state": _sanitize_repair_text(
                data.get("diagnosis"),
                fallback=str(base_repair_brief.get("current_state") or ""),
            ),
            "avoid": _sanitize_repair_list(data.get("must_avoid"), fallback=list(base_repair_brief.get("avoid") or []))[:10],
            "needed_next_target": _sanitize_repair_text(
                data.get("must_use_current_candidate_type")
                or base_repair_brief.get("needed_next_target"),
                fallback="current grounded candidate",
            ),
            "repair_strategy": repair_strategy,
            "planner_instruction": _sanitize_repair_text(
                data.get("planner_instruction"),
                fallback=str(base_repair_brief.get("planner_instruction") or ""),
            ),
            "executor_instruction": executor_instruction,
            "llm_repair_critic": {
                "model_name": model_name,
                "prompt_tokens": decoded.get("prompt_eval_count"),
                "completion_tokens": decoded.get("eval_count"),
                "confidence": data.get("confidence"),
                "raw_response_preview": content[:1000],
                "schema": "critic_only_no_actions_no_bids",
            },
        }
    )
    return refined
