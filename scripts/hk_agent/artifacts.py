"""Artifact and timing helpers for H/k agent runs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from webarena_exp.io_utils import append_jsonl, read_jsonl, write_json
from webarena_exp.types import ControllerDecision, EvaluatorSignal, ExecutorStep, Plan


def utc_now() -> str:
    """Return an ISO timestamp in UTC."""

    return datetime.now(UTC).isoformat()


@dataclass
class PhaseTracker:
    """Track elapsed time for named run phases."""

    started_at: float = field(default_factory=time.perf_counter)
    phases_ms: dict[str, int] = field(default_factory=dict)

    def measure(self, name: str):
        tracker = self

        class _Context:
            def __enter__(self):
                self.started = time.perf_counter()
                return self

            def __exit__(self, exc_type, exc, tb):
                tracker.phases_ms[name] = tracker.phases_ms.get(name, 0) + int((time.perf_counter() - self.started) * 1000)

        return _Context()

    @property
    def total_runtime_ms(self) -> int:
        return int((time.perf_counter() - self.started_at) * 1000)


class HkArtifactWriter:
    """Write structured artifacts for one H/k task run."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.step_trace_path = output_dir / "step_trace.jsonl"
        self.evaluator_path = output_dir / "runtime_evaluator_signals.jsonl"
        self.controller_path = output_dir / "controller_decisions.jsonl"
        self.planner_calls_path = output_dir / "planner_calls.jsonl"
        self.executor_calls_path = output_dir / "executor_calls.jsonl"
        self.executor_prompts_dir = output_dir / "executor_prompts"
        self.executor_grounding_dir = output_dir / "executor_grounding"

    def reset(self) -> None:
        for path in [
            self.step_trace_path,
            self.evaluator_path,
            self.controller_path,
            self.planner_calls_path,
            self.executor_calls_path,
        ]:
            path.unlink(missing_ok=True)
        for directory in [self.executor_prompts_dir, self.executor_grounding_dir]:
            if directory.exists():
                for path in directory.glob("*"):
                    if path.is_file():
                        path.unlink(missing_ok=True)

    def write_plan(self, plan: Plan) -> Path:
        path = self.output_dir / "plan.json"
        write_json(path, plan)
        return path

    def log_step(self, step: ExecutorStep | dict[str, Any]) -> None:
        append_jsonl(self.step_trace_path, step)

    def log_runtime_signal(self, signal: EvaluatorSignal) -> None:
        append_jsonl(self.evaluator_path, signal)

    def log_controller_decision(self, decision: ControllerDecision) -> None:
        append_jsonl(self.controller_path, decision)

    def log_planner_call(self, row: dict[str, Any]) -> None:
        append_jsonl(self.planner_calls_path, row)

    def log_executor_call(self, row: dict[str, Any]) -> None:
        append_jsonl(self.executor_calls_path, row)

    def write_executor_prompt(self, call_index: int, prompt: str) -> Path:
        self.executor_prompts_dir.mkdir(parents=True, exist_ok=True)
        path = self.executor_prompts_dir / f"call_{call_index:02d}.md"
        path.write_text(prompt, encoding="utf-8")
        return path

    def write_executor_grounding(self, call_index: int, payload: dict[str, Any]) -> Path:
        self.executor_grounding_dir.mkdir(parents=True, exist_ok=True)
        path = self.executor_grounding_dir / f"call_{call_index:02d}.json"
        write_json(path, payload)
        return path

    def runtime_counts(self) -> dict[str, int]:
        evaluator_rows = read_jsonl(self.evaluator_path)
        controller_rows = read_jsonl(self.controller_path)
        return {
            "runtime_replans": sum(1 for row in controller_rows if row.get("decision") in {"local_replan", "global_replan"}),
            "runtime_no_progress_events": sum(1 for row in evaluator_rows if row.get("no_progress") or row.get("loop_or_no_progress_flag")),
            "runtime_invalid_actions": sum(1 for row in evaluator_rows if row.get("invalid_action") or row.get("action_validity_flag") is False),
            "runtime_loop_events": sum(1 for row in evaluator_rows if row.get("loop_detected")),
        }

    def mean_runtime_progress(self) -> float | None:
        rows = read_jsonl(self.evaluator_path)
        scores = [row.get("progress_score") for row in rows if row.get("progress_score") is not None]
        return sum(scores) / len(scores) if scores else None


def write_agent_response(path: Path, task_type: str, retrieved_data: Any = None, error_details: str | None = None) -> Path:
    """Write WebArena-Verified compatible agent response."""

    response = {
        "task_type": task_type.upper(),
        "status": "SUCCESS" if error_details is None else "UNKNOWN_ERROR",
        "retrieved_data": retrieved_data,
        "error_details": error_details,
    }
    write_json(path, response)
    return path


def parse_agent_response_from_action(action: str) -> dict[str, Any] | None:
    """Extract a JSON final response from send_msg_to_user(...) when possible."""

    prefix = "send_msg_to_user("
    if not action.strip().startswith(prefix):
        return None
    inner = action.strip()[len(prefix) :].rstrip(")")
    try:
        text = json.loads(inner)
    except json.JSONDecodeError:
        text = inner.strip("'\"")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
