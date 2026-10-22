#!/usr/bin/env python3
"""Loopback recording proxy between S-Code and OpenRouter for the edit-format benchmark.

Each S-Code run is pointed at http://127.0.0.1:<port>/r/<run_id>/v1. The proxy:
- injects the configured provider routing and optional reasoning settings;
- streams the upstream response through unchanged;
- retries only before any response byte reaches S-Code;
- appends one record per model call to <runs_dir>/<run_id>/model_calls.jsonl;
- later records the serving provider in generations.jsonl.

A hard cost stop answers 429 once the recorded spend reaches --max-cost-usd.
The OpenRouter key exists only in this process's environment and is never
written to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

RUN_PATH = re.compile(r"^/r/([A-Za-z0-9_.-]{1,255})/v1/chat/completions$")
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_ERROR_BODY_BYTES = 4096
CALLS_FILE = "model_calls.jsonl"
GENERATIONS_FILE = "generations.jsonl"
GENERATION_FIELDS = (
    "provider_name",
    "model",
    "total_cost",
    "native_tokens_prompt",
    "native_tokens_completion",
    "native_tokens_reasoning",
    "native_tokens_cached",
    "latency",
    "finish_reason",
    "native_finish_reason",
    "upstream_id",
    "is_byok",
)


def load_config(path: Path) -> dict[str, Any]:
    """Load and validate proxy settings; every model must pin one provider without fallbacks."""
    config = json.loads(path.read_text())
    models = config.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("config requires a nonempty models object")
    for model, settings in models.items():
        provider = settings.get("provider") if isinstance(settings, dict) else None
        if not isinstance(provider, dict):
            raise ValueError(f"{model}: provider object required")
        order = provider.get("order")
        if not (isinstance(order, list) and len(order) == 1 and isinstance(order[0], str) and order[0]):
            raise ValueError(f"{model}: provider.order must name exactly one provider")
        if provider.get("allow_fallbacks") is not False:
            raise ValueError(f"{model}: provider.allow_fallbacks must be false")
        if provider.get("require_parameters") is not True:
            raise ValueError(f"{model}: provider.require_parameters must be true")
    return config


def sanitize_tool_arguments(messages: Any) -> tuple[Any, int]:
    """Replace invalid JSON tool-call arguments in the replayed history with `{}`.

    When a model emits malformed arguments, S-Code rejects the call and later
    replays the assistant message verbatim. Some providers parse historical
    arguments and answer HTTP 400, which ends the turn and turns a format error
    into an infrastructure failure. The matching tool result still carries
    S-Code's parse error. The replacement must not look like a usable shape, or
    a model may copy it into a new call.
    """
    if not isinstance(messages, list):
        return messages, 0
    count = 0
    cleaned = []
    for message in messages:
        calls = message.get("tool_calls") if isinstance(message, dict) else None
        if message.get("role") != "assistant" or not isinstance(calls, list):
            cleaned.append(message)
            continue
        new_calls = []
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            arguments = function.get("arguments") if isinstance(function, dict) else None
            if isinstance(arguments, str):
                try:
                    json.loads(arguments)
                except json.JSONDecodeError:
                    call = {**call, "function": {**function, "arguments": "{}"}}
                    count += 1
            new_calls.append(call)
        cleaned.append({**message, "tool_calls": new_calls})
    return cleaned, count


def prepare_body(body: dict[str, Any], settings: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Inject routing and reasoning; drop parameters the pinned provider does not accept.

    With require_parameters=true, OpenRouter refuses providers that do not
    support every request parameter. Some endpoints reject `temperature`,
    which S-Code always sends, so each model may list parameters to drop. The
    dropped names are returned so every call record shows what was removed.
    """
    prepared = dict(body)
    prepared["messages"], sanitized = sanitize_tool_arguments(prepared.get("messages"))
    prepared["_sanitized_tool_arguments"] = sanitized
    dropped = [name for name in settings.get("drop_parameters", []) if name in prepared]
    for name in dropped:
        del prepared[name]
    # Model-card sampling parameters S-Code does not send itself (e.g. top_p).
    for name, value in (settings.get("set_parameters") or {}).items():
        prepared[name] = value
    prepared["provider"] = settings["provider"]
    if "reasoning" in settings:
        prepared["reasoning"] = settings["reasoning"]
    return prepared, dropped


def stream_tool_call(index: int, name: Any, arguments: str) -> dict[str, Any]:
    """Summarize one tool call exactly as the upstream stream carried it, before S-Code parses it."""
    try:
        json.loads(arguments)
        valid = True
    except json.JSONDecodeError:
        valid = False
    encoded = arguments.encode()
    return {
        "index": index,
        "name": name,
        "bytes": len(encoded),
        "valid_json": valid,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "tail": arguments[-24:],
    }


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class Ledger:
    """Thread-safe spend accounting with a hard stop."""

    def __init__(self, max_cost_usd: float | None) -> None:
        self.max_cost_usd = max_cost_usd
        self.total_cost_usd = 0.0
        self.lock = threading.Lock()

    def exhausted(self) -> bool:
        with self.lock:
            return self.max_cost_usd is not None and self.total_cost_usd >= self.max_cost_usd

    def add(self, cost: float) -> float:
        with self.lock:
            self.total_cost_usd += cost
            return self.total_cost_usd


class Recorder:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.lock = threading.Lock()

    def append(self, run_id: str, name: str, record: dict[str, Any]) -> None:
        directory = self.runs_dir / run_id
        line = json.dumps(record, sort_keys=True) + "\n"
        with self.lock:
            directory.mkdir(parents=True, exist_ok=True)
            with open(directory / name, "a", encoding="utf-8") as handle:
                handle.write(line)


def connect(upstream: Any, timeout: float) -> http.client.HTTPConnection:
    connection_class = (
        http.client.HTTPSConnection if upstream.scheme == "https" else http.client.HTTPConnection
    )
    return connection_class(upstream.hostname, upstream.port, timeout=timeout)


def fetch_generation(
    config: dict[str, Any],
    api_key: str,
    recorder: Recorder,
    run_id: str,
    generation_id: str,
) -> None:
    """Look up the serving provider once OpenRouter has the generation stats."""
    upstream = urlsplit(config.get("upstream", "https://openrouter.ai/api/v1"))
    delay = float(config.get("generation_delay_seconds", 3.0))
    attempts = int(config.get("generation_attempts", 5))
    path = f"{upstream.path.rstrip('/')}/generation?{urlencode({'id': generation_id})}"
    record: dict[str, Any] = {"run_id": run_id, "generation_id": generation_id}
    for attempt in range(1, attempts + 1):
        time.sleep(delay * attempt)
        connection = connect(upstream, 30.0)
        try:
            connection.request("GET", path, headers={"Authorization": f"Bearer {api_key}"})
            response = connection.getresponse()
            payload = response.read()
        except (OSError, http.client.HTTPException) as error:
            record["error"] = f"{type(error).__name__}"
            continue
        finally:
            connection.close()
        if response.status != 200:
            record["error"] = f"status {response.status}"
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            record["error"] = "invalid JSON"
            continue
        data = data.get("data", data) if isinstance(data, dict) else {}
        record.pop("error", None)
        record.update({field: data.get(field) for field in GENERATION_FIELDS})
        break
    record["attempts"] = attempt
    recorder.append(run_id, GENERATIONS_FILE, record)


def make_handler(
    config: dict[str, Any],
    recorder: Recorder,
    ledger: Ledger,
    api_key: str,
    attempts: int,
    backoff_seconds: float,
) -> type[BaseHTTPRequestHandler]:
    upstream = urlsplit(config.get("upstream", "https://openrouter.ai/api/v1"))
    upstream_timeout = float(config.get("upstream_timeout_seconds", 300))

    class Handler(BaseHTTPRequestHandler):
        server_version = "editbench-orproxy"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def send_json(self, status: int, message: str) -> None:
            data = json.dumps({"error": {"message": message}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            match = RUN_PATH.match(self.path)
            if not match:
                self.send_json(404, "unknown proxy path")
                return
            run_id = match.group(1)
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                self.send_json(400, "request body required")
                return
            try:
                body = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                body = None
            if not isinstance(body, dict):
                self.send_json(400, "request body must be a JSON object")
                return
            model = body.get("model")
            record: dict[str, Any] = {
                "run_id": run_id,
                "model": model,
                "started_at": time.time(),
                "request_bytes": length,
                "messages": len(body.get("messages") or []),
                "tools_sha256": digest(body.get("tools")),
                "temperature": body.get("temperature"),
                "max_tokens": body.get("max_tokens"),
            }
            settings = config["models"].get(model) if isinstance(model, str) else None
            if settings is None:
                record.update(status=400, error="model not configured")
                recorder.append(run_id, CALLS_FILE, record)
                self.send_json(400, f"model {model!r} is not configured in the proxy")
                return
            if ledger.exhausted():
                record.update(status=429, error="budget exhausted", censored=True)
                recorder.append(run_id, CALLS_FILE, record)
                self.send_json(429, "experiment budget exhausted")
                return
            record["provider"] = settings["provider"]
            record["reasoning"] = settings.get("reasoning")
            prepared, dropped = prepare_body(body, settings)
            record["dropped_parameters"] = dropped
            record["set_parameters"] = settings.get("set_parameters") or {}
            record["sanitized_tool_arguments"] = prepared.pop("_sanitized_tool_arguments")
            self.forward(run_id, json.dumps(prepared).encode(), record)

        def forward(self, run_id: str, payload: bytes, record: dict[str, Any]) -> None:
            path = f"{upstream.path.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }
            attempt = 0
            while True:
                attempt += 1
                connection = connect(upstream, upstream_timeout)
                try:
                    connection.request("POST", path, body=payload, headers=headers)
                    response = connection.getresponse()
                except (OSError, http.client.HTTPException) as error:
                    connection.close()
                    if attempt < attempts:
                        time.sleep(backoff_seconds * attempt)
                        continue
                    record.update(
                        status=502,
                        attempts=attempt,
                        error=f"upstream connection failed: {type(error).__name__}",
                    )
                    recorder.append(run_id, CALLS_FILE, record)
                    self.send_json(502, "upstream connection failed")
                    return
                if response.status in RETRYABLE_STATUS and attempt < attempts:
                    response.read()
                    connection.close()
                    time.sleep(backoff_seconds * attempt)
                    continue
                break

            record.update(attempts=attempt, status=response.status)
            generation_id = None
            usage = None
            finish_reason = None
            first_byte_at = None
            error_body = b""
            tool_calls: dict[int, dict[str, Any]] = {}
            stream_handle = None
            timing_handle = None
            if config.get("save_streams") and response.status < 400:
                stream_path = recorder.runs_dir / run_id / "streams" / f"{time.time_ns()}.sse"
                stream_path.parent.mkdir(parents=True, exist_ok=True)
                stream_handle = open(stream_path, "wb")
                timing_handle = open(stream_path.with_suffix(".timing"), "w", encoding="utf-8")
                record["stream_file"] = str(stream_path.relative_to(recorder.runs_dir / run_id))
            # Gaps between received lines. S-Code's 60 s model stream idle timer
            # counts from the request start and resets only on parsed events, so
            # SSE comments such as ": OPENROUTER PROCESSING" keep the socket alive
            # without resetting it; `data:` gaps approximate what S-Code sees.
            last_line_at = last_data_at = record["started_at"]
            max_line_gap = max_data_gap = 0.0
            self.send_response(response.status)
            self.send_header(
                "Content-Type", response.getheader("Content-Type", "application/octet-stream")
            )
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    line = response.readline()
                    if not line:
                        break
                    now = time.time()
                    if first_byte_at is None:
                        first_byte_at = now
                    max_line_gap = max(max_line_gap, now - last_line_at)
                    last_line_at = now
                    if line.startswith(b"data: "):
                        max_data_gap = max(max_data_gap, now - last_data_at)
                        last_data_at = now
                    if stream_handle is not None:
                        stream_handle.write(line)
                        timing_handle.write(f"{now - record['started_at']:.3f}\t{len(line)}\n")
                    self.wfile.write(line)
                    self.wfile.flush()
                    if response.status >= 400:
                        error_body += line[: max(0, MAX_ERROR_BODY_BYTES - len(error_body))]
                        continue
                    if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]":
                        continue
                    try:
                        chunk = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    generation_id = generation_id or chunk.get("id")
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        if not isinstance(choice, dict):
                            continue
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                        delta = choice.get("delta")
                        for call in (delta.get("tool_calls") or []) if isinstance(delta, dict) else []:
                            function = call.get("function") if isinstance(call, dict) else None
                            if not isinstance(function, dict):
                                continue
                            entry = tool_calls.setdefault(int(call.get("index") or 0), {"name": None, "arguments": ""})
                            entry["name"] = entry["name"] or function.get("name")
                            if isinstance(function.get("arguments"), str):
                                entry["arguments"] += function["arguments"]
            except (BrokenPipeError, ConnectionResetError):
                record["client_disconnected"] = True
            except (OSError, http.client.HTTPException) as error:
                record["upstream_stream_error"] = type(error).__name__
            finally:
                connection.close()
                if stream_handle is not None:
                    stream_handle.close()
                    timing_handle.close()

            cost = usage.get("cost") if isinstance(usage, dict) else None
            cost_usd = float(cost) if isinstance(cost, (int, float)) else 0.0
            finished_at = time.time()
            record.update(
                max_line_gap_seconds=round(max_line_gap, 3),
                max_data_gap_seconds=round(max_data_gap, 3),
                # Silence on `data:` lines when the call ended; for a call S-Code
                # abandoned, this is how long it had seen no event.
                tail_data_gap_seconds=round(finished_at - last_data_at, 3),
            )
            record.update(
                finished_at=finished_at,
                first_byte_seconds=None if first_byte_at is None else first_byte_at - record["started_at"],
                generation_id=generation_id,
                usage=usage,
                finish_reason=finish_reason,
                tool_calls=[
                    stream_tool_call(index, entry["name"], entry["arguments"])
                    for index, entry in sorted(tool_calls.items())
                ],
                cost_usd=cost_usd,
                ledger_total_usd=ledger.add(cost_usd),
                error_body=error_body.decode("utf-8", "replace") or None,
            )
            recorder.append(run_id, CALLS_FILE, record)
            if generation_id and config.get("fetch_generation", True):
                threading.Thread(
                    target=fetch_generation,
                    args=(config, api_key, recorder, run_id, generation_id),
                    daemon=True,
                ).start()

    return Handler


def serve(
    config: dict[str, Any],
    runs_dir: Path,
    api_key: str,
    port: int = 0,
    max_cost_usd: float | None = None,
    attempts: int = 3,
    backoff_seconds: float = 2.0,
) -> tuple[ThreadingHTTPServer, Ledger]:
    ledger = Ledger(max_cost_usd)
    handler = make_handler(config, Recorder(runs_dir), ledger, api_key, attempts, backoff_seconds)
    return ThreadingHTTPServer(("127.0.0.1", port), handler), ledger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--backoff-seconds", type=float, default=2.0)
    parser.add_argument("--port-file", type=Path, help="write the bound port here once listening")
    parser.add_argument("--save-streams", action="store_true", help="keep each raw upstream SSE stream under <run>/streams/")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.save_streams:
        config["save_streams"] = True
    api_key = os.environ.get(config.get("api_key_env", "OPENROUTER_API_KEY"))
    if not api_key:
        print("the configured API key environment variable is not set", file=sys.stderr)
        return 2
    server, _ = serve(
        config,
        args.runs_dir,
        api_key,
        args.port,
        args.max_cost_usd,
        args.attempts,
        args.backoff_seconds,
    )
    port = server.server_address[1]
    if args.port_file:
        temporary = args.port_file.with_suffix(".tmp")
        temporary.write_text(str(port))
        temporary.replace(args.port_file)
    print(json.dumps({"listening": f"http://127.0.0.1:{port}"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
