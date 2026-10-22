#!/usr/bin/env python3
"""Regression coverage for the OpenRouter recording proxy, against a fake upstream."""

from __future__ import annotations

import http.client
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "orproxy.py"
spec = importlib.util.spec_from_file_location("orproxy", SCRIPT)
orproxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orproxy)

API_KEY = "test-key-0123456789abcdef"
SSE = (
    b'data: {"id":"gen-1","choices":[{"delta":{"content":"hi"}}]}\n\n'
    b": OPENROUTER PROCESSING\n\n"
    b'data: {"id":"gen-1","choices":[{"delta":{},"finish_reason":"tool_calls"}],'
    b'"usage":{"prompt_tokens":5,"completion_tokens":2,"cost":0.25}}\n\n'
    b"data: [DONE]\n\n"
)


class FakeUpstream:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.failures_before_success = 0
        self.sse = SSE
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                upstream.requests.append({"body": body, "authorization": self.headers["Authorization"]})
                if upstream.failures_before_success > 0:
                    upstream.failures_before_success -= 1
                    data = b'{"error":{"message":"overloaded"}}'
                    self.send_response(503)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(upstream.sse)

            def do_GET(self):
                data = json.dumps({"data": {"provider_name": "FakeProvider", "total_cost": 0.25}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/api/v1"


def settings(**provider_overrides):
    provider = {"order": ["fake"], "allow_fallbacks": False, "require_parameters": True}
    provider.update(provider_overrides)
    return {"provider": provider, "reasoning": {"effort": "high"}}


class ProxyTest(unittest.TestCase):
    def setUp(self):
        self.upstream = FakeUpstream()
        self.directory = tempfile.TemporaryDirectory()
        self.runs = Path(self.directory.name)
        self.config = {
            "upstream": self.upstream.url,
            "models": {"z-ai/glm-5.3": settings()},
            "generation_delay_seconds": 0.01,
        }

    def tearDown(self):
        self.upstream.server.shutdown()
        self.upstream.server.server_close()
        self.directory.cleanup()

    def start(self, **options):
        server, ledger = orproxy.serve(self.config, self.runs, API_KEY, backoff_seconds=0.0, **options)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1], ledger

    def post(self, port, body, path="/r/run-1/v1/chat/completions"):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        data = json.dumps(body).encode()
        connection.request("POST", path, body=data, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        payload = response.read()
        connection.close()
        return response.status, payload

    def records(self, name="model_calls.jsonl"):
        path = self.runs / "run-1" / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def request_body(self):
        return {
            "model": "z-ai/glm-5.3",
            "temperature": 0.0,
            "max_tokens": 8192,
            "stream": True,
            "messages": [{"role": "user", "content": "task"}],
            "tools": [{"type": "function", "function": {"name": "apply_patch"}}],
        }

    def test_streams_unchanged_injects_routing_and_records_usage(self):
        port, ledger = self.start()
        status, payload = self.post(port, self.request_body())
        self.assertEqual(status, 200)
        self.assertEqual(payload, SSE)
        sent = self.upstream.requests[0]
        self.assertEqual(sent["authorization"], f"Bearer {API_KEY}")
        self.assertEqual(sent["body"]["provider"], settings()["provider"])
        self.assertEqual(sent["body"]["reasoning"], {"effort": "high"})
        self.assertEqual(sent["body"]["messages"], self.request_body()["messages"])
        [record] = self.records()
        self.assertEqual(record["generation_id"], "gen-1")
        self.assertEqual(record["usage"]["cost"], 0.25)
        self.assertEqual(record["finish_reason"], "tool_calls")
        self.assertEqual(record["attempts"], 1)
        self.assertEqual(record["tools_sha256"], orproxy.digest(self.request_body()["tools"]))
        self.assertEqual(ledger.total_cost_usd, 0.25)
        deadline = time.time() + 5
        while not self.records("generations.jsonl") and time.time() < deadline:
            time.sleep(0.02)
        [generation] = self.records("generations.jsonl")
        self.assertEqual(generation["provider_name"], "FakeProvider")
        for path in self.runs.rglob("*"):
            if path.is_file():
                self.assertNotIn(API_KEY, path.read_text())

    def test_drops_configured_parameters_and_records_them(self):
        self.config["models"]["z-ai/glm-5.3"]["drop_parameters"] = ["temperature", "not_sent"]
        self.config["fetch_generation"] = False
        port, _ = self.start()
        self.assertEqual(self.post(port, self.request_body())[0], 200)
        sent = self.upstream.requests[0]["body"]
        self.assertNotIn("temperature", sent)
        self.assertEqual(sent["max_tokens"], 8192)
        self.assertEqual(self.records()[0]["dropped_parameters"], ["temperature"])

    def test_records_tool_call_arguments_as_streamed_and_saves_raw_stream(self):
        self.config["fetch_generation"] = False
        self.config["save_streams"] = True
        self.upstream.sse = (
            b'data: {"id":"gen-2","choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"apply_patch","arguments":"{\\"files\\": [{\\"path\\""}}]}}]}\n\n'
            b'data: {"id":"gen-2","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":": \\"a\\"}]}"}},{"index":1,"id":"c2","function":{"name":"read_file","arguments":"{\\"path\\": \\"b\\"}"}}]},"finish_reason":"tool_calls"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        port, _ = self.start()
        status, payload = self.post(port, self.request_body())
        self.assertEqual((status, payload), (200, self.upstream.sse))
        [record] = self.records()
        first, second = record["tool_calls"]
        self.assertEqual((first["name"], first["valid_json"], first["tail"]), ("apply_patch", True, '{"files": [{"path": "a"}]}'[-24:]))
        self.assertEqual(first["bytes"], len('{"files": [{"path": "a"}]}'))
        self.assertEqual((second["index"], second["name"], second["valid_json"]), (1, "read_file", True))
        stream = self.runs / "run-1" / record["stream_file"]
        self.assertEqual(stream.read_bytes(), self.upstream.sse)
        timing = stream.with_suffix(".timing").read_text().splitlines()
        self.assertEqual(len(timing), self.upstream.sse.count(b"\n"))
        self.assertEqual([int(row.split("\t")[1]) for row in timing], [len(line) for line in self.upstream.sse.splitlines(keepends=True)])
        for field in ("max_line_gap_seconds", "max_data_gap_seconds", "tail_data_gap_seconds"):
            self.assertGreaterEqual(record[field], 0.0)

    def test_truncated_streamed_arguments_are_marked_invalid(self):
        self.config["fetch_generation"] = False
        self.upstream.sse = (
            b'data: {"id":"gen-3","choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"apply_patch","arguments":"{\\"files\\": [{\\"path\\": \\"a\\"}"}}]},"finish_reason":"tool_calls"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        port, _ = self.start()
        self.assertEqual(self.post(port, self.request_body())[0], 200)
        [record] = self.records()
        self.assertFalse(record["tool_calls"][0]["valid_json"])
        self.assertNotIn("stream_file", record)

    def test_invalid_tool_arguments_in_history_are_replaced_and_counted(self):
        self.config["fetch_generation"] = False
        port, _ = self.start()
        broken = '{"files":[{"path":"a","edits":[{"old_text":"x","new_text":"y"}]'
        body = self.request_body()
        body["messages"] = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a"}'}},
                    {"id": "c2", "type": "function", "function": {"name": "apply_patch", "arguments": broken}},
                ],
            },
            {"role": "tool", "tool_call_id": "c2", "content": '{"error":"tool arguments are not valid JSON"}'},
        ]
        self.assertEqual(self.post(port, body)[0], 200)
        sent_calls = self.upstream.requests[0]["body"]["messages"][1]["tool_calls"]
        self.assertEqual(sent_calls[0]["function"]["arguments"], '{"path":"a"}')
        self.assertEqual(sent_calls[1]["function"]["arguments"], "{}")
        self.assertNotIn("invalid_json_arguments", json.dumps(self.upstream.requests[0]["body"]))
        self.assertNotIn("_sanitized_tool_arguments", self.upstream.requests[0]["body"])
        self.assertEqual(self.records()[0]["sanitized_tool_arguments"], 1)

    def test_set_parameters_override_request_values_and_are_recorded(self):
        self.config["models"]["z-ai/glm-5.3"]["set_parameters"] = {"top_p": 0.95}
        self.config["fetch_generation"] = False
        port, _ = self.start()
        self.assertEqual(self.post(port, self.request_body())[0], 200)
        sent = self.upstream.requests[0]["body"]
        self.assertEqual(sent["top_p"], 0.95)
        self.assertEqual(sent["temperature"], 0.0)
        self.assertEqual(self.records()[0]["set_parameters"], {"top_p": 0.95})

    def test_retries_retryable_status_before_the_first_byte(self):
        self.upstream.failures_before_success = 2
        port, _ = self.start(attempts=3)
        status, payload = self.post(port, self.request_body())
        self.assertEqual((status, payload), (200, SSE))
        self.assertEqual(len(self.upstream.requests), 3)
        self.assertEqual(self.records()[0]["attempts"], 3)

    def test_final_upstream_error_is_passed_through_and_recorded(self):
        self.upstream.failures_before_success = 5
        self.config["fetch_generation"] = False
        port, _ = self.start(attempts=2)
        status, payload = self.post(port, self.request_body())
        self.assertEqual(status, 503)
        self.assertIn(b"overloaded", payload)
        [record] = self.records()
        self.assertEqual((record["status"], record["attempts"]), (503, 2))
        self.assertIn("overloaded", record["error_body"])

    def test_budget_stop_answers_429_without_calling_upstream(self):
        self.config["fetch_generation"] = False
        port, _ = self.start(max_cost_usd=0.2)
        self.assertEqual(self.post(port, self.request_body())[0], 200)
        status, _ = self.post(port, self.request_body())
        self.assertEqual(status, 429)
        self.assertEqual(len(self.upstream.requests), 1)
        self.assertTrue(self.records()[1]["censored"])

    def test_rejects_unknown_paths_and_unconfigured_models(self):
        port, _ = self.start()
        self.assertEqual(self.post(port, self.request_body(), path="/v1/chat/completions")[0], 404)
        body = self.request_body() | {"model": "other/model"}
        self.assertEqual(self.post(port, body)[0], 400)
        self.assertEqual(self.upstream.requests, [])
        self.assertEqual(self.records()[0]["error"], "model not configured")

    def test_config_requires_one_pinned_provider_without_fallbacks(self):
        for bad in (
            settings(allow_fallbacks=True),
            settings(require_parameters=False),
            settings(order=["a", "b"]),
            {"provider": None},
        ):
            path = self.runs / "config.json"
            path.write_text(json.dumps({"models": {"m": bad}}))
            with self.assertRaises(ValueError):
                orproxy.load_config(path)
        path = self.runs / "config.json"
        path.write_text(json.dumps({"models": {"m": settings()}}))
        self.assertIn("m", orproxy.load_config(path)["models"])


if __name__ == "__main__":
    unittest.main()
