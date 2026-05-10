#!/usr/bin/env python3
"""Check the local minimal WebArena-Verified / AgentLab setup."""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from pathlib import Path


REQUIRED_ENV = [
    "AGENTLAB_EXP_ROOT",
    "WA_SHOPPING",
    "WA_SHOPPING_ADMIN",
    "WA_REDDIT",
    "WA_GITLAB",
    "WA_WIKIPEDIA",
    "WA_MAP",
    "WA_HOMEPAGE",
]

IMPORTS = [
    ("agentlab", "AgentLab experiment runner"),
    ("browsergym", "BrowserGym environment interface"),
    ("browsergym.webarena_verified", "BrowserGym WebArena-Verified integration"),
    ("webarena_verified", "WebArena-Verified toolkit"),
]


def status(label: str, state: str, detail: str = "", next_step: str = "") -> None:
    line = f"{label:<38} {state}"
    if detail:
        line += f" - {detail}"
    print(line)
    if next_step:
        print(f"{'':<38} nächster Schritt: {next_step}")


def load_dotenv_if_available() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv
    except Exception:
        status(
            ".env laden",
            "optional",
            "python-dotenv ist nicht installiert",
            "pip install -r requirements.txt ausführen",
        )
        return

    load_dotenv(env_path)
    status(".env laden", "OK", str(env_path))


def import_state(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


def is_missing_value(value: str | None) -> bool:
    return value is None or value.strip() == "" or value.strip().lower() == "todo"


def main() -> int:
    print("Minimaler Setup-Check für WebArena-Verified / BrowserGym / AgentLab")
    print("=" * 72)

    py_version = sys.version_info
    py_text = platform.python_version()
    if (py_version.major, py_version.minor) in {(3, 11), (3, 12)}:
        status("Python-Version", "OK", py_text)
    else:
        status(
            "Python-Version",
            "fehlt",
            py_text,
            "Python 3.12 venv verwenden; Python 3.11 kann für Teile funktionieren",
        )

    load_dotenv_if_available()

    print("\nPython-Imports")
    print("-" * 72)
    import_results: dict[str, bool] = {}
    for module_name, description in IMPORTS:
        ok = import_state(module_name)
        import_results[module_name] = ok
        status(
            module_name,
            "OK" if ok else "fehlt",
            description,
            "" if ok else "pip install -r requirements.txt in einer passenden .venv ausführen",
        )

    print("\nEnvironment-Variablen")
    print("-" * 72)
    missing_urls = []
    for key in REQUIRED_ENV:
        value = os.getenv(key)
        if is_missing_value(value):
            state = "optional" if key != "AGENTLAB_EXP_ROOT" else "fehlt"
            next_step = (
                "für AgentLab-Resultate setzen, z. B. ./agentlab-results"
                if key == "AGENTLAB_EXP_ROOT"
                else "setzen, sobald die WebArena-Instanz erreichbar ist"
            )
            status(key, state, "nicht gesetzt oder todo", next_step)
            if key != "AGENTLAB_EXP_ROOT":
                missing_urls.append(key)
        else:
            status(key, "OK", value)

    print("\nEinordnung")
    print("-" * 72)
    if missing_urls:
        print(
            "WebArena-Verified ist noch nicht direkt ausführbar, weil Live-URLs fehlen. "
            "Der Fallback-Smoke-Test mit BrowserGym/AgentLab bleibt der nächste sinnvolle Schritt."
        )
    else:
        print("Alle WebArena-URL-Variablen sind gesetzt; ein einzelner Task kann als nächstes getestet werden.")

    if not import_results.get("agentlab") or not import_results.get("browsergym"):
        print("nächster Schritt: Dependencies in einer Python-3.12-venv installieren.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
