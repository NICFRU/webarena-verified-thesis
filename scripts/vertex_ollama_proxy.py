#!/usr/bin/env python3
"""Small Ollama-compatible proxy for Vertex AI MaaS chat calls.

This lets the existing H/k runner keep using its Ollama `/api/chat` client while
the actual model call is sent to Vertex AI with Application Default Credentials.
It is intended for short speed/compatibility tests, not as a production server.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import google.auth
import google.auth.transport.requests


DEFAULT_MODEL = "gemma-4-26b-a4b-it-maas"
DEFAULT_LOCATION = "global"
DEFAULT_PUBLISHER = "google"


class VertexClient:
    """Minimal REST client for Vertex AI generateContent."""

    def __init__(
        self,
        *,
        project_id: str,
        location: str = DEFAULT_LOCATION,
        publisher: str = DEFAULT_PUBLISHER,
        default_model: str = DEFAULT_MODEL,
        force_default_model: bool = False,
        timeout_seconds: int = 600,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.publisher = publisher
        self.default_model = default_model
        self.force_default_model = force_default_model
        self.timeout_seconds = timeout_seconds
        self.credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.auth_request = google.auth.transport.requests.Request()

    def access_token(self) -> str:
        if not self.credentials.valid:
            self.credentials.refresh(self.auth_request)
        return str(self.credentials.token)

    def endpoint(self, model: str) -> str:
        host = "aiplatform.googleapis.com" if self.location == "global" else f"{self.location}-aiplatform.googleapis.com"
        model_name = model or self.default_model
        if "/" in model_name:
            model_path = model_name
        else:
            model_path = f"publishers/{self.publisher}/models/{model_name}"
        return (
            f"https://{host}/v1/projects/{self.project_id}/locations/{self.location}/"
            f"{model_path}:generateContent"
        )

    def generate(self, *, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = Request(
            self.endpoint(model),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.access_token()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Vertex HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Vertex request failed: {exc}") from exc


def _messages_to_vertex(messages: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    system_texts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        text = str(message.get("content") or "")
        if role == "system":
            system_texts.append(text)
            continue
        vertex_role = "model" if role == "assistant" else "user"
        contents.append({"role": vertex_role, "parts": [{"text": text}]})
    system_instruction = None
    if system_texts:
        system_instruction = {"parts": [{"text": "\n\n".join(system_texts)}]}
    if not contents:
        contents = [{"role": "user", "parts": [{"text": ""}]}]
    return system_instruction, contents


def _generation_config(ollama_payload: dict[str, Any]) -> dict[str, Any]:
    options = dict(ollama_payload.get("options") or {})
    config: dict[str, Any] = {
        "temperature": float(options.get("temperature", 0.1)),
        "topP": float(options.get("top_p", 0.95)),
        "maxOutputTokens": int(options.get("num_predict", 600)),
    }
    if options.get("top_k") is not None:
        config["topK"] = int(options["top_k"])
    if options.get("stop"):
        config["stopSequences"] = list(options["stop"])
    if str(ollama_payload.get("format") or "").lower() == "json":
        config["responseMimeType"] = "application/json"
    return config


def _vertex_payload_from_ollama(ollama_payload: dict[str, Any]) -> dict[str, Any]:
    system_instruction, contents = _messages_to_vertex(list(ollama_payload.get("messages") or []))
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": _generation_config(ollama_payload),
    }
    if system_instruction is not None:
        payload["systemInstruction"] = system_instruction
    return payload


def _text_from_vertex(response: dict[str, Any]) -> str:
    candidates = response.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(str(part.get("text") or "") for part in parts)


def _ollama_response_from_vertex(response: dict[str, Any], *, model: str, elapsed_ns: int) -> dict[str, Any]:
    usage = response.get("usageMetadata") or {}
    prompt_tokens = usage.get("promptTokenCount")
    completion_tokens = usage.get("candidatesTokenCount")
    return {
        "model": model,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message": {"role": "assistant", "content": _text_from_vertex(response)},
        "done": True,
        "total_duration": elapsed_ns,
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
    }


def make_handler(client: VertexClient):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VertexOllamaProxy/0.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/", "/api/tags"}:
                self._send_json({"models": [{"name": client.default_model}]})
                return
            self.send_error(404, "not found")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/chat":
                self.send_error(404, "only /api/chat is implemented")
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
                ollama_payload = json.loads(self.rfile.read(length).decode("utf-8"))
                model = str(ollama_payload.get("model") or client.default_model)
                vertex_model = client.default_model if client.force_default_model else model
                vertex_payload = _vertex_payload_from_ollama(ollama_payload)
                started = time.perf_counter_ns()
                vertex_response = client.generate(model=vertex_model, payload=vertex_payload)
                elapsed_ns = time.perf_counter_ns() - started
                self._send_json(_ollama_response_from_vertex(vertex_response, model=model, elapsed_ns=elapsed_ns))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[vertex-proxy] {self.address_string()} - {format % args}", flush=True)

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Expose Vertex AI MaaS through an Ollama-compatible /api/chat endpoint.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--project-id", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--publisher", default=os.environ.get("VERTEX_MAAS_PUBLISHER", DEFAULT_PUBLISHER))
    parser.add_argument("--model", default=os.environ.get("VERTEX_MAAS_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--force-default-model",
        action="store_true",
        help="Ignore incoming Ollama model names and route every request to --model. Useful when local aliases like gemma4:26b should be served by one Vertex MaaS model.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()

    if not args.project_id:
        raise SystemExit("Set GOOGLE_CLOUD_PROJECT or pass --project-id.")
    client = VertexClient(
        project_id=args.project_id,
        location=args.location,
        publisher=args.publisher,
        default_model=args.model,
        force_default_model=args.force_default_model,
        timeout_seconds=args.timeout_seconds,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(client))
    print(
        f"Vertex Ollama proxy listening on http://{args.host}:{args.port} "
        f"for model={args.model} project={args.project_id} location={args.location}",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
