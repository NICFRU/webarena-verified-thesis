"""Trace logging helpers for local agent architecture prototypes."""

from __future__ import annotations

from pathlib import Path

from .io_utils import append_jsonl, write_json
from .types import ControllerDecision, EvaluatorSignal, ExecutorStep, Plan, RunTrace


class TraceLogger:
    """Write structured planner, executor, evaluator, and controller artifacts."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.step_trace_path = output_dir / "step_trace.jsonl"
        self.evaluator_path = output_dir / "evaluator_signals.jsonl"
        self.controller_path = output_dir / "controller_decisions.jsonl"

    def reset(self) -> None:
        """Clear per-run JSONL files."""

        for path in [self.step_trace_path, self.evaluator_path, self.controller_path]:
            path.unlink(missing_ok=True)

    def write_plan(self, plan: Plan) -> Path:
        """Write the planner output."""

        path = self.output_dir / "plan.json"
        write_json(path, plan)
        return path

    def write_planner_call(self, call_index: int, plan: Plan, prompt: str | None, raw_response: str | None, warnings: list[str] | None) -> Path:
        """Write one planner-call bundle for initial planning or replanning."""

        call_dir = self.output_dir / "planner_calls" / f"call_{call_index:02d}"
        write_json(call_dir / "plan.json", plan)
        write_json(call_dir / "warnings.json", warnings or [])
        if prompt is not None:
            (call_dir / "planner_prompt.md").write_text(prompt, encoding="utf-8")
        if raw_response is not None:
            (call_dir / "planner_raw_response.txt").write_text(raw_response, encoding="utf-8")
        return call_dir

    def log_executor_step(self, step: ExecutorStep) -> None:
        """Append one executor step."""

        append_jsonl(self.step_trace_path, step)

    def log_reset(self, step_index: int, url: str, observation_keys: list[str]) -> None:
        """Append the environment reset event in the same step trace."""

        append_jsonl(
            self.step_trace_path,
            {
                "step_index": step_index,
                "module": "executor",
                "action": "env.reset",
                "subgoal_id": "sg1",
                "url_after": url,
                "observation_keys": observation_keys,
                "status": "success",
            },
        )

    def log_evaluator_signal(self, signal: EvaluatorSignal) -> None:
        """Append one runtime evaluator signal."""

        append_jsonl(self.evaluator_path, signal)

    def log_controller_decision(self, decision: ControllerDecision) -> None:
        """Append one controller decision."""

        append_jsonl(self.controller_path, decision)

    def write_run_trace(self, trace: RunTrace) -> Path:
        """Write run-level metrics."""

        path = self.output_dir / "run_trace.json"
        write_json(path, trace)
        return path
