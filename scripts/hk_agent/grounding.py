"""Grounded observation helpers for BrowserGym executor actions.

The helpers in this module are intentionally small and dependency-light. They
borrow the Plan-and-Act idea of giving the executor cleaned HTML and local
element context, while keeping BrowserGym action strings as the public action
interface.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


@dataclass(frozen=True)
class GroundedCandidate:
    """One currently visible/actionable target the executor may reference."""

    bid: str
    role: str
    text: str = ""
    tag: str | None = None
    href: str | None = None
    placeholder: str | None = None
    aria_label: str | None = None
    name: str | None = None
    value: str | None = None
    context: str | None = None
    html: str | None = None
    source: str = "dom"

    def to_prompt_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, "")}


def compact_text(value: Any, limit: int = 240) -> str:
    """Normalize whitespace and truncate a value for prompt use."""

    text = " ".join(str(value or "").split())
    return text[:limit]


def ax_candidates(obs: dict[str, Any], limit: int = 120) -> list[GroundedCandidate]:
    """Extract BrowserGym bid candidates from accessibility-tree text."""

    text = str(obs.get("axtree_object") or "")
    candidates: list[GroundedCandidate] = []
    seen: set[str] = set()
    patterns = [
        re.compile(r"\[(?P<bid>[A-Za-z0-9_-]+)\]\s+(?P<role>[A-Za-z_ ]+)\s+'(?P<name>[^']*)'"),
        re.compile(r"\[(?P<bid>[A-Za-z0-9_-]+)\]\s+(?P<role>[A-Za-z_ ]+)\s+\"(?P<name>[^\"]*)\""),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            bid = match.group("bid")
            if bid in seen:
                continue
            seen.add(bid)
            candidates.append(
                GroundedCandidate(
                    bid=bid,
                    role=" ".join(match.group("role").split()),
                    text=compact_text(match.group("name")),
                    source="ax",
                )
            )
            if len(candidates) >= limit:
                return candidates
    return candidates


def _candidate_html(row: dict[str, Any], limit: int = 900) -> str:
    html = str(row.get("outer_html") or "")
    if not html:
        return ""
    return clean_html_fragment(html, keep_ids={str(row.get("bid") or "")}, limit=limit)


def dom_candidates(page, limit: int = 320) -> list[GroundedCandidate]:
    """Extract visible candidate elements from the live Playwright DOM."""

    script = """
    (limit) => {
      const selector = [
        '[data-label-id]',
        '[bid]',
        'a[href]',
        'button',
        'input',
        'textarea',
        'select',
        '[role="textbox"]',
        '[role="button"]',
        '[role="link"]',
        '[role="combobox"]',
        '[role="option"]',
        '[role="menuitem"]',
        '[aria-haspopup]',
        '[contenteditable="true"]',
        '.CodeMirror',
        '.cm-editor',
        '.cm-content',
        '.ace_editor',
        '.monaco-editor'
      ].join(',');
      const els = Array.from(document.querySelectorAll(selector));
      const rows = [];
      const seen = new Set();
      const compact = (text, maxLen = 500) => (text || '').replace(/\\s+/g, ' ').trim().slice(0, maxLen);
      const activeModal = document.querySelector('[role="dialog"], [aria-modal="true"], .modal.show, .modal[style*="display: block"]');
      const activeModalText = compact(activeModal ? (activeModal.innerText || activeModal.textContent || '') : '', 1000);
      const modalHint = (el) => {
        if (!activeModalText) return '';
        const closestDialog = el.closest('[role="dialog"]') || el.closest('[aria-modal="true"]') || el.closest('.modal');
        if (closestDialog) return compact(`inside_modal | modal_text=${closestDialog.innerText || closestDialog.textContent || ''}`, 1000);
        return compact(`background_while_modal_visible | active_modal_text=${activeModalText}`, 1000);
      };
      const editorHint = (el) => {
        const parts = [];
        const tagName = el.tagName.toLowerCase();
        if (tagName === 'html' || tagName === 'body') return '';
        const classText = `${el.className || ''} ${el.getAttribute('class') || ''}`.toLowerCase();
        const attrText = [
          el.getAttribute('role') || '',
          el.getAttribute('aria-label') || '',
          el.getAttribute('placeholder') || '',
          el.getAttribute('name') || '',
          el.id || '',
        ].join(' ').toLowerCase();
        const descendant = el.querySelector && el.querySelector('textarea, [contenteditable="true"], .CodeMirror, .cm-editor, .cm-content, .ace_editor, .monaco-editor, [role="textbox"]');
        if (el.matches('textarea, [contenteditable="true"], [role="textbox"], .CodeMirror, .cm-editor, .cm-content, .ace_editor, .monaco-editor') || descendant) parts.push('editor_like');
        if (/editor|codemirror|monaco|ace_|textarea|blob|file-content|code|cm-content|cm-editor/.test(`${classText} ${attrText}`)) parts.push('code_editor_hint');
        const editable = el.matches('textarea, [contenteditable="true"]') ? el : descendant;
        if (editable) {
          parts.push(`editable_tag=${editable.tagName.toLowerCase()}`);
          const value = editable.value || editable.innerText || editable.textContent || '';
          if (value) parts.push(`editable_value=${compact(value, 500)}`);
        }
        return compact(parts.join(' | '), 900);
      };
      const labelText = (el) => {
        const parts = [];
        if (el.id) {
          const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
          if (label) parts.push(label.innerText || label.textContent || '');
        }
        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
          for (const id of labelledBy.split(/\\s+/)) {
            const node = document.getElementById(id);
            if (node) parts.push(node.innerText || node.textContent || '');
          }
        }
        const closestLabel = el.closest('label');
        if (closestLabel) parts.push(closestLabel.innerText || closestLabel.textContent || '');
        const describedBy = el.getAttribute('aria-describedby');
        if (describedBy) {
          for (const id of describedBy.split(/\\s+/)) {
            const node = document.getElementById(id);
            if (node) parts.push(node.innerText || node.textContent || '');
          }
        }
        return compact(parts.join(' '), 300);
      };
      for (const el of els) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const visible = rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
        if (!visible) continue;
        const bid = el.getAttribute('data-label-id') || el.getAttribute('bid') || '';
        if (!bid || seen.has(bid)) continue;
        seen.add(bid);
        rows.push({
          bid,
          tag: el.tagName.toLowerCase(),
          role: el.getAttribute('role') || el.tagName.toLowerCase(),
          text: (el.innerText || el.textContent || '').trim(),
          href: el.href || el.getAttribute('href') || '',
          placeholder: el.getAttribute('placeholder') || '',
          aria_label: el.getAttribute('aria-label') || '',
          name: el.getAttribute('name') || '',
          value: el.value || el.getAttribute('value') || '',
          label_text: labelText(el),
          dialog_text: compact((el.closest('[role="dialog"]') || el.closest('[aria-modal="true"]') || el.closest('.modal') || {}).innerText || '', 900),
          modal_hint: modalHint(el),
          row_text: compact((el.closest('tr') || el.closest('[role="row"]') || {}).innerText || '', 700),
          form_text: compact((el.closest('form') || {}).innerText || '', 700),
          section_text: compact((el.closest('section') || el.closest('[role="main"]') || el.closest('.content') || {}).innerText || '', 700),
          parent_text: compact((el.parentElement || {}).innerText || '', 500),
          editor_hint: editorHint(el),
          disabled: el.disabled || el.getAttribute('aria-disabled') || '',
          aria_expanded: el.getAttribute('aria-expanded') || '',
          aria_pressed: el.getAttribute('aria-pressed') || '',
          aria_selected: el.getAttribute('aria-selected') || '',
          outer_html: el.outerHTML || ''
        });
        if (rows.length >= limit) break;
      }
      return rows;
    }
    """
    try:
        rows = page.evaluate(script, limit)
    except Exception:
        return []
    candidates: list[GroundedCandidate] = []
    for row in rows or []:
        bid = str(row.get("bid") or "").strip()
        if not bid:
            continue
        candidates.append(
            GroundedCandidate(
                bid=bid,
                role=compact_text(row.get("role"), 80),
                text=compact_text(row.get("text")),
                tag=compact_text(row.get("tag"), 40),
                href=compact_text(row.get("href"), 500),
                placeholder=compact_text(row.get("placeholder")),
                aria_label=compact_text(row.get("aria_label")),
                name=compact_text(row.get("name"), 120),
                value=compact_text(row.get("value"), 180),
                context=compact_text(
                    " | ".join(
                        str(row.get(key) or "")
                        for key in (
                            "label_text",
                            "dialog_text",
                            "modal_hint",
                            "row_text",
                            "form_text",
                            "section_text",
                            "parent_text",
                            "editor_hint",
                            "disabled",
                            "aria_expanded",
                            "aria_pressed",
                            "aria_selected",
                        )
                        if row.get(key)
                    ),
                    700,
                ),
                html=_candidate_html(row),
                source="dom",
            )
        )
    return candidates


def merge_candidates(*groups: list[GroundedCandidate], limit: int = 160) -> list[GroundedCandidate]:
    """Merge candidates by bid, preserving richer DOM fields when available."""

    merged: dict[str, GroundedCandidate] = {}
    order: list[str] = []
    for group in groups:
        for candidate in group:
            if candidate.bid not in merged:
                merged[candidate.bid] = candidate
                order.append(candidate.bid)
                continue
            current = merged[candidate.bid]
            merged[candidate.bid] = GroundedCandidate(
                bid=candidate.bid,
                role=current.role or candidate.role,
                text=candidate.text or current.text,
                tag=candidate.tag or current.tag,
                href=candidate.href or current.href,
                placeholder=candidate.placeholder or current.placeholder,
                aria_label=candidate.aria_label or current.aria_label,
                name=candidate.name or current.name,
                value=candidate.value or current.value,
                context=candidate.context or current.context,
                html=candidate.html or current.html,
                source="dom+ax" if {current.source, candidate.source} == {"dom", "ax"} else current.source,
            )
    return [merged[bid] for bid in order[:limit]]


def grounded_candidates(obs: dict[str, Any], page, limit: int = 320) -> list[GroundedCandidate]:
    """Return merged current candidates from AX tree and live DOM."""

    return merge_candidates(dom_candidates(page, limit=limit), ax_candidates(obs, limit=limit), limit=limit)


def candidate_bid_set(candidates: list[GroundedCandidate]) -> set[str]:
    return {candidate.bid for candidate in candidates if candidate.bid}


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "task",
    "find",
    "open",
    "page",
    "click",
    "enter",
    "return",
    "show",
    "use",
    "auf",
    "der",
    "die",
    "das",
    "und",
    "mit",
}


def task_keywords(task: dict[str, Any], subgoal: Any | None = None, limit: int = 36) -> list[str]:
    """Extract stable task words for candidate ranking without using eval answers."""

    pieces = [str(task.get("intent", ""))]
    if subgoal is not None:
        pieces.extend([str(getattr(subgoal, "objective", "")), str(getattr(subgoal, "expected_outcome", ""))])
    text = " ".join(pieces).lower()
    tokens = re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text)
    ordered: list[str] = []
    for token in tokens:
        if token in STOPWORDS or token in ordered:
            continue
        ordered.append(token)
        if len(ordered) >= limit:
            break
    return ordered


def candidate_search_text(candidate: GroundedCandidate) -> str:
    """Return all textual fields used for scientific, task-local ranking."""

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
            candidate.html,
        ]
    ).lower()


def prioritize_candidates(
    candidates: list[GroundedCandidate],
    *,
    task: dict[str, Any],
    subgoal: Any | None = None,
    site_name: str = "",
) -> list[GroundedCandidate]:
    """Rank current candidates by relevance while preserving the full visible set."""

    keywords = task_keywords(task, subgoal)
    site = site_name.lower()

    def score_index(item: tuple[int, GroundedCandidate]) -> tuple[int, int]:
        index, candidate = item
        haystack = candidate_search_text(candidate)
        score = 0
        for keyword in keywords:
            if keyword in haystack:
                score += 8 if keyword in {candidate.text.lower(), (candidate.name or "").lower()} else 3
        role = f"{candidate.role} {candidate.tag}".lower()
        if any(part in role for part in ["input", "textarea", "select"]):
            score += 8
        if any(part in role for part in ["button", "link", "option"]):
            score += 5
        if candidate.href:
            score += 3
        if candidate.context:
            score += 4
        if site == "shopping_admin" and candidate.context and any(term in candidate.context.lower() for term in ["edit", "filter", "search", "select", "status", "qty", "stock"]):
            score += 8
        if site == "gitlab" and any(term in haystack for term in ["group", "project", "file", "edit", "branch", "commit", "fork"]):
            score += 5
        if site == "gitlab" and any(
            term in haystack
            for term in [
                "website url",
                "website_url",
                "homepage",
                "profile settings",
                "update profile",
                "update profile settings",
                "user[website_url]",
            ]
        ):
            score += 20
        if site == "gitlab" and any(term in haystack for term in ["star", "unstar", "starrers", "most stars"]):
            score += 10
        if site == "gitlab" and any(
            term in haystack
            for term in [
                "editor_like",
                "code_editor_hint",
                "editable_tag=textarea",
                "contenteditable",
                "textarea",
                "codemirror",
                "monaco",
                "ace_editor",
                "file-content",
            ]
        ):
            score += 18
        if site == "gitlab" and "inside_modal" in haystack:
            score += 18
        if site == "gitlab" and "background_while_modal_visible" in haystack:
            score -= 8
        if site == "gitlab" and "invite members" in haystack and any(
            term in haystack for term in ["username or email", "select a role", "inside_modal", "invite button"]
        ):
            score += 16
        if site == "gitlab" and "filter members" in haystack and "background_while_modal_visible" in haystack:
            score -= 24
        if site == "gitlab" and any(
            term in haystack
            for term in [
                "save",
                "update profile",
                "commit",
                "create",
                "fork project",
                "invite",
                "add member",
                "new group",
                "target namespace",
                "select namespace",
            ]
        ):
            score += 10
        if any(term in haystack for term in ["modal", "dialog", "confirmation", "success", "submit", "cancel"]):
            score += 4
        if site == "shopping" and any(term in haystack for term in ["add to cart", "cart", "checkout", "search", "product"]):
            score += 5
        return (-score, index)

    return [candidate for _index, candidate in sorted(enumerate(candidates), key=score_index)]


def focus_modal_candidates(candidates: list[GroundedCandidate]) -> list[GroundedCandidate]:
    """Prefer dialog/modal controls when a modal is active.

    This is intentionally generic: if the DOM marks current candidates as
    inside a modal/dialog, background candidates are likely blocked by an
    overlay and should not dominate the executor prompt.
    """

    inside = [candidate for candidate in candidates if "inside_modal" in candidate_search_text(candidate)]
    if not inside:
        return candidates
    neutral = [
        candidate
        for candidate in candidates
        if "inside_modal" not in candidate_search_text(candidate)
        and "background_while_modal_visible" not in candidate_search_text(candidate)
    ]
    return [*inside, *neutral]


def visible_evidence_text(page, extra_text: str = "", limit: int = 12000) -> str:
    """Return text that can be used to validate final retrieved answers."""

    pieces = []
    try:
        pieces.append(page.locator("body").inner_text(timeout=2000))
    except Exception:
        pass
    try:
        pieces.append(page.content())
    except Exception:
        pass
    try:
        rows = page.evaluate(
            """(limit) => Array.from(document.querySelectorAll('input, textarea, select, [contenteditable="true"], [role="textbox"]'))
              .slice(0, limit)
              .map((el) => [
                el.getAttribute('data-label-id') || el.getAttribute('bid') || '',
                el.getAttribute('name') || '',
                el.getAttribute('aria-label') || '',
                el.getAttribute('placeholder') || '',
                el.value || el.getAttribute('value') || el.innerText || el.textContent || ''
              ].filter(Boolean).join(' '))
              .filter(Boolean)""",
            250,
        )
        if isinstance(rows, list):
            pieces.append("\n".join(str(row) for row in rows if row))
    except Exception:
        pass
    if extra_text:
        pieces.append(extra_text)
    return compact_text("\n".join(pieces), limit)


def clean_html_fragment(html: str, keep_ids: set[str] | None = None, limit: int = 2500) -> str:
    """Clean one HTML fragment while preserving useful interaction attributes."""

    keep_ids = keep_ids or set()
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "footer"]):
        node.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    allowed = {
        "id",
        "data-label-id",
        "bid",
        "href",
        "role",
        "title",
        "type",
        "name",
        "value",
        "placeholder",
        "aria-label",
        "aria-multiline",
        "aria-expanded",
        "aria-selected",
        "selected",
        "contenteditable",
    }
    for tag in soup.find_all(True):
        label_id = str(tag.attrs.get("data-label-id") or tag.attrs.get("bid") or tag.attrs.get("id") or "")
        if label_id not in keep_ids:
            tag.attrs.pop("data-label-id", None)
            tag.attrs.pop("bid", None)
        for attr in list(tag.attrs):
            if attr not in allowed:
                del tag.attrs[attr]
        if tag.name not in {"a", "button", "input", "textarea", "select", "option"} and label_id not in keep_ids:
            if not tag.attrs and len(list(tag.children)) <= 1:
                try:
                    tag.unwrap()
                except Exception:
                    pass
    for text in soup.find_all(string=True):
        if isinstance(text, NavigableString):
            normalized = " ".join(str(text).split())
            if normalized:
                text.replace_with(normalized)
            else:
                text.extract()
    cleaned = " ".join(soup.get_text(" ").split()) if not str(soup).strip() else str(soup)
    cleaned = "\n".join(line.strip() for line in BeautifulSoup(cleaned, "html.parser").prettify().splitlines() if line.strip())
    return cleaned[:limit]


def grounded_observation(obs: dict[str, Any], page, candidates: list[GroundedCandidate]) -> dict[str, Any]:
    """Build a prompt-ready grounded observation payload."""

    try:
        title = page.title()
    except Exception as exc:
        title = f"<title unavailable: {exc}>"
    try:
        body_text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        body_text = ""
    candidate_html = "\n\n".join(
        f"[{candidate.bid}] {candidate.html[:350]}"
        for candidate in candidates[:12]
        if candidate.html
    )
    return {
        "current_url": page.url,
        "page_title": title,
        "last_action": obs.get("last_action", ""),
        "last_action_error": obs.get("last_action_error", ""),
        "visible_text_excerpt": compact_text(body_text, 3000),
        "candidate_html": candidate_html[:1800],
    }


def previous_round_snippets(previous_steps: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    """Compact previous steps for Plan-and-Act-style action history."""

    snippets: list[dict[str, Any]] = []
    for step in previous_steps[-limit:]:
        snippets.append(
            {
                "step_index": step.get("step_index"),
                "subgoal_id": step.get("subgoal_id"),
                "action": step.get("action"),
                "status": step.get("status"),
                "url_before": step.get("url_before"),
                "url_after": step.get("url_after"),
                "page_title": step.get("page_title") or step.get("title_after"),
                "error": step.get("error"),
                "target_candidate": step.get("target_candidate"),
                "mutation_action_kind": step.get("mutation_action_kind"),
                "mutation_phase": step.get("mutation_phase"),
                "state_change_hint": step.get("state_change_hint"),
                "visible_state_after": step.get("visible_state_after"),
            }
        )
    return snippets


def find_target_candidate(action: str, candidates: list[GroundedCandidate]) -> dict[str, Any] | None:
    """Return the candidate referenced by an action string, if any."""

    match = re.search(r'\(\s*"([^"]*)"', action)
    if not match:
        return None
    target = match.group(1)
    for candidate in candidates:
        if candidate.bid == target:
            return candidate.to_prompt_dict()
    return None
