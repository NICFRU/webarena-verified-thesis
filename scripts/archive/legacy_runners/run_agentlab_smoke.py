#!/usr/bin/env python3
"""Fallback smoke test for the AgentLab / BrowserGym toolchain."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


SUMMARY_TEMPLATE: dict[str, Any] = {
    "benchmark": None,
    "task_id": None,
    "agent_name": None,
    "h": None,
    "k": None,
    "success": None,
    "total_steps": None,
    "total_runtime_ms": None,
    "total_tokens": None,
    "num_invalid_actions": 0,
    "num_replans": 0,
    "num_no_progress_events": 0,
    "abort_reason": None,
    "result_path": None,
}


def write_summary(**updates: Any) -> Path:
    out = Path("runs/minimal_summary.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {**SUMMARY_TEMPLATE, **updates}
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return out


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run_browsergym_openended_probe(result_root: Path) -> bool:
    """Exercise BrowserGym registration without assuming an LLM API key."""
    code = """
import gymnasium as gym
import browsergym.core
env = gym.make(
    "browsergym/openended",
    task_kwargs={"start_url": "data:text/html,<title>BrowserGym smoke</title><button>OK</button>"},
    wait_for_user_message=False,
)
obs, info = env.reset()
print("browsergym/openended reset OK")
print("observation_keys", sorted(obs.keys())[:8])
env.close()
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
    )
    (result_root / "browsergym_openended_probe.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (result_root / "browsergym_openended_probe.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    print(proc.stdout.strip())
    if proc.returncode != 0:
        print(proc.stderr.strip())
    return proc.returncode == 0


def main() -> int:
    print("AgentLab / BrowserGym Fallback Smoke Test")
    print("=" * 72)

    result_root = Path(os.getenv("AGENTLAB_EXP_ROOT", "./agentlab-results")) / "minimal_smoke"
    result_root.mkdir(parents=True, exist_ok=True)

    if not has_module("agentlab"):
        summary = write_summary(
            benchmark="miniwob_tiny_test",
            agent_name="non_api_or_builtin_agent",
            abort_reason="agentlab_import_missing",
            result_path=str(result_root),
        )
        print("fehlt - AgentLab ist nicht importierbar.")
        print("nächster Schritt: pip install -r requirements.txt in einer passenden .venv")
        print(f"Result-Pfad vorbereitet: {result_root}")
        print(f"Summary geschrieben: {summary}")
        return 0

    if not has_module("browsergym"):
        summary = write_summary(
            benchmark="miniwob_tiny_test",
            agent_name="non_api_or_builtin_agent",
            abort_reason="browsergym_import_missing",
            result_path=str(result_root),
        )
        print("fehlt - BrowserGym ist nicht importierbar.")
        print("nächster Schritt: pip install -r requirements.txt in einer passenden .venv")
        print(f"Summary geschrieben: {summary}")
        return 0

    print("OK - AgentLab und BrowserGym sind importierbar.")
    print("Benchmark: bevorzugt miniwob_tiny_test; Fallback-Probe: browsergym/openended")
    print("Agent: nicht-API-basierter Smoke-Probe ohne LLM-Key")
    print(f"Result-Pfad: {result_root}")

    ok = run_browsergym_openended_probe(result_root)
    summary = write_summary(
        benchmark="browsergym/openended",
        agent_name="non_api_smoke_probe",
        success=ok,
        abort_reason=None if ok else "browsergym_probe_failed",
        result_path=str(result_root),
    )
    print(f"Summary geschrieben: {summary}")
    print("Inspection: agentlab-xray <result-path> oder python scripts/inspect_results.py <result-path>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

