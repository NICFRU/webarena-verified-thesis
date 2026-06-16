"""Prompt composition helpers for H/k agent architecture variants."""

from __future__ import annotations

from pathlib import Path
from typing import Any


V2_PROMPT_ROOT = Path("prompts/v2")
WEBARENA_VERIFIED_PROMPT_ROOT = Path("external/webarena-verified/examples/prompts")

SITE_METADATA = {
    "shopping": {
        "platform_name": "E-commerce Store",
        "description": "An online shopping platform where customers can browse products, add items to cart, and make purchases.",
        "auth": "You are already logged in as emma.lopez@gmail.com. To re-authenticate, use credentials: emma.lopez@gmail.com / Password.123. If re-authentication fails, terminate with PERMISSION_DENIED_ERROR status.",
    },
    "reddit": {
        "platform_name": "Discussion Forum",
        "description": "A social news aggregation, content rating, and discussion website where users can post content and vote on submissions.",
        "auth": "You are already logged in as MarvelsGrantMan136. To re-authenticate, use credentials: MarvelsGrantMan136 / test1234. If re-authentication fails, terminate with PERMISSION_DENIED_ERROR status.",
    },
    "gitlab": {
        "platform_name": "GitLab",
        "description": "A web-based Git repository manager providing wiki, issue tracking, and CI/CD pipeline features.",
        "auth": "You are already logged in as byteblaze. To re-authenticate, use credentials: byteblaze / hello1234. If re-authentication fails, terminate with PERMISSION_DENIED_ERROR status.",
    },
    "shopping_admin": {
        "platform_name": "Merchant Admin Portal",
        "description": "An admin portal to manage an e-commerce business.",
        "auth": "You are already logged in as admin. To re-authenticate, use credentials: admin / admin1234. If re-authentication fails, terminate with PERMISSION_DENIED_ERROR status.",
    },
    "map": {
        "platform_name": "Map Service",
        "description": "An interactive map platform for searching locations, getting directions, and exploring geographic information.",
        "auth": "No authentication required. However, assume that I'm located in Pennsylvania, USA.",
    },
    "wikipedia": {
        "platform_name": "Wikipedia",
        "description": "A free online encyclopedia with user-contributed content.",
        "auth": "No authentication required.",
    },
}


def resolve_agent_architecture(value: str | None, experiment_name: str | None) -> str:
    """Resolve the architecture variant while keeping old commands convenient."""

    if value:
        return value
    normalized_name = experiment_name.lower().replace("-", "_") if experiment_name else ""
    if normalized_name and "v3_repair_llm" in normalized_name:
        return "v3_repair_llm"
    if normalized_name and "v3_repair" in normalized_name:
        return "v3_repair_brief"
    if normalized_name and "v3" in normalized_name:
        return "v3"
    if normalized_name and "planact" in normalized_name:
        return "v2_planact"
    if normalized_name and "restart1" in normalized_name:
        return "v2_restart1"
    if normalized_name and "guarded" in normalized_name:
        return "v2_guarded"
    if normalized_name and "v2" in normalized_name:
        return "v2"
    return "v1"


def _read_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _webarena_prompt_path(task: dict[str, Any], site_name: str) -> Path:
    sites = sorted(str(site) for site in (task.get("sites") or [site_name]))
    return WEBARENA_VERIFIED_PROMPT_ROOT / ("-".join(sites) + ".md")


def _render_webarena_prompt_template(template: str, task: dict[str, Any]) -> str:
    start_urls = task.get("start_urls", [])
    start_url_lines = "\n".join(f"  - {url}" for url in start_urls) or "  - <current benchmark start URL>"
    rendered = template.replace("{{INTENT}}", str(task.get("intent", "")))
    rendered = re_sub_start_urls(rendered, start_url_lines)
    return rendered


def re_sub_start_urls(template: str, start_url_lines: str) -> str:
    """Render the small Jinja loop used in WebArena-Verified example prompts."""

    start_marker = "{% for start_url in START_URLS %}"
    end_marker = "{% endfor %}"
    if start_marker not in template or end_marker not in template:
        return template.replace("{{ START_URLS }}", start_url_lines)
    before, rest = template.split(start_marker, 1)
    _loop_body, after = rest.split(end_marker, 1)
    return before + start_url_lines + after


def webarena_verified_prompt_basis(task: dict[str, Any], site_name: str) -> tuple[str, str | None]:
    """Return the WebArena-Verified prompt basis and its source path when available."""

    path = _webarena_prompt_path(task, site_name)
    template = _read_if_exists(path)
    if not template:
        return _official_site_contract(task, site_name), None
    rendered = _render_webarena_prompt_template(template, task)
    provenance = "\n".join(
        [
            "# Prompt Provenance",
            f"- Base prompt source: {path}",
            "- Source family: WebArena-Verified example prompts.",
            "- v2_planact/v3 append grounding/validation rules but keep the WebArena-Verified task contract and final response schema as the base.",
        ]
    )
    return f"{provenance}\n\n{rendered}", str(path)


def _official_site_contract(task: dict[str, Any], site_name: str) -> str:
    sites = [str(site) for site in task.get("sites", [])] or [site_name]
    start_urls = task.get("start_urls", [])
    metadata_rows = [(site, SITE_METADATA.get(site, SITE_METADATA.get(site_name, {}))) for site in sites]
    if len(metadata_rows) == 1:
        site, metadata = metadata_rows[0]
        header = (
            f"You are an autonomous web agent operating in {metadata.get('platform_name', site)}. "
            "Begin from the provided start URLs and work within the current session to complete the task objective."
        )
        site_context = "\n".join(
            [
                "## Site Context",
                f"- Platform: {metadata.get('platform_name', site)}",
                f"- Description: {metadata.get('description', 'Benchmark web platform.')}",
                f"- Authentication: {metadata.get('auth', 'Use the current benchmark session.')} Keep the session active; do not log out or switch accounts.",
            ]
        )
    else:
        header = (
            "You are an autonomous web agent operating across multiple platforms. "
            "Begin from the provided start URLs and work within the current session to complete the task objective."
        )
        site_lines = ["## Site Context", "This task involves interaction with multiple platforms:"]
        for site, metadata in metadata_rows:
            site_lines.extend(
                [
                    "",
                    f"### {metadata.get('platform_name', site)}",
                    f"- Platform: {metadata.get('platform_name', site)}",
                    f"- Description: {metadata.get('description', 'Benchmark web platform.')}",
                    f"- Authentication: {metadata.get('auth', 'Use the current benchmark session.')}",
                ]
            )
        site_lines.append("Keep sessions active on all platforms; do not log out or switch accounts.")
        site_context = "\n".join(site_lines)

    start_url_lines = "\n".join(f"  - {url}" for url in start_urls) or "  - <current benchmark start URL>"
    return "\n\n".join(
        [
            "# WebArena-Verified Task Contract",
            header,
            site_context,
            "\n".join(
                [
                    "## Task Input",
                    f"- Task Objective: `{task.get('intent', '')}`",
                    "- Start URLs:",
                    start_url_lines,
                ]
            ),
            "\n".join(
                [
                    "## Task Types",
                    "- RETRIEVE: Retrieving data is the main objective.",
                    "- MUTATE: Creating, updating, or deleting data/state is the main objective.",
                    "- NAVIGATE: Navigating to show a specific page or search result is the main objective.",
                ]
            ),
            "\n".join(
                [
                    "## Operational Constraints",
                    "- Start URLs provide context; if specific, the objective relates to that page's content or section.",
                    "- Remain within the domain or domains of the provided start URLs.",
                    "- Avoid destructive actions unless the objective explicitly requires them.",
                    "- Do not download files.",
                    "- Complete the task autonomously without requesting user input or feedback.",
                    "- The final answer must follow the WebArena-Verified response JSON format.",
                ]
            ),
            "\n".join(
                [
                    "## Final Response Format",
                    '{"task_type":"RETRIEVE|MUTATE|NAVIGATE","status":"SUCCESS|NOT_FOUND_ERROR|ACTION_NOT_ALLOWED_ERROR|PERMISSION_DENIED_ERROR|DATA_VALIDATION_ERROR|UNKNOWN_ERROR","retrieved_data":[... ] or null,"error_details":null or "<explanation>"}',
                    "- When task_type is RETRIEVE, retrieved_data must always be a list.",
                    "- For MUTATE and NAVIGATE, retrieved_data should be null.",
                    "- Return a list of objects only if the task objective explicitly requests objects.",
                ]
            ),
        ]
    )


def build_executor_system_prompt(
    *,
    task: dict[str, Any],
    site_name: str,
    prompt_path: Path,
    architecture: str = "v1",
    prompt_root: Path = V2_PROMPT_ROOT,
) -> str:
    """Return the system prompt for the selected executor architecture."""

    if architecture not in {"v2", "v2_guarded", "v2_restart1", "v2_planact", "v3", "v3_repair_brief", "v3_repair_llm"}:
        return prompt_path.read_text(encoding="utf-8")

    official_contract, _source_path = webarena_verified_prompt_basis(task, site_name)
    executor_base = _read_if_exists(prompt_root / "executor_base.md")
    site_prompt = _read_if_exists(prompt_root / "sites" / f"{site_name}.md")
    site_tier_prompt = ""
    try:
        from .capabilities import capability_tier, infer_task_capability

        tier = capability_tier(infer_task_capability(task, site_name))
        site_tier_prompt = _read_if_exists(prompt_root / "sites" / f"{site_name}_{tier}.md")
    except Exception:
        site_tier_prompt = ""
    parts = [official_contract, executor_base]
    if site_prompt:
        parts.append(site_prompt)
    if site_tier_prompt:
        parts.append(site_tier_prompt)
    return "\n\n".join(part for part in parts if part.strip())
