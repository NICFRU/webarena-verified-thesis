#!/usr/bin/env python3
"""Inspect AgentLab/BrowserGym result folders with graceful fallbacks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


INTERESTING_SUFFIXES = {".json", ".jsonl", ".csv", ".txt", ".log", ".html", ".zip"}


def try_agentlab(path: Path) -> bool:
    try:
        import agentlab  # noqa: F401
    except Exception:
        return False

    print("AgentLab ist importierbar. Kein stabiles Loader-API wird hier vorausgesetzt.")
    print("Nutze bei vollständigen Runs zusätzlich: agentlab-xray <result-path>")
    return True


def preview_json(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  JSON konnte nicht gelesen werden: {exc}")
        return
    if isinstance(data, dict):
        print(f"  JSON keys: {', '.join(sorted(data.keys())[:12])}")
    elif isinstance(data, list):
        print(f"  JSON list entries: {len(data)}")
    else:
        print(f"  JSON type: {type(data).__name__}")


def inspect_path(path: Path) -> None:
    if path.is_file():
        print(f"Datei: {path}")
        print(f"Groesse: {path.stat().st_size} Bytes")
        if path.suffix == ".json":
            preview_json(path)
        return

    print(f"Verzeichnis: {path}")
    files = [p for p in path.rglob("*") if p.is_file()]
    print(f"Dateien gesamt: {len(files)}")
    interesting = [p for p in files if p.suffix.lower() in INTERESTING_SUFFIXES]
    print(f"Relevante Dateien: {len(interesting)}")

    for item in sorted(interesting)[:50]:
        rel = item.relative_to(path)
        print(f"- {rel} ({item.stat().st_size} Bytes)")
        if item.name == "minimal_summary.json" or item.suffix == ".json":
            preview_json(item)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_path", help="Path to an AgentLab result directory or summary file.")
    args = parser.parse_args()
    path = Path(args.result_path)

    if not path.exists():
        print(f"fehlt - Pfad existiert nicht: {path}")
        return 1

    print("Result Inspection")
    print("=" * 72)
    try_agentlab(path)
    inspect_path(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

