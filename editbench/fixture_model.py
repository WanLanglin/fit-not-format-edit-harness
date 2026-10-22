#!/usr/bin/env python3
"""Scripted OpenAI-compatible model for offline end-to-end runs.

It plays one fixed trajectory against a single file: read the file, send one
correct apply_patch call in the requested form, then finish. The script is a
JSON file {"path", "before", "after", "form"}, where form is "lines", "text"
or "patch". The edit is computed from the before/after contents and the
revision the model sees in the read_file result, so a successful run
exercises the real schema, revision checks and edit application.
"""

from __future__ import annotations

import argparse
import os
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def changed_block(before: list[str], after: list[str]) -> tuple[int, int, int, int]:
    """Half-open before/after line ranges covering every difference."""
    prefix = 0
    while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(before), len(after)) - prefix
        and before[len(before) - 1 - suffix] == after[len(after) - 1 - suffix]
    ):
        suffix += 1
    return prefix, len(before) - suffix, prefix, len(after) - suffix


def unique_block(
    before_text: str, before: list[str], start: int, end: int, line_start: bool
) -> tuple[int, int]:
    """Widen [start, end) until it is nonempty and its text occurs exactly once.

    Text edits match anywhere in the file; patch hunks only at line starts,
    mirroring S-Code's apply_file_edits.
    """
    while True:
        if end > start:
            block = "".join(before[start:end])
            positions, offset = 0, 0
            while (found := before_text.find(block, offset)) != -1:
                if not line_start or found == 0 or before_text[found - 1] == "\n":
                    positions += 1
                offset = found + 1
            if positions == 1:
                return start, end
        if start == 0 and end == len(before):
            return start, end
        start = max(0, start - 1)
        end = min(len(before), end + 1)


def edit_arguments(script: dict[str, Any], revision: str) -> dict[str, Any]:
    path, before_text, after_text, form = script["path"], script["before"], script["after"], script["form"]
    before = before_text.splitlines(keepends=True)
    after = after_text.splitlines(keepends=True)
    b_start, b_end, a_start, a_end = changed_block(before, after)
    start, end = unique_block(before_text, before, b_start, b_end, line_start=form == "patch")
    new_lines = before[start:b_start] + after[a_start:a_end] + before[b_end:end]
    if form in ("lines", "lines_anchored"):
        new_text = "".join(new_lines)
        if new_text.endswith("\n"):
            new_text = new_text[:-1]
        edit = {"start_line": start + 1, "end_line": end, "new_text": new_text}
        if form == "lines_anchored":
            edit["first_line"] = before[start].rstrip("\r\n")
            edit["last_line"] = before[end - 1].rstrip("\r\n")
        return {"files": [{"path": path, "expected_revision": revision, "edits": [edit]}]}
    if form == "text":
        return {
            "files": [
                {
                    "path": path,
                    "expected_revision": revision,
                    "edits": [{"old_text": "".join(before[start:end]), "new_text": "".join(new_lines)}],
                }
            ]
        }
    if form == "patch":
        body = [" " + line for line in before[start:b_start]]
        body += ["-" + line for line in before[b_start:b_end]]
        body += ["+" + line for line in after[a_start:a_end]]
        body += [" " + line for line in before[b_end:end]]
        text = "".join(line if line.endswith("\n") else line + "\n" for line in body)
        # EDITBENCH_FIXTURE_NAMED_HEADER=1 writes `@@ <the line above the hunk>`, the
        # header form some models emit and the reference Codex apply_patch accepts.
        header = "@@"
        if os.environ.get("EDITBENCH_FIXTURE_NAMED_HEADER") and start > 0 and before[start - 1].strip():
            header = "@@ " + before[start - 1].strip()
        return {
            "patch": f"*** Begin Patch\n*** Update File: {path}\n{header}\n{text}*** End Patch",
            "revisions": {path: revision},
        }
    raise ValueError(f"unknown form {form!r}")


def frames_for(request: dict[str, Any], script: dict[str, Any]) -> list[dict[str, Any]]:
    tools = {tool.get("function", {}).get("name") for tool in request.get("tools", [])}
    tool_results = [message for message in request.get("messages", []) if message.get("role") == "tool"]

    def call(name: str, arguments: dict[str, Any], call_id: str) -> list[dict[str, Any]]:
        return [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": call_id,
                                    "function": {"name": name, "arguments": json.dumps(arguments)},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20}},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ]

    if not tool_results:
        if "read_file" not in tools or "apply_patch" not in tools:
            raise ValueError(f"expected read_file and apply_patch tools, got {sorted(tools)}")
        return call("read_file", {"path": script["path"]}, "call_read")
    # EDITBENCH_FIXTURE_BAD_FIRST_EDIT=1 scripts one rejected edit (a file entry
    # with neither content nor edits) before the correct one, so a run shows the
    # error text the model would read.
    bad_first = bool(os.environ.get("EDITBENCH_FIXTURE_BAD_FIRST_EDIT")) and script["form"] != "patch"
    if len(tool_results) in ((1, 2) if bad_first else (1,)):
        content = tool_results[0].get("content")
        result = json.loads(content) if isinstance(content, str) else content
        revision = result.get("revision")
        if not isinstance(revision, str):
            raise ValueError(f"read_file result has no revision: {str(content)[:200]}")
        # The three-tool arms offer each form under its own name.
        by_form = {"lines": "edit_lines", "lines_anchored": "edit_lines", "text": "edit_text", "patch": "apply_patch"}
        name = by_form[script["form"]] if "edit_lines" in tools else "apply_patch"
        if bad_first and len(tool_results) == 1:
            broken = {"files": [{"path": script["path"], "expected_revision": revision, "edits": []}]}
            if script["form"] == "lines_anchored":
                # A range whose last line is misquoted: the anchored arm must refuse it.
                broken = edit_arguments(script, revision)
                broken["files"][0]["edits"][0]["last_line"] = "this is not the last line"
            return call(name, broken, "call_bad_edit")
        arguments = edit_arguments(script, revision)
        # EDITBENCH_FIXTURE_SHIFTED_EDIT=1 numbers the anchored range one line off
        # while quoting the right lines, so boundary alignment must place it.
        if script["form"] == "lines_anchored" and os.environ.get("EDITBENCH_FIXTURE_SHIFTED_EDIT"):
            edit = arguments["files"][0]["edits"][0]
            shift = 1 if edit["end_line"] < len(script["before"].splitlines()) else -1
            if edit["start_line"] + shift >= 1:
                edit["start_line"] += shift
                edit["end_line"] += shift
        return call(name, arguments, "call_edit")
    return [
        {"choices": [{"delta": {"content": "done"}, "finish_reason": None}]},
        {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 2}},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]


def make_handler(script: dict[str, Any], log: Path | None) -> type[BaseHTTPRequestHandler]:
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_POST(self) -> None:
            if not self.path.endswith("/chat/completions"):
                self.send_error(404)
                return
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            try:
                frames = frames_for(request, script)
            except (ValueError, KeyError, json.JSONDecodeError) as error:
                if log:
                    with lock, log.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"error": str(error)}) + "\n")
                self.send_error(400, str(error)[:200])
                return
            if log:
                with lock, log.open("a", encoding="utf-8") as handle:
                    # Record what the agent actually sent, not just how much: the
                    # role of every message plus a preview, so a run can prove
                    # which system prompts reached the model.
                    preview = [
                        {
                            "role": message.get("role"),
                            "chars": len(message.get("content") if isinstance(message.get("content"), str) else json.dumps(message.get("content"))),
                            "head": (message.get("content") if isinstance(message.get("content"), str) else json.dumps(message.get("content")))[:400],
                        }
                        for message in request.get("messages", [])
                    ]
                    handle.write(json.dumps({"messages": len(request.get("messages", [])), "message_preview": preview, "frames": frames}) + "\n")
            body = "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n"
            encoded = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def serve(script: dict[str, Any], log: Path | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", 0), make_handler(script, log))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("script", type=Path)
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args(argv)
    server = serve(json.loads(args.script.read_text()), args.log)
    args.port_file.write_text(str(server.server_address[1]))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
