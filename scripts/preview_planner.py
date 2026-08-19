#!/usr/bin/env python3
"""Preview planner outputs for the local WebArena-Verified task set."""

from __future__ import annotations

import argparse
from pathlib import Path

from tqdm import tqdm

from webarena_exp.hardcoded_tasks import HARDCODED_TASKS, hardcoded_task_names
from webarena_exp.io_utils import write_json
from webarena_exp.planner import PlannerRequest, build_plan
from webarena_exp.site_definitions import SITE_INPUTS, site_names
from webarena_exp.types import SiteInput
from webarena_exp.webarena_cli import export_agent_input, write_site_config


def select_sites(names: list[str] | None) -> list[SiteInput]:
    """Select enabled sites with hardcoded planner-preview tasks."""

    selected_names = names or hardcoded_task_names()
    known = set(site_names(include_disabled=True))
    selected = []
    for name in selected_names:
        if name not in known:
            raise ValueError(f"Unknown site: {name}. Known sites: {', '.join(sorted(known))}")
        site = SITE_INPUTS[name]
        if not site.enabled:
            raise ValueError(f"Site {name!r} is excluded: {site.exclusion_reason}")
        if name not in HARDCODED_TASKS:
            raise ValueError(f"No planner-preview task is defined for site {name!r}")
        selected.append(site)
    return selected


def load_task(repo_root: Path, site: SiteInput, output_root: Path) -> dict:
    """Render the official task input when possible; otherwise create a direct task."""

    spec = HARDCODED_TASKS[site.name]
    if spec.task_id is None:
        return {
            "sites": [site.name],
            "task_id": None,
            "start_urls": [site.base_url],
            "intent": spec.intent,
            "task_type": spec.task_type,
        }

    config_path = write_site_config(repo_root, site, output_dir=output_root / "configs")
    task_path = output_root / "rendered_tasks" / site.name / f"task_{spec.task_id}.json"
    rendered = export_agent_input(repo_root, spec.task_id, config_path, task_path)
    task = rendered[0]
    task["task_type"] = spec.task_type
    return task


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("external/webarena-verified"))
    parser.add_argument("--output-root", type=Path, default=Path("output/planner-preview"))
    parser.add_argument("--sites", nargs="*", help="Optional subset, e.g. --sites gitlab shopping")
    parser.add_argument("--h", type=int, default=0, help="Planning horizon. 0 means full plan.")
    parser.add_argument("--planner-mode", choices=["ollama"], default="ollama")
    parser.add_argument("--model", default="gemma4:26b", help="Ollama model name for --planner-mode ollama.")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--prompt-path", type=Path, default=Path("prompts/v3/planner_system.md"))
    parser.add_argument("--user-template-path", type=Path, default=Path("prompts/v3/prompt_user_template.md"))
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    output_root = args.output_root if args.output_root.is_absolute() else repo_root / args.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    sites = select_sites(args.sites)

    results = []
    with tqdm(total=len(sites), desc="Planner preview", unit="site") as bar:
        for site in sites:
            spec = HARDCODED_TASKS[site.name]
            task = load_task(repo_root, site, output_root)
            label = str(spec.task_id) if spec.task_id is not None else "direct"
            task_dir = output_root / site.name / label
            request = PlannerRequest(
                task=task,
                site_name=site.name,
                h=args.h,
                target_hint=spec.target_path,
                retrieved_data_hint=spec.retrieved_data,
                initial_observation="Planner preview has no live browser observation. Plan for both possible states: login page or already authenticated page.",
            )
            artifacts = build_plan(
                request,
                planner_mode=args.planner_mode,
                model_name=args.model,
                ollama_base_url=args.ollama_base_url,
                prompt_path=args.prompt_path,
                user_template_path=args.user_template_path,
            )
            write_json(task_dir / "task_input.json", task)
            write_json(task_dir / "plan.json", artifacts.plan)
            if artifacts.prompt is not None:
                (task_dir / "planner_prompt.md").write_text(artifacts.prompt, encoding="utf-8")
            if artifacts.raw_response is not None:
                (task_dir / "planner_raw_response.txt").write_text(artifacts.raw_response, encoding="utf-8")

            result = {
                "site": site.name,
                "task_id": spec.task_id,
                "planner_mode": artifacts.plan.planner_mode,
                "model_name": artifacts.model_name,
                "h": args.h,
                "subgoal_count": len(artifacts.plan.subgoals),
                "output_dir": str(task_dir),
                "plan": str(task_dir / "plan.json"),
                "warnings": artifacts.warnings or [],
            }
            results.append(result)
            warning_text = f" warnings={','.join(artifacts.warnings)}" if artifacts.warnings else ""
            tqdm.write(f"[PLAN] {site.name}: task={spec.task_id or 'direct'} subgoals={len(artifacts.plan.subgoals)}{warning_text}")
            bar.update(1)

    write_json(
        output_root / "summary.json",
        {
            "planner_mode": args.planner_mode,
            "model": args.model if args.planner_mode == "ollama" else None,
            "h": args.h,
            "results": results,
        },
    )
    print(f"\nSummary: {output_root / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
