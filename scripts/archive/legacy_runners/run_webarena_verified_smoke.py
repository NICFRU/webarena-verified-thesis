#!/usr/bin/env python3
"""Prepare a tiny WebArena-Verified smoke check without launching a full benchmark."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
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

WEB_ENV_KEYS = [
    "WA_SHOPPING",
    "WA_SHOPPING_ADMIN",
    "WA_REDDIT",
    "WA_GITLAB",
    "WA_WIKIPEDIA",
    "WA_MAP",
    "WA_HOMEPAGE",
]


def write_summary(**updates: Any) -> Path:
    out = Path("runs/minimal_summary.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {**SUMMARY_TEMPLATE, **updates}
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return out


def missing_env_keys() -> list[str]:
    missing = []
    for key in WEB_ENV_KEYS:
        value = os.getenv(key)
        if value is None or value.strip() == "" or value.strip().lower() == "todo":
            missing.append(key)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/webarena_verified_config.example.json",
        help="Path to a WebArena-Verified config JSON file.",
    )
    parser.add_argument("--task-id", default="108", help="Tiny example task id for CLI examples.")
    args = parser.parse_args()

    print("WebArena-Verified Smoke Preparation")
    print("=" * 72)

    if importlib.util.find_spec("webarena_verified") is None:
        summary = write_summary(
            benchmark="webarena-verified",
            task_id=args.task_id,
            abort_reason="webarena_verified_import_missing",
        )
        print("fehlt - Python-Paket 'webarena_verified' ist nicht importierbar.")
        print("nächster Schritt: pip install -r requirements.txt in einer passenden .venv")
        print(f"Summary geschrieben: {summary}")
        return 0

    config_path = Path(args.config)
    if not config_path.exists():
        summary = write_summary(
            benchmark="webarena-verified",
            task_id=args.task_id,
            abort_reason="config_missing",
        )
        print(f"fehlt - Config-Datei nicht gefunden: {config_path}")
        print("nächster Schritt: configs/webarena_verified_config.example.json kopieren und anpassen")
        print(f"Summary geschrieben: {summary}")
        return 0

    missing = missing_env_keys()
    if missing:
        summary = write_summary(
            benchmark="webarena-verified",
            task_id=args.task_id,
            abort_reason="webarena_urls_missing",
        )
        print("optional - Live-URLs fehlen oder stehen noch auf todo:")
        for key in missing:
            print(f"  - {key}")
        print("\nKein großer Benchmark wird gestartet.")
        print("Sobald die URLs laufen, teste z. B.:")
        print(
            "  webarena-verified eval-tasks "
            f"--task-ids {args.task_id} --config {config_path} "
            "--output-dir runs/webarena_verified/smoke"
        )
        print("Dataset-Export als reine Vorbereitung:")
        print("  webarena-verified dataset-get --output runs/webarena_verified/dataset.json")
        print(f"Summary geschrieben: {summary}")
        return 0

    summary = write_summary(
        benchmark="webarena-verified",
        task_id=args.task_id,
        abort_reason="manual_cli_step_required",
        result_path="runs/webarena_verified/smoke",
    )
    print("OK - Paket, Config und URL-Variablen sind vorhanden.")
    print("Nächster manueller Smoke-Befehl:")
    print(
        "  webarena-verified eval-tasks "
        f"--task-ids {args.task_id} --config {config_path} "
        "--output-dir runs/webarena_verified/smoke"
    )
    print(f"Summary geschrieben: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

