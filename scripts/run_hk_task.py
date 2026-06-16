#!/usr/bin/env python3
"""Run one H/k Planner/Executor/Evaluator/Controller task.

This is the neutral entrypoint for the thesis runner. The historical
``run_hk_task44_prototype`` module still contains the implementation so older
commands keep working while the experiment moves beyond Task 44.
"""

from __future__ import annotations

from run_hk_task44_prototype import main


if __name__ == "__main__":
    raise SystemExit(main())
