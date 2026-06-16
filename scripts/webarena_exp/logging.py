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
        self.planner_calls_path = output_dir / "planner_calls.jsonl"
        self.executor_calls_path = output_dir / "executor_calls.jsonl"

    def reset(self) -> None:
        """Clear per-run JSONL files."""

        for path in [self.step_trace_path, self.evaluator_path, self.controller_path, self.planner_calls_path, self.executor_calls_path]:
            path.unlink(missing_ok=True)

    def write_plan(self, plan: Plan) -> Path:
        """Write the planner output."""

        path = self.output_dir / "plan.json"
        write_json(path, plan)
        return path

    def write_planner_call(
        self,
        call_index: int,
        plan: Plan,
        prompt: str | None,
        raw_response: str | None,
        warnings: list[str] | None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        elapsed_ms: int | None = None,
        model_name: str | None = None,
    ) -> Path:
        """Write one planner-call bundle for initial planning or replanning."""

        call_dir = self.output_dir / "planner_calls" / f"call_{call_index:02d}"
        plan_path = call_dir / "plan.json"
        warnings_path = call_dir / "warnings.json"
        prompt_path = call_dir / "planner_prompt.md"
        raw_response_path = call_dir / "planner_raw_response.txt"
        write_json(plan_path, plan)
        write_json(warnings_path, warnings or [])
        if prompt is not None:
            prompt_path.write_text(prompt, encoding="utf-8")
        if raw_response is not None:
            raw_response_path.write_text(raw_response, encoding="utf-8")
        append_jsonl(
            self.planner_calls_path,
            {
                "call_index": call_index,
                "planner_mode": plan.planner_mode,
                "model_name": model_name,
                "task_id": plan.task_id,
                "h": plan.h,
                "subgoal_count": len(plan.subgoals),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "elapsed_ms": elapsed_ms,
                "warnings": warnings or [],
                "prompt_path": str(prompt_path) if prompt is not None else None,
                "raw_response_path": str(raw_response_path) if raw_response is not None else None,
                "plan_path": str(plan_path),
                "warnings_path": str(warnings_path),
            },
        )
        return call_dir

    def log_executor_step(self, step: ExecutorStep) -> None:
        """Append one executor step."""

        append_jsonl(self.step_trace_path, step)

    def write_executor_call(
        self,
        call_index: int,
        subgoal_id: str,
        prompt: str | None,
        raw_response: str | None,
        parsed_action: dict | None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        elapsed_ms: int | None = None,
        model_name: str | None = None,
    ) -> Path:
        """Write one action-executor LLM call bundle."""

        call_dir = self.output_dir / "executor_calls" / f"call_{call_index:02d}"
        call_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = call_dir / "executor_prompt.md"
        raw_response_path = call_dir / "executor_raw_response.txt"
        action_path = call_dir / "executor_action.json"
        if prompt is not None:
            prompt_path.write_text(prompt, encoding="utf-8")
        if raw_response is not None:
            raw_response_path.write_text(raw_response, encoding="utf-8")
        if parsed_action is not None:
            write_json(action_path, parsed_action)
        append_jsonl(
            self.executor_calls_path,
            {
                "call_index": call_index,
                "subgoal_id": subgoal_id,
                "model_name": model_name,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "elapsed_ms": elapsed_ms,
                "action": parsed_action.get("action") if parsed_action else None,
                "action_type": parsed_action.get("action_type") if parsed_action else None,
                "prompt_path": str(prompt_path) if prompt is not None else None,
                "raw_response_path": str(raw_response_path) if raw_response is not None else None,
                "action_path": str(action_path) if parsed_action is not None else None,
            },
        )
        return call_dir

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
